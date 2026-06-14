import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { getDashboardStats, type DashboardStats } from '../api'
import { VerdictBadge } from '../components/VerdictBadge'
import { Spinner } from '../components/Spinner'

const VERDICT_COLORS = { BLOCK: '#ef4444', REVIEW: '#f59e0b', CLEAR: '#22c55e' }
const BAND_COLORS: Record<string, string> = { low: '#22c55e', medium: '#facc15', high: '#f97316', critical: '#ef4444' }

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs text-gray-500 uppercase tracking-wide font-medium">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

export function Dashboard() {
  const [data, setData] = useState<DashboardStats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getDashboardStats().then(setData).catch(() => setError('Could not load stats'))
  }, [])

  if (error) return <p className="text-red-500 p-4">{error}</p>
  if (!data) return <div className="flex justify-center py-20"><Spinner size="lg" /></div>

  const verdictData = Object.entries(data.verdict_distribution).map(([name, value]) => ({ name, value }))
  const bandData = Object.entries(data.risk_band_counts).map(([name, value]) => ({ name: name.toUpperCase(), value }))

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total accounts" value={data.total_accounts.toLocaleString()} />
        <StatCard label="Screening events" value={data.total_screening_events.toLocaleString()} />
        <StatCard
          label="Verdicts differ"
          value={`${data.verdicts_differ_pct}%`}
          sub={`${data.verdicts_differ_count.toLocaleString()} events where AI ≠ static rule`}
        />
        <StatCard
          label="BLOCK / REVIEW"
          value={`${data.verdict_distribution.BLOCK} / ${data.verdict_distribution.REVIEW}`}
          sub="account-level screenings"
        />
      </div>

      {/* Charts */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Verdict donut */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Verdict distribution</h2>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={verdictData} dataKey="value" cx="50%" cy="50%" innerRadius={55} outerRadius={90} label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ''} ${((percent ?? 0) * 100).toFixed(0)}%`}>
                {verdictData.map(entry => (
                  <Cell key={entry.name} fill={VERDICT_COLORS[entry.name as keyof typeof VERDICT_COLORS]} />
                ))}
              </Pie>
              <Tooltip formatter={(v: unknown) => (typeof v === 'number' ? v.toLocaleString() : String(v))} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Risk band bar */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Risk band distribution</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={bandData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v: unknown) => (typeof v === 'number' ? v.toLocaleString() : String(v))} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {bandData.map(entry => (
                  <Cell key={entry.name} fill={BAND_COLORS[entry.name.toLowerCase()] ?? '#94a3b8'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top risk accounts */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Top 5 highest-risk accounts</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
              <th className="text-left py-2 pr-4">Account</th>
              <th className="text-left py-2 pr-4">Name</th>
              <th className="text-right py-2 pr-4">Risk score</th>
              <th className="text-center py-2 pr-4">Band</th>
              <th className="text-center py-2 pr-4">Verdict</th>
              <th className="text-right py-2">Match score</th>
            </tr>
          </thead>
          <tbody>
            {data.top_risk_accounts.map(a => (
              <tr key={a.account_id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="py-2 pr-4">
                  <Link to={`/accounts/${a.account_id}`} className="text-blue-600 hover:underline font-mono text-xs">
                    {a.account_id}
                  </Link>
                </td>
                <td className="py-2 pr-4 text-gray-700 max-w-[160px] truncate">{a.full_name}</td>
                <td className="py-2 pr-4 text-right font-semibold tabular-nums">{a.overall_risk_score.toFixed(1)}</td>
                <td className="py-2 pr-4 text-center">
                  <span className="text-xs font-medium text-gray-600">{a.risk_band}</span>
                </td>
                <td className="py-2 pr-4 text-center">
                  <VerdictBadge verdict={a.latest_verdict} />
                </td>
                <td className="py-2 text-right tabular-nums text-gray-600">{a.match_score?.toFixed(1) ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
