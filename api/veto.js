/**
 * Set / clear listing vetoes (Hide / Park).
 *
 * POST   { item_id, status: "hidden"|"parked" }
 * DELETE { item_id }  or POST { item_id, clear: true }
 */
const {
  setVetoStatus,
  clearVeto,
} = require("../lib/listingVetoes");

function readBody(req) {
  return new Promise((resolve, reject) => {
    if (req.body && typeof req.body === "object") {
      resolve(req.body);
      return;
    }
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 1e6) reject(new Error("body_too_large"));
    });
    req.on("end", () => {
      if (!raw) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

module.exports = async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST" && req.method !== "DELETE") {
    res.statusCode = 405;
    res.json({ error: "method_not_allowed" });
    return;
  }
  try {
    const body = await readBody(req);
    const itemId = body.item_id ?? body.itemId;
    const clear =
      req.method === "DELETE" ||
      body.clear === true ||
      body.action === "clear" ||
      body.status === "clear";
    if (clear) {
      const result = await clearVeto(itemId);
      res.statusCode = 200;
      res.json({ ok: true, ...result });
      return;
    }
    const status = body.status;
    const result = await setVetoStatus(itemId, status);
    res.statusCode = 200;
    res.json({ ok: true, ...result });
  } catch (err) {
    res.statusCode = err.status || 500;
    res.json({ error: String(err.message || err) });
  }
};
