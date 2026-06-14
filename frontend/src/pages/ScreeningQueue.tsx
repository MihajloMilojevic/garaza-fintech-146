import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getScreeningQueue, type ScreeningResult } from '../api'
import { VerdictBadge } from '../components/VerdictBadge'
import { ThresholdBar } from '../components/ThresholdBar'
import { Spinner } from '../components/Spinner'

const CONTEXTS = ['', 'account', 'transaction']

export function ScreeningQueue() {
  const [results, setResults]       = useState<ScreeningResult[]>([])
  const [total, setTotal]           = useState(0)
  const [page, setPage]             = useState(1)
  const [loading, setLoading]       = useState(false)
  const [context, setContext]       = useState('')
  const [differOnly, setDifferOnly] = useState(false)
  const [expanded, setExpanded]     = useState<string | null>(null)
  const LIMIT = 30

  const load = useCallback(() => {
    setLoading(true)
    getScreeningQueue({
      verdict: 'REVIEW',
      page,
      limit: LIMIT,
      ...(context ? { context } : {}),
      ...(differOnly ? { verdicts_differ: true } : {}),
    })
      .then(d => { setResults(d.results); setTotal(d.total) })
      .finally(() => setLoading(false))
  }, [page, context, differOnly])

  useEffect(() => { setPage(1) }, [context, differOnly])
  useEffect(() => { load() }, [load])

  const pages = Math.ceil(total / LIMIT)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Screening Queue</h1>
        <span className="text-sm text-gray-500">{total.toLocaleString()} REVIEW events</span>
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <select
          value={context}
          onChange={e => setContext(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {CONTEXTS.map(c => <option key={c} value={c}>{c || 'All contexts'}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input type="checkbox" checked={differOnly} onChange={e => setDifferOnly(e.target.checked)} className="rounded" />
          AI ≠ static rule only ⚡
        </label>
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Spinner size="lg" /></div>
      ) : (
        <div className="space-y-2">
          {results.map(r => (
            <div key={r.screening_id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              {/* Row */}
              <div
                className="flex items-center gap-4 px-4 py-3 cursor-pointer hover:bg-gray-50"
                onClick={() => setExpanded(expanded === r.screening_id ? null : r.screening_id)}
              >
                <VerdictBadge verdict={r.verdict} />
                <span className="font-mono text-xs text-gray-500 w-28 shrink-0">{r.screening_id}</span>
                <Link
                  to={`/accounts/${r.account_id}`}
                  className="text-blue-600 hover:underline font-mono text-xs w-24 shrink-0"
                  onClick={e => e.stopPropagation()}
                >
                  {r.account_id}
                </Link>
                <span className="text-xs text-gray-500 capitalize">{r.context}</span>
                <span className="text-xs text-gray-400 ml-auto">{r.screened_at?.replace('T', ' ').slice(0, 16)}</span>
                {r.verdicts_differ && <span className="text-xs text-orange-500 font-medium">⚡ AI ≠ rule</span>}
                <span className="text-gray-300">{expanded === r.screening_id ? '▲' : '▼'}</span>
              </div>

              {/* Expanded threshold view */}
              {expanded === r.screening_id && (
                <div className="border-t border-gray-100 px-6 py-4 bg-gray-50">
                  <div className="max-w-2xl">
                    <p className="text-xs text-gray-500 mb-3">
                      match_score = <strong>{r.match_score.toFixed(2)}</strong> ·
                      t_block = <strong>{r.t_block.toFixed(4)}</strong> ·
                      t_review = <strong>{r.t_review.toFixed(4)}</strong>
                    </p>
                    <ThresholdBar
                      tBlock={r.t_block}
                      tReview={r.t_review}
                      matchScore={r.match_score}
                    />
                    <div className="mt-3 flex gap-3">
                      <Link
                        to={`/accounts/${r.account_id}`}
                        className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
                      >
                        View account
                      </Link>
                      <button className="text-xs border border-gray-300 px-3 py-1.5 rounded-lg hover:bg-white text-gray-600">
                        Mark reviewed ✓
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {pages > 1 && (
        <div className="flex justify-center gap-2 text-sm">
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1.5 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-50">← Prev</button>
          <span className="px-3 py-1.5 text-gray-500">Page {page} / {pages}</span>
          <button disabled={page === pages} onClick={() => setPage(p => p + 1)} className="px-3 py-1.5 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-50">Next →</button>
        </div>
      )}
    </div>
  )
}
