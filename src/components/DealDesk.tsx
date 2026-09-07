import { useCallback, useEffect, useMemo, useState } from 'react'
import { HuntsPanel } from '#/components/HuntsPanel'
import {
  buyBandPresentation,
  factorRows,
  histogramRows,
  isDeclaredV2,
  isV2,
  keepCounts,
  matchesBandFilter,
  matchesScoreFilter,
  scoreLabel,
  scoreScaleLabel,
  sellerComparator,
  sortFinds,
  usableRank,
  vetoPayload,
} from '#/components/scoreView.js'
import type {
  FactorRow,
  HistogramRow,
  ScoreRow,
} from '#/components/scoreView.js'

type VetoMode = 'active' | 'parked' | 'bought' | 'all'
type Tab = 'finds' | 'bundles' | 'sellers' | 'run' | 'hunts'

type ScoreFields = ScoreRow

type Find = ScoreFields & {
  id?: number | string
  title?: string
  watch?: string
  seller?: string
  seller_id?: number | string
  reason?: string
  deal_score?: number
  value_band?: string
  source?: string
  price?: number
  price_num?: number
  currency?: string
  url?: string
  scam_risk?: string
  kept_at?: string
  brand?: string
  size?: string
  veto_status?: string | null
}

type BundleItem = ScoreFields & {
  id?: number | string
  title?: string
  watch?: string
  role?: string
  deal_score?: number
  value_band?: string
  price?: number
  url?: string
  brand?: string
  size?: string
  veto_status?: string | null
}

type Bundle = {
  seller?: string
  seller_id?: number | string
  kind?: string
  country?: string
  listing_sum?: number
  checkout_extra_ron?: number
  checkout_total?: number
  effective_price_per_useful_item?: number
  suggested_offer_ron?: number
  offer_weak?: boolean
  reason?: string
  kept_at?: string
  veto_status?: string | null
  items?: BundleItem[]
}

type Seller = {
  seller?: string
  seller_id?: number | string
  profile_url?: string
  best_score?: number
  avg_score?: number
  keeps?: number
  listings?: number
  score_version?: number | null
  legacy_score?: boolean
  score_tier?: number
  bands?: Record<string, number>
  country?: string
  watches?: string[]
}

type Snapshot = {
  finds?: Find[]
  bundles?: Bundle[]
  sellers?: Seller[]
  watches?: string[]
  run?: Record<string, any>
  meta?: Record<string, any>
}

type GhRun = {
  id: number
  status: string
  conclusion?: string | null
  event?: string
  created_at?: string
  html_url?: string
  display_title?: string
}

const REMOVE_REASONS = [
  ['', 'No reason'],
  ['sold_unavailable', 'Sold / unavailable'],
  ['wrong_size', 'Wrong size'],
  ['bad_fit_style', 'Bad fit / style'],
  ['low_quality_condition', 'Low quality / condition'],
  ['poor_value', 'Poor value'],
  ['rarely_useful', 'Rarely useful'],
  ['already_own_similar', 'Already own similar'],
  ['other', 'Other'],
] as const

function fmtPrice(n: unknown, currency = 'RON') {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return `${Number(n).toFixed(0)} ${currency || 'RON'}`
}

