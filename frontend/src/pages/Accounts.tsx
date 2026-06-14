import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAccounts, type AccountSummary } from '../api'
import { VerdictBadge } from '../components/VerdictBadge'
import { Spinner } from '../components/Spinner'

const RISK_BANDS = ['', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
const VERDICTS   = ['', 'BLOCK', 'REVIEW', 'CLEAR']

function useDebounce<T>(value: T, ms: number): T {
  const [dv, setDv] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDv(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return dv
}

export function Accounts() {
  const [accounts, setAccounts] = useState<AccountSummary[]>([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [loading, setLoading]   = useState(false)
  const [search, setSearch]     = useState('')
  const [riskBand, setRiskBand] = useState('')
  const [verdict, setVerdict]   = useState('')
  const navigate = useNavigate()

  const dSearch = useDebounce(search, 300)
  const LIMIT = 50

  const load = useCallback(() => {
    setLoading(true)
    getAccounts({
      page,
      limit: LIMIT,
      ...(dSearch  ? { search: dSearch }    : {}),
      ...(riskBand ? { risk_band: riskBand } : {}),
      ...(verdict  ? { verdict }             : {}),
    })
      .then(d => { setAccounts(d.accounts); setTotal(d.total) })
      .finally(() => setLoading(false))
  }, [page, dSearch, riskBand, verdict])

  useEffect(() => { setPage(1) }, [dSearch, riskBand, verdict])
  useEffect(() => { load() }, [load])

  const pages = Math.ceil(total / LIMIT)

  const BAND_COLOR: Record<string, string> = {
    LOW: 'text-green-700', MEDIUM: 'text-yellow-700', HIGH: 'text-orange-600', CRITICAL: 'text-red-700'
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-gray-900">Account Explorer</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <input
          type="search"
          placeholder="Search by ID or name…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <select
          value={riskBand}
          onChange={e => setRiskBand(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {RISK_BANDS.map(b => <option key={b} value={b}>{b || 'All risk bands'}</option>)}
        </select>
        <select
          value={verdict}
          onChange={e => setVerdict(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {VERDICTS.map(v => <option key={v} value={v}>{v || 'All verdicts'}</option>)}
        </select>
        <span className="ml-auto text-sm text-gray-500 self-center">
          {total.toLocaleString()} accounts
        </span>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-16"><Spinner size="lg" /></div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr className="text-xs text-gray-500 uppercase tracking-wide">
                <th className="text-left px-4 py-3">Account ID</th>
                <th className="text-left px-4 py-3">Name</th>
                <th className="text-left px-4 py-3">Type</th>
                <th className="text-left px-4 py-3">KYC</th>
                <th className="text-right px-4 py-3">Risk</th>
                <th className="text-center px-4 py-3">Band</th>
                <th className="text-right px-4 py-3">Match</th>
                <th className="text-center px-4 py-3">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {accounts.map(a => (
                <tr
                  key={a.account_id}
                  className="hover:bg-blue-50 cursor-pointer transition-colors"
                  onClick={() => navigate(`/accounts/${a.account_id}`)}
                >
                  <td className="px-4 py-3 font-mono text-xs text-blue-700">{a.account_id}</td>
                  <td className="px-4 py-3 max-w-[180px] truncate text-gray-800">{a.full_name}</td>
                  <td className="px-4 py-3 text-gray-600 capitalize">{a.account_type}</td>
                  <td className="px-4 py-3 text-gray-600">{a.kyc_status}</td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums">{a.overall_risk_score?.toFixed(1) ?? '—'}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`text-xs font-semibold ${BAND_COLOR[a.risk_band] ?? 'text-gray-600'}`}>{a.risk_band}</span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-gray-600">{a.latest_match_score?.toFixed(1) ?? '—'}</td>
                  <td className="px-4 py-3 text-center">
                    <VerdictBadge verdict={a.latest_verdict} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex justify-center gap-2 text-sm">
          <button
            disabled={page === 1}
            onClick={() => setPage(p => p - 1)}
            className="px-3 py-1.5 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-50"
          >← Prev</button>
          <span className="px-3 py-1.5 text-gray-500">Page {page} / {pages}</span>
          <button
            disabled={page === pages}
            onClick={() => setPage(p => p + 1)}
            className="px-3 py-1.5 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-50"
          >Next →</button>
        </div>
      )}
    </div>
  )
}
