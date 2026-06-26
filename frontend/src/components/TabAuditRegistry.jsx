import { useState, useEffect } from 'react'
import { api } from '../api.js'

// T10 Lot F4 — page "Audit ZimaTAG" : lecture + edition du registre des audits.
// Les modifications sont persistees en base (audit_registry) via POST et prises
// en compte a la prochaine generation de rapport (lecture live).

const CLASSEMENTS = ['probleme', 'INFO', 'KPI', 'SKIP']
const ONGLETS = ['cockpit', 'kpi', 'qualite', 'integrite', 'metadonnees',
                 'doublons', 'casse', 'images', 'donnees', 'informations']

const CLS_BADGE = {
  probleme: 'badge-red', INFO: 'badge-blue', KPI: 'badge-gray', SKIP: 'badge-yellow',
}

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
        par_dossier: draft.par_dossier,  // T10 Lot G3
      }
      await api.auditRegistryUpdate(draft.audit_key, fields)
      setMsg('✓'); onSaved(draft)
    } catch (e) { setMsg('✗ ' + e.message) } finally { setBusy(false) }
  }

  return (
    <tr style={{ opacity: draft.actif ? 1 : 0.5 }}>
      <td className="mono" style={{ fontSize: 12 }}>{draft.audit_key}</td>
      <td>
        <input value={draft.libelle || ''} onChange={e => set('libelle', e.target.value)}
               style={{ width: 150, fontSize: 12 }} />
      </td>
      <td>
        <select value={draft.onglet_cible} onChange={e => set('onglet_cible', e.target.value)}
                style={{ fontSize: 12 }}>
          {ONGLETS.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      </td>
      <td>
        <select value={draft.classement_cible} onChange={e => set('classement_cible', e.target.value)}
                style={{ fontSize: 12 }}>
          {CLASSEMENTS.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </td>
      <td style={{ textAlign: 'center' }}>
        <input type="checkbox" checked={!!draft.dans_health}
               onChange={e => set('dans_health', e.target.checked ? 1 : 0)} />
      </td>
      <td>
        <input type="number" step="0.1" min="0" value={draft.poids_cible ?? 0}
               onChange={e => set('poids_cible', parseFloat(e.target.value) || 0)}
               style={{ width: 60, fontSize: 12 }} />
      </td>
      <td style={{ textAlign: 'center' }}>
        <input type="checkbox" checked={!!draft.actif}
               onChange={e => set('actif', e.target.checked ? 1 : 0)} />
      </td>
      <td style={{ textAlign: 'center' }} title={draft.classement_cible === 'INFO'
          ? 'Afficher cet audit INFO dans la vue Par dossier'
          : 'Pertinent uniquement pour les audits INFO (les problemes y sont deja, KPI/SKIP jamais)'}>
        {/* T10 Lot G3 : par_dossier editable seulement pour les INFO */}
        <input type="checkbox" checked={!!draft.par_dossier}
               disabled={draft.classement_cible !== 'INFO'}
               onChange={e => set('par_dossier', e.target.checked ? 1 : 0)} />
      </td>
      <td>
        <input value={draft.note || ''} onChange={e => set('note', e.target.value)}
               placeholder="note…" style={{ width: 140, fontSize: 12 }} />
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
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

export default function TabAuditRegistry() {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true); setErr('')
    try { setRows(await api.auditRegistry()) }
    catch (e) { setErr(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  function onSaved(updated) {
    setRows(rs => rs.map(r => r.audit_key === updated.audit_key ? updated : r))
  }

  if (loading) return <div className="card">⟳ Chargement du registre…</div>
  if (err) return <div className="card" style={{ color: 'var(--danger)' }}>✗ {err}</div>
  if (!rows) return null

  // grouper par onglet, dans l'ordre d'apparition
  const groups = {}
  for (const r of rows) (groups[r.onglet_cible] = groups[r.onglet_cible] || []).push(r)

  return (
    <div>
      <div className="card" style={{ marginBottom: 12, display: 'flex',
           justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <strong>🛠 Audit ZimaTAG — registre des audits</strong>
          <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 4 }}>
            {rows.length} audits · les modifications sont prises en compte au prochain rapport généré.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn-ghost" onClick={load} style={{ fontSize: 12 }}>↻ Recharger</button>
          <a className="btn-ghost" href="/api/audit-registry/export" target="_blank" rel="noreferrer"
             style={{ fontSize: 12, textDecoration: 'none' }}>⬇ Exporter JSON</a>
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
            <table style={{ minWidth: 880, fontSize: 12 }}>
              <thead><tr>
                <th>Clé</th><th>Libellé</th><th>Onglet</th><th>Classement</th>
                <th>Health</th><th>Poids</th><th>Actif</th><th>Dossier</th><th>Note</th><th></th>
              </tr></thead>
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
