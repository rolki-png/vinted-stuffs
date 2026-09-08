export interface ScoreRow {
	score_version?: number | null;
	buy_score?: number | null;
	buy_band?: string | null;
	score_confidence?: number | null;
	score_interval_low?: number | null;
	score_interval_high?: number | null;
	score_factors?: Record<string, unknown> | null;
	factor_evidence?: Record<string, unknown> | null;
	verification_concern?: string | null;
	verification_reason?: string | null;
	rank_position?: number | null;
	rank_confidence?: string | null;
	legacy_score?: boolean;
	hunt_fit?: boolean;
	deal_score?: number | null;
	value_band?: string | null;
	veto_status?: string | null;
	source?: string | null;
	watch?: string | null;
	brand?: string | null;
	size?: string | null;
	price?: number | null;
	price_num?: number | null;
	title?: string | null;
	kept_at?: string | null;
}

export interface SellerScoreRow {
	score_version?: number | null;
	legacy_score?: boolean;
	score_tier?: number | null;
	best_score?: number | null;
	avg_score?: number | null;
	keeps?: number | null;
	listings?: number | null;
}

export interface FactorRow {
	key: string;
	label: string;
	value: string;
	evidence: string;
}

export interface HistogramRow {
	label: string;
	count: number;
}

export interface UsableRank {
	position: number;
	confidence: "low" | "medium" | "high";
}

export interface BandPresentation {
	label: string;
	className: string;
}

export interface VetoPayload {
	item_id: number;
	status?: string;
	clear?: true;
	hunt_name?: string | null;
	brand?: string | null;
	size?: string | null;
	price_ron?: number | null;
	title?: string | null;
	score_version?: 2;
	buy_score?: number;
	buy_band?: string;
	deal_score?: number;
	value_band?: string;
	reason_code?: string;
}

export function isDeclaredV2(row: unknown): row is ScoreRow & {
	score_version: 2;
};
export function isV2(row: unknown): row is ScoreRow & {
	score_version: 2;
	buy_score: number;
};
export function isKeep(row: unknown): boolean;
export function numericScore(row: ScoreRow | null | undefined): number;
export function filterScore(row: ScoreRow | null | undefined): number | null;
export function matchesScoreFilter(
	row: ScoreRow | null | undefined,
	filter: string,
): boolean;
export function matchesBandFilter(
	row: ScoreRow | null | undefined,
	filter: string,
): boolean;
export function scoreLabel(row: ScoreRow | null | undefined): string;
export function scoreScaleLabel(row: ScoreRow | null | undefined): string;
export function usableRank(row: ScoreRow | null | undefined): UsableRank | null;
export function buyBandPresentation(
	row: ScoreRow | null | undefined,
): BandPresentation;
export function findComparator<T extends ScoreRow>(
	sort: string,
	options?: { useRanks?: boolean },
): (left: T, right: T) => number;
export function sortFinds<T extends ScoreRow>(
	rows: readonly T[] | null | undefined,
	sort: string,
): T[];
export function sortBundles<
	T extends {
		bundle_score?: number | null;
		bundle_rank_position?: number | null;
		kept_at?: string | null;
	},
>(rows: readonly T[] | null | undefined, sort: string): T[];
export function bundleConfidenceLabel(
	confidence: number | null | undefined,
): "low" | "medium" | "high" | null;
export function keepCounts(rows: readonly ScoreRow[] | null | undefined): {
	keeps: number;
};
export function sellerComparator<T extends SellerScoreRow>(
	sort: string,
): (left: T, right: T) => number;
export function vetoScoreContext(
	row: ScoreRow | null | undefined,
):
	| { score_version: 2; buy_score: number; buy_band: string }
	| Record<string, never>;
export function vetoPayload(
	itemId: string | number,
	status: string | null,
	row: ScoreRow | null | undefined,
	reasonCode?: string,
): VetoPayload;
export function factorRows(row: ScoreRow | null | undefined): FactorRow[];
export function histogramRows(
	histogram: Record<string, unknown> | null | undefined,
): HistogramRow[];
