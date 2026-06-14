import { createFileRoute, Link } from "@tanstack/react-router";
import { useSuspenseQuery } from "@tanstack/react-query";
import { TopNav } from "@/components/TopNav";
import { qk } from "@/lib/api/queries";
import { verdictColor } from "@/lib/api/client";

export const Route = createFileRoute("/dashboard")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Nexus — Dashboard" },
      { name: "description", content: "Verdict mix, risk bands, and top-risk accounts at a glance." },
      { property: "og:title", content: "Nexus — Dashboard" },
      { property: "og:description", content: "Verdict mix, risk bands, and top-risk accounts at a glance." },
    ],
  }),
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(qk.dashboardStats());
  },
  component: DashboardStatsPage,
  errorComponent: ({ error }) => (
    <div className="p-8 text-sm text-rose-600">Failed to load stats: {error.message}</div>
  ),
  notFoundComponent: () => <div className="p-8 text-sm">Not found.</div>,
});

function DashboardStatsPage() {
  const { data } = useSuspenseQuery(qk.dashboardStats());
  const verdicts = ["BLOCK", "REVIEW", "CLEAR"] as const;
  const bands = [
    { key: "critical", color: "#7f1d1d" },
    { key: "high", color: "#ef4444" },
    { key: "medium", color: "#f59e0b" },
    { key: "low", color: "#10b981" },
  ] as const;

  return (
    <div className="min-h-dvh w-full bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
        <TopNav />
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Dashboard</h1>

        <div className="grid grid-cols-12 gap-6">
          <section className="col-span-12 md:col-span-4 rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="mb-4 text-sm font-bold uppercase tracking-wider text-slate-500">
              Verdict distribution (accounts)
            </h2>
            <div className="space-y-3">
              {verdicts.map((v) => {
                const count = data.verdict_distribution[v] ?? 0;
                const pct = (count / data.total_accounts) * 100;
                return (
                  <div key={v}>
                    <div className="mb-1 flex justify-between text-sm">
                      <span className="font-bold" style={{ color: verdictColor(v) }}>
                        {v}
                      </span>
                      <span className="font-mono text-slate-700">
                        {count.toLocaleString()} · {pct.toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full"
                        style={{ width: `${pct}%`, background: verdictColor(v) }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="col-span-12 md:col-span-4 rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="mb-4 text-sm font-bold uppercase tracking-wider text-slate-500">
              Risk bands
            </h2>
            <div className="space-y-3">
              {bands.map((b) => {
                const count = data.risk_band_counts[b.key] ?? 0;
                const pct = (count / data.total_accounts) * 100;
                return (
                  <div key={b.key}>
                    <div className="mb-1 flex justify-between text-sm">
                      <span className="font-bold uppercase" style={{ color: b.color }}>
                        {b.key}
                      </span>
                      <span className="font-mono text-slate-700">
                        {count.toLocaleString()} · {pct.toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full" style={{ width: `${pct}%`, background: b.color }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="col-span-12 md:col-span-4 rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="mb-4 text-sm font-bold uppercase tracking-wider text-slate-500">
              Totals
            </h2>
            <dl className="space-y-3 text-sm">
              <Stat label="Accounts" value={data.total_accounts.toLocaleString()} />
              <Stat label="Screening events" value={data.total_screening_events.toLocaleString()} />
              <Stat
                label="AI vs rules divergence"
                value={`${data.verdicts_differ_count.toLocaleString()} (${data.verdicts_differ_pct.toFixed(2)}%)`}
              />
            </dl>
          </section>

          <section className="col-span-12 rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="mb-4 text-sm font-bold uppercase tracking-wider text-slate-500">
              Top risk accounts
            </h2>
            <ul className="divide-y divide-slate-100">
              {data.top_risk_accounts.map((a) => (
                <li key={a.account_id} className="py-3">
                  <Link
                    to="/accounts/$id"
                    params={{ id: a.account_id }}
                    className="grid grid-cols-12 items-center gap-3 rounded-lg px-2 py-1 hover:bg-slate-50"
                  >
                    <span className="col-span-3 font-mono text-sm font-bold text-slate-900">
                      {a.account_id}
                    </span>
                    <span className="col-span-4 truncate text-sm text-slate-700">
                      {a.full_name}
                    </span>
                    <span className="col-span-2 text-sm font-semibold">
                      {a.overall_risk_score.toFixed(2)} · {a.risk_band}
                    </span>
                    <span className="col-span-2 text-sm">
                      match {a.match_score.toFixed(1)}
                    </span>
                    <span
                      className="col-span-1 inline-flex items-center justify-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase text-white"
                      style={{ background: verdictColor(a.latest_verdict) }}
                    >
                      {a.latest_verdict}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-bold text-slate-900">{value}</dd>
    </div>
  );
}