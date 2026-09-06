// @ts-nocheck
export async function triggerWorkflow({ fullSweep = false, skipScoring = false } = {}) {
  const repo = process.env.GITHUB_REPO
  const token = process.env.GITHUB_TOKEN
  const workflow = process.env.GITHUB_WORKFLOW || "vinted-bot.yml"
  const ref = process.env.GITHUB_REF || "main"
  if (!repo || !token) {
    const err = new Error("GITHUB_REPO and GITHUB_TOKEN are required")
    err.status = 500
    throw err
  }

  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`
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
  })

  if (res.status !== 204 && res.status !== 200) {
    const text = await res.text()
    const err = new Error(`GitHub dispatch failed (${res.status}): ${text.slice(0, 300)}`)
    err.status = res.status
    throw err
  }
  return { ok: true, repo, workflow, ref, full_sweep: Boolean(fullSweep) }
}

export function authorized(request) {
  const expected = process.env.DASHBOARD_SECRET || ""
  if (!expected) return false
  const header = request.headers.get("x-dashboard-secret") || ""
  const bearer = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "")
  return header === expected || bearer === expected
}

export async function listWorkflowRuns() {
  const repo = process.env.GITHUB_REPO
  const token = process.env.GITHUB_TOKEN
  const workflow = process.env.GITHUB_WORKFLOW || "vinted-bot.yml"
  if (!repo || !token) {
    return { runs: [], note: "GITHUB_REPO/TOKEN not configured" }
  }
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/runs?per_page=5`
  const gh = await fetch(url, {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "User-Agent": "vinted-hunt-dashboard",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  })
  if (!gh.ok) {
    const text = await gh.text()
    const err = new Error(text.slice(0, 300))
    err.status = gh.status
    throw err
  }
  const data = await gh.json()
  return {
    runs: (data.workflow_runs || []).map((r) => ({
      id: r.id,
      status: r.status,
      conclusion: r.conclusion,
      event: r.event,
      created_at: r.created_at,
      updated_at: r.updated_at,
      html_url: r.html_url,
      display_title: r.display_title,
    })),
  }
}
