import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { buildFindsPage, parseFilters } from "../src/server/findsPage.js";

assert.equal(parseFilters({ page: "2", limit: "50" }).page, 2);
assert.equal(parseFilters({ limit: "999" }).limit, 100);
assert.equal(parseFilters({}).limit, 50);
assert.equal(parseFilters({ family: "maternity" }).family, "maternity");
assert.equal(parseFilters({ family: "nope" }).family, "");
assert.equal(parseFilters({}).family, "");

const root = fs.mkdtempSync(path.join(os.tmpdir(), "finds-page-"));
const data = path.join(root, "data");
fs.mkdirSync(data);

const rows = [];
for (let i = 1; i <= 60; i += 1) {
	rows.push({
		id: i,
		title: `item ${i}`,
		watch: "Gym",
		seller: "s",
		seller_id: 1,
		score_version: 2,
		buy_score: 100 - (i % 40),
		buy_band: "keep",
		score_confidence: 0.8,
		score_interval_low: 80,
		score_interval_high: 95,
		verification_concern: "none",
		hunt_fit: true,
		has_score: true,
		price: 10 + i,
		source: "index",
	});
}
fs.writeFileSync(path.join(data, "indexed_scores.json"), JSON.stringify(rows));
fs.writeFileSync(path.join(data, "best_deals.json"), "[]");
fs.writeFileSync(path.join(data, "bundle_pool.json"), "[]");
fs.writeFileSync(path.join(data, "last_run.json"), "{}");
fs.writeFileSync(path.join(data, "seen_listings.json"), "{}");

const previousCwd = process.cwd();
delete process.env.DATABASE_URL;
delete process.env.COCKROACH_DATABASE_URL;
delete process.env.GITHUB_TOKEN;
delete process.env.GITHUB_REPO;
try {
	process.chdir(root);
	const page1 = await buildFindsPage({
		page: 1,
		limit: 50,
		sort: "score-desc",
	});
	assert.equal(page1.finds.length, 50);
	assert.equal(page1.total, 60);
	assert.equal(page1.pages, 2);
	assert.equal(page1.page, 1);
	const page2 = await buildFindsPage({
		page: 2,
		limit: 50,
		sort: "score-desc",
	});
	assert.equal(page2.finds.length, 10);
	assert.equal(page2.page, 2);
	const filtered = await buildFindsPage({
		page: 1,
		limit: 50,
		min_score: "95",
	});
	assert.ok(filtered.finds.every((row) => Number(row.buy_score) >= 95));
	assert.ok(filtered.total < 60);
} finally {
	process.chdir(previousCwd);
	fs.rmSync(root, { recursive: true, force: true });
}

const legacyRoot = fs.mkdtempSync(path.join(os.tmpdir(), "finds-legacy-"));
const legacyData = path.join(legacyRoot, "data");
fs.mkdirSync(legacyData);
fs.writeFileSync(
	path.join(legacyData, "indexed_scores.json"),
	JSON.stringify([
		{
			id: 9572667753,
			title: "Rochie lungă de vară alăptat L",
			watch: "Mamalicious maternity L-XL",
			seller: "cosinna29",
			deal_score: 3,
			value_band: "skip",
			has_score: true,
			reason:
				"Size is indicated as L but the listing is not explicitly confirmed for the target fit and represents a single piece of low-value clothing.",
			source: "index",
		},
		{
			id: 9928503543,
			title: "Super sukienka do karmienia piersią",
			watch: "Mamalicious maternity XL-L/XL",
			seller: "nataliab-r",
			score_version: 2,
			buy_score: 0,
			buy_band: "skip",
			score_confidence: 0.75,
			hunt_fit: false,
			has_score: true,
			source: "index",
		},
	]),
);
fs.writeFileSync(path.join(legacyData, "best_deals.json"), "[]");
fs.writeFileSync(path.join(legacyData, "bundle_pool.json"), "[]");
fs.writeFileSync(path.join(legacyData, "last_run.json"), "{}");
fs.writeFileSync(path.join(legacyData, "seen_listings.json"), "{}");

const legacyCwd = process.cwd();
delete process.env.DATABASE_URL;
delete process.env.COCKROACH_DATABASE_URL;
delete process.env.GITHUB_TOKEN;
delete process.env.GITHUB_REPO;
try {
	process.chdir(legacyRoot);
	const page = await buildFindsPage({
		page: 1,
		limit: 50,
		sort: "score-desc",
	});
	assert.equal(page.total, 1);
	assert.equal(page.finds.length, 1);
	assert.equal(page.finds[0].watch, "Mamalicious maternity XL-L/XL");
	const oldHunt = await buildFindsPage({
		page: 1,
		limit: 50,
		watch: "Mamalicious maternity L-XL",
	});
	assert.equal(oldHunt.total, 1);
	assert.equal(oldHunt.finds[0].id, 9928503543);
	assert.equal(oldHunt.finds[0].watch, "Mamalicious maternity XL-L/XL");
} finally {
	process.chdir(legacyCwd);
	fs.rmSync(legacyRoot, { recursive: true, force: true });
}

