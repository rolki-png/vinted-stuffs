import assert from "node:assert/strict";
import fs from "node:fs";
import {
	coerceEnrichment,
	ENRICHMENT_FIELDS,
	mergeEnrichment,
	scoreUpdateDecision,
} from "../src/server/listingVetoEnrichment.js";

for (const field of ["score_version", "buy_score", "buy_band"]) {
	assert.ok(ENRICHMENT_FIELDS.includes(field));
}

const v2 = mergeEnrichment(
	{ deal_score: 9, value_band: "steal" },
	coerceEnrichment({
		score_version: 2,
		buy_score: "88",
		buy_band: "keep",
	}),
);
assert.equal(v2.score_version, 2);
assert.equal(v2.buy_score, 88);
assert.equal(v2.buy_band, "keep");
assert.equal(v2.deal_score, null);
assert.equal(v2.value_band, null);

const metadataOnly = mergeEnrichment(
	v2,
	coerceEnrichment({ title: "updated" }),
);
assert.equal(metadataOnly.score_version, 2);
assert.equal(metadataOnly.buy_score, 88);
assert.equal(metadataOnly.buy_band, "keep");

const overwritten = mergeEnrichment(
	v2,
	coerceEnrichment({ deal_score: 9, value_band: "steal" }),
);
assert.equal(overwritten.score_version, 2);
assert.equal(overwritten.buy_score, 88);
assert.equal(overwritten.buy_band, "keep");
assert.equal(overwritten.deal_score, null);
assert.equal(overwritten.value_band, null);

assert.equal(
	scoreUpdateDecision(
		coerceEnrichment({
			score_version: 2,
			buy_score: 88,
			buy_band: "keep",
		}),
	),
	"v2",
);
assert.equal(
	scoreUpdateDecision(coerceEnrichment({ score_version: 2, buy_score: 88 })),
	"preserve",
);
assert.equal(
	scoreUpdateDecision(
		coerceEnrichment({
			score_version: 2,
			buy_score: 101,
			buy_band: "exceptional",
			deal_score: 9,
			value_band: "steal",
		}),
	),
	"preserve",
);
assert.equal(
	scoreUpdateDecision(coerceEnrichment({ deal_score: 9 })),
	"preserve",
);
assert.equal(
	scoreUpdateDecision(coerceEnrichment({ deal_score: 9, value_band: "steal" })),
	"preserve",
);

const legacyContext = coerceEnrichment({
	deal_score: 9,
	value_band: "steal",
	title: "old",
});
const partialV2 = mergeEnrichment(
	legacyContext,
	coerceEnrichment({
		score_version: 2,
		buy_score: 88,
		title: "new metadata",
	}),
);
assert.equal(partialV2.deal_score, null);
assert.equal(partialV2.value_band, null);
assert.equal(partialV2.score_version, null);
assert.equal(partialV2.title, "new metadata");

const partialLegacy = mergeEnrichment(
	v2,
	coerceEnrichment({ deal_score: 10, title: "metadata only" }),
);
assert.equal(partialLegacy.score_version, 2);
assert.equal(partialLegacy.buy_score, 88);
assert.equal(partialLegacy.buy_band, "keep");
assert.equal(partialLegacy.deal_score, null);
assert.equal(partialLegacy.title, "metadata only");

const routeSource = fs.readFileSync(
	new URL("../src/routes/api/veto.ts", import.meta.url),
	"utf8",
);
const storeSource = fs.readFileSync(
	new URL("../src/server/listingVetoes.ts", import.meta.url),
	"utf8",
);
const migrationSource = fs.readFileSync(
	new URL("../python/sql/005_listing_veto_v2_scores.sql", import.meta.url),
	"utf8",
);
for (const [field, sqlType] of Object.entries({
	score_version: "INT",
	buy_score: "INT",
	buy_band: "TEXT",
})) {
	assert.match(routeSource, new RegExp(`['"]${field}['"]`));
	assert.match(storeSource, new RegExp(`${field} ${sqlType} NULL`));
	assert.match(
		storeSource,
		new RegExp(`ADD COLUMN IF NOT EXISTS ${field} ${sqlType} NULL`),
	);
	assert.match(migrationSource, new RegExp(`${field} ${sqlType} NULL`));
}

console.log("ok listing-veto-v2");
