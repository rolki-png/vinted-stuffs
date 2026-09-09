import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { exportRow, indexBundleOpportunities } from "../src/server/scoredDb.ts";
import { buildSnapshot } from "../src/server/snapshot.ts";

const root = fs.mkdtempSync(path.join(os.tmpdir(), "dashboard-snapshot-"));
const data = path.join(root, "data");
fs.mkdirSync(data);

const v2 = (id, buyScore, rankPosition, extra = {}) => ({
	id,
	watch: "Gym",
	title: `v2 ${id}`,
	price: 50,
	seller_id: 10,
	seller: "mixed-seller",
	score_version: 2,
	buy_score: buyScore,
	buy_band: "keep",
	score_confidence: 0.8,
	score_interval_low: buyScore - 5,
	score_interval_high: buyScore + 5,
	score_factors: { usefulness: buyScore },
	factor_evidence: { usefulness: "frequent use" },
	verification_concern: "none",
	verification_reason: "",
	rank_position: rankPosition,
	rank_confidence: "high",
	hunt_fit: true,
	has_score: true,
	...extra,
});

const exported = exportRow({
	item_id: 99,
	hunt_name: "Gym",
	title: "DB row",
	score_version: 2,
	buy_score: 89,
	buy_band: "keep",
	score_confidence: 0.75,
	score_interval_low: 84,
	score_interval_high: 94,
	score_factors: { usefulness: 89 },
	factor_evidence: { usefulness: "frequent use" },
	verification_concern: "inspect",
	verification_reason: "check seams",
	rank_position: 3,
	rank_confidence: "medium",
	deal_score: 10,
	value_band: "steal",
	scam_risk: "low",
	reason: "stale legacy reason",
	has_score: true,
});
assert.equal(exported.legacy_score, undefined);
assert.equal(exported.buy_score, 89);
assert.equal(exported.deal_score, null);
assert.equal(exported.value_band, undefined);
assert.equal(exported.reason, undefined);
assert.equal(exported.verification_reason, "check seams");
assert.deepEqual(exported.score_factors, { usefulness: 89 });
assert.deepEqual(exported.factor_evidence, { usefulness: "frequent use" });

const bundleRows = [
	v2(11, 90, 2),
	v2(12, 70, 1, { buy_band: "bundle" }),
	{
		id: 13,
		seller_id: 10,
		deal_score: 9,
		value_band: "steal",
		hunt_fit: true,
		has_score: true,
	},
	{
		id: 14,
		seller_id: 10,
		deal_score: 7,
		value_band: "acceptable",
		hunt_fit: true,
		has_score: true,
	},
];
const opportunities = indexBundleOpportunities(bundleRows);
assert.equal(opportunities.length, 1);
assert.deepEqual(
	opportunities[0].items.map((item) => item.id),
	[11, 12],
);
assert.equal(opportunities[0].family, "gym");
const v2Bundle = opportunities.find((bundle) => bundle.items[0].id === 11);
assert.equal(v2Bundle.items[0].buy_score, 90);
assert.equal(v2Bundle.items[0].legacy_score, undefined);
assert.ok(v2Bundle.bundle_score != null);

const familySplit = indexBundleOpportunities([
	v2(21, 71, 1, {
		buy_band: "bundle",
		watch: "Mamalicious maternity XL-L/XL",
		seller_id: 99,
	}),
	v2(22, 68, 2, {
		buy_band: "bundle",
		watch: "Seraphine maternity",
		seller_id: 99,
	}),
	v2(23, 72, 1, {
		buy_band: "bundle",
		watch: "Craft ADV M-L",
		seller_id: 99,
	}),
	v2(24, 64, 2, {
		buy_band: "bundle",
		watch: "Craft ADV M-L",
		seller_id: 99,
	}),
]);
assert.equal(familySplit.length, 2);
assert.deepEqual(
	familySplit.map((b) => b.family).sort(),
	["gym", "maternity"],
);
const mama = familySplit.find((b) => b.family === "maternity");
assert.deepEqual(mama.items.map((i) => i.id).sort(), [21, 22]);
assert.ok(mama.bundle_score != null);

