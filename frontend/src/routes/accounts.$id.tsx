import { createFileRoute, Link } from "@tanstack/react-router";
import { useSuspenseQuery, useQuery } from "@tanstack/react-query";
import { TopNav } from "@/components/TopNav";
import { ThresholdBar } from "@/components/ThresholdBar";
import { AuditPanel } from "@/components/AuditPanel";
import { qk } from "@/lib/api/queries";
import { verdictColor } from "@/lib/api/client";

export const Route = createFileRoute("/accounts/$id")({
  ssr: false,
  head: ({ params }) => ({
    meta: [
      { title: `${params.id} — Account` },
      { name: "description", content: `Risk profile, screening, and transactions for ${params.id}.` },
      { property: "og:title", content: `${params.id} — Account` },
      { property: "og:description", content: `Risk profile, screening, and transactions for ${params.id}.` },
    ],
  }),
  loader: ({ context, params }) => {
    context.queryClient.ensureQueryData(qk.account(params.id));
    context.queryClient.prefetchQuery(qk.accountTxs(params.id, { limit: 20 }));
    context.queryClient.prefetchQuery(qk.thresholdExplain(params.id));
  },
  component: AccountDetailPage,
  errorComponent: ({ error }) => (
    <div className="p-8 text-sm text-rose-600">Failed to load account: {error.message}</div>
  ),
  notFoundComponent: () => <div className="p-8 text-sm">Not found.</div>,
});

function AccountDetailPage() {
  const { id } = Route.useParams();
  const { data: account } = useSuspenseQuery(qk.account(id));
  const txQ = useQuery(qk.accountTxs(id, { limit: 20 }));
  const thresholdQ = useQuery(qk.thresholdExplain(id));

  return (
    <div className="min-h-dvh w-full bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
        <TopNav />
        <header className="rounded-2xl border border-slate-200 bg-white p-6">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-400">Account</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-4">
            <h1 className="font-mono text-2xl font-bold text-slate-900">{account.account.account_id}</h1>
            <span className="text-xl text-slate-700">{account.account.full_name}</span>
            <span
              className="rounded-full px-3 py-1 text-xs font-bold uppercase text-white"
              style={{ background: verdictColor(account.latest_screening.verdict) }}
            >
              {account.latest_screening.verdict}
            </span>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold uppercase text-slate-700">
              {account.risk_score.risk_band} · {account.risk_score.overall_risk_score.toFixed(2)}
            </span>
          </div>
          <p className="mt-2 text-sm text-slate-500">
            {account.account.account_type} · {account.account.account_status} ·{" "}
            {account.account.country_residence.toUpperCase()} · created {account.account.created_at}
          </p>
        </header>

        <div className="grid grid-cols-12 gap-6">
          <section className="col-span-12 lg:col-span-7 rounded-2xl border border-slate-200 bg-white p-6 space-y-6">
            <div>
              <h2 className="mb-4 text-sm font-bold uppercase tracking-wider text-slate-500">
                Threshold decision
              </h2>
              <ThresholdBar
                t_review={account.threshold_decision.t_review}
                t_block={account.threshold_decision.t_block}
                match_score={account.threshold_decision.match_score}
              />
              <p className="mt-2 text-sm text-slate-600">{account.threshold_decision.zone}</p>
            </div>

            {thresholdQ.data && (
              <div className="rounded-xl bg-slate-50 p-4 text-sm">
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">
                  Why these thresholds?
                </h3>
                <p className="mb-2 text-slate-700">{thresholdQ.data.formula.interpretation}</p>
                <dl className="grid grid-cols-1 gap-x-6 gap-y-1 md:grid-cols-2">
                  {Object.entries(thresholdQ.data.formula).map(([k, v]) =>
                    k === "interpretation" ? null : (
                      <div key={k} className="flex justify-between gap-3">
                        <dt className="font-mono text-xs text-slate-500">{k}</dt>
                        <dd className="font-semibold text-slate-800">{String(v)}</dd>
                      </div>
                    ),
                  )}
                </dl>
              </div>
            )}

            <div>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-bold uppercase tracking-wider text-slate-500">
                  Recent transactions
                </h2>
                {txQ.data && (
                  <span className="text-xs text-slate-500">{txQ.data.total} total</span>
                )}
              </div>
              {txQ.isLoading ? (
                <p className="text-sm text-slate-500">Loading…</p>
              ) : txQ.data && txQ.data.transactions.length > 0 ? (
                <ul className="divide-y divide-slate-100">
                  {txQ.data.transactions.map((t) => (
                    <li key={t.transaction_id} className="grid grid-cols-12 gap-2 py-2 text-sm">
                      <span className="col-span-3 font-mono text-xs text-slate-700">
                        {t.transaction_id}
                      </span>
                      <span className="col-span-2 font-bold text-slate-900">
                        {t.amount.toLocaleString(undefined, {
                          style: "currency",
                          currency: t.currency,
                        })}
                      </span>
                      <span className="col-span-2 text-slate-600">{t.payment_rail}</span>
                      <span className="col-span-3 truncate text-slate-600">
                        → {t.recipient_name ?? `(${t.recipient_type})`} · {t.recipient_country}
                      </span>
                      <span className="col-span-2 text-right text-xs text-slate-500">
                        {new Date(t.timestamp).toLocaleDateString()}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-500">No transactions for this account.</p>
              )}
            </div>

            <div>
              <Link
                to="/transactions/$id"
                params={{ id: account.latest_screening.screening_id }}
                className="inline-flex rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700"
              >
                Open latest screening →
              </Link>
            </div>
          </section>

          <aside className="col-span-12 lg:col-span-5 rounded-2xl border border-slate-200 bg-white p-6">
            <AuditPanel
              verdict={account.audit.verdict}
              audit_narrative={account.audit.audit_narrative}
              audit_factors={account.audit.audit_factors}
              class_probabilities={account.audit.class_probabilities}
              feature_contributions={account.audit.feature_contributions}
              block_probability={account.audit.block_probability}
            />
          </aside>
        </div>
      </div>
    </div>
  );
}