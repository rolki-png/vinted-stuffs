import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type Hunt = {
  name?: string
  query?: string
  country?: string
  order?: string
  per_page?: number
  price_to?: number
  hunt_price?: number
  target_type?: string
  target_sizes?: string[]
  notes?: string
  bundle_hunt?: boolean
  family?: string
  min_deal_score?: number
  brand_ids?: number[]
  size_ids?: number[]
  [key: string]: unknown
}

type BrandHit = { id: number; title: string; slug?: string }
type SizeEntry = { id: number; title: string }
type SizeGroup = {
  id: number
  caption?: string
  description?: string
  sizes: SizeEntry[]
}

type Props = {
  onOps: (msg: { text: string; kind?: 'ok' | 'err' }) => void
}

const FAMILIES = ['', 'maternity', 'gym', 'sneakers', 'knitwear', 'other'] as const

function blankHunt(): Hunt {
  return {
    name: '',
    query: '',
    country: 'ro',
    order: 'newest_first',
    per_page: 24,
    price_to: 200,
    hunt_price: 100,
    target_type: '',
    target_sizes: [],
    notes: '',
  }
}

function cloneHunt(h: Hunt): Hunt {
  return JSON.parse(JSON.stringify(h))
}

function sizeHint(h: Hunt) {
  const ts = Array.isArray(h.target_sizes) ? h.target_sizes.join('/') : ''
  const n = Array.isArray(h.size_ids) ? h.size_ids.length : 0
  if (ts && n) return `${ts} · ${n} ids`
  if (ts) return ts
  if (n) return `${n} size ids`
  return 'any size'
}

function formValid(h: Hunt) {
  return Boolean(String(h.name || '').trim() && String(h.query || '').trim() && String(h.target_type || '').trim())
}

