/**
 * Vercel Cron entrypoint — dispatches the GitHub Actions hunt.
 * Vercel sends Authorization: Bearer <CRON_SECRET>.
 * Prefer GitHub Actions' own schedule; use this as a backup or sole scheduler.
 */
const { triggerWorkflow } = require("./trigger");

module.exports = async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "GET" && req.method !== "POST") {
    res.statusCode = 405;
    res.json({ error: "method_not_allowed" });
    return;
  }

  const cronSecret = process.env.CRON_SECRET || "";
  const auth = req.headers.authorization || "";
  const ok = Boolean(cronSecret) && auth === `Bearer ${cronSecret}`;

  if (!ok) {
    res.statusCode = 401;
    res.json({ error: "unauthorized" });
    return;
  }

  try {
    const result = await triggerWorkflow({ fullSweep: false });
    res.statusCode = 200;
    res.json({ ...result, via: "cron" });
  } catch (err) {
    res.statusCode = err.status || 500;
    res.json({ error: "cron_trigger_failed", message: String(err.message || err) });
  }
};
