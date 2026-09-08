// @ts-nocheck

import fs from "node:fs";
import path from "node:path";
import { applyToRow, assignBundleRanks } from "./bundleScore.js";
import { queryFindsSummary } from "./findsPage.js";
import { jsonFromGithubContents } from "./githubContents.js";
import { applyToBundles, applyToFinds, loadVetoMap } from "./listingVetoes.ts";
import { indexBundleOpportunities, loadIndexedFromDb } from "./scoredDb.ts";
import {
	displayScore,
	histogramBins,
	isDeclaredV2,
	isKeep,
	isV2,
	mergeScoreRows,
	sanitizeScoreRow,
	sellerScoreRows,
	sortBundleScoreRows,
	sortScoreRows,
} from "./scoreSemantics.js";

/**
 * Shared snapshot builder for Vercel APIs and local Node tooling.
 * On Vercel: reads data/* live from GitHub (bot commits after each run).
 * Locally: prefers filesystem under data/.
 */

function num(v) {
	const n = Number(v);
	return Number.isFinite(n) ? n : null;
}

function legacyScore(v) {
	if (v == null) return null;
	const n = parseInt(v, 10);
	return Number.isFinite(n) ? n : null;
}

async function fetchGithubJson(relPath) {
	const repo = process.env.GITHUB_REPO;
	const token = process.env.GITHUB_TOKEN;
	const ref = process.env.GITHUB_REF || "main";
	if (!repo || !token) {
		throw new Error("GITHUB_REPO and GITHUB_TOKEN required to load live data");
	}
	const url = `https://api.github.com/repos/${repo}/contents/${relPath}?ref=${encodeURIComponent(ref)}`;
	const res = await fetch(url, {
		headers: {
			Accept: "application/vnd.github+json",
			Authorization: `Bearer ${token}`,
			"User-Agent": "vinted-hunt-dashboard",
			"X-GitHub-Api-Version": "2022-11-28",
		},
	});
	if (res.status === 404) return null;
	if (!res.ok) {
		const text = await res.text();
		throw new Error(
			`GitHub ${res.status} for ${relPath}: ${text.slice(0, 200)}`,
		);
	}
	const body = await res.json();
	return jsonFromGithubContents(body, relPath, { token });
}

function readLocalJson(relPath, fallback) {
	const full = path.join(process.cwd(), relPath);
	if (!fs.existsSync(full)) return fallback;
	try {
		return JSON.parse(fs.readFileSync(full, "utf8"));
	} catch {
		return fallback;
	}
}

async function loadJson(name, fallback) {
	const rel = `data/${name}`;
	if (process.env.GITHUB_TOKEN && process.env.GITHUB_REPO) {
		try {
			const remote = await fetchGithubJson(rel);
			return remote == null ? fallback : remote;
		} catch (err) {
			// Fall back to files shipped with the deployment if GitHub is down.
			const local = readLocalJson(rel, null);
			if (local != null) return local;
			throw err;
		}
	}
	return readLocalJson(rel, fallback);
}

function dashboardRow(row) {
	const out = sanitizeScoreRow({
		...row,
		deal_score: legacyScore(row?.deal_score),
	});
	if (isDeclaredV2(row)) {
		if (out.source === "keep" && !isKeep(row)) out.source = "scored";
	}
	return out;
}

function mergeFindRow(current, incoming) {
	if (!current) return dashboardRow(incoming);
	const merged = mergeScoreRows(current, incoming);
	return dashboardRow(merged);
}

function dashboardBundle(bundle) {
	return applyToRow({
		...bundle,
		items: (bundle?.items || []).map((item) => dashboardRow(item)),
	});
}

function mergeBundles(current, incoming) {
	const items = new Map();
	for (const item of [...(current?.items || []), ...(incoming?.items || [])]) {
		if (item.id == null) continue;
		const key = String(item.id);
		items.set(key, mergeFindRow(items.get(key), item));
	}
	const currentHasV2 = (current?.items || []).some(isV2);
	const incomingHasV2 = (incoming?.items || []).some(isV2);
	const preferred =
		incomingHasV2 && !currentHasV2
			? incoming
			: currentHasV2 && !incomingHasV2
				? current
				: incoming;
	const other = preferred === current ? incoming : current;
	return applyToRow({
		...(other || {}),
		...(preferred || {}),
		items: sortBundleScoreRows([...items.values()]),
	});
}

function sellerEntry(sellers, { sid, login, country }) {
	if (sid == null && !login) return;
	const key = String(sid || login);
	const row = sellers.get(key) || {
		seller_id: sid || null,
		seller: login || null,
		country: country || null,
		item_ids: new Set(),
		watches: new Set(),
		score_rows: new Map(),
	};
	if (login && !row.seller) row.seller = login;
	if (sid && !row.seller_id) row.seller_id = sid;
	if (country && !row.country) row.country = country;
	sellers.set(key, row);
	return row;
}

