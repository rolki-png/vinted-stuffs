import assert from "node:assert/strict";
import {
	displayScore,
	histogramBins,
	isKeep,
	isV2,
	mergeScoreRows,
	preferredScoreRow,
	scoreFields,
	sellerScoreRows,
	sortBundleScoreRows,
	sortScoreRows,
	v2WatchNames,
} from "../src/server/scoreSemantics.js";

const v2 = {
	score_version: 2,
	buy_score: 88,
	buy_band: "keep",
	score_confidence: 0.7,
	hunt_fit: true,
	verification_concern: "none",
};
const leftover = { deal_score: 9, value_band: "steal", hunt_fit: true };
const malformedV2 = {
	score_version: 2,
	buy_score: 101,
	buy_band: "exceptional",
	deal_score: 10,
	value_band: "steal",
	hunt_fit: true,
};
assert.equal(displayScore(v2), 88);
assert.equal(displayScore(leftover), null);
assert.equal(displayScore({}), null);
assert.equal(isV2({ ...v2, buy_score: null }), false);
for (const buyScore of [-1, 100.5, 101, true, ""]) {
	assert.equal(isV2({ ...v2, buy_score: buyScore }), false);
}
assert.equal(displayScore(malformedV2), null);
assert.equal(isKeep(malformedV2), false);
assert.equal(isKeep(v2), true);
assert.equal(isKeep({ ...v2, score_confidence: 0.59 }), false);
assert.equal(isKeep(leftover), false);
assert.deepEqual(sellerScoreRows([leftover, v2]), [v2]);
assert.deepEqual(sellerScoreRows([malformedV2, leftover]), []);
assert.equal(preferredScoreRow(leftover, v2), v2);
assert.equal(preferredScoreRow(v2, leftover), v2);
assert.deepEqual(
	mergeScoreRows(
		{
			id: 7,
			title: "old title",
			source: "keep",
			reason: "old reason",
			...leftover,
		},
		{
			id: 7,
			source: "index",
			...v2,
			score_factors: { value: 91 },
			factor_evidence: { value: "strong utility" },
			verification_reason: "check care label",
		},
	),
	{
		id: 7,
		title: "old title",
		source: "keep",
		...v2,
		score_factors: { value: 91 },
		factor_evidence: { value: "strong utility" },
		verification_reason: "check care label",
	},
);
assert.equal(
	mergeScoreRows(
		{ id: 8, source: "keep", ...leftover },
		{
			id: 8,
			source: "index",
			...v2,
			buy_score: 70,
			buy_band: "bundle",
		},
	).source,
	"index",
);
assert.deepEqual(
	scoreFields({
		...v2,
		score_interval_low: "82",
		score_interval_high: 93,
		score_factors: { value: 91 },
		factor_evidence: { value: "strong utility" },
		verification_reason: "check fabric",
		rank_position: "2",
		rank_confidence: "medium",
	}),
	{
		score_version: 2,
		buy_score: 88,
		buy_band: "keep",
		score_confidence: 0.7,
		score_interval_low: 82,
		score_interval_high: 93,
		score_factors: { value: 91 },
		factor_evidence: { value: "strong utility" },
		verification_concern: "none",
		verification_reason: "check fabric",
		rank_position: 2,
		rank_confidence: "medium",
	},
);
assert.deepEqual(
	scoreFields({
		...v2,
		score_factors: '{"value":91}',
		factor_evidence: null,
	}).score_factors,
	{ value: 91 },
);
assert.deepEqual(
	scoreFields({ ...v2, factor_evidence: null }).factor_evidence,
	{},
);
const boundedMalformed = scoreFields(malformedV2);
assert.equal(boundedMalformed.score_version, 2);
assert.equal(boundedMalformed.buy_score, null);
assert.equal(boundedMalformed.buy_band, null);
assert.equal(boundedMalformed.legacy_score, undefined);
assert.deepEqual(
	sortScoreRows([
		{ id: 1, ...leftover, deal_score: 10 },
		{
			id: 2,
			...v2,
			buy_score: 92,
			rank_position: 2,
			rank_confidence: "high",
		},
		{
			id: 3,
			...v2,
			buy_score: 86,
			rank_position: 1,
			rank_confidence: "high",
		},
		{ id: 4, ...v2, buy_score: 80, rank_position: null },
	]).map((row) => row.id),
	[2, 3, 4, 1],
);
assert.deepEqual(
	sortScoreRows([
		{ id: "valid", ...v2 },
		{ id: "leftover", ...leftover },
		{ id: "malformed", ...malformedV2 },
	]).map((row) => row.id),
	["valid", "leftover", "malformed"],
);
assert.deepEqual(
	sortScoreRows([
		{
			id: "old-ranked",
			...v2,
			buy_score: 80,
			rank_position: 1,
			rank_confidence: "high",
		},
		{
			id: "new-unranked",
			...v2,
			buy_score: 95,
			rank_position: null,
			rank_confidence: null,
		},
	]).map((row) => row.id),
	["new-unranked", "old-ranked"],
);
assert.deepEqual(
	sortScoreRows([
		{
			id: "rank-two",
			...v2,
			buy_score: 95,
			rank_position: 2,
			rank_confidence: "high",
		},
		{
			id: "rank-one",
			...v2,
			buy_score: 80,
			rank_position: 1,
			rank_confidence: "medium",
		},
	]).map((row) => row.id),
	["rank-one", "rank-two"],
);
assert.deepEqual(
	sortScoreRows([
		{
			id: "rank-one-old",
			...v2,
			buy_score: 80,
			rank_position: 1,
			rank_confidence: "high",
		},
		{
			id: "rank-two-old",
			...v2,
			buy_score: 95,
			rank_position: 2,
			rank_confidence: "high",
		},
		{
			id: "new-unranked-middle",
			...v2,
			buy_score: 90,
		},
	]).map((row) => row.id),
	["rank-two-old", "new-unranked-middle", "rank-one-old"],
);
assert.deepEqual(
	sortBundleScoreRows([
		{ id: "keep-tie", ...v2, buy_score: 95, buy_band: "keep" },
		{
			id: "exceptional-tie",
			...v2,
			buy_score: 95,
			buy_band: "exceptional",
		},
		{ id: "leftover-hunt", ...leftover, deal_score: 9, value_band: "hunt" },
		{ id: "leftover-steal", ...leftover, deal_score: 9, value_band: "steal" },
	]).map((row) => row.id),
	["keep-tie", "exceptional-tie", "leftover-hunt", "leftover-steal"],
);
assert.deepEqual(histogramBins({ "80-89": 4, "90-100": 2 }), [
	{ label: "80–89", count: 4 },
	{ label: "90–100", count: 2 },
]);
assert.deepEqual(
	v2WatchNames([
		{
			watch: "Mamalicious maternity L-XL",
			deal_score: 8,
			has_score: true,
			reason: "Correct brand, right size (XL), and good price for knitwear.",
		},
		{ watch: "Mamalicious maternity XL-L/XL", ...v2 },
		{ watch: "Mamalicious maternity XL-L/XL", ...v2, id: 2 },
	]),
	["Mamalicious maternity XL-L/XL"],
);
console.log("ok score-semantics");