function fmtWhen(iso?: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function fmtConfidence(value: unknown) {
  if (
    value == null ||
    typeof value === 'boolean' ||
    (typeof value === 'string' && value.trim() === '')
  ) {
    return '—'
  }
  const confidence = Number(value)
  if (!Number.isFinite(confidence)) return '—'
  return `${Math.round(confidence * 100)}%`
}

function ScoreSummary({ row }: { row: ScoreFields & { deal_score?: number } }) {
  const v2 = isV2(row)
  const rank = usableRank(row)
  return (
    <>
      <div>
        {scoreLabel(row)}
        {v2 ? <span className="score-denominator"> /100</span> : null}
      </div>
      <span className={v2 ? 'score-meta' : 'legacy-score'}>
        {scoreScaleLabel(row)}
      </span>
      {v2 ? (
        <>
          <span className="score-meta">
            Confidence {fmtConfidence(row.score_confidence)}
          </span>
          {rank ? (
            <span className="score-meta">
              Rank #{rank.position} · {rank.confidence}
            </span>
          ) : null}
        </>
      ) : null}
    </>
  )
}

function ScoreEvidence({ row }: { row: ScoreFields }) {
  if (!isV2(row)) return null
  const factors = factorRows(row)
  return (
    <details className="score-evidence">
      <summary>Why this score</summary>
      {factors.length ? (
        factors.map((factor: FactorRow) => (
          <div className="factor-row" key={factor.key}>
            <span>{factor.label}</span>
            <strong>{factor.value}</strong>
            <small>{factor.evidence || 'No supporting note'}</small>
          </div>
        ))
      ) : (
        <small>Factor evidence unavailable.</small>
      )}
    </details>
  )
}

function VerificationSummary({ row }: { row: Find | BundleItem }) {
  if (isV2(row)) {
    const concern = row.verification_concern || 'none'
    const concernClass =
      concern === 'block'
        ? 'verification-block'
        : concern === 'inspect'
          ? 'verification-inspect'
          : ''
    return (
      <div className={concernClass}>
        <strong>{concern}</strong>
        <span className="reason">
          {row.verification_reason || 'No additional verification note'}
        </span>
      </div>
    )
  }
  if (isDeclaredV2(row)) {
    return <span className="verification-block">Invalid v2 score data</span>
  }
  const legacyRisk = 'scam_risk' in row ? row.scam_risk : null
  return (
    <span className="legacy-score">
      Legacy risk: {legacyRisk || 'not recorded'}
    </span>
  )
}

function VetoButtons({
  itemId,
  status,
  onSet,
  onError,
}: {
  itemId?: string | number
  status?: string | null
  onSet: (
    id: string | number,
    status: string | null,
    reasonCode?: string,
  ) => Promise<void>
  onError: (msg: string) => void
}) {
  const [reasonCode, setReasonCode] = useState('')

  useEffect(() => {
    setReasonCode('')
  }, [itemId, status])

  if (itemId == null) return null
  const setStatus = (nextStatus: string | null, reason?: string) => {
    onSet(itemId, nextStatus, reason)
      .then(() => setReasonCode(''))
      .catch((e) => onError(String(e.message || e)))
  }
  if (status === 'parked' || status === 'bought') {
    return (
      <button
        type="button"
        className="btn veto-btn"
        onClick={() => setStatus(null)}
      >
        Undo
      </button>
    )
  }
  if (status === 'removed' || status === 'hidden') {
    return null
  }
  return (
    <>
      <button
        type="button"
        className="btn veto-btn"
        onClick={() => setStatus('bought')}
      >
        Bought
      </button>
      <span className="remove-controls">
        <select
          className="remove-reason"
          aria-label={`Remove reason for listing ${itemId}`}
          value={reasonCode}
          onChange={(event) => setReasonCode(event.target.value)}
        >
          {REMOVE_REASONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn veto-btn"
          onClick={() => setStatus('removed', reasonCode || undefined)}
        >
          Remove
        </button>
        <small className="remove-learning-note">
          Other and Sold/unavailable do not affect taste learning.
        </small>
      </span>
      <button
        type="button"
        className="btn veto-btn"
        onClick={() => setStatus('parked')}
      >
        Park
      </button>
    </>
  )
}

export function DealDesk() {
  const [data, setData] = useState<Snapshot | null>(null)
  const [runs, setRuns] = useState<GhRun[]>([])
  const [tab, setTab] = useState<Tab>('finds')
  const [opsMsg, setOpsMsg] = useState<{
    text: string
    kind?: 'ok' | 'err'
  } | null>(null)
  const [toast, setToast] = useState<{
    text: string
    undoId?: string | number
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [q, setQ] = useState('')
  const [watch, setWatch] = useState('')
  const [band, setBand] = useState('')
  const [minScore, setMinScore] = useState('')
  const [source, setSource] = useState('')
  const [veto, setVeto] = useState<VetoMode>('active')
  const [sort, setSort] = useState('score-desc')
  const [sellerSort, setSellerSort] = useState('best')

  const loadRuns = useCallback(async () => {
    try {
      const res = await fetch('/api/runs', { cache: 'no-store' })
      if (!res.ok) return [] as GhRun[]
      const json = await res.json()
      return (json.runs || []) as GhRun[]
    } catch {
      return [] as GhRun[]
    }
  }, [])

  const load = useCallback(async () => {
    setError(null)
    const qs = veto !== 'active' ? `?veto=${encodeURIComponent(veto)}` : ''
    const res = await fetch(`/api/dashboard${qs}`, { cache: 'no-store' })
    if (!res.ok) throw new Error(`API ${res.status}`)
    const json = (await res.json()) as Snapshot
    setData(json)
    setRuns(await loadRuns())
    setLive(true)
  }, [veto, loadRuns])

  useEffect(() => {
    load().catch((err) => {
      setError(
        `Failed to load snapshot: ${err.message}. Locally run npm run dev, or deploy to Vercel.`,
      )
    })
  }, [load])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 8000)
    return () => window.clearTimeout(t)
  }, [toast])

  const triggerHunt = async (fullSweep: boolean) => {
    setBusy(true)
    setOpsMsg({
      text: fullSweep ? 'Dispatching full sweep…' : 'Dispatching hunt…',
    })
    try {
      const res = await fetch('/api/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_sweep: fullSweep }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok)
        throw new Error(json.message || json.error || `HTTP ${res.status}`)
      setOpsMsg({
        text: `Queued on GitHub (${json.repo} / ${json.workflow}). Check Runs tab.`,
        kind: 'ok',
      })
      setRuns(await loadRuns())
      setTab('run')
    } catch (err: any) {
      setOpsMsg({ text: String(err.message || err), kind: 'err' })
    } finally {
      setBusy(false)
    }
  }

  const scoreRowFor = (itemId: string | number) => {
    const id = String(itemId)
    const find = (data?.finds || []).find((f) => String(f.id) === id)
    if (find) return find
    for (const b of data?.bundles || []) {
      const it = (b.items || []).find((x) => String(x.id) === id)
      if (it) return it
    }
    return {}
  }

  const setVetoStatus = async (
    itemId: string | number,
    status: string | null,
    reasonCode?: string,
  ) => {
    const body = vetoPayload(
      itemId,
      status,
      scoreRowFor(itemId),
      status === 'removed' ? reasonCode : undefined,
    )
    const res = await fetch('/api/veto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const json = await res.json().catch(() => ({}))
    if (!res.ok)
      throw new Error(json.error || json.message || `HTTP ${res.status}`)
    if (status == null) setToast({ text: `Cleared veto on #${itemId}` })
    else if (status === 'removed') setToast({ text: `Removed #${itemId}` })
    else if (status === 'bought')
      setToast({ text: `Marked bought #${itemId}`, undoId: itemId })
    else setToast({ text: `Parked #${itemId}`, undoId: itemId })
    await load()
  }

  const finds = useMemo(() => {
    let rows = [...(data?.finds || [])]
    const query = q.trim().toLowerCase()
    rows = rows.filter((f) => {
      if (watch && f.watch !== watch) return false
      if (!matchesBandFilter(f, band)) return false
      if (!matchesScoreFilter(f, minScore)) return false
      if (source && f.source !== source) return false
      if (query) {
        const blob =
          `${f.title || ''} ${f.watch || ''} ${f.seller || ''} ${f.reason || ''}`.toLowerCase()
        if (!blob.includes(query)) return false
      }
      return true
    })
    return sortFinds(rows, sort)
  }, [data, q, watch, band, minScore, source, sort])

  const sellers = useMemo(() => {
    const rows = [...(data?.sellers || [])]
    rows.sort(sellerComparator(sellerSort))
    return rows
  }, [data, sellerSort])

  const run = data?.run || {}
  const qualifiedKeeps = keepCounts(data?.finds || [])
  const lede = error
    ? error
    : run.finished_at
      ? `Last finished run ${fmtWhen(run.finished_at)} · data via ${data?.meta?.source || 'local'}${
          data?.meta?.indexed_source
            ? ` · index via ${data.meta.indexed_source}`
            : ''
        }. Refresh after Actions finishes to pull new keeps.`
      : `Waiting for a finished run snapshot · data via ${data?.meta?.source || 'local'}${
          data?.meta?.indexed_source
            ? ` · index via ${data.meta.indexed_source}`
            : ''
        }.`

  const stats: Array<[string, string | number]> = [
    ['Scored last run', run.scored ?? '—'],
    ['Index (DB)', data?.meta?.indexed_count ?? '—'],
    ['V2 qualified keeps', qualifiedKeeps.v2],
    ['Legacy keeps /10', qualifiedKeeps.legacy],
    ['Bundles', (data?.bundles || []).length],
    ['Sellers tracked', (data?.sellers || []).length],
    ['Alerts last run', run.alerts ?? '—'],
    ['Seen keys', run.seen_keys ?? '—'],
  ]

  const hist = histogramRows(run.score_histogram)
  const histMax = Math.max(1, ...hist.map((row: HistogramRow) => row.count), 1)

  return (
    <div className="page">
      <header className="hero">
        <div>
          <p className="brand">Vinted Hunt</p>
          <h1>Deal desk</h1>
          <p className="lede">{lede}</p>
        </div>
        <div className="hero-actions">
          <button
            type="button"
            className="btn btn-accent"
            disabled={busy}
            onClick={() => triggerHunt(false)}
          >
            Run hunt
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => triggerHunt(true)}
          >
            Full sweep
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => load().catch(console.error)}
          >
            Refresh
          </button>
          {live ? <span className="pulse">live</span> : null}
        </div>
      </header>

      <section className="ops">
        <p className={`ops-msg${opsMsg?.kind ? ` ${opsMsg.kind}` : ''}`}>
          {opsMsg?.text || ''}
        </p>
      </section>

      <section className="stats" aria-label="Run summary">
        {stats.map(([k, v]) => (
          <div className="stat" key={k}>
            <div className="k">{k}</div>
            <div className="v">{v}</div>
          </div>
        ))}
      </section>

      <nav className="tabs" role="tablist">
        {(
          [
            ['finds', 'Finds'],
            ['bundles', 'Bundles'],
            ['sellers', 'Top sellers'],
            ['run', 'Runs'],
            ['hunts', 'Hunts'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`tab${tab === id ? ' active' : ''}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === 'finds' ? (
        <section className="panel active">
          <div className="toolbar">
            <label>
              Search
              <input
                type="search"
                placeholder="title, watch, seller…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </label>
            <label>
              Hunt
              <select value={watch} onChange={(e) => setWatch(e.target.value)}>
                <option value="">All</option>
                {(data?.watches || []).map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Band
              <select value={band} onChange={(e) => setBand(e.target.value)}>
                <option value="">All</option>
                <optgroup label="V2 utility bands">
                  <option value="v2:exceptional">V2 exceptional</option>
                  <option value="v2:keep">V2 keep</option>
                  <option value="v2:good">V2 good</option>
                  <option value="v2:bundle">V2 bundle</option>
                  <option value="v2:skip">V2 skip</option>
                </optgroup>
                <optgroup label="Legacy history /10">
                  <option value="legacy:steal">Legacy steal</option>
                  <option value="legacy:hunt">Legacy hunt</option>
                  <option value="legacy:acceptable">Legacy acceptable</option>
                  <option value="legacy:skip">Legacy skip</option>
                </optgroup>
              </select>
            </label>
            <label>
              Score threshold
              <select
                value={minScore}
                onChange={(e) => setMinScore(e.target.value)}
              >
                <option value="">Any score version</option>
                <option value="v2:60">V2 60+ /100</option>
                <option value="v2:75">V2 75+ /100</option>
                <option value="v2:85">V2 85+ /100</option>
                <option value="v2:95">V2 95+ /100</option>
                <option value="legacy">Legacy only /10</option>
              </select>
            </label>
            <label>
              Source
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="">All</option>
                <option value="keep">kept</option>
                <option value="index">score index</option>
                <option value="scored">last-run top</option>
                <option value="pool">bundle pool</option>
              </select>
            </label>
            <label>
              Status
              <select
                value={veto}
                onChange={(e) => setVeto(e.target.value as VetoMode)}
              >
                <option value="active">Active</option>
                <option value="parked">Parked</option>
                <option value="bought">Bought</option>
                <option value="all">All</option>
              </select>
            </label>
            <label>
              Sort
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="score-desc">Score ↓</option>
                <option value="score-asc">Score ↑</option>
                <option value="price-asc">Price ↑</option>
                <option value="price-desc">Price ↓</option>
                <option value="date-desc">Newest keep</option>
                <option value="watch">Hunt A–Z</option>
              </select>
            </label>
          </div>
          <p className="count">
            {finds.length} listing{finds.length === 1 ? '' : 's'}
          </p>
          {toast ? (
            <p className="ops-msg ok">
              {toast.text}{' '}
              {toast.undoId != null ? (
                <button
                  type="button"
                  className="btn"
                  onClick={() =>
                    setVetoStatus(toast.undoId!, null).catch(console.error)
                  }
                >
                  Undo
                </button>
              ) : null}
            </p>
          ) : null}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Score</th>
                  <th>Band</th>
                  <th>Title</th>
                  <th>Price</th>
                  <th>Hunt</th>
                  <th>Seller</th>
                  <th>Verification</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {finds.length ? (
                  finds.map((f: Find) => {
                    const sellerLabel =
                      f.seller || (f.seller_id ? `#${f.seller_id}` : '—')
                    const buyBand = buyBandPresentation(f)
                    return (
                      <tr key={String(f.id)}>
                        <td className="score">
                          <ScoreSummary row={f} />
                        </td>
                        <td>
                          {isV2(f) ? (
                            <span className={`pill ${buyBand.className}`}>
                              {buyBand.label}
                            </span>
                          ) : isDeclaredV2(f) ? (
                            <span className="pill unknown">Invalid v2</span>
                          ) : (
                            <span className="legacy-score">
                              Legacy band: {f.value_band || 'not recorded'}
                            </span>
                          )}{' '}
                          <span className={`pill ${f.source || ''}`}>
                            {f.source || ''}
                          </span>{' '}
                          {f.veto_status ? (
                            <span className={`pill ${f.veto_status}`}>
                              {f.veto_status}
                            </span>
                          ) : null}
                        </td>
                        <td>
                          <div className="title">{f.title || '—'}</div>
                          {!isDeclaredV2(f) && f.reason ? (
                            <span className="reason">
                              Legacy rationale: {f.reason}
                            </span>
                          ) : null}
                          <ScoreEvidence row={f} />
                        </td>
                        <td className="mono">
                          {fmtPrice(f.price_num ?? f.price, f.currency)}
                        </td>
                        <td>{f.watch || '—'}</td>
                        <td>
                          {f.seller_id ? (
                            <a
                              className="link"
                              href={`https://www.vinted.ro/member/${f.seller_id}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {sellerLabel}
                            </a>
                          ) : (
                            sellerLabel
                          )}
                        </td>
                        <td>
                          <VerificationSummary row={f} />
                        </td>
                        <td className="actions">
                          {f.url ? (
                            <a
                              className="link"
                              href={f.url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Open
                            </a>
                          ) : null}
                          <VetoButtons
                            itemId={f.id}
                            status={f.veto_status}
                            onSet={setVetoStatus}
                            onError={(msg) =>
                              setOpsMsg({ text: msg, kind: 'err' })
                            }
                          />
                        </td>
                      </tr>
                    )
                  })
                ) : (
                  <tr>
                    <td colSpan={8}>No finds match these filters.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {tab === 'bundles' ? (
        <section className="panel active">
          <div className="toolbar">
            <label>
              Status
              <select
                value={veto}
                onChange={(e) => setVeto(e.target.value as VetoMode)}
              >
                <option value="active">Active</option>
                <option value="parked">Parked</option>
                <option value="bought">Bought</option>
                <option value="all">All</option>
              </select>
            </label>
          </div>
          {!(data?.bundles || []).length ? (
            <div className="empty">
              No wardrobe opportunities yet. Near hauls appear when a seller’s
              closet clears the fee gate; index near/bundles come from the
              Cockroach score cache when the same seller has multiple hunt-fits;
              value hauls when the model confirms a steal/hunt.
            </div>
          ) : (
            <div className="bundle-grid">
              {(data?.bundles || []).map((b, idx) => {
                const kind = b.kind || 'keep_bundle'
                const kindLabel =
                  kind === 'value_haul'
                    ? 'value haul'
                    : kind === 'near_haul'
                      ? 'near haul'
                      : kind === 'index_near_bundle'
                        ? 'index near'
                        : kind === 'index_keep_bundle'
                          ? 'index bundle'
                          : 'keep bundle'
                const pillClass =
                  kind === 'value_haul'
                    ? 'haul'
                    : kind === 'near_haul' || kind === 'index_near_bundle'
                      ? 'near'
                      : 'keep'
                return (
                  <article className="bundle" key={idx}>
                    <h3>
                      {b.seller_id ? (
                        <a
                          className="link"
                          href={`https://www.vinted.ro/member/${b.seller_id}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {b.seller || b.seller_id}
                        </a>
                      ) : (
                        b.seller || 'seller'
                      )}{' '}
                      <span className={`pill ${pillClass}`}>{kindLabel}</span>
                      {b.veto_status ? (
                        <span className={`pill ${b.veto_status}`}>
                          {' '}
                          {b.veto_status}
                        </span>
                      ) : null}
                    </h3>
                    <p className="bundle-meta">
                      {b.country || '?'} · listings{' '}
                      {Number(b.listing_sum || 0).toFixed(0)} + extra{' '}
                      {b.checkout_extra_ron ?? '?'} ={' '}
                      <strong>
                        {Number(
                          b.checkout_total ||
                            Number(b.listing_sum || 0) +
                              Number(b.checkout_extra_ron || 0),
                        ).toFixed(0)}{' '}
                        RON
                      </strong>
                      {b.effective_price_per_useful_item != null
                        ? ` · ~${Number(b.effective_price_per_useful_item).toFixed(0)} RON/item`
                        : ''}
                      {b.suggested_offer_ron != null ? (
                        <>
                          {' '}
                          ·{' '}
                          <strong>
                            offer ~{Number(b.suggested_offer_ron).toFixed(0)}{' '}
                            RON
                          </strong>
                          {b.offer_weak ? (
                            <span className="pill near"> weak</span>
                          ) : null}
                        </>
                      ) : null}
                      {b.reason ? ` · ${b.reason}` : ''} · {fmtWhen(b.kept_at)}
                    </p>
                    <div className="bundle-items">
                      {(b.items || []).map((it) => (
                        <div className="bundle-item" key={String(it.id)}>
                          <span
                            className={`pill ${it.role === 'keep' ? 'keep' : 'hunt'}`}
                          >
                            {it.role || ''}
                          </span>
                          <div>
                            <div className="title">
                              {it.title || ''}
                              {it.veto_status ? (
                                <span className={`pill ${it.veto_status}`}>
                                  {' '}
                                  {it.veto_status}
                                </span>
                              ) : null}
                            </div>
                            <span className="reason">{it.watch || ''}</span>
                            <div className="score bundle-score">
                              <ScoreSummary row={it} />
                            </div>
                            <div className="bundle-verification">
                              <VerificationSummary row={it} />
                            </div>
                            <ScoreEvidence row={it} />
                          </div>
                          <div>
                            <div className="mono">{fmtPrice(it.price)}</div>
                            {it.url ? (
                              <a
                                className="link"
                                href={it.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Open
                              </a>
                            ) : null}
                            <VetoButtons
                              itemId={it.id}
                              status={it.veto_status}
                              onSet={setVetoStatus}
                              onError={(msg) =>
                                setOpsMsg({ text: msg, kind: 'err' })
                              }
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </article>
                )
              })}
            </div>
          )}
        </section>
      ) : null}

      {tab === 'sellers' ? (
        <section className="panel active">
          <div className="toolbar">
            <label>
              Sort sellers
              <select
                value={sellerSort}
                onChange={(e) => setSellerSort(e.target.value)}
              >
                <option value="best">Best score</option>
                <option value="avg">Avg score</option>
                <option value="keeps">Keep count</option>
                <option value="listings">Listings</option>
              </select>
            </label>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Seller</th>
                  <th>Best score</th>
                  <th>Average</th>
                  <th>Qualified keeps</th>
                  <th>Listings</th>
                  <th>Country</th>
                  <th>Hunts</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sellers.length ? (
                  sellers.map((s, i) => {
                    const v2Seller =
                      s.score_tier === 2 ||
                      (s.score_tier == null && s.score_version === 2)
                    const legacySeller = !v2Seller && s.legacy_score === true
                    const scale = v2Seller ? '/100' : legacySeller ? '/10' : ''
                    return (
                      <tr key={String(s.seller_id || s.seller || i)}>
                        <td className="mono">{i + 1}</td>
                        <td>
                          {s.profile_url ? (
                            <a
                              className="link"
                              href={s.profile_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {s.seller}
                            </a>
                          ) : (
                            s.seller
                          )}
                        </td>
                        <td className="score">
                          {s.best_score ?? '—'} {scale}
                          <span
                            className={v2Seller ? 'score-meta' : 'legacy-score'}
                          >
                            {v2Seller
                              ? 'V2 utility'
                              : legacySeller
                                ? 'Legacy history'
                                : 'Unscored'}
                          </span>
                          <span className="seller-bands">
                            {Object.entries(s.bands || {}).map(
                              ([name, count]) => (
                                <span className={`pill ${name}`} key={name}>
                                  {name} {count}
                                </span>
                              ),
                            )}
                          </span>
                        </td>
                        <td className="mono">
                          {s.avg_score ?? '—'} {scale}
                        </td>
                        <td>
                          {s.keeps ?? 0}
                          <span
                            className={v2Seller ? 'score-meta' : 'legacy-score'}
                          >
                            {v2Seller
                              ? 'V2 qualified'
                              : legacySeller
                                ? 'Legacy rule'
                                : 'No score family'}
                          </span>
                        </td>
                        <td>{s.listings}</td>
                        <td>{(s.country || '—').toUpperCase()}</td>
                        <td>
                          {(s.watches || []).slice(0, 3).join(', ') || '—'}
                        </td>
                        <td>
                          {s.profile_url ? (
                            <a
                              className="link"
                              href={s.profile_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Profile
                            </a>
                          ) : null}
                        </td>
                      </tr>
                    )
                  })
                ) : (
                  <tr>
                    <td colSpan={9}>
                      No seller scores yet — appears once listings carry
                      seller_id (after this sweep finishes / pool fills).
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {tab === 'hunts' ? (
        <HuntsPanel
          onOps={(msg) => {
            setOpsMsg(msg)
          }}
        />
      ) : null}

      {tab === 'run' ? (
        <section className="panel active">
          <div className="bundle">
            <h3>Last scoring snapshot</h3>
            <p className="bundle-meta">
              finished {fmtWhen(run.finished_at)} · scored {run.scored ?? '—'} ·
              solo keeps {run.solo_keeps ?? '—'} · bundles {run.bundles ?? '—'}{' '}
              · alerts {run.alerts ?? '—'}
            </p>
            <p className="reason">
              V2 utility histogram (/100, ten-point bins)
            </p>
            {hist.length ? (
              <div className="hist">
                {hist.map(({ label, count }: HistogramRow) => {
                  const h = Math.max(8, Math.round((count / histMax) * 100))
                  return (
                    <div
                      className="bar"
                      key={label}
                      style={{ height: h }}
                      title={`${label}: ${count}`}
                    >
                      <strong>{count}</strong>
                      <span>{label}</span>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="legacy-score">
                No v2 histogram is available for this historical run.
              </p>
            )}
          </div>
          <div className="bundle" style={{ marginTop: '1rem' }}>
            <h3>GitHub Actions</h3>
            <p className="bundle-meta">
              Cron every 15m on GitHub · optional daily Vercel cron → same
              workflow
            </p>
            <div className="bundle-items">
              {runs.length ? (
                runs.map((r) => (
                  <div className="bundle-item" key={r.id}>
                    <span
                      className={`pill ${
                        r.conclusion === 'success'
                          ? 'steal'
                          : r.status === 'in_progress' || r.status === 'queued'
                            ? 'hunt'
                            : 'skip'
                      }`}
                    >
                      {r.status}
                      {r.conclusion ? ` / ${r.conclusion}` : ''}
                    </span>
                    <div>
                      <div className="title">
                        {r.display_title || r.event || 'run'}
                      </div>
                      <span className="reason">
                        {fmtWhen(r.created_at)} · {r.event || ''}
                      </span>
                    </div>
                    <div>
                      {r.html_url ? (
                        <a
                          className="link"
                          href={r.html_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          GitHub
                        </a>
                      ) : null}
                    </div>
                  </div>
                ))
              ) : (
                <p className="reason">
                  No GitHub Actions runs visible yet (set GITHUB_TOKEN +
                  GITHUB_REPO on Vercel).
                </p>
              )}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  )
}
