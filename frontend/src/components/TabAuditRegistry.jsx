import { useState, useEffect, useRef } from 'react'
import { api } from '../api.js'

// T10 Lot F4/G3/H : page "Audit ZimaTAG" — edition du registre + largeurs de colonnes
// redimensionnables et persistees (table ui_prefs cote serveur, cle audit_col_widths).

const CLASSEMENTS = ['probleme', 'INFO', 'KPI', 'SKIP']
const ONGLETS = ['cockpit', 'kpi', 'qualite', 'integrite', 'metadonnees',
                 'doublons', 'casse', 'images', 'donnees', 'informations']

// Colonnes (ordre = affichage) + largeurs par defaut (px) = alignement initial.
const COLS = [
  { key: 'cle',        label: 'Clé',        w: 200 },
  { key: 'libelle',    label: 'Libellé',    w: 180 },
  { key: 'onglet',     label: 'Onglet',     w: 130 },
  { key: 'classement', label: 'Classement', w: 120 },
  { key: 'health',     label: 'Health',     w: 60  },
  { key: 'poids',      label: 'Poids',      w: 70  },
  { key: 'actif',      label: 'Actif',      w: 60  },
  { key: 'dossier',    label: 'Dossier',    w: 70  },
  { key: 'note',       label: 'Note',       w: 170 },
  { key: 'actions',    label: '',           w: 130 },
]
const DEFAULT_WIDTHS = Object.fromEntries(COLS.map(c => [c.key, c.w]))
const MIN_W = 40
const PREF_KEY = 'audit_col_widths'

