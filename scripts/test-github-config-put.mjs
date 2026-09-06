/**
 * Tip-race retry for putConfigJson (mocked fetch).
 * Run: node scripts/test-github-config-put.mjs
 */
import assert from "node:assert/strict"
import { putConfigJson } from "../src/server/githubConfig.js"

process.env.GITHUB_REPO = "owner/repo"
process.env.GITHUB_TOKEN = "tok"
process.env.GITHUB_REF = "main"

const blobA = "sha-blob-a"
const config = { watches: [{ name: "A", query: "q", country: "ro", target_type: "t", notes: "" }] }

function contentsGetBody(sha, cfg) {
  return {
    sha,
    encoding: "base64",
    content: Buffer.from(`${JSON.stringify(cfg, null, 2)}\n`, "utf8").toString("base64"),
  }
}

async function testTipRaceRetry() {
  let puts = 0
  const fetchFn = async (url, init) => {
    const method = (init?.method || "GET").toUpperCase()
    if (method === "GET") {
      return {
        ok: true,
        status: 200,
        async json() {
          return contentsGetBody(blobA, config)
        },
        async text() {
          return ""
        },
      }
    }
    // PUT
    puts += 1
    if (puts === 1) {
      return {
        ok: false,
        status: 409,
        async text() {
          return JSON.stringify({ message: "is at X but expected Y" })
        },
      }
    }
    return {
      ok: true,
      status: 200,
      async text() {
        return JSON.stringify({ content: { sha: "sha-blob-b" }, commit: { sha: "commit1" } })
      },
    }
  }

  const result = await putConfigJson({
    config,
    sha: blobA,
    message: "desk: replace hunt A [skip ci]",
    fetchFn,
  })
  assert.equal(puts, 2)
  assert.equal(result.sha, "sha-blob-b")
}

async function testRealConflict() {
  let puts = 0
  const fetchFn = async (url, init) => {
    const method = (init?.method || "GET").toUpperCase()
    if (method === "GET") {
      return {
        ok: true,
        status: 200,
        async json() {
          // After 409, re-GET shows different blob
          return contentsGetBody(puts === 0 ? blobA : "sha-other", config)
        },
        async text() {
          return ""
        },
      }
    }
    puts += 1
    return {
      ok: false,
      status: 409,
      async text() {
        return "{}"
      },
    }
  }

  await assert.rejects(
    () =>
      putConfigJson({
        config,
        sha: blobA,
        message: "desk: replace hunt A [skip ci]",
        fetchFn,
      }),
    (err) => err.code === "conflict" && err.status === 409,
  )
  assert.equal(puts, 1)
}

await testTipRaceRetry()
await testRealConflict()
console.log("ok github-config-put")
