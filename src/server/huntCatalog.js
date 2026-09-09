// @ts-nocheck
/**
 * Brand-id hunts match Vinted catalog by brand, not listing title keywords.
 * Used so Finds does not keep showing old keyword-search junk.
 */
import fs from "node:fs";
import path from "node:path";

function loadHuntsFromConfig() {
	const file = path.join(process.cwd(), "python", "config.json");
	try {
		const cfg = JSON.parse(fs.readFileSync(file, "utf8"));
		return Array.isArray(cfg.watches) ? cfg.watches : [];
	} catch {
		return [];
	}
}

function catalogBrandNeedles(query) {
	const q = String(query || "").trim().toLowerCase();
	if (!q) return [];
	const stop = new Set([
		"leggings",
		"maternity",
		"dress",
		"shorts",
		"gym",
		"running",
		"technical",
		"polo",
		"size",
		"training",
	]);
	const needles = [];
	for (const token of q.replace(/[/-]/g, " ").split(/\s+/).filter(Boolean)) {
		if (stop.has(token) || /^\d+$/.test(token)) continue;
		if (token.length < 4 && !/[0-9&]/.test(token)) continue;
		if (!needles.includes(token)) needles.push(token);
	}
	return needles;
}

function listingMatchesHuntCatalog(listing, watch) {
	const ids = watch?.brand_ids;
	if (!Array.isArray(ids) || !ids.length) return true;
	const brand = String(listing?.brand || "").trim().toLowerCase();
		if (!brand) return false;
	const needles = catalogBrandNeedles(watch.query);
	if (!needles.length) return true;
	return needles.some((n) => brand.includes(n));
}

function brandedHunts(hunts) {
	return (hunts || []).filter(
		(w) =>
			Array.isArray(w?.brand_ids) &&
			w.brand_ids.length &&
			String(w.query || "").trim(),
	);
}

/**
 * SQL fragment: brand-id hunts only keep rows whose stored brand contains the hunt query.
 * `params` is mutated. Column prefix defaults to `best` (finds CTE).
 */
function catalogBrandSql(hunts, params, column = "best") {
	const branded = brandedHunts(hunts);
	if (!branded.length) return "TRUE";
	const notBranded = [];
	const matched = [];
	for (const w of branded) {
		params.push(w.name);
		notBranded.push(`$${params.length}`);
		params.push(w.name);
		const nameIdx = params.length;
		const needles = catalogBrandNeedles(w.query);
		if (!needles.length) {
			matched.push(`${column}.hunt_name = $${nameIdx}`);
			continue;
		}
		const needleSql = needles.map((n) => {
			params.push(`%${n}%`);
			return `COALESCE(${column}.brand, '') ILIKE $${params.length}`;
		});
		matched.push(
			`(${column}.hunt_name = $${nameIdx} AND (${needleSql.join(" OR ")}))`,
		);
	}
	return `(${column}.hunt_name NOT IN (${notBranded.join(", ")}) OR ${matched.join(" OR ")})`;
}

function filterRowsToHuntCatalog(rows, hunts) {
	const byName = new Map((hunts || []).map((w) => [w.name, w]));
	return (rows || []).filter((row) => {
		const watch = byName.get(row.watch);
		if (!watch) return true;
		return listingMatchesHuntCatalog(listingBrandRow(row), watch);
	});
}

function listingBrandRow(row) {
	return { brand: row.brand, watch: row.watch };
}

export {
	brandedHunts,
	catalogBrandNeedles,
	catalogBrandSql,
	filterRowsToHuntCatalog,
	listingMatchesHuntCatalog,
	loadHuntsFromConfig,
};