function Row({ row, onSaved }) {
  const [draft, setDraft] = useState(row)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const dirty = JSON.stringify(draft) !== JSON.stringify(row)
  function set(k, v) { setDraft({ ...draft, [k]: v }) }

  async function save() {
    setBusy(true); setMsg('')
    try {
      const fields = {
        libelle: draft.libelle, onglet_cible: draft.onglet_cible,
        classement_cible: draft.classement_cible, dans_health: draft.dans_health,
        poids_cible: draft.poids_cible, actif: draft.actif,
        decision: draft.decision, note: draft.note,
        par_dossier: draft.par_dossier,
      }
      await api.auditRegistryUpdate(draft.audit_key, fields)
      setMsg('✓'); onSaved(draft)
    } catch (e) { setMsg('✗ ' + e.message) } finally { setBusy(false) }
  }

  const td = { overflow: 'hidden', textOverflow: 'ellipsis' }
  return (
    <tr style={{ opacity: draft.actif ? 1 : 0.5 }}>
      <td className="mono" style={{ ...td, fontSize: 12 }} title={draft.audit_key}>{draft.audit_key}</td>
      <td style={td}>
        <input value={draft.libelle || ''} onChange={e => set('libelle', e.target.value)}
               style={{ width: '100%', fontSize: 12 }} />
      </td>
      <td style={td}>
        <select value={draft.onglet_cible} onChange={e => set('onglet_cible', e.target.value)}
                style={{ width: '100%', fontSize: 12 }}>
          {ONGLETS.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      </td>
      <td style={td}>
        <select value={draft.classement_cible} onChange={e => set('classement_cible', e.target.value)}
                style={{ width: '100%', fontSize: 12 }}>
          {CLASSEMENTS.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </td>
      <td style={{ ...td, textAlign: 'center' }}>
        <input type="checkbox" checked={!!draft.dans_health}
               onChange={e => set('dans_health', e.target.checked ? 1 : 0)} />
      </td>
      <td style={td}>
        <input type="number" step="0.1" min="0" value={draft.poids_cible ?? 0}
               onChange={e => set('poids_cible', parseFloat(e.target.value) || 0)}
               style={{ width: '100%', fontSize: 12 }} />
      </td>
      <td style={{ ...td, textAlign: 'center' }}>
        <input type="checkbox" checked={!!draft.actif}
               onChange={e => set('actif', e.target.checked ? 1 : 0)} />
      </td>
      <td style={{ ...td, textAlign: 'center' }} title={draft.classement_cible === 'INFO'
          ? 'Afficher cet audit INFO dans la vue Par dossier'
          : 'Pertinent uniquement pour les audits INFO'}>
        <input type="checkbox" checked={!!draft.par_dossier}
               disabled={draft.classement_cible !== 'INFO'}
               onChange={e => set('par_dossier', e.target.checked ? 1 : 0)} />
      </td>
      <td style={td}>
        <input value={draft.note || ''} onChange={e => set('note', e.target.value)}
               placeholder="note…" style={{ width: '100%', fontSize: 12 }} />
      </td>
      <td style={{ ...td, whiteSpace: 'nowrap' }}>
        <button className="btn-primary" disabled={!dirty || busy} onClick={save}
                style={{ fontSize: 12, padding: '2px 8px' }}>
          {busy ? '…' : 'Enregistrer'}
        </button>
        {msg && <span style={{ marginLeft: 6, fontSize: 12,
                 color: msg[0] === '✓' ? 'var(--success)' : 'var(--danger)' }}>{msg}</span>}
      </td>
    </tr>
  )
}

// En-tete partage avec poignees de resize.
function HeadRow({ widths, onResize }) {
  const drag = useRef(null)
  function down(key, e) {
    drag.current = { key, startX: e.clientX, startW: widths[key] }
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    e.preventDefault()
  }
  function move(e) {
    if (!drag.current) return
    const dx = e.clientX - drag.current.startX
    onResize(drag.current.key, Math.max(MIN_W, drag.current.startW + dx))
  }
  function up() {
    drag.current = null
    document.body.style.cursor = ''
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  return (
    <tr>
      {COLS.map(c => (
        <th key={c.key} style={{ position: 'relative', userSelect: 'none' }}>
          {c.label}
          <span onMouseDown={e => down(c.key, e)}
                style={{ position: 'absolute', top: 0, right: 0, width: 6, height: '100%',
                         cursor: 'col-resize', background: 'transparent' }} />
        </th>
      ))}
    </tr>
  )
}

export default function TabAuditRegistry() {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [widths, setWidths] = useState(DEFAULT_WIDTHS)
  const [savingW, setSavingW] = useState(false)
  const [wMsg, setWMsg] = useState('')

  async function load() {
    setLoading(true); setErr('')
    try {
      const data = await api.auditRegistry()
      setRows(data)
      // largeurs persistees (sinon defauts)
      try {
        const pref = await api.uiPrefGet(PREF_KEY)
        if (pref && pref.value) setWidths({ ...DEFAULT_WIDTHS, ...pref.value })
      } catch (e) { /* defauts */ }
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  function onSaved(updated) {
    setRows(rs => rs.map(r => r.audit_key === updated.audit_key ? updated : r))
  }
  function onResize(key, w) { setWidths(prev => ({ ...prev, [key]: w })) }

  async function saveWidths() {
    setSavingW(true); setWMsg('')
    try { await api.uiPrefSet(PREF_KEY, widths); setWMsg('✓ largeurs enregistrées') }
    catch (e) { setWMsg('✗ ' + e.message) } finally { setSavingW(false) }
  }
  function resetWidths() { setWidths(DEFAULT_WIDTHS); setWMsg('largeurs par défaut (non enregistrées)') }

  if (loading) return <div className="card">⟳ Chargement du registre…</div>
  if (err) return <div className="card" style={{ color: 'var(--danger)' }}>✗ {err}</div>
  if (!rows) return null

  const groups = {}
  for (const r of rows) (groups[r.onglet_cible] = groups[r.onglet_cible] || []).push(r)

  const colgroup = (
    <colgroup>{COLS.map(c => <col key={c.key} style={{ width: widths[c.key] }} />)}</colgroup>
  )

  return (
    <div>
      <div className="card" style={{ marginBottom: 12, display: 'flex',
           justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <strong>🛠 Audit ZimaTAG — registre des audits</strong>
          <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 4 }}>
            {rows.length} audits · glissez le bord des colonnes pour ajuster les largeurs.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {wMsg && <span style={{ fontSize: 12, color: wMsg[0] === '✓' ? 'var(--success)' : 'var(--muted)' }}>{wMsg}</span>}
          <button className="btn-ghost" onClick={resetWidths} style={{ fontSize: 12 }}>↺ Réinitialiser</button>
          <button className="btn-primary" onClick={saveWidths} disabled={savingW} style={{ fontSize: 12 }}>
            {savingW ? '…' : '💾 Enregistrer largeurs'}
          </button>
          <button className="btn-ghost" onClick={load} style={{ fontSize: 12 }}>↻ Recharger</button>
          <a className="btn-ghost" href="/api/audit-registry/export" target="_blank" rel="noreferrer"
             style={{ fontSize: 12, textDecoration: 'none' }}>⬇ Export JSON</a>
        </div>
      </div>

      {Object.entries(groups).map(([grp, items]) => (
        <div key={grp} className="card" style={{ marginBottom: 12, padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)',
               background: 'var(--bg)', fontWeight: 600 }}>
            {grp} <span style={{ color: 'var(--muted)', fontWeight: 400, fontSize: 12 }}>
              ({items.length})</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ tableLayout: 'fixed', width: 'max-content', fontSize: 12 }}>
              {colgroup}
              <thead><HeadRow widths={widths} onResize={onResize} /></thead>
              <tbody>
                {items.map(r => <Row key={r.audit_key} row={r} onSaved={onSaved} />)}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  )
}