const desk = fs.readFileSync(
	new URL("../src/components/DealDesk.tsx", import.meta.url),
	"utf8",
);
const catalogRoot = fs.mkdtempSync(path.join(os.tmpdir(), "finds-catalog-"));
const catalogData = path.join(catalogRoot, "data");
fs.mkdirSync(catalogData);
fs.mkdirSync(path.join(catalogRoot, "python"));
fs.writeFileSync(
	path.join(catalogRoot, "python", "config.json"),
	JSON.stringify({
		watches: [
			{
				name: "Ten Thousand gym M-L",
				query: "ten thousand",
				brand_ids: [3162601],
			},
		],
	}),
);
fs.writeFileSync(
	path.join(catalogData, "indexed_scores.json"),
	JSON.stringify([
		{
			id: 1,
			title: "An Abundance of Katherines - John Green ENG",
			watch: "Ten Thousand gym M-L",
			brand: "Penguin",
			seller: "dommypt",
			score_version: 2,
			buy_score: 0,
			buy_band: "skip",
			score_confidence: 0,
			has_score: true,
			source: "index",
		},
		{
			id: 2,
			title: "Interval Shorts",
			watch: "Ten Thousand gym M-L",
			brand: "Ten Thousand",
			seller: "real",
			score_version: 2,
			buy_score: 10,
			buy_band: "skip",
			score_confidence: 0.4,
			has_score: true,
			source: "index",
		},
	]),
);
fs.writeFileSync(path.join(catalogData, "best_deals.json"), "[]");
fs.writeFileSync(path.join(catalogData, "bundle_pool.json"), "[]");
fs.writeFileSync(path.join(catalogData, "last_run.json"), "{}");
fs.writeFileSync(path.join(catalogData, "seen_listings.json"), "{}");

const catalogCwd = process.cwd();
delete process.env.DATABASE_URL;
delete process.env.COCKROACH_DATABASE_URL;
delete process.env.GITHUB_TOKEN;
delete process.env.GITHUB_REPO;
try {
	process.chdir(catalogRoot);
	const page = await buildFindsPage({
		page: 1,
		limit: 50,
		watch: "Ten Thousand gym M-L",
	});
	assert.equal(page.total, 1);
	assert.equal(page.finds[0].id, 2);
} finally {
	process.chdir(catalogCwd);
	fs.rmSync(catalogRoot, { recursive: true, force: true });
}

const familyRoot = fs.mkdtempSync(path.join(os.tmpdir(), "finds-family-"));
const familyData = path.join(familyRoot, "data");
fs.mkdirSync(familyData);
const v2Find = (id, watch, buyScore) => ({
	id,
	title: `${watch} ${id}`,
	watch,
	seller: "s",
	score_version: 2,
	buy_score: buyScore,
	buy_band: buyScore >= 85 ? "keep" : "skip",
	score_confidence: 0.8,
	hunt_fit: true,
	has_score: true,
	source: "index",
});
fs.writeFileSync(
	path.join(familyData, "indexed_scores.json"),
	JSON.stringify([
		v2Find(1, "Lululemon gym M-L", 92),
		v2Find(2, "Mamalicious maternity XL-L/XL", 71),
		v2Find(3, "Seraphine maternity XL-L/XL", 88),
	]),
);
fs.writeFileSync(path.join(familyData, "best_deals.json"), "[]");
fs.writeFileSync(path.join(familyData, "bundle_pool.json"), "[]");
fs.writeFileSync(path.join(familyData, "last_run.json"), "{}");
fs.writeFileSync(path.join(familyData, "seen_listings.json"), "{}");
const familyCwd = process.cwd();
delete process.env.DATABASE_URL;
delete process.env.COCKROACH_DATABASE_URL;
delete process.env.GITHUB_TOKEN;
delete process.env.GITHUB_REPO;
try {
	process.chdir(familyRoot);
	const page = await buildFindsPage({
		page: 1,
		limit: 50,
		family: "maternity",
		sort: "score-desc",
	});
	assert.equal(page.total, 2);
	assert.deepEqual(
		page.finds.map((row) => row.id),
		[3, 2],
	);
} finally {
	process.chdir(familyCwd);
	fs.rmSync(familyRoot, { recursive: true, force: true });
}

assert.match(desk, /\/api\/finds/);
assert.match(desk, /setPage/);
assert.match(desk, /Prev/);
assert.match(desk, /Family/);
assert.match(desk, /<option value="maternity">/);

console.log("ok finds-page");