fs.writeFileSync(
	path.join(data, "best_deals.json"),
	JSON.stringify([
		{
			id: 1,
			title: "old keep",
			seller_id: 10,
			seller: "mixed-seller",
			deal_score: 10,
			value_band: "steal",
			hunt_fit: true,
			reason: "legacy keep reason",
		},
		v2(6, 89, null, {
			seller_id: 30,
			seller: "standalone-v2",
			source: "keep",
			deal_score: 10,
			value_band: "steal",
			scam_risk: "low",
			reason: "stale legacy reason",
			verification_reason: "verify fabric",
		}),
		{
			id: 7,
			seller_id: 40,
			seller: "malformed-v2",
			score_version: 2,
			buy_score: 101,
			buy_band: "exceptional",
			deal_score: 10,
			value_band: "steal",
			reason: "must not become legacy",
		},
	]),
);
fs.writeFileSync(path.join(data, "best_bundles.json"), "[]");
fs.writeFileSync(
	path.join(data, "indexed_scores.json"),
	JSON.stringify([
		v2(1, 88, null),
		{
			id: 2,
			title: "legacy same seller",
			seller_id: 10,
			seller: "mixed-seller",
			deal_score: 9,
			value_band: "steal",
			hunt_fit: true,
			has_score: true,
		},
		{
			id: 3,
			title: "legacy only seller",
			watch: "Mamalicious maternity L-XL",
			seller_id: 20,
			seller: "legacy-seller",
			deal_score: 10,
			value_band: "steal",
			hunt_fit: true,
			has_score: true,
		},
		v2(4, 92, 2),
		v2(5, 86, 1),
		{
			id: 8,
			title: "valid legacy sibling",
			seller_id: 40,
			seller: "malformed-v2",
			deal_score: 8,
			value_band: "acceptable",
			hunt_fit: true,
			has_score: true,
		},
	]),
);
fs.writeFileSync(
	path.join(data, "bundle_pool.json"),
	JSON.stringify([
		{
			item: {
				id: 4,
				title: "stale pool copy",
				price: { amount: 50, currency_code: "RON" },
				user: { id: 10, login: "mixed-seller" },
			},
			watch: "Gym",
			score: {
				deal_score: 10,
				value_band: "steal",
				hunt_fit: true,
			},
		},
	]),
);
fs.writeFileSync(
	path.join(data, "last_run.json"),
	JSON.stringify({
		top: [
			{
				id: 5,
				deal_score: 10,
				value_band: "steal",
				hunt_fit: true,
			},
		],
		score_histogram: { "80-89": 4, "90-100": 2 },
	}),
);
fs.writeFileSync(path.join(data, "seen_listings.json"), "{}");

const previousCwd = process.cwd();
delete process.env.DATABASE_URL;
delete process.env.COCKROACH_DATABASE_URL;
delete process.env.GITHUB_TOKEN;
delete process.env.GITHUB_REPO;
try {
	process.chdir(root);
	const snapshot = await buildSnapshot();
	assert.deepEqual(snapshot.finds, []);
	assert.equal(snapshot.meta.finds_paged, true);
	assert.ok(Number(snapshot.meta.finds_total) >= 1);
	assert.ok(Array.isArray(snapshot.watches));
	assert.deepEqual(snapshot.watches, ["Gym"]);

	const mixedSeller = snapshot.sellers.find((row) => row.seller_id === 10);
	assert.equal(mixedSeller.score_version, 2);
	assert.equal(mixedSeller.best_score, 92);
	assert.equal(mixedSeller.avg_score, 88.67);
	assert.equal(mixedSeller.keeps, 3);
	assert.equal(mixedSeller.listings, 4);
	const legacySeller = snapshot.sellers.find((row) => row.seller_id === 20);
	assert.equal(legacySeller.score_tier, 0);
	assert.equal(legacySeller.avg_score, null);
	const mixedMalformedSeller = snapshot.sellers.find(
		(row) => row.seller_id === 40,
	);
	assert.equal(mixedMalformedSeller.score_version, null);
	assert.equal(mixedMalformedSeller.score_tier, 0);
	assert.equal(mixedMalformedSeller.avg_score, null);
	assert.deepEqual(snapshot.run.score_histogram_bins, [
		{ label: "80–89", count: 4 },
		{ label: "90–100", count: 2 },
	]);
} finally {
	process.chdir(previousCwd);
	fs.rmSync(root, { recursive: true, force: true });
}

