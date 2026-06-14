import { useMemo, useState } from 'react'
import type { GraphNode, GraphEdge } from '../api'

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  accountId: string
}

const NODE_COLOR: Record<string, string> = {
  source:   '#3b82f6',
  account:  '#8b5cf6',
  wallet:   '#f59e0b',
  external: '#6b7280',
}

// A simple table-based graph summary (real force-directed layout would need d3 / react-force-graph)
export function TransactionGraph({ nodes, edges, accountId }: Props) {
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [filter, setFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')

  const recipients = nodes.filter(n => n.id !== accountId)

  const filtered = useMemo(() => {
    let list = recipients
    if (typeFilter) list = list.filter(n => n.type === typeFilter)
    if (filter) list = list.filter(n => n.label.toLowerCase().includes(filter.toLowerCase()) || n.id.toLowerCase().includes(filter.toLowerCase()))
    return list
  }, [recipients, filter, typeFilter])

  const edgeMap = useMemo(() => {
    const m: Record<string, GraphEdge> = {}
    for (const e of edges) m[e.to] = e
    return m
  }, [edges])

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div className="bg-blue-50 rounded-lg p-3 text-center">
          <p className="text-xs text-blue-600 font-medium">Total connections</p>
          <p className="text-2xl font-bold text-blue-700">{recipients.length}</p>
        </div>
        <div className="bg-purple-50 rounded-lg p-3 text-center">
          <p className="text-xs text-purple-600 font-medium">Account recipients</p>
          <p className="text-2xl font-bold text-purple-700">{recipients.filter(n => n.type === 'account').length}</p>
        </div>
        <div className="bg-amber-50 rounded-lg p-3 text-center">
          <p className="text-xs text-amber-600 font-medium">Crypto wallets</p>
          <p className="text-2xl font-bold text-amber-700">{recipients.filter(n => n.type === 'wallet').length}</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        <input
          type="search"
          placeholder="Filter recipients…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm flex-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <select
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All types</option>
          <option value="account">Account</option>
          <option value="wallet">Wallet</option>
          <option value="external">External</option>
        </select>
      </div>

      <div className="flex gap-4">
        {/* Node list */}
        <div className="flex-1 overflow-hidden rounded-lg border border-gray-200">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-gray-200 text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="text-left px-3 py-2">Recipient</th>
                <th className="text-center px-3 py-2">Type</th>
                <th className="text-right px-3 py-2">Txns</th>
                <th className="text-right px-3 py-2">Avg amount</th>
                <th className="text-center px-3 py-2">Risk</th>
                <th className="text-center px-3 py-2">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 max-h-96 overflow-y-auto">
              {filtered.slice(0, 100).map(node => {
                const edge = edgeMap[node.id]
                const isSelected = selected?.id === node.id
                return (
                  <tr
                    key={node.id}
                    className={`cursor-pointer transition-colors ${isSelected ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                    onClick={() => setSelected(isSelected ? null : node)}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span
                          className="inline-block w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: NODE_COLOR[node.type] ?? '#94a3b8' }}
                        />
                        <span className={`truncate max-w-[160px] ${node.is_sanctioned ? 'text-red-700 font-semibold' : 'text-gray-700'}`}>
                          {node.label}
                        </span>
                        {node.is_sanctioned && <span className="text-red-500" title="Sanctioned">⚠️</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-center text-gray-500 capitalize">{node.type}</td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums">{edge?.transaction_count ?? node.transaction_count ?? 0}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-gray-600">
                      {edge?.avg_amount != null ? `$${edge.avg_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—'}
                    </td>
                    <td className="px-3 py-2 text-center tabular-nums">
                      {node.overall_risk_score != null ? node.overall_risk_score.toFixed(0) : '—'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      {node.latest_verdict ? (
                        <span className={`text-xs font-semibold ${
                          node.latest_verdict === 'BLOCK' ? 'text-red-600' :
                          node.latest_verdict === 'REVIEW' ? 'text-amber-600' : 'text-green-600'
                        }`}>{node.latest_verdict}</span>
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {filtered.length > 100 && (
            <p className="text-xs text-gray-400 text-center py-2 border-t border-gray-100">
              Showing 100 of {filtered.length} — filter to narrow down
            </p>
          )}
        </div>

        {/* Detail panel */}
        {selected && (
          <div className="w-64 shrink-0 bg-white border border-gray-200 rounded-lg p-4 space-y-3 self-start">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs text-gray-400 capitalize">{selected.type}</p>
                <p className="font-semibold text-gray-900 text-sm break-all">{selected.label}</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-gray-300 hover:text-gray-500 text-lg leading-none ml-2">×</button>
            </div>

            {selected.overall_risk_score != null && (
              <div>
                <p className="text-xs text-gray-400">Risk score</p>
                <p className="font-bold text-lg">{selected.overall_risk_score.toFixed(1)}</p>
                <p className="text-xs text-gray-500">{selected.risk_band}</p>
              </div>
            )}

            {selected.latest_verdict && (
              <div>
                <p className="text-xs text-gray-400">Latest verdict</p>
                <span className={`text-sm font-semibold ${
                  selected.latest_verdict === 'BLOCK' ? 'text-red-600' :
                  selected.latest_verdict === 'REVIEW' ? 'text-amber-600' : 'text-green-600'
                }`}>{selected.latest_verdict}</span>
              </div>
            )}

            {(() => {
              const edge = edgeMap[selected.id]
              if (!edge) return null
              return (
                <>
                  <div>
                    <p className="text-xs text-gray-400">Transactions</p>
                    <p className="font-semibold">{edge.transaction_count} txns · ${edge.total_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })} total</p>
                    <p className="text-xs text-gray-500">Avg ${edge.avg_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Rails</p>
                    <p className="text-xs text-gray-600">{Object.entries(edge.payment_rails).map(([k,v]) => `${k} (${v})`).join(', ')}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Currencies</p>
                    <p className="text-xs text-gray-600">{Object.entries(edge.currencies).map(([k,v]) => `${k} (${v})`).join(', ')}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Date range</p>
                    <p className="text-xs text-gray-600">{edge.first_transaction?.slice(0, 10)} → {edge.last_transaction?.slice(0, 10)}</p>
                  </div>
                </>
              )
            })()}

            {selected.chain && (
              <div>
                <p className="text-xs text-gray-400">Chain</p>
                <p className="text-sm">{selected.chain}</p>
              </div>
            )}
            {selected.is_sanctioned && (
              <p className="text-xs text-red-600 font-semibold">⚠️ Sanctioned address</p>
            )}
            {selected.type === 'account' && (
              <a
                href={`/accounts/${selected.id}`}
                className="block text-center text-xs bg-blue-600 text-white rounded-lg py-1.5 hover:bg-blue-700"
              >
                View account →
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