export function HuntsPanel({ onOps }: Props) {
  const [sha, setSha] = useState<string | null>(null)
  const [watches, setWatches] = useState<Hunt[]>([])
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [selectedKey, setSelectedKey] = useState<string | null>(null) // name or '__new__'
  const [originalName, setOriginalName] = useState<string | null>(null)
  const [draft, setDraft] = useState<Hunt | null>(null)
  const [baseline, setBaseline] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)

  const [brandQ, setBrandQ] = useState('')
  const [brandHits, setBrandHits] = useState<BrandHit[]>([])
  const [brandWarn, setBrandWarn] = useState<string | null>(null)
  const [selectedBrands, setSelectedBrands] = useState<BrandHit[]>([])

  const [sizeGroups, setSizeGroups] = useState<SizeGroup[]>([])
  const [sizeGroupId, setSizeGroupId] = useState<string>('')
  const [sizeWarn, setSizeWarn] = useState<string | null>(null)

  const brandTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const dirty = useMemo(() => {
    if (!draft) return false
    return JSON.stringify(draft) !== baseline
  }, [draft, baseline])

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return watches
    return watches.filter((w) => {
      const hay = `${w.name || ''} ${w.query || ''}`.toLowerCase()
      return hay.includes(q)
    })
  }, [watches, filter])

  const load = useCallback(async () => {
    setLoadErr(null)
    setConflict(false)
    const res = await fetch('/api/hunts', { cache: 'no-store' })
    const json = await res.json().catch(() => ({}))
    if (!res.ok) {
      const msg = String(json.message || `Load failed (${res.status})`)
      setLoadErr(msg)
      onOps({ text: msg, kind: 'err' })
      throw new Error(msg)
    }
    setSha(json.sha || null)
    setWatches(Array.isArray(json.watches) ? json.watches : [])
    return json
  }, [onOps])

  useEffect(() => {
    load().catch(() => {})
  }, [load])

  useEffect(() => {
    fetch('/api/size-groups?country=ro', { cache: 'force-cache' })
      .then(async (res) => {
        const json = await res.json()
        if (!res.ok) {
          setSizeWarn(String(json.message || 'Size groups unavailable'))
          setSizeGroups([])
          return
        }
        setSizeWarn(null)
        setSizeGroups(json.size_groups || [])
      })
      .catch((e) => {
        setSizeWarn(String(e.message || e))
        setSizeGroups([])
      })
  }, [])

  useEffect(() => {
    if (brandTimer.current) clearTimeout(brandTimer.current)
    if (!brandQ.trim()) {
      setBrandHits([])
      setBrandWarn(null)
      return
    }
    brandTimer.current = setTimeout(() => {
      fetch(`/api/brands?q=${encodeURIComponent(brandQ.trim())}&country=ro&limit=10`, {
        cache: 'no-store',
      })
        .then(async (res) => {
          const json = await res.json()
          if (!res.ok) {
            setBrandWarn(String(json.message || 'Brands unavailable'))
            setBrandHits([])
            return
          }
          setBrandWarn(null)
          setBrandHits(json.brands || [])
        })
        .catch((e) => {
          setBrandWarn(String(e.message || e))
          setBrandHits([])
        })
    }, 280)
    return () => {
      if (brandTimer.current) clearTimeout(brandTimer.current)
    }
  }, [brandQ])

  const applySelection = useCallback((hunt: Hunt | null, key: string | null, isNew: boolean) => {
    if (!hunt) {
      setSelectedKey(null)
      setOriginalName(null)
      setDraft(null)
      setBaseline('')
      setSelectedBrands([])
      return
    }
    const d = cloneHunt(hunt)
    d.country = 'ro'
    if (!Array.isArray(d.target_sizes)) d.target_sizes = []
    setSelectedKey(key)
    setOriginalName(isNew ? null : String(hunt.name || ''))
    setDraft(d)
    setBaseline(JSON.stringify(d))
    setSelectedBrands(
      Array.isArray(d.brand_ids)
        ? d.brand_ids.map((id) => ({ id, title: `#${id}` }))
        : [],
    )
  }, [])

  const guardDirty = useCallback(() => {
    if (!dirty) return true
    return window.confirm('Discard unsaved changes?')
  }, [dirty])

  const selectExisting = (w: Hunt) => {
    if (!guardDirty()) return
    applySelection(w, String(w.name), false)
  }

  const startNew = () => {
    if (!guardDirty()) return
    applySelection(blankHunt(), '__new__', true)
  }

  const startDuplicate = () => {
    if (!draft || selectedKey === '__new__') return
    if (!guardDirty()) return
    const d = cloneHunt(draft)
    d.name = `${String(d.name || 'hunt').trim()} copy`
    applySelection(d, '__new__', true)
  }

  const patchDraft = (patch: Partial<Hunt>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch, country: 'ro' } : prev))
  }

  const addBrand = (b: BrandHit) => {
    setSelectedBrands((prev) => {
      if (prev.some((x) => x.id === b.id)) return prev
      return [...prev, b]
    })
    setDraft((prev) => {
      if (!prev) return prev
      const ids = Array.isArray(prev.brand_ids) ? [...prev.brand_ids] : []
      if (!ids.includes(b.id)) ids.push(b.id)
      return { ...prev, brand_ids: ids }
    })
    setBrandQ('')
    setBrandHits([])
  }

  const removeBrand = (id: number) => {
    setSelectedBrands((prev) => prev.filter((b) => b.id !== id))
    setDraft((prev) => {
      if (!prev) return prev
      const ids = (prev.brand_ids || []).filter((x) => x !== id)
      const next = { ...prev }
      if (ids.length) next.brand_ids = ids
      else delete next.brand_ids
      return next
    })
  }

  const toggleSize = (id: number) => {
    setDraft((prev) => {
      if (!prev) return prev
      const ids = Array.isArray(prev.size_ids) ? [...prev.size_ids] : []
      const i = ids.indexOf(id)
      if (i >= 0) ids.splice(i, 1)
      else ids.push(id)
      const next = { ...prev }
      if (ids.length) next.size_ids = ids
      else delete next.size_ids
      return next
    })
  }

  const activeGroup = sizeGroups.find((g) => String(g.id) === sizeGroupId)

  const reloadHunts = async () => {
    if (dirty && !window.confirm('Reload will discard unsaved changes. Continue?')) return
    try {
      await load()
      applySelection(null, null, false)
      onOps({ text: 'Hunts reloaded from GitHub', kind: 'ok' })
    } catch {
      /* load already reported */
    }
  }

  const save = async () => {
    if (!draft || !sha || !formValid(draft)) return
    setBusy(true)
    try {
      const isNew = selectedKey === '__new__' || originalName == null
      const body = {
        mode: isNew ? 'add' : 'replace',
        sha,
        originalName: isNew ? undefined : originalName,
        hunt: {
          ...draft,
          country: 'ro',
          brand_ids: selectedBrands.map((b) => b.id),
        },
      }
      const res = await fetch('/api/hunts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await res.json().catch(() => ({}))
      if (res.status === 409 || json.error === 'conflict') {
        setConflict(true)
        onOps({
          text: 'Config changed on GitHub since you loaded it.',
          kind: 'err',
        })
        return
      }
      if (!res.ok) {
        onOps({ text: String(json.message || `Save failed (${res.status})`), kind: 'err' })
        return
      }
      setSha(json.sha)
      setWatches(json.watches || [])
      const saved = (json.watches || []).find((w: Hunt) => w.name === json.name) || draft
      applySelection(saved, String(json.name), false)
      onOps({
        text: 'Saved — next hunt run will use this list',
        kind: 'ok',
      })
    } catch (e: any) {
      onOps({ text: `Save failed — try again (${e.message || e})`, kind: 'err' })
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!draft || !sha || selectedKey === '__new__' || !originalName) return
    if (
      !window.confirm(
        `Stop searching ${originalName}? History and seen keys stay.`,
      )
    ) {
      return
    }
    setBusy(true)
    try {
      const res = await fetch('/api/hunts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'remove', sha, originalName }),
      })
      const json = await res.json().catch(() => ({}))
      if (res.status === 409 || json.error === 'conflict') {
        setConflict(true)
        onOps({
          text: 'Config changed on GitHub since you loaded it.',
          kind: 'err',
        })
        return
      }
      if (!res.ok) {
        onOps({ text: String(json.message || `Remove failed (${res.status})`), kind: 'err' })
        return
      }
      setSha(json.sha)
      setWatches(json.watches || [])
      applySelection(null, null, false)
      onOps({
        text: `Removed ${originalName} — next hunt run will use this list`,
        kind: 'ok',
      })
    } catch (e: any) {
      onOps({ text: `Save failed — try again (${e.message || e})`, kind: 'err' })
    } finally {
      setBusy(false)
    }
  }

  const renaming =
    draft &&
    originalName &&
    selectedKey !== '__new__' &&
    String(draft.name || '').trim() !== originalName

  const canSave = Boolean(draft && sha && dirty && formValid(draft) && !busy)

  return (
    <section className="panel active hunts-panel">
      {loadErr ? (
        <p className="reason" style={{ color: 'var(--danger)' }}>
          {loadErr}{' '}
          <button type="button" className="btn" onClick={() => load().catch(() => {})}>
            Retry
          </button>
        </p>
      ) : null}
      {conflict ? (
        <p className="reason" style={{ color: 'var(--danger)' }}>
          Config changed on GitHub since you loaded it.{' '}
          <button type="button" className="btn btn-accent" onClick={reloadHunts}>
            Reload hunts
          </button>
        </p>
      ) : null}

      <div className="hunts-layout">
        <div className="hunts-list">
          <div className="hunts-list-head">
            <label>
              Filter
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="name or query"
              />
            </label>
            <button type="button" className="btn btn-accent" onClick={startNew} disabled={busy}>
              New hunt
            </button>
          </div>
          {!watches.length ? (
            <p className="reason">
              No hunts yet.{' '}
              <button type="button" className="linklike" onClick={startNew}>
                New hunt
              </button>
            </p>
          ) : (
            <ul className="hunts-ul">
              {filtered.map((w) => {
                const active = selectedKey === w.name
                return (
                  <li key={String(w.name)}>
                    <button
                      type="button"
                      className={`hunts-row${active ? ' active' : ''}`}
                      onClick={() => selectExisting(w)}
                    >
                      <strong>{w.name}</strong>
                      <span className="reason">
                        {w.query} · RO · {sizeHint(w)}
                        {w.bundle_hunt ? ' · bundle seed' : ''}
                        {Array.isArray(w.brand_ids) && w.brand_ids.length
                          ? ` · ${w.brand_ids.length} brand${w.brand_ids.length === 1 ? '' : 's'}`
                          : ''}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div className="hunts-form">
          {!draft ? (
            <p className="reason">Select a hunt or create a new one.</p>
          ) : (
            <>
              <div className="hunts-form-head">
                <button type="button" className="btn btn-accent" disabled={!canSave} onClick={save}>
                  Save
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={busy || selectedKey === '__new__' || !originalName}
                  onClick={remove}
                >
                  Remove
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={busy || selectedKey === '__new__'}
                  onClick={startDuplicate}
                >
                  Duplicate
                </button>
              </div>

              {renaming ? (
                <p className="reason" style={{ color: 'var(--hunt)' }}>
                  Rename starts a <strong>new</strong> hunt identity (fresh seen keys). Old name’s
                  history stays orphaned.
                </p>
              ) : null}

              <div className="hunts-fields">
                <label>
                  Name
                  <input
                    value={String(draft.name || '')}
                    onChange={(e) => patchDraft({ name: e.target.value })}
                  />
                </label>
                <label>
                  Query
                  <input
                    value={String(draft.query || '')}
                    onChange={(e) => patchDraft({ query: e.target.value })}
                  />
                </label>
                <label>
                  Country
                  <input value="RO catalog" disabled readOnly />
                </label>
                <label>
                  Order
                  <select
                    value={String(draft.order || 'newest_first')}
                    onChange={(e) => patchDraft({ order: e.target.value })}
                  >
                    <option value="newest_first">newest_first</option>
                    <option value="relevance">relevance</option>
                    <option value="price_low_to_high">price_low_to_high</option>
                    <option value="price_high_to_low">price_high_to_low</option>
                  </select>
                </label>
                <label>
                  Per page
                  <input
                    type="number"
                    min={1}
                    value={draft.per_page ?? ''}
                    onChange={(e) =>
                      patchDraft({
                        per_page: e.target.value === '' ? undefined : Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Price to
                  <input
                    type="number"
                    min={0}
                    value={draft.price_to ?? ''}
                    onChange={(e) =>
                      patchDraft({
                        price_to: e.target.value === '' ? undefined : Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Hunt price
                  <input
                    type="number"
                    min={0}
                    value={draft.hunt_price ?? ''}
                    onChange={(e) =>
                      patchDraft({
                        hunt_price: e.target.value === '' ? undefined : Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Min deal score
                  <input
                    type="number"
                    min={0}
                    value={draft.min_deal_score ?? ''}
                    onChange={(e) =>
                      patchDraft({
                        min_deal_score:
                          e.target.value === '' ? undefined : Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Target type
                  <input
                    value={String(draft.target_type || '')}
                    onChange={(e) => patchDraft({ target_type: e.target.value })}
                  />
                </label>
                <label>
                  Target sizes (scorer text)
                  <input
                    value={(draft.target_sizes || []).join(', ')}
                    onChange={(e) =>
                      patchDraft({
                        target_sizes: e.target.value
                          .split(/[,;]/)
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                    placeholder="M, L"
                  />
                </label>
                <label>
                  Family
                  <select
                    value={String(draft.family || '')}
                    onChange={(e) => {
                      const v = e.target.value
                      setDraft((prev) => {
                        if (!prev) return prev
                        const next = { ...prev }
                        if (v) next.family = v
                        else delete next.family
                        return next
                      })
                    }}
                  >
                    {FAMILIES.map((f) => (
                      <option key={f || 'empty'} value={f}>
                        {f || '(none)'}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="hunts-check">
                  <input
                    type="checkbox"
                    checked={Boolean(draft.bundle_hunt)}
                    onChange={(e) =>
                      patchDraft({
                        bundle_hunt: e.target.checked ? true : undefined,
                      })
                    }
                  />
                  Bundle hunt (seed only)
                </label>
                <label className="hunts-span">
                  Notes
                  <textarea
                    rows={4}
                    value={String(draft.notes || '')}
                    onChange={(e) => patchDraft({ notes: e.target.value })}
                  />
                </label>

                <div className="hunts-span">
                  <div className="hunts-subhead">Brands</div>
                  {brandWarn ? <p className="reason">{brandWarn}</p> : null}
                  <div className="hunts-chips">
                    {selectedBrands.map((b) => (
                      <button
                        key={b.id}
                        type="button"
                        className="pill hunt"
                        onClick={() => removeBrand(b.id)}
                        title="Remove brand"
                      >
                        {b.title} ×
                      </button>
                    ))}
                  </div>
                  <input
                    type="search"
                    placeholder="Search brands…"
                    value={brandQ}
                    onChange={(e) => setBrandQ(e.target.value)}
                  />
                  {brandHits.length ? (
                    <ul className="hunts-suggest">
                      {brandHits.map((b) => (
                        <li key={b.id}>
                          <button type="button" onClick={() => addBrand(b)}>
                            {b.title} <span className="mono">#{b.id}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>

                <div className="hunts-span">
                  <div className="hunts-subhead">Sizes</div>
                  {sizeWarn ? <p className="reason">{sizeWarn}</p> : null}
                  <select value={sizeGroupId} onChange={(e) => setSizeGroupId(e.target.value)}>
                    <option value="">Choose size group…</option>
                    {sizeGroups.map((g) => (
                      <option key={g.id} value={String(g.id)}>
                        {g.description || g.caption || `Group ${g.id}`}
                      </option>
                    ))}
                  </select>
                  {activeGroup ? (
                    <div className="hunts-chips" style={{ marginTop: '0.5rem' }}>
                      {activeGroup.sizes.map((s) => {
                        const on = (draft.size_ids || []).includes(s.id)
                        return (
                          <button
                            key={s.id}
                            type="button"
                            className={`pill${on ? ' steal' : ''}`}
                            onClick={() => toggleSize(s.id)}
                          >
                            {s.title}
                          </button>
                        )
                      })}
                    </div>
                  ) : null}
                  {(draft.size_ids || []).length ? (
                    <p className="reason">{(draft.size_ids || []).length} size id(s) selected</p>
                  ) : null}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
