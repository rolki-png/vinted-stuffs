const ENRICHMENT_FIELDS = [
	"hunt_name",
	"hunt_family",
	"brand",
	"size",
	"price_ron",
	"value_band",
	"deal_score",
	"score_version",
	"buy_score",
	"buy_band",
	"title",
];

const INTEGER_FIELDS = new Set(["deal_score", "score_version", "buy_score"]);
const SCORE_FIELDS = [
	"value_band",
	"deal_score",
	"score_version",
	"buy_score",
	"buy_band",
];
const ALLOWED_BUY_BANDS = new Set([
	"skip",
	"bundle",
	"good",
	"keep",
	"exceptional",
]);

function coerceEnrichment(enrichment) {
	const out = Object.fromEntries(ENRICHMENT_FIELDS.map((key) => [key, null]));
	if (!enrichment || typeof enrichment !== "object") return out;
	for (const key of ENRICHMENT_FIELDS) {
		if (enrichment[key] == null) continue;
		if (key === "price_ron") {
			const value = Number(enrichment[key]);
			out[key] = Number.isFinite(value) ? value : null;
		} else if (INTEGER_FIELDS.has(key)) {
			const value = Number(enrichment[key]);
			out[key] =
				typeof enrichment[key] !== "boolean" &&
				!(
					typeof enrichment[key] === "string" && enrichment[key].trim() === ""
				) &&
				Number.isInteger(value)
					? value
					: null;
		} else {
			const value = String(enrichment[key]).trim();
			out[key] = value || null;
		}
	}
	return out;
}

function scoreUpdateDecision(enrichment) {
	const hasV2Input =
		enrichment &&
		typeof enrichment === "object" &&
		["score_version", "buy_score", "buy_band"].some(
			(key) => Object.hasOwn(enrichment, key) && enrichment[key] != null,
		);
	const value = coerceEnrichment(enrichment);
	if (
		value.score_version === 2 &&
		Number.isInteger(value.buy_score) &&
		value.buy_score >= 0 &&
		value.buy_score <= 100 &&
		ALLOWED_BUY_BANDS.has(value.buy_band)
	) {
		return "v2";
	}
	if (hasV2Input) return "preserve";
	return "preserve";
}

function prepareEnrichmentForWrite(enrichment) {
	const value = coerceEnrichment(enrichment);
	const scoreUpdateKind = scoreUpdateDecision(enrichment);
	if (scoreUpdateKind === "v2") {
		value.deal_score = null;
		value.value_band = null;
	} else {
		for (const key of SCORE_FIELDS) value[key] = null;
	}
	return { enrichment: value, scoreUpdateKind };
}

function mergeEnrichment(previous, incoming) {
	const currentPrepared = prepareEnrichmentForWrite(previous);
	const incomingPrepared = prepareEnrichmentForWrite(incoming);
	const current = currentPrepared.enrichment;
	const next = incomingPrepared.enrichment;
	const merged = {};
	for (const key of ENRICHMENT_FIELDS.filter(
		(key) => !SCORE_FIELDS.includes(key),
	)) {
		merged[key] = next[key] != null ? next[key] : current[key];
	}
	const scoreSource =
		incomingPrepared.scoreUpdateKind === "preserve" ? current : next;
	for (const key of SCORE_FIELDS) {
		merged[key] = scoreSource[key];
	}
	return merged;
}

export {
	ALLOWED_BUY_BANDS,
	coerceEnrichment,
	ENRICHMENT_FIELDS,
	mergeEnrichment,
	prepareEnrichmentForWrite,
	scoreUpdateDecision,
};