{
	const staleRoot = fs.mkdtempSync(
		path.join(os.tmpdir(), "dashboard-snapshot-stale-index-"),
	);
	const staleData = path.join(staleRoot, "data");
	fs.mkdirSync(staleData);
	const huntKeep = v2(31, 91, 1, {
		seller_id: 7,
		seller: "hunt-keep",
		buy_band: "keep",
	});
	const huntExtra = v2(32, 70, 2, {
		seller_id: 7,
		seller: "hunt-keep",
		buy_band: "bundle",
	});
	const valueA = v2(41, 72, 1, {
		seller_id: 8,
		seller: "value-seller",
		buy_band: "bundle",
	});
	const valueB = v2(42, 66, 2, {
		seller_id: 8,
		seller: "value-seller",
		buy_band: "bundle",
	});
	const nearA = v2(51, 61, 1, {
		seller_id: 9,
		seller: "near-seller",
		buy_band: "bundle",
	});
	const nearB = v2(52, 62, 2, {
		seller_id: 9,
		seller: "near-seller",
		buy_band: "bundle",
	});
	const mamaA = v2(21, 71, 1, {
		buy_band: "bundle",
		watch: "Mamalicious maternity XL-L/XL",
		seller_id: 99,
	});
	const mamaB = v2(22, 68, 2, {
		buy_band: "bundle",
		watch: "Seraphine maternity",
		seller_id: 99,
	});
	const gymA = v2(23, 72, 1, {
		buy_band: "bundle",
		watch: "Craft ADV M-L",
		seller_id: 99,
	});
	const gymB = v2(24, 64, 2, {
		buy_band: "bundle",
		watch: "Craft ADV M-L",
		seller_id: 99,
	});
	for (const name of [
		"best_deals.json",
		"indexed_scores.json",
		"bundle_pool.json",
		"seen_listings.json",
	]) {
		fs.writeFileSync(path.join(staleData, name), name === "seen_listings.json" ? "{}" : "[]");
	}
	fs.writeFileSync(path.join(staleData, "last_run.json"), "{}");
	fs.writeFileSync(
		path.join(staleData, "best_bundles.json"),
		JSON.stringify([
			{
				kind: "keep_bundle",
				seller_id: 7,
				seller: "hunt-keep",
				items: [huntKeep, huntExtra],
			},
			{
				kind: "value_haul",
				seller_id: 8,
				seller: "value-seller",
				items: [valueA, valueB],
			},
			{
				kind: "near_haul",
				seller_id: 9,
				seller: "near-seller",
				items: [nearA, nearB],
			},
			{
				kind: "index_near_bundle",
				seller_id: 99,
				seller: "mixed-seller",
				items: [mamaA, mamaB, gymA, gymB],
			},
			{
				kind: "index_keep_bundle",
				seller_id: 99,
				seller: "mixed-seller",
				items: [mamaA, gymA],
			},
		]),
	);
	const staleCwd = process.cwd();
	delete process.env.DATABASE_URL;
	delete process.env.COCKROACH_DATABASE_URL;
	delete process.env.GITHUB_TOKEN;
	delete process.env.GITHUB_REPO;
	try {
		process.chdir(staleRoot);
		const snapshot = await buildSnapshot({
			dbIndexed: {
				rows: [mamaA, mamaB, gymA, gymB],
				count: 4,
				source: "cockroach",
			},
		});
		const gitIndexKinds = snapshot.bundles.filter(
			(b) =>
				b.kind === "index_keep_bundle" || b.kind === "index_near_bundle",
		);
		assert.equal(
			gitIndexKinds.some((b) => b.items.map((i) => i.id).sort().join(",") === "21,22,23,24"),
			false,
		);
		assert.equal(
			gitIndexKinds.some((b) => b.items.map((i) => i.id).sort().join(",") === "21,23"),
			false,
		);
		assert.equal(gitIndexKinds.length, 2);
		assert.deepEqual(
			gitIndexKinds.map((b) => b.family).sort(),
			["gym", "maternity"],
		);
		assert.ok(snapshot.bundles.some((b) => b.kind === "keep_bundle"));
		assert.ok(snapshot.bundles.some((b) => b.kind === "value_haul"));
		assert.ok(snapshot.bundles.some((b) => b.kind === "near_haul"));
	} finally {
		process.chdir(staleCwd);
		fs.rmSync(staleRoot, { recursive: true, force: true });
	}
}

