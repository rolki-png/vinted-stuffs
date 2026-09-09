import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(
	new URL("../src/components/DealDesk.tsx", import.meta.url),
	"utf8",
);
const styles = fs.readFileSync(
	new URL("../src/styles.css", import.meta.url),
	"utf8",
);

assert.doesNotMatch(source, /#\/server\/scoreSemantics\.js/);
assert.doesNotMatch(source, /Rescore legacy v2/);
assert.doesNotMatch(source, /legacy_active_v2/);
assert.match(source, /usableRank\(row\)/);
assert.match(source, /usableRank\(row\)/);
assert.match(source, /buyBandPresentation\(f\)/);
assert.doesNotMatch(source, /f\.buy_band \|\| 'skip'/);
assert.doesNotMatch(source, /className="pill skip">Invalid v2/);

const controlsStart = source.indexOf('className="remove-controls"');
const controlsEnd = source.indexOf("</span>", controlsStart);
assert.ok(controlsStart >= 0 && controlsEnd > controlsStart);
const controls = source.slice(controlsStart, controlsEnd);
assert.ok(
	controls.indexOf('className="remove-reason"') <
		controls.search(/setStatus\(["']removed["']/),
	"Remove reason selector must precede Remove in keyboard order",
);
assert.doesNotMatch(controls, /\btitle=/);
assert.match(
	controls,
	/Other and Sold\/unavailable do not affect taste learning\./,
);
assert.match(styles, /\.pill\.unknown\s*\{/);
assert.match(styles, /\.remove-learning-note\s*\{/);
assert.doesNotMatch(styles, /\.risk-(?:high|medium|low)\s*\{/);

assert.match(source, /Family/);
assert.match(source, /<option value="maternity">/);
assert.match(source, /Newest → oldest/);
assert.match(source, /Best → worst/);
assert.match(source, /bundleSort/);
assert.match(source, /Bundle \{b\.bundle_score\}/);
assert.match(source, /\/api\/finds/);
assert.match(source, /Prev/);

assert.match(source, /function bundleHuntFamily/);
assert.match(source, /bundleHuntFamily\(b\) === family/);
const bundlesTab = source.slice(source.indexOf('{tab === "bundles"'));
assert.match(bundlesTab, /Family/);
assert.match(bundlesTab, /<option value="maternity">/);

console.log("ok deal-desk-presentation");
