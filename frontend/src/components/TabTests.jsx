import { useState, useCallback } from 'react'
import { api } from '../api.js'

const STATUS = {
  ok:   { color:'#22c55e', icon:'\u25CF', label:'OK' },
  fail: { color:'#ef4444', icon:'\u2717', label:'ECHEC' },
}

function Badge({ status }) {
  const s = STATUS[status] || STATUS.fail
  return (
    <span style={{ fontSize:11, fontWeight:600, padding:'2px 8px', borderRadius:4,
      background:s.color + '22', color:s.color, whiteSpace:'nowrap' }}>
      {s.icon} {s.label}
    </span>
  )
}

export default function TabTests() {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err,  setErr]  = useState('')

  const run = useCallback(() => {
    setBusy(true); setErr('')
    api.selftest()
      .then(d => setData(d))
      .catch(e => setErr(e.message || String(e)))
      .finally(() => setBusy(false))
  }, [])

  const verdictColor = data && (data.verdict === 'ok' ? '#22c55e' : '#ef4444')

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
      <div className="card">
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', flexWrap:'wrap', gap:10 }}>
          <h3 style={{ fontSize:14, margin:0 }}>Tests fonctionnels (jeu temoin)</h3>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            {data && (
              <span style={{ fontSize:12, fontWeight:600, padding:'4px 10px', borderRadius:4,
                background:verdictColor + '22', color:verdictColor }}>
                {data.passed}/{data.passed + data.failed} OK
              </span>
            )}
            <button className="btn-primary" onClick={run} disabled={busy} style={{ fontSize:12, padding:'6px 12px' }}>
              {busy ? '\u27F3 ...' : '\u25B6 Lancer les tests'}
            </button>
          </div>
        </div>
        <div style={{ marginTop:8, fontSize:11, color:'var(--muted)' }}>
          Exerce les briques du module diagnostic (signatures, agregation, filtrage), la forme de la sante et un parametre d'audit. Lecture seule.
        </div>
      </div>

      {err && (
        <div className="card" style={{ color:'var(--danger)', fontSize:13 }}>{'\u2717'} {err}</div>
      )}

      {data && (
        <div className="card" style={{ padding:0, overflow:'hidden' }}>
          {data.tests.map((t, i) => (
            <div key={t.name} style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 14px',
              borderBottom: i < data.tests.length - 1 ? '1px solid var(--border)' : 'none', flexWrap:'wrap' }}>
              <div style={{ minWidth:96 }}><Badge status={t.status} /></div>
              <div style={{ flex:'1 1 200px', minWidth:0 }}>
                <div style={{ fontSize:13, color:'var(--text)' }}>{t.name}</div>
                {t.detail && <div className="mono" style={{ fontSize:11, color:'var(--muted)', wordBreak:'break-word', marginTop:2 }}>{t.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}

      {!data && !err && (
        <div className="card" style={{ color:'var(--muted)', fontSize:13 }}>
          {busy ? '\u27F3 Execution...' : 'Cliquez sur \u00AB Lancer les tests \u00BB.'}
        </div>
      )}
    </div>
  )
}
