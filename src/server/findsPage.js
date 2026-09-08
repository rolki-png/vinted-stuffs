// @ts-nocheck
/**
 * Paged Finds read model: Cockroach SQL when available, JSON fallback otherwise.
 */
import fs from "node:fs";
import path from "node:path";
import pg from "pg";
import {
	matchesBandFilter,
	matchesScoreFilter,
	sortFinds,
} from "../components/scoreView.js";
import { jsonFromGithubContents } from "./githubContents.js";
import { applyToFinds, loadVetoMap } from "./listingVetoes.ts";
import { databaseUrl, exportRow, loadIndexedFromDb } from "./scoredDb.ts";
import { mergeScoreRows } from "./scoreSemantics.js";

const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 100;

function sslConfig() {
	const caPath =
		process.env.PGSSLROOTCERT ||
		path.join(process.env.HOME || "", ".postgresql", "root.crt");
	if (fs.existsSync(caPath)) {
		return { ca: fs.readFileSync(caPath), rejectUnauthorized: true };
	}
	return { rejectUnauthorized: true };
}

async function withClient(fn) {
	const url = databaseUrl();
	if (!url) return null;
	let connectionString = url;
	if (
		!fs.existsSync(path.join(process.env.HOME || "", ".postgresql", "root.crt"))
	) {
		connectionString = url.replace(/sslmode=verify-full/gi, "sslmode=require");
	}
	const client = new pg.Client({
		connectionString,
		ssl: sslConfig(),
		connectionTimeoutMillis: 8000,
		query_timeout: 20000,
	});
	try {
		await client.connect();
		return await fn(client);
	} finally {
		try {
			await client.end();
		} catch {
			/* ignore */
		}
	}
}

function clampPage(page) {
	const n = Math.trunc(Number(page) || 1);
	return Number.isFinite(n) && n >= 1 ? n : 1;
}

function clampLimit(limit) {
	const n = Math.trunc(Number(limit) || DEFAULT_LIMIT);
	if (!Number.isFinite(n) || n < 1) return DEFAULT_LIMIT;
	return Math.min(MAX_LIMIT, n);
}

function parseFilters(raw = {}) {
	return {
		page: clampPage(raw.page),
		limit: clampLimit(raw.limit),
		veto: ["active", "parked", "bought", "all"].includes(raw.veto)
			? raw.veto
			: "active",
		watch: String(raw.watch || "").trim(),
		band: String(raw.band || "").trim(),
		minScore: String(raw.min_score || raw.minScore || "").trim(),
		source: String(raw.source || "").trim(),
		q: String(raw.q || "").trim(),
		sort: String(raw.sort || "score-desc").trim() || "score-desc",
	};
}

function vetoSql(mode, params) {
	if (mode === "all") {
		return `(v.status IS NULL OR v.status NOT IN ('removed', 'hidden'))`;
	}
	if (mode === "parked") {
		params.push("parked");
		return `v.status = $${params.length}`;
	}
	if (mode === "bought") {
		params.push("bought");
		return `v.status = $${params.length}`;
	}
	return `(v.status IS NULL OR v.status NOT IN ('removed', 'hidden', 'bought'))`;
}

function bandSql(band, params) {
	if (!band) return "TRUE";
	const raw = String(band);
	const value = raw.includes(":") ? raw.split(":", 2)[1] : raw;
	const scale = raw.includes(":") ? raw.split(":", 2)[0] : "v2";
	if (!value || scale === "legacy") return "TRUE";
	params.push(value);
	return `best.score_version = 2 AND best.buy_score IS NOT NULL AND best.buy_score BETWEEN 0 AND 100 AND best.buy_band = $${params.length}`;
}

function minScoreSql(minScore, params) {
	if (!minScore) return "TRUE";
	const match = /^(?:v2:)?(\d+)$/.exec(String(minScore));
	if (!match) return "TRUE";
	params.push(Number(match[1]));
	return `best.score_version = 2 AND best.buy_score IS NOT NULL AND best.buy_score BETWEEN 0 AND 100 AND best.buy_score >= $${params.length}`;
}

