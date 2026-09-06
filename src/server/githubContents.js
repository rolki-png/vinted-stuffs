// @ts-nocheck
/**
 * Decode GitHub Contents API payloads into JSON.
 * Files ≤1MB are inline base64; larger files only expose download_url.
 */

async function jsonFromGithubContents(
  body,
  relPath,
  { fetchFn = fetch, token = "" } = {},
) {
  if (body && body.encoding === "base64" && body.content) {
    return JSON.parse(Buffer.from(body.content, "base64").toString("utf8"))
  }
  if (body && body.download_url) {
    const headers = {
      "User-Agent": "vinted-hunt-dashboard",
      Accept: "application/vnd.github.raw",
    }
    if (token) headers.Authorization = `Bearer ${token}`
    const dl = await fetchFn(body.download_url, { headers })
    if (!dl.ok) {
      const text = await dl.text()
      throw new Error(
        `GitHub download ${dl.status} for ${relPath}: ${String(text).slice(0, 200)}`,
      )
    }
    return await dl.json()
  }
  throw new Error(`Unexpected GitHub contents payload for ${relPath}`)
}

export { jsonFromGithubContents }
