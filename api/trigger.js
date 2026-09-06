/**
 * Trigger the GitHub Actions hunt workflow (workflow_dispatch).
 * Open from the desk UI — auth is the GITHUB_TOKEN server-side, not a pasted secret.
 */
async function triggerWorkflow({ fullSweep = false, skipScoring = false } = {}) {
  const repo = process.env.GITHUB_REPO;
  const token = process.env.GITHUB_TOKEN;
  const workflow = process.env.GITHUB_WORKFLOW || "vinted-bot.yml";
  const ref = process.env.GITHUB_REF || "main";
  if (!repo || !token) {
    const err = new Error("GITHUB_REPO and GITHUB_TOKEN are required");
    err.status = 500;
    throw err;
  }

  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "User-Agent": "vinted-hunt-dashboard",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref,
      inputs: {
        skip_scoring: String(Boolean(skipScoring)),
        full_sweep: String(Boolean(fullSweep)),
      },
    }),
  });

  if (res.status !== 204 && res.status !== 200) {
    const text = await res.text();
    const err = new Error(`GitHub dispatch failed (${res.status}): ${text.slice(0, 300)}`);
    err.status = res.status;
    throw err;
  }
  return { ok: true, repo, workflow, ref, full_sweep: Boolean(fullSweep) };
}

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
  if (req.method !== "POST") {
    res.statusCode = 405;
    res.json({ error: "method_not_allowed" });
    return;
  }
  try {
    const body = await readBody(req);
    const result = await triggerWorkflow({
      fullSweep: Boolean(body.full_sweep || body.fullSweep),
      skipScoring: Boolean(body.skip_scoring || body.skipScoring),
    });
    res.statusCode = 200;
    res.json(result);
  } catch (err) {
    res.statusCode = err.status || 500;
    res.json({ error: "trigger_failed", message: String(err.message || err) });
  }
};

module.exports.triggerWorkflow = triggerWorkflow;