function sortSql(sort) {
	const vetoOrd = `CASE COALESCE(joined.veto_status, '')
    WHEN '' THEN 0 WHEN 'parked' THEN 1 WHEN 'bought' THEN 2 ELSE 3 END`;
	const scored = `CASE WHEN joined.score_version = 2 AND joined.buy_score IS NOT NULL AND joined.buy_score BETWEEN 0 AND 100 THEN 1 ELSE 0 END`;
	const score = `COALESCE(joined.buy_score, -1)`;
	switch (sort) {
		case "score-asc":
			return `${vetoOrd} ASC, ${scored} DESC, ${score} ASC, joined.item_id ASC`;
		case "price-asc":
			return `${vetoOrd} ASC, joined.price ASC NULLS LAST, joined.item_id ASC`;
		case "price-desc":
			return `${vetoOrd} ASC, joined.price DESC NULLS LAST, joined.item_id ASC`;
		case "date-desc":
			return `${vetoOrd} ASC, joined.scored_at DESC NULLS LAST, joined.item_id ASC`;
		case "watch":
			return `${vetoOrd} ASC, joined.hunt_name ASC, joined.item_id ASC`;
		case "score-desc":
		default:
			return `${vetoOrd} ASC, ${scored} DESC, ${score} DESC, joined.rank_position ASC NULLS LAST, joined.item_id ASC`;
	}
}

const SELECT_COLS = `
  item_id, hunt_name, title, price, currency, brand, size, condition, url,
  favourite_count, seller_id, seller_login, seller_country,
  deal_score, value_band, hunt_fit, scam_risk,
  score_version, buy_score, buy_band, score_confidence,
  score_interval_low, score_interval_high, score_factors, factor_evidence,
  verification_concern, verification_reason, rank_position, rank_confidence,
  reason, has_score, scored_at, source
`;

async function queryFindsFromDb(filters) {
	return withClient(async (client) => {
		const params = [];
		const where = [
			`has_score = true`,
			`COALESCE(reason, '') <> 'unavailable during backfill'`,
		];
		if (filters.watch) {
			params.push(filters.watch);
			where.push(`hunt_name = $${params.length}`);
		}

		const bestWhere = where.join(" AND ");
		const band = bandSql(filters.band, params);
		const minScore = minScoreSql(filters.minScore, params);
		const veto = vetoSql(filters.veto, params);

		const qParams = [...params];
		let qClause = "TRUE";
		if (filters.q) {
			qParams.push(`%${filters.q.replace(/[%_]/g, "\\$&")}%`);
			const i = qParams.length;
			qClause = `(best.title ILIKE $${i} OR best.hunt_name ILIKE $${i} OR COALESCE(best.seller_login, '') ILIKE $${i})`;
		}

		const cte = `
      WITH best AS (
        SELECT DISTINCT ON (item_id) ${SELECT_COLS}
        FROM scored_listings
        WHERE ${bestWhere}
        ORDER BY item_id,
          CASE WHEN score_version = 2 AND buy_score IS NOT NULL AND buy_score BETWEEN 0 AND 100 THEN 2 ELSE 0 END DESC,
          COALESCE(buy_score, deal_score, -1) DESC,
          scored_at DESC NULLS LAST
      ),
      joined AS (
        SELECT best.*,
          CASE WHEN v.status = 'hidden' THEN 'removed' ELSE v.status END AS veto_status
        FROM best
        LEFT JOIN listing_vetoes v ON v.item_id = best.item_id
        WHERE ${veto}
          AND (${band})
          AND (${minScore})
          AND (${qClause})
      )
    `;

		const countRes = await client.query(
			`${cte} SELECT COUNT(*)::int AS n FROM joined`,
			qParams,
		);
		const total = countRes.rows[0]?.n ?? 0;
		const pages = total === 0 ? 0 : Math.ceil(total / filters.limit);
		const page = pages === 0 ? 1 : Math.min(filters.page, pages);
		const offset = (page - 1) * filters.limit;

		const listParams = [...qParams, filters.limit, offset];
		const listRes = await client.query(
			`${cte}
       SELECT * FROM joined
       ORDER BY ${sortSql(filters.sort)}
       LIMIT $${listParams.length - 1} OFFSET $${listParams.length}`,
			listParams,
		);

		const finds = listRes.rows.map((row) => {
			const exported = exportRow(row);
			if (row.veto_status) exported.veto_status = row.veto_status;
			else delete exported.veto_status;
			exported.price_num =
				exported.price != null && Number.isFinite(Number(exported.price))
					? Number(exported.price)
					: null;
			return exported;
		});

		return {
			finds,
			page,
			limit: filters.limit,
			total,
			pages,
			source: "cockroach",
		};
	});
}

