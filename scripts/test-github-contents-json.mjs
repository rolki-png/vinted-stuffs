/**
 * Unit checks for GitHub Contents → JSON decoding (files >1MB use download_url).
 * Run: node scripts/test-github-contents-json.mjs
 */
import assert from "node:assert/strict"
import { jsonFromGithubContents } from "../src/server/githubContents.js"

async function testInlineBase64() {
  const payload = { hello: "world", n: 1 }
  const body = {
    encoding: "base64",
    content: Buffer.from(JSON.stringify(payload), "utf8").toString("base64"),
  }
  const got = await jsonFromGithubContents(body, "data/tiny.json", {
    fetchFn: async () => {
      throw new Error("should not download")
    },
  })
  assert.deepEqual(got, payload)
}

async function testLargeFileDownloadUrl() {
  const payload = [{ id: 1 }, { id: 2 }]
  let downloaded = false
  const body = {
    encoding: "none",
    size: 2_000_000,
    content: "",
    download_url: "https://raw.githubusercontent.com/example/repo/main/data/indexed_scores.json",
  }
  const got = await jsonFromGithubContents(body, "data/indexed_scores.json", {
    token: "test-token",
    fetchFn: async (url, init) => {
      downloaded = true
      assert.equal(url, body.download_url)
      assert.equal(init?.headers?.Authorization, "Bearer test-token")
      return {
        ok: true,
        status: 200,
        async json() {
          return payload
        },
        async text() {
          return ""
        },
      }
    },
  })
  assert.equal(downloaded, true)
  assert.deepEqual(got, payload)
}

async function testUnexpectedThrows() {
  await assert.rejects(
    () => jsonFromGithubContents({ encoding: "none" }, "data/x.json", { fetchFn: async () => ({}) }),
    /Unexpected GitHub contents payload/,
  )
}

await testInlineBase64()
await testLargeFileDownloadUrl()
await testUnexpectedThrows()
console.log("ok github-contents-json")
