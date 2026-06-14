import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getAccount, getTransactions, type AccountDetail, type TransactionsResponse } from '../api'
import { VerdictBadge } from '../components/VerdictBadge'
import { ThresholdBar } from '../components/ThresholdBar'
import { AuditPanel } from '../components/AuditPanel'
import { RiskBar } from '../components/RiskBar'
import { Spinner } from '../components/Spinner'
import { TransactionGraph } from '../components/TransactionGraph'

function Pill({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <div className={`rounded-lg border px-4 py-3 ${highlight ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-white'}`}>
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-sm font-semibold mt-0.5 ${highlight ? 'text-red-700' : 'text-gray-800'}`}>{value}</p>
    </div>
  )
}

export function AccountDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail]     = useState<AccountDetail | null>(null)
  const [txData, setTxData]     = useState<TransactionsResponse | null>(null)
  const [txPage, setTxPage]     = useState(1)
  const [loadingTx, setLoadingTx] = useState(false)
  const [tab, setTab]           = useState<'overview' | 'transactions' | 'graph' | 'relationships'>('overview')

  useEffect(() => {
    if (!id) return
    getAccount(id).then(setDetail)
  }, [id])

  useEffect(() => {
    if (!id) return
    setLoadingTx(true)
    getTransactions(id, { page: txPage, limit: 20 })
      .then(setTxData)
      .finally(() => setLoadingTx(false))
  }, [id, txPage])

  if (!detail) return <div className="flex justify-center py-20"><Spinner size="lg" /></div>

  const { account, risk_score, threshold_decision, audit } = detail
  const tx = txData
  const te = tx?.threshold_explanation
  const RISK_COMPONENTS = [
    { label: 'PEP & Sanctions risk',    value: risk_score.pep_sanctions_risk },
    { label: 'Behavioural risk',         value: risk_score.behavioural_risk },
    { label: 'Geographic risk',          value: risk_score.geographic_risk },
    { label: 'Identity / KYC risk',      value: risk_score.identity_kyc_risk },
    { label: 'Relationship network risk', value: risk_score.relationship_network_risk },
  ]

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Link to="/accounts" className="text-xs text-gray-400 hover:text-gray-600">← Accounts</Link>
          </div>
          <h1 className="text-xl font-bold text-gray-900 truncate">{account.full_name}</h1>
          <p className="text-sm text-gray-500 font-mono">{account.account_id}</p>
        </div>
        <div className="flex items-center gap-3">
          <VerdictBadge verdict={audit.verdict} large />
          <span className="text-sm text-gray-500">Risk {risk_score.overall_risk_score.toFixed(1)} · {risk_score.risk_band}</span>
        </div>
      </div>

      {/* Threshold bar */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Threshold visualisation</h2>
        <ThresholdBar
          tBlock={threshold_decision.t_block}
          tReview={threshold_decision.t_review}
          matchScore={threshold_decision.match_score}
        />
        {te && (
          <p className="mt-3 text-xs text-gray-500 border-t border-gray-100 pt-3">
            {te.static_vs_dynamic}
          </p>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 flex gap-1">
        {(['overview', 'transactions', 'graph', 'relationships'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px ${
              tab === t ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {t === 'relationships' ? `Relationships (${tx?.relationship_count ?? '…'})` :
             t === 'transactions' ? `Transactions (${tx?.summary.total_transactions ?? '…'})` : t}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {tab === 'overview' && (
        <div className="grid md:grid-cols-2 gap-6">
          {/* Account info */}
          <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
            <h2 className="text-sm font-semibold text-gray-700">Account info</h2>
            <div className="grid grid-cols-2 gap-3">
              <Pill label="Type"       value={account.account_type} />
              <Pill label="KYC status" value={account.kyc_status} />
              <Pill label="KYC completeness" value={`${(account.kyc_completeness * 100).toFixed(0)}%`} />
              <Pill label="Activity tier" value={account.activity_tier} />
              <Pill label="Status"     value={account.account_status} />
              <Pill label="Country"    value={account.country_residence || '—'} />
              <Pill label="PEP"        value={account.is_pep ? 'Yes' : 'No'} highlight={!!account.is_pep} />
              <Pill label="Complex ownership" value={account.has_complex_ownership ? 'Yes' : 'No'} />
              <Pill label="Shell company" value={account.shell_company_flag ? 'Yes' : 'No'} highlight={!!account.shell_company_flag} />
              <Pill label="Created"    value={account.created_at?.split(' ')[0] ?? '—'} />
            </div>
          </div>

          {/* Risk score breakdown */}
          <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-700">Risk score breakdown</h2>
              <span className="text-2xl font-bold text-gray-900">{risk_score.overall_risk_score.toFixed(1)}</span>
            </div>
            <div className="space-y-2.5">
              {RISK_COMPONENTS.map(c => <RiskBar key={c.label} label={c.label} value={c.value} />)}
            </div>
            <p className="text-xs text-gray-400">{risk_score.risk_formula}</p>
          </div>

          {/* Threshold formula */}
          {te && (
            <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
              <h2 className="text-sm font-semibold text-gray-700">Threshold formula</h2>
              <div className="font-mono text-xs text-gray-600 space-y-1 bg-gray-50 rounded-lg p-3">
                <p>{te.risk_deviation}</p>
                <p>{te.adjustment}</p>
                <p>{te.t_block_unclamped} → clamped {te.t_block_clamp_range} = <strong>{te.t_block_final}</strong></p>
                <p>{te.t_review_unclamped} → clamped {te.t_review_clamp_range} = <strong>{te.t_review_final}</strong></p>
              </div>
              <p className="text-xs text-gray-500">{te.interpretation}</p>
              <div className="grid grid-cols-3 gap-2 text-xs">
                {Object.entries(te.decision_zones).map(([v, zone]) => (
                  <div key={v} className="bg-gray-50 rounded p-2">
                    <p className="font-semibold text-gray-700">{v}</p>
                    <p className="text-gray-500 mt-0.5">{zone}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Audit panel */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">AI audit</h2>
            <AuditPanel
              audit={tx?.model_output ?? audit}
              tBlock={threshold_decision.t_block}
              tReview={threshold_decision.t_review}
            />
          </div>
        </div>
      )}

      {/* Transactions tab */}
      {tab === 'transactions' && (
        <div className="space-y-4">
          {tx && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: 'Total sent', value: `$${tx.summary.total_sent_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}` },
                { label: 'Avg transaction', value: `$${tx.summary.avg_transaction_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}` },
                { label: 'Unique recipients', value: tx.summary.unique_recipients },
                { label: 'BLOCK / REVIEW', value: `${tx.summary.screening_verdicts.BLOCK ?? 0} / ${tx.summary.screening_verdicts.REVIEW ?? 0}` },
              ].map(c => (
                <div key={c.label} className="bg-white rounded-xl border border-gray-200 px-4 py-3">
                  <p className="text-xs text-gray-500">{c.label}</p>
                  <p className="text-lg font-bold text-gray-900">{c.value}</p>
                </div>
              ))}
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {loadingTx ? (
              <div className="flex justify-center py-10"><Spinner /></div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr className="text-xs text-gray-500 uppercase tracking-wide">
                    <th className="text-left px-4 py-3">ID</th>
                    <th className="text-right px-4 py-3">Amount</th>
                    <th className="text-left px-4 py-3">Rail</th>
                    <th className="text-left px-4 py-3">Recipient</th>
                    <th className="text-left px-4 py-3">Country</th>
                    <th className="text-right px-4 py-3">Match</th>
                    <th className="text-center px-4 py-3">Verdict</th>
                    <th className="text-left px-4 py-3">Time</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {txData?.transactions.map(t => (
                    <tr key={t.transaction_id} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-mono text-xs text-gray-500">{t.transaction_id}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {t.amount?.toLocaleString(undefined, { maximumFractionDigits: 2 })} {t.currency}
                      </td>
                      <td className="px-4 py-2 text-gray-600">{t.payment_rail}</td>
                      <td className="px-4 py-2 max-w-[140px]">
                        {t.recipient_account_id ? (
                          <Link to={`/accounts/${t.recipient_account_id}`} className="text-blue-600 hover:underline font-mono text-xs">
                            {t.recipient_account_id}
                          </Link>
                        ) : (
                          <span className="text-gray-600 text-xs truncate block">{t.recipient_name || t.recipient_wallet_id?.slice(0, 12) + '…' || '—'}</span>
                        )}
                        {t.recipient_risk_score != null && (
                          <span className="text-xs text-gray-400">risk {t.recipient_risk_score.toFixed(0)}</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-gray-600">{t.recipient_country}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {t.screening?.match_score?.toFixed(1) ?? '—'}
                      </td>
                      <td className="px-4 py-2 text-center">
                        {t.screening ? <VerdictBadge verdict={t.screening.dynamic_verdict} /> : <span className="text-gray-300">—</span>}
                        {t.screening?.verdicts_differ && (
                          <span className="ml-1 text-xs text-orange-500" title="Dynamic and static verdicts differ">⚡</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-400">{t.timestamp?.replace('T', ' ').slice(0, 16)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Pagination */}
          {txData && txData.total > 20 && (
            <div className="flex justify-center gap-2 text-sm">
              <button disabled={txPage === 1} onClick={() => setTxPage(p => p - 1)} className="px-3 py-1.5 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-50">← Prev</button>
              <span className="px-3 py-1.5 text-gray-500">Page {txPage} / {Math.ceil(txData.total / 20)}</span>
              <button disabled={txPage >= Math.ceil(txData.total / 20)} onClick={() => setTxPage(p => p + 1)} className="px-3 py-1.5 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-50">Next →</button>
            </div>
          )}
        </div>
      )}

      {/* Graph tab */}
      {tab === 'graph' && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Connection graph</h2>
          {tx ? (
            <TransactionGraph
              nodes={tx.transaction_graph.nodes}
              edges={tx.transaction_graph.edges}
              accountId={id!}
            />
          ) : (
            <div className="flex justify-center py-10"><Spinner /></div>
          )}
        </div>
      )}

      {/* Relationships tab */}
      {tab === 'relationships' && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {tx && tx.relationships.length === 0 ? (
            <p className="text-sm text-gray-400 p-6">No formal relationships recorded.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr className="text-xs text-gray-500 uppercase tracking-wide">
                  <th className="text-left px-4 py-3">Entity</th>
                  <th className="text-left px-4 py-3">Type</th>
                  <th className="text-center px-4 py-3">PEP</th>
                  <th className="text-center px-4 py-3">Sanctioned</th>
                  <th className="text-left px-4 py-3">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {tx?.relationships.map(r => (
                  <tr key={r.relationship_id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-800">{r.related_entity_name}</td>
                    <td className="px-4 py-2 capitalize text-gray-600">{r.relationship_type}</td>
                    <td className="px-4 py-2 text-center">
                      {r.related_is_pep ? <span className="text-amber-600 font-semibold">Yes</span> : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-2 text-center">
                      {r.related_is_sanctioned ? (
                        <span className="text-red-600 font-semibold" title={r.sanctioned_entity_id ?? ''}>Yes ⚠️</span>
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-400">{r.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
