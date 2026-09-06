// @ts-nocheck
import { jsonFromGithubContents } from "./githubContents.js"
import {
  CONFIG_PATH,
  applyWatchMutation,
  serializeConfigJson,
  classifyContents409,
} from "./huntConfig.js"

function ghEnv() {
  const repo = process.env.GITHUB_REPO
  const token = process.env.GITHUB_TOKEN
  const ref = process.env.GITHUB_REF || "main"
  if (!repo || !token) {
    const err = new Error("GITHUB_REPO and GITHUB_TOKEN are required")
    err.status = 500
    err.code = "config_env"
    throw err
  }
  return { repo, token, ref }
}

function ghHeaders(token, extra = {}) {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "User-Agent": "vinted-hunt-dashboard",
    "X-GitHub-Api-Version": "2022-11-28",
    ...extra,
  }
}

async function getConfigJson({ fetchFn = fetch } = {}) {
  const { repo, token, ref } = ghEnv()
  const url = `https://api.github.com/repos/${repo}/contents/${CONFIG_PATH}?ref=${encodeURIComponent(ref)}`
  const res = await fetchFn(url, { headers: ghHeaders(token) })
  if (res.status === 404) {
    const err = new Error(`Config not found: ${CONFIG_PATH}`)
    err.status = 404
    err.code = "not_found"
    throw err
  }
  if (!res.ok) {
    const text = await res.text()
    const err = new Error(`GitHub ${res.status} reading config: ${text.slice(0, 200)}`)
    err.status = res.status === 401 || res.status === 403 ? res.status : 502
    err.code = res.status === 401 || res.status === 403 ? "auth" : "upstream"
    throw err
  }
  const body = await res.json()
  const sha = body.sha
  const config = await jsonFromGithubContents(body, CONFIG_PATH, { token, fetchFn })
  return { config, sha, path: CONFIG_PATH, ref }
}

async function putConfigJsonOnce({ config, sha, message, fetchFn = fetch }) {
  const { repo, token, ref } = ghEnv()
  const url = `https://api.github.com/repos/${repo}/contents/${CONFIG_PATH}`
  const content = Buffer.from(serializeConfigJson(config), "utf8").toString("base64")
  const res = await fetchFn(url, {
    method: "PUT",
    headers: ghHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify({
      message,
      content,
      sha,
      branch: ref,
    }),
  })
  const text = await res.text()
  let parsed = null
  try {
    parsed = text ? JSON.parse(text) : null
  } catch {
    parsed = null
  }
  return { res, text, parsed }
}

/**
 * PUT config with one tip-race retry on 409 when blob sha unchanged.
 */
async function putConfigJson({ config, sha, message, fetchFn = fetch }) {
  let attemptSha = sha
  let attempt = await putConfigJsonOnce({ config, sha: attemptSha, message, fetchFn })

  if (attempt.res.status === 409) {
    const fresh = await getConfigJson({ fetchFn })
    const cls = classifyContents409(attemptSha, fresh.sha)
    if (cls.retry) {
      attemptSha = fresh.sha
      attempt = await putConfigJsonOnce({ config, sha: attemptSha, message, fetchFn })
    } else {
      const err = new Error("Config changed on GitHub since you loaded it")
      err.status = 409
      err.code = "conflict"
      err.sha = fresh.sha
      throw err
    }
  }

  if (attempt.res.status === 401 || attempt.res.status === 403) {
    const err = new Error("GitHub token can’t write config")
    err.status = attempt.res.status
    err.code = "auth"
    throw err
  }
  if (attempt.res.status === 404) {
    const err = new Error("Config file/repo not found")
    err.status = 404
    err.code = "not_found"
    throw err
  }
  if (attempt.res.status === 409) {
    const err = new Error("Config changed on GitHub since you loaded it")
    err.status = 409
    err.code = "conflict"
    throw err
  }
  if (!attempt.res.ok) {
    const err = new Error(
      `GitHub ${attempt.res.status} writing config: ${String(attempt.text).slice(0, 200)}`,
    )
    err.status = attempt.res.status >= 500 ? 502 : attempt.res.status
    err.code = "upstream"
    throw err
  }

  const newSha = attempt.parsed?.content?.sha || attempt.parsed?.commit?.sha || null
  // Prefer blob sha from content; if missing, re-GET
  if (!attempt.parsed?.content?.sha) {
    const fresh = await getConfigJson({ fetchFn })
    return { sha: fresh.sha, config: fresh.config, commit: attempt.parsed }
  }
  return { sha: newSha, config, commit: attempt.parsed }
}

/**
 * Load watches + sha for the desk.
 */
async function loadHunts({ fetchFn = fetch } = {}) {
  const { config, sha, ref } = await getConfigJson({ fetchFn })
  const watches = Array.isArray(config.watches) ? config.watches : []
  return { sha, watches, ref, path: CONFIG_PATH }
}

/**
 * Mutate watches and commit.
 */
async function mutateHunts({ mode, hunt, originalName, sha, fetchFn = fetch }) {
  if (!sha) {
    const err = new Error("sha is required")
    err.status = 400
    err.code = "validation"
    throw err
  }
  const loaded = await getConfigJson({ fetchFn })
  if (loaded.sha !== sha) {
    const err = new Error("Config changed on GitHub since you loaded it")
    err.status = 409
    err.code = "conflict"
    err.sha = loaded.sha
    throw err
  }

  const applied = applyWatchMutation(loaded.config, { mode, hunt, originalName })
  if (!applied.ok) {
    const err = new Error(applied.error || "validation failed")
    err.status = 400
    err.code = "validation"
    throw err
  }

  const put = await putConfigJson({
    config: applied.config,
    sha: loaded.sha,
    message: applied.message,
    fetchFn,
  })

  const watches = Array.isArray(put.config.watches) ? put.config.watches : []
  return {
    ok: true,
    sha: put.sha,
    watches,
    name: applied.name,
    mode,
  }
}

export { getConfigJson, putConfigJson, loadHunts, mutateHunts, CONFIG_PATH }