{
	const enrichRoot = fs.mkdtempSync(
		path.join(os.tmpdir(), "dashboard-snapshot-enrich-bundles-"),
	);
	const enrichData = path.join(enrichRoot, "data");
	fs.mkdirSync(enrichData);
	for (const name of [
		"best_deals.json",
		"indexed_scores.json",
		"bundle_pool.json",
		"seen_listings.json",
	]) {
		fs.writeFileSync(
			path.join(enrichData, name),
			name === "seen_listings.json" ? "{}" : "[]",
		);
	}
	fs.writeFileSync(path.join(enrichData, "last_run.json"), "{}");
	fs.writeFileSync(
		path.join(enrichData, "best_bundles.json"),
		JSON.stringify([
			{
				kind: "keep_bundle",
				seller_id: 77,
				seller: "legacy-cart",
				items: [
					{
						role: "keep",
						id: 701,
						title: "legacy keep",
						price: 40,
						deal_score: 8,
						watch: "Mamalicious maternity XL-L/XL",
					},
					{
						role: "extra",
						id: 702,
						title: "legacy extra",
						price: 35,
						deal_score: 7,
						watch: "Mamalicious maternity XL-L/XL",
					},
				],
			},
		]),
	);
	const enrichCwd = process.cwd();
	delete process.env.DATABASE_URL;
	delete process.env.COCKROACH_DATABASE_URL;
	delete process.env.GITHUB_TOKEN;
	delete process.env.GITHUB_REPO;
	try {
		process.chdir(enrichRoot);
		const snapshot = await buildSnapshot({
			dbIndexed: {
				rows: [
					v2(701, 88, 1, {
						buy_band: "keep",
						watch: "Mamalicious maternity XL-L/XL",
						seller_id: 77,
						seller: "legacy-cart",
						score_confidence: 0.82,
					}),
					v2(702, 66, 2, {
						buy_band: "bundle",
						watch: "Mamalicious maternity XL-L/XL",
						seller_id: 77,
						seller: "legacy-cart",
						score_confidence: 0.8,
					}),
				],
				count: 2,
				source: "cockroach",
			},
		});
		const cart = snapshot.bundles.find(
			(b) =>
				b.seller_id === 77 &&
				(b.items || []).some((it) => it.id === 701) &&
				(b.items || []).some((it) => it.id === 702),
		);
		assert.ok(cart);
		const byId = Object.fromEntries(
			(cart.items || []).map((it) => [String(it.id), it]),
		);
		assert.equal(byId["701"].buy_score, 88);
		assert.equal(byId["702"].buy_score, 66);
		assert.ok(cart.bundle_score != null);
		assert.ok(cart.bundle_rank_position != null);
	} finally {
		process.chdir(enrichCwd);
		fs.rmSync(enrichRoot, { recursive: true, force: true });
	}
}

console.log("ok dashboard-snapshot");
