import { createFileRoute, Link } from "@tanstack/react-router";
import { useSuspenseQuery } from "@tanstack/react-query";
import { useState } from "react";
import { TopNav } from "@/components/TopNav";
import { qk } from "@/lib/api/queries";
import { verdictColor } from "@/lib/api/client";

export const Route = createFileRoute("/accounts")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Nexus — Accounts" },
      { name: "description", content: "Search and filter the screened accounts portfolio." },
      { property: "og:title", content: "Nexus — Accounts" },
      { property: "og:description", content: "Search and filter the screened accounts portfolio." },
    ],
  }),
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(qk.accounts({ page: 1, limit: 50 }));
  },
  component: AccountsPage,
  errorComponent: ({ error }) => (
    <div className="p-8 text-sm text-rose-600">Failed to load accounts: {error.message}</div>
  ),
  notFoundComponent: () => <div className="p-8 text-sm">Not found.</div>,
});

function AccountsPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [riskBand, setRiskBand] = useState("");
  const [verdict, setVerdict] = useState("");

  const { data } = useSuspenseQuery(
    qk.accounts({
      page,
      limit: 50,
      search: search || undefined,
      risk_band: riskBand || undefined,
      verdict: verdict || undefined,
    }),
  );

  const totalPages = Math.max(1, Math.ceil(data.total / data.limit));

  return (
    <div className="min-h-dvh w-full bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
        <TopNav />
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Accounts</h1>
            <p className="text-sm text-slate-500">
              {data.total.toLocaleString()} accounts matching filters
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              placeholder="Search id or name"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm"
            />
            <select
              value={riskBand}
              onChange={(e) => {
                setRiskBand(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold"
            >
              <option value="">All bands</option>
              {["low", "medium", "high", "critical"].map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
            <select
              value={verdict}
              onChange={(e) => {
                setVerdict(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold"
            >
              <option value="">All verdicts</option>
              {["BLOCK", "REVIEW", "CLEAR"].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
        </header>

        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="hidden md:grid grid-cols-12 gap-3 px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <div className="col-span-2">Account</div>
            <div className="col-span-3">Name</div>
            <div className="col-span-1">Type</div>
            <div className="col-span-2">Risk</div>
            <div className="col-span-2">Match</div>
            <div className="col-span-2 text-right">Verdict</div>
          </div>
          <ul className="space-y-1">
            {data.accounts.map((a) => (
              <li key={a.account_id}>
                <Link
                  to="/accounts/$id"
                  params={{ id: a.account_id }}
                  className="grid grid-cols-12 gap-3 rounded-lg border border-transparent px-3 py-3 hover:border-slate-200 hover:bg-slate-50"
                >
                  <span className="col-span-2 font-mono text-sm font-bold text-slate-900">
                    {a.account_id}
                  </span>
                  <span className="col-span-3 truncate text-sm text-slate-700">{a.full_name}</span>
                  <span className="col-span-1 text-xs text-slate-500">{a.account_type}</span>
                  <span className="col-span-2 text-sm">
                    {a.overall_risk_score.toFixed(2)} · {a.risk_band}
                  </span>
                  <span className="col-span-2 text-sm">{a.latest_match_score.toFixed(2)}</span>
                  <span className="col-span-2 flex justify-end">
                    <span
                      className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider"
                      style={{
                        background: `${verdictColor(a.latest_verdict)}15`,
                        color: verdictColor(a.latest_verdict),
                        border: `1px solid ${verdictColor(a.latest_verdict)}40`,
                      }}
                    >
                      {a.latest_verdict}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {data.accounts.length === 0 && (
            <p className="py-12 text-center text-sm text-slate-500">No accounts match.</p>
          )}
        </div>

        <div className="flex items-center justify-between text-sm">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold disabled:opacity-50"
          >
            ← Prev
          </button>
          <span className="text-slate-500">
            Page {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold disabled:opacity-50"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}