function bumpSeller(sellers, { sid, login, country, scoreRow, itemId, watch }) {
	const row = sellerEntry(sellers, { sid, login, country });
	if (!row) return;
	if (itemId != null) {
		const key = String(itemId);
		row.item_ids.add(key);
		const current = row.score_rows.get(key);
		row.score_rows.set(key, mergeFindRow(current, scoreRow || {}));
	}
	if (watch) row.watches.add(watch);
}

async function buildSnapshot({ vetoMode = "active" } = {}) {
	const mode = ["active", "parked", "bought", "all"].includes(vetoMode)
		? vetoMode
		: "active";

	// Prefer Cockroach for indexed finds. Skip the GitHub export when DB has rows —
	// indexed_scores.json often exceeds GitHub's 1MB Contents inline limit (~4MB+).
	const dbIndexedPromise = loadIndexedFromDb(10000);
	const summaryPromise = queryFindsSummary(mode);
	const [deals, bundlesRaw, pool, run, seen, dbIndexed, vetoes, findsSummary] =
		await Promise.all([
			loadJson("best_deals.json", []),
			loadJson("best_bundles.json", []),
			loadJson("bundle_pool.json", []),
			loadJson("last_run.json", {}),
			loadJson("seen_listings.json", {}),
			dbIndexedPromise,
			loadVetoMap(),
			summaryPromise,
		]);

	const indexedFile =
		dbIndexed && Array.isArray(dbIndexed.rows) && dbIndexed.rows.length
			? []
			: await loadJson("indexed_scores.json", []);

	const indexed =
		dbIndexed && Array.isArray(dbIndexed.rows) && dbIndexed.rows.length
			? dbIndexed.rows
			: Array.isArray(indexedFile)
				? indexedFile
				: [];
	const indexedSource =
		dbIndexed?.source || (indexed.length ? "indexed_scores.json" : "none");
	const indexedTotal = dbIndexed?.count ?? indexed.length;

	const bundles = Array.isArray(bundlesRaw)
		? bundlesRaw.map(dashboardBundle)
		: [];
	if (dbIndexed?.rows?.length) {
		const indexOpps = indexBundleOpportunities(dbIndexed.rows).map(
			dashboardBundle,
		);
		const existingByFp = new Map(
			bundles.map((b, index) => {
				const ids = (b.items || [])
					.map((it) => String(it.id))
					.filter(Boolean)
					.sort()
					.join(",");
				return [`${b.seller_id || ""}:${ids}`, index];
			}),
		);
		for (const opp of indexOpps) {
			const ids = (opp.items || [])
				.map((it) => String(it.id))
				.filter(Boolean)
				.sort()
				.join(",");
			const fp = `${opp.seller_id || ""}:${ids}`;
			const existingIndex = existingByFp.get(fp);
			if (existingIndex == null) {
				bundles.push(opp);
				existingByFp.set(fp, bundles.length - 1);
			} else {
				bundles[existingIndex] = mergeBundles(bundles[existingIndex], opp);
			}
		}
	}

	const findsById = new Map();

	for (const row of Array.isArray(deals) ? deals : []) {
		if (row.id == null) continue;
		findsById.set(
			String(row.id),
			dashboardRow({
				...row,
				source: "keep",
				price_num: num(row.price),
			}),
		);
	}

	for (const row of indexed) {
		if (row.id == null) continue;
		const id = String(row.id);
		const existing = findsById.get(id);
		const merged = mergeFindRow(existing, { ...row, source: "index" });
		merged.price_num = num(merged.price);
		findsById.set(id, merged);
	}

	for (const row of run.top || []) {
		if (row.id == null) continue;
		const id = String(row.id);
		const base = findsById.get(id) || {};
		const merged = mergeFindRow(base, { ...row, source: "scored" });
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
		const merged = mergeFindRow(existing, {
			id: item.id,
			title: item.title || existing.title,
			price: price != null ? price : existing.price,
			currency: currency || existing.currency || "RON",
			url: item.url || existing.url,
			watch: raw.watch || existing.watch,
			...sc,
			seller_id: raw.seller_id || user.id || existing.seller_id,
			seller: user.login || raw.seller || existing.seller,
			seller_country:
				(item._profile && item._profile.country_code) ||
				existing.seller_country,
			source: "pool",
		});
		merged.price_num = num(merged.price);
		findsById.set(id, merged);
	}

	// Propagate known usernames onto finds/bundles that only have seller_id.
	const loginBySid = new Map();
	for (const f of findsById.values()) {
		if (f.seller_id != null && f.seller)
			loginBySid.set(String(f.seller_id), f.seller);
	}
	for (const b of Array.isArray(bundles) ? bundles : []) {
		if (b.seller_id != null && b.seller)
			loginBySid.set(String(b.seller_id), b.seller);
		for (const it of b.items || []) {
			if ((it.seller_id || b.seller_id) != null && (it.seller || b.seller)) {
				loginBySid.set(
					String(it.seller_id || b.seller_id),
					it.seller || b.seller,
				);
			}
		}
	}
	for (const f of findsById.values()) {
		if (
			!f.seller &&
			f.seller_id != null &&
			loginBySid.has(String(f.seller_id))
		) {
			f.seller = loginBySid.get(String(f.seller_id));
		}
	}
	for (const b of Array.isArray(bundles) ? bundles : []) {
		if (
			!b.seller &&
			b.seller_id != null &&
			loginBySid.has(String(b.seller_id))
		) {
			b.seller = loginBySid.get(String(b.seller_id));
		}
		for (const it of b.items || []) {
			const sid = it.seller_id || b.seller_id;
			if (!it.seller && sid != null && loginBySid.has(String(sid))) {
				it.seller = loginBySid.get(String(sid));
			}
			if (!it.seller && b.seller) it.seller = b.seller;
		}
	}

	const finds = sortScoreRows([...findsById.values()]);

	const dataSource =
		indexedSource === "cockroach"
			? `cockroach+${
					process.env.GITHUB_TOKEN && process.env.GITHUB_REPO
						? `github:${process.env.GITHUB_REPO}`
						: "json"
				}`
			: process.env.GITHUB_TOKEN && process.env.GITHUB_REPO
				? `github:${process.env.GITHUB_REPO}@${process.env.GITHUB_REF || "main"}`
				: "local-filesystem";

	const findsApplied = sortScoreRows(applyToFinds(finds, vetoes, { mode }));
	const keeps = findsApplied.filter((row) => isKeep(row)).length;
	const watchesFromFinds = [
		...new Set(findsApplied.map((f) => f.watch).filter(Boolean)),
	].sort();
	const bundlesApplied = assignBundleRanks(
		applyToBundles(Array.isArray(bundles) ? bundles : [], vetoes, { mode }).map(
			(row) => applyToRow(row),
		),
	);

	// Rebuild sellers from post-veto desk rows so Remove drops sold inventory
	// from Top sellers / one-off aggregates.
	const sellers = new Map();
	for (const f of findsApplied) {
		bumpSeller(sellers, {
			sid: f.seller_id,
			login: f.seller,
			country: f.seller_country,
			scoreRow: f,
			itemId: f.id,
			watch: f.watch,
		});
	}
	for (const b of bundlesApplied) {
		sellerEntry(sellers, {
			sid: b.seller_id,
			login: b.seller,
			country: b.country,
		});
		for (const it of b.items || []) {
			bumpSeller(sellers, {
				sid: it.seller_id || b.seller_id,
				login: it.seller || b.seller,
				country: b.country,
				scoreRow: it,
				itemId: it.id,
				watch: it.watch,
			});
		}
	}

	const sellerRows = [...sellers.values()]
		.map((row) => {
			const allScoreRows = [...row.score_rows.values()];
			const selected = sellerScoreRows(allScoreRows).filter(
				(scoreRow) => displayScore(scoreRow) != null,
			);
			const scores = selected.map(displayScore);
			const bands = {};
			for (const scoreRow of selected) {
				const band = isV2(scoreRow) ? scoreRow.buy_band : null;
				if (band) bands[band] = (bands[band] || 0) + 1;
			}
			const hasScore = selected.some(isV2);
			return {
				seller_id: row.seller_id,
				seller: row.seller || `user ${row.seller_id}`,
				country: row.country,
				listings: row.item_ids.size,
				keeps: selected.filter(isKeep).length,
				avg_score: scores.length
					? Math.round(
							(scores.reduce((sum, value) => sum + value, 0) / scores.length) *
								100,
						) / 100
					: null,
				best_score: scores.length ? Math.max(...scores) : null,
				score_version: hasScore ? 2 : null,
				score_tier: hasScore ? 2 : 0,
				bands,
				watches: [...row.watches].sort(),
				profile_url: row.seller_id
					? `https://www.vinted.ro/member/${row.seller_id}`
					: null,
			};
		})
		.sort(
			(a, b) =>
				b.score_tier - a.score_tier ||
				(b.best_score ?? -Infinity) - (a.best_score ?? -Infinity) ||
				(b.avg_score ?? -Infinity) - (a.avg_score ?? -Infinity) ||
				b.keeps - a.keeps,
		);

	return {
		finds: [],
		bundles: bundlesApplied,
		sellers: sellerRows,
		watches: findsSummary?.watches?.length
			? findsSummary.watches
			: watchesFromFinds,
		veto_mode: mode,
		run: {
			finished_at: run.finished_at || null,
			scored: run.scored ?? null,
			solo_keeps: run.solo_keeps ?? null,
			bundles: run.bundles ?? null,
			alerts: run.alerts ?? null,
			score_histogram: run.score_histogram || {},
			score_histogram_bins: histogramBins(run.score_histogram),
			seen_keys: (seen.seen_keys || []).length,
			run_count: seen.run_count ?? null,
			last_run: seen.last_run || null,
		},
		meta: {
			source: dataSource,
			generated_at: new Date().toISOString(),
			indexed_count: indexedTotal,
			indexed_source: indexedSource,
			veto_count: Object.keys(vetoes || {}).length,
			finds_total: findsSummary?.finds_total ?? findsApplied.length,
			keeps: findsSummary?.keeps ?? keeps,
			finds_paged: true,
		},
	};
}

export { buildSnapshot };