async function loadJson(name, fallback) {
	const local = path.join(process.cwd(), "data", name);
	if (fs.existsSync(local)) {
		try {
			return JSON.parse(fs.readFileSync(local, "utf8"));
		} catch {
			return fallback;
		}
	}
	if (process.env.GITHUB_TOKEN && process.env.GITHUB_REPO) {
		try {
			const remote = await jsonFromGithubContents(`data/${name}`);
			return remote ?? fallback;
		} catch {
			return fallback;
		}
	}
	return fallback;
}

function num(v) {
	const n = Number(v);
	return Number.isFinite(n) ? n : null;
}

function buildMemoryCorpus({ deals, indexed, pool, run, vetoes, mode }) {
	const findsById = new Map();
	for (const row of Array.isArray(deals) ? deals : []) {
		if (row?.id == null) continue;
		findsById.set(String(row.id), {
			...row,
			source: "keep",
			price_num: num(row.price),
		});
	}
	for (const row of Array.isArray(indexed) ? indexed : []) {
		if (row?.id == null) continue;
		const id = String(row.id);
		const existing = findsById.get(id);
		const merged = mergeScoreRows(existing, {
			...row,
			source: row.source || "index",
		});
		merged.price_num = num(merged.price);
		findsById.set(id, merged);
	}
	for (const row of run?.top || []) {
		if (row?.id == null) continue;
		const id = String(row.id);
		const base = findsById.get(id) || {};
		const merged = mergeScoreRows(base, { ...row, source: "scored" });
		merged.price_num = num(merged.price);
		merged.kept_at = base.kept_at || null;
		findsById.set(id, merged);
	}
	for (const raw of Array.isArray(pool) ? pool : []) {
		const item = raw.item || {};
		const sc = raw.score || {};
		if (item.id == null) continue;
		const id = String(item.id);
		const user = item.user || {};
		const price =
			item.price && typeof item.price === "object"
				? item.price.amount
				: item.price;
		const currency =
			item.price && typeof item.price === "object"
				? item.price.currency_code
				: null;
		const existing = findsById.get(id) || {};
		const merged = mergeScoreRows(existing, {
			id: item.id,
			title: item.title || existing.title,
			price: price != null ? price : existing.price,
			currency: currency || existing.currency || "RON",
			url: item.url || existing.url,
			watch: raw.watch || existing.watch,
			...sc,
			seller_id: raw.seller_id || user.id || existing.seller_id,
			seller: user.login || raw.seller || existing.seller,
			source: "pool",
		});
		merged.price_num = num(merged.price);
		findsById.set(id, merged);
	}
	return applyToFinds([...findsById.values()], vetoes, { mode });
}

function filterMemoryRows(rows, filters) {
	const query = filters.q.toLowerCase();
	return rows.filter((f) => {
		if (filters.watch && f.watch !== filters.watch) return false;
		if (!matchesBandFilter(f, filters.band)) return false;
		if (!matchesScoreFilter(f, filters.minScore)) return false;
		if (filters.source && f.source !== filters.source) return false;
		if (query) {
			const blob =
				`${f.title || ""} ${f.watch || ""} ${f.seller || ""} ${f.reason || ""}`.toLowerCase();
			if (!blob.includes(query)) return false;
		}
		return true;
	});
}

function pageRows(rows, filters) {
	const sorted = sortFinds(rows, filters.sort);
	const total = sorted.length;
	const pages = total === 0 ? 0 : Math.ceil(total / filters.limit);
	const page = pages === 0 ? 1 : Math.min(filters.page, pages);
	const start = (page - 1) * filters.limit;
	return {
		finds: sorted.slice(start, start + filters.limit),
		page,
		limit: filters.limit,
		total,
		pages,
	};
}

async function enrichFromOverlays(finds) {
	if (!finds.length) return finds;
	const [deals, pool, run] = await Promise.all([
		loadJson("best_deals.json", []),
		loadJson("bundle_pool.json", []),
		loadJson("last_run.json", {}),
	]);
	const byId = new Map();
	for (const row of Array.isArray(deals) ? deals : []) {
		if (row?.id == null) continue;
		byId.set(String(row.id), { ...row, source: "keep" });
	}
	for (const row of run?.top || []) {
		if (row?.id == null) continue;
		const id = String(row.id);
		if (!byId.has(id)) byId.set(id, { ...row, source: "scored" });
	}
	for (const raw of Array.isArray(pool) ? pool : []) {
		const item = raw.item || {};
		if (item.id == null) continue;
		const id = String(item.id);
		if (byId.has(id)) continue;
		const user = item.user || {};
		const price =
			item.price && typeof item.price === "object"
				? item.price.amount
				: item.price;
		byId.set(id, {
			id: item.id,
			title: item.title,
			price,
			url: item.url,
			watch: raw.watch,
			...(raw.score || {}),
			seller_id: raw.seller_id || user.id,
			seller: user.login || raw.seller,
			source: "pool",
		});
	}
	return finds.map((row) => {
		const overlay = byId.get(String(row.id));
		if (!overlay) return row;
		const merged = mergeScoreRows(row, overlay);
		if (overlay.source === "keep") merged.source = "keep";
		else if (!merged.source) merged.source = row.source;
		merged.price_num = num(merged.price);
		if (row.veto_status) merged.veto_status = row.veto_status;
		return merged;
	});
}

async function buildFindsPage(rawFilters = {}) {
	const filters = parseFilters(rawFilters);
	const tinySource = ["keep", "pool", "scored"].includes(filters.source);

	if (!tinySource) {
		try {
			const fromDb = await queryFindsFromDb(filters);
			if (fromDb) {
				fromDb.finds = await enrichFromOverlays(fromDb.finds);
				if (filters.source === "index") {
					fromDb.finds = fromDb.finds.filter((f) => f.source === "index");
				}
				return fromDb;
			}
		} catch (err) {
			console.error("findsPage: SQL path failed:", err.message || err);
		}
	}

	const [deals, pool, run, vetoes, dbIndexed] = await Promise.all([
		loadJson("best_deals.json", []),
		loadJson("bundle_pool.json", []),
		loadJson("last_run.json", {}),
		loadVetoMap(),
		tinySource ? Promise.resolve(null) : loadIndexedFromDb(10000),
	]);
	let indexed = dbIndexed?.rows || [];
	if (!indexed.length && !tinySource) {
		indexed = await loadJson("indexed_scores.json", []);
	}
	if (tinySource) indexed = [];

	const corpus = buildMemoryCorpus({
		deals,
		indexed,
		pool,
		run,
		vetoes,
		mode: filters.veto,
	});
	const filtered = filterMemoryRows(corpus, filters);
	const paged = pageRows(filtered, filters);
	return {
		...paged,
		source:
			dbIndexed?.source || (indexed.length ? "indexed_scores.json" : "json"),
	};
}

async function queryFindsSummary(vetoMode = "active") {
	const filters = parseFilters({ veto: vetoMode, page: 1, limit: 1 });
	try {
		const summary = await withClient(async (client) => {
			const params = [];
			const veto = vetoSql(filters.veto, params);
			const sql = `
        WITH best AS (
          SELECT DISTINCT ON (item_id) item_id, hunt_name, score_version, buy_score,
                 buy_band, score_confidence, hunt_fit, verification_concern, deal_score, value_band
          FROM scored_listings
          WHERE has_score = true
            AND COALESCE(reason, '') <> 'unavailable during backfill'
          ORDER BY item_id,
            CASE WHEN score_version = 2 AND buy_score IS NOT NULL AND buy_score BETWEEN 0 AND 100 THEN 2 ELSE 0 END DESC,
            COALESCE(buy_score, -1) DESC
        ),
        joined AS (
          SELECT best.*
          FROM best
          LEFT JOIN listing_vetoes v ON v.item_id = best.item_id
          WHERE ${veto}
        )
        SELECT
          COUNT(*)::int AS finds_total,
          COUNT(*) FILTER (
            WHERE score_version = 2 AND buy_score IS NOT NULL AND buy_score BETWEEN 0 AND 100
              AND buy_score >= 85 AND COALESCE(score_confidence, 0) >= 0.6
              AND hunt_fit IS TRUE AND COALESCE(verification_concern, '') <> 'block'
          )::int AS keeps
        FROM joined
      `;
			const res = await client.query(sql, params);
			const watchesRes = await client.query(
				`SELECT DISTINCT hunt_name AS watch FROM scored_listings
         WHERE has_score = true AND COALESCE(hunt_name, '') <> ''
         ORDER BY 1`,
			);
			const row = res.rows[0] || {};
			return {
				finds_total: row.finds_total ?? 0,
				keeps: row.keeps ?? 0,
				watches: watchesRes.rows.map((r) => r.watch).filter(Boolean),
				source: "cockroach",
			};
		});
		if (summary) return summary;
	} catch (err) {
		console.error("findsPage: summary failed:", err.message || err);
	}
	return null;
}

export {
	buildFindsPage,
	DEFAULT_LIMIT,
	MAX_LIMIT,
	parseFilters,
	queryFindsSummary,
};
