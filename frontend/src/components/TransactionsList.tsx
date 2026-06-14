import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { useSuspenseQuery } from "@tanstack/react-query";
import { RISK_COLORS } from "./GraphPanel";
import { TopNav } from "./TopNav";
import { qk } from "@/lib/api/queries";
import { verdictToRisk, type Verdict } from "@/lib/api/client";

const RISK_LABEL = {
  low: "Low Risk",
  medium: "For Review",
  high: "High Risk",
} as const;

const VERDICT_FILTERS: { label: string; value: Verdict | undefined }[] = [
  { label: "All", value: undefined },
  { label: "Block", value: "BLOCK" },
  { label: "Review", value: "REVIEW" },
  { label: "Clear", value: "CLEAR" },
];

const PAGE_SIZE = 20;

export function TransactionsList() {
  const { verdict, page = 1 } = useSearch({ from: "/" });
  const navigate = useNavigate({ from: "/" });

  const { data } = useSuspenseQuery(
    qk.screeningList({ limit: PAGE_SIZE, verdict, page }),
  );
  const items = data.results;
  const total = data.total;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  const highCount = items.filter((t) => t.verdict === "BLOCK").length;
  const mediumCount = items.filter((t) => t.verdict === "REVIEW").length;
  const lowCount = items.filter((t) => t.verdict === "CLEAR").length;
  const firstReview = items.find((t) => t.verdict === "REVIEW");

  const setVerdict = (v: Verdict | undefined) =>
    navigate({ search: () => ({ verdict: v, page: 1 }) });

  const setPage = (p: number) =>
    navigate({ search: (prev) => ({ ...prev, page: p }) });

  return (
    <div className="min-h-dvh w-full bg-slate-50 p-6 text-slate-900">
      <style>{LIST_STYLES}</style>
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
        <TopNav />

        {/* Header */}
        <header className="ai-btn-premium relative overflow-hidden flex flex-col gap-6 rounded-2xl p-8 md:flex-row md:items-center md:justify-between">
          <div aria-hidden="true" className="ai-orb-top" />
          <div aria-hidden="true" className="ai-orb-left-mid" />
          <div className="relative z-20 space-y-3">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
              Screening Queue
            </p>
            <h1 className="text-3xl font-bold tracking-tight text-white">Screening Events</h1>
            <p className="text-base text-slate-300">
              {total.toLocaleString()} matching events · select one to inspect its risk graph.
            </p>
          </div>
          <div className="relative z-20 grid grid-cols-3 gap-3">
            <StatPill label="Block" count={highCount} color={RISK_COLORS.high.solid} />
            <StatPill label="Review" count={mediumCount} color={RISK_COLORS.medium.solid} />
            <StatPill label="Clear" count={lowCount} color={RISK_COLORS.low.solid} />
          </div>
        </header>

        {/* Smart Review CTA */}
        <section className="sokin-section relative overflow-hidden rounded-2xl p-8">
          <div aria-hidden="true" className="sokin-orb-top" />
          <div aria-hidden="true" className="sokin-orb-left" />
          <div className="relative z-20 flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
            <div className="space-y-3 max-w-xl">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
                AI Assistant
              </p>
              <h2 className="text-3xl font-bold tracking-tight text-white">
                Smart Screening Review
              </h2>
              <p className="text-base text-slate-300">
                Step through REVIEW-zone screenings one by one. Nexus AI surfaces
                context, signals, and a recommended action for each — clear or block
                in seconds.
              </p>
            </div>
            {firstReview ? (
              <Link
                to="/transactions/$id"
                params={{ id: firstReview.screening_id }}
                className="inline-flex items-center justify-center rounded-xl bg-white px-6 py-4 text-sm font-bold uppercase tracking-wider text-slate-900 transition-all hover:bg-slate-100 hover:shadow-[0_8px_32px_-8px_rgba(255,255,255,0.4)]"
              >
                Start Review →
              </Link>
            ) : (
              <span className="inline-flex items-center justify-center rounded-xl bg-white/10 px-6 py-4 text-sm font-bold uppercase tracking-wider text-slate-400">
                No review-zone events
              </span>
            )}
          </div>
        </section>

        {/* Table card */}
        <div
          className="rounded-2xl border border-[#1b2642] bg-white p-6"
          style={{ boxShadow: "inset 0 2px 16px 0 rgba(0,68,254,0.13)" }}
        >
          {/* Table header row */}
          <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-xl font-bold text-slate-800">All screening events</h2>

            {/* Verdict filter pills */}
            <div className="flex items-center gap-2">
              {VERDICT_FILTERS.map(({ label, value }) => {
                const isActive = verdict === value;
                const color =
                  value === "BLOCK" ? RISK_COLORS.high.solid
                  : value === "REVIEW" ? RISK_COLORS.medium.solid
                  : value === "CLEAR" ? RISK_COLORS.low.solid
                  : "#64748b";
                return (
                  <button
                    key={label}
                    onClick={() => setVerdict(value)}
                    className="rounded-full px-4 py-1.5 text-xs font-bold uppercase tracking-wider transition-all"
                    style={
                      isActive
                        ? { background: `${color}20`, color, border: `1px solid ${color}60` }
                        : { background: "transparent", color: "#94a3b8", border: "1px solid #e2e8f0" }
                    }
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Show count */}
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400">
              Page {page} of {totalPages || 1} · {total.toLocaleString()} total
            </span>
            {verdict && (
              <span
                className="rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-wider"
                style={{
                  background: `${verdict === "BLOCK" ? RISK_COLORS.high.solid : verdict === "REVIEW" ? RISK_COLORS.medium.solid : RISK_COLORS.low.solid}15`,
                  color: verdict === "BLOCK" ? RISK_COLORS.high.solid : verdict === "REVIEW" ? RISK_COLORS.medium.solid : RISK_COLORS.low.solid,
                }}
              >
                Filtered: {verdict}
              </span>
            )}
          </div>

          {/* Column headers */}
          <div className="hidden md:grid grid-cols-12 gap-4 px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <div className="col-span-3">Screening</div>
            <div className="col-span-3">Account</div>
            <div className="col-span-2">Match Score</div>
            <div className="col-span-2">Context</div>
            <div className="col-span-2 text-right">Verdict</div>
          </div>

          {/* Items */}
          <motion.ul
            className="flex flex-col gap-2"
            initial="hidden"
            animate="visible"
            key={`${verdict}-${page}`}
            variants={{
              hidden: {},
              visible: { transition: { staggerChildren: 0.03 } },
            }}
          >
            {items.map((t) => {
              const risk = verdictToRisk(t.verdict);
              const c = RISK_COLORS[risk];
              return (
                <motion.li
                  key={t.screening_id}
                  variants={{
                    hidden: { opacity: 0, y: 10, scale: 0.99 },
                    visible: {
                      opacity: 1,
                      y: 0,
                      scale: 1,
                      transition: { duration: 0.28, ease: "easeOut" },
                    },
                  }}
                >
                  <Link
                    to="/transactions/$id"
                    params={{ id: t.screening_id }}
                    className="grid grid-cols-12 gap-4 items-center rounded-xl border border-slate-200 bg-white px-4 py-4 transition-all hover:border-[#0044fe] hover:shadow-[0_8px_24px_-12px_rgba(0,68,254,0.35)]"
                  >
                    <div className="col-span-12 md:col-span-3">
                      <div className="font-mono text-sm font-bold text-slate-900">{t.screening_id}</div>
                      <div className="text-xs text-slate-500">
                        {new Date(t.screened_at).toLocaleString()}
                      </div>
                    </div>
                    <div className="col-span-6 md:col-span-3 font-mono text-sm font-semibold text-slate-700">
                      {t.account_id}
                    </div>
                    <div className="col-span-6 md:col-span-2 text-base font-bold text-slate-900">
                      {t.match_score.toFixed(2)}
                    </div>
                    <div className="col-span-6 md:col-span-2 text-sm text-slate-600">
                      {t.context}
                      {t.verdicts_differ && (
                        <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-amber-700">
                          AI≠rule
                        </span>
                      )}
                    </div>
                    <div className="col-span-6 md:col-span-2 flex md:justify-end">
                      <span
                        className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider"
                        style={{
                          background: `${c.solid}15`,
                          color: c.solid,
                          border: `1px solid ${c.solid}40`,
                        }}
                      >
                        <span className="h-2 w-2 rounded-full" style={{ background: c.solid }} />
                        {RISK_LABEL[risk]} · {t.match_score.toFixed(1)}
                      </span>
                    </div>
                  </Link>
                </motion.li>
              );
            })}
          </motion.ul>

          {items.length === 0 && (
            <p className="py-12 text-center text-sm text-slate-500">No screening events found.</p>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-6 flex items-center justify-center gap-2">
              <PaginationButton
                onClick={() => setPage(page - 1)}
                disabled={page <= 1}
                label="← Prev"
              />
              {getPaginationRange(page, totalPages).map((p, i) =>
                p === "…" ? (
                  <span key={`ellipsis-${i}`} className="px-2 text-slate-400 text-sm">…</span>
                ) : (
                  <button
                    key={p}
                    onClick={() => setPage(p as number)}
                    className="h-9 w-9 rounded-lg text-sm font-semibold transition-all"
                    style={
                      p === page
                        ? { background: "#0044fe", color: "white" }
                        : { background: "transparent", color: "#64748b", border: "1px solid #e2e8f0" }
                    }
                  >
                    {p}
                  </button>
                ),
              )}
              <PaginationButton
                onClick={() => setPage(page + 1)}
                disabled={page >= totalPages}
                label="Next →"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PaginationButton({
  onClick,
  disabled,
  label,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 transition-all hover:border-[#0044fe] hover:text-[#0044fe] disabled:cursor-not-allowed disabled:opacity-40"
    >
      {label}
    </button>
  );
}

function getPaginationRange(current: number, total: number): (number | "…")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | "…")[] = [];
  if (current <= 4) {
    pages.push(1, 2, 3, 4, 5, "…", total);
  } else if (current >= total - 3) {
    pages.push(1, "…", total - 4, total - 3, total - 2, total - 1, total);
  } else {
    pages.push(1, "…", current - 1, current, current + 1, "…", total);
  }
  return pages;
}

function StatPill({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div
      className="rounded-xl border px-4 py-3 text-center backdrop-blur-sm"
      style={{ borderColor: `${color}55`, background: `${color}1a` }}
    >
      <div className="text-2xl font-bold text-white">{count}</div>
      <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color }}>
        {label}
      </div>
    </div>
  );
}

const LIST_STYLES = `
  @keyframes breathe-top {
    0%   { transform: scale(1)    translate(0%, 0%);    opacity: 0.25; }
    33%  { transform: scale(1.06) translate(-2%, 3%);   opacity: 0.30; }
    66%  { transform: scale(1.10) translate(3%, 1%);    opacity: 0.20; }
    100% { transform: scale(1)    translate(0%, 0%);    opacity: 0.25; }
  }
  @keyframes breathe-left {
    0%   { transform: scale(1)    translate(0%, 0%);    opacity: 0.15; }
    50%  { transform: scale(1.12) translate(4%, -3%);   opacity: 0.22; }
    100% { transform: scale(1)    translate(0%, 0%);    opacity: 0.15; }
  }
  .ai-orb-top {
    position: absolute; top: -15%; right: -15%;
    width: 60%; height: 60%; border-radius: 50%;
    background: radial-gradient(circle at 60% 40%, #b3cbff 0%, #4667ff 50%, transparent 75%);
    filter: blur(44px); animation: breathe-top 11s ease-in-out infinite;
    pointer-events: none; z-index: 10;
  }
  .ai-orb-left-mid {
    position: absolute; top: 15%; left: -25%;
    width: 65%; height: 65%; border-radius: 50%;
    background: radial-gradient(circle at 30% 50%, #c4d5ff 0%, #7aa0e8 55%, transparent 75%);
    filter: blur(40px); animation: breathe-left 13s ease-in-out infinite;
    pointer-events: none; z-index: 10;
  }
  .ai-btn-premium {
    position: relative; overflow: hidden;
    background: #0f172a; border: 1px solid #334155;
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.1),
      inset 0 -12px 24px -4px rgba(0,68,254,0.2),
      0 4px 20px -2px rgba(15,23,42,0.3);
  }
  .sokin-section {
    background: radial-gradient(120% 90% at 80% 10%, #e23048 0%, #c8102e 28%, #8e1322 55%, #4a0610 100%);
    border: 1px solid rgba(255,255,255,0.12);
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.14),
      0 12px 32px -8px rgba(74,6,16,0.45);
  }
  .sokin-orb-top {
    position: absolute; top: -15%; right: -15%;
    width: 50%; height: 100%; border-radius: 50%;
    background: radial-gradient(circle at 60% 40%, #ffb3bb 0%, #ff5e6c 50%, transparent 75%);
    filter: blur(50px); animation: breathe-top 11s ease-in-out infinite;
    pointer-events: none; z-index: 1;
  }
  .sokin-orb-left {
    position: absolute; top: 10%; left: -20%;
    width: 55%; height: 120%; border-radius: 50%;
    background: radial-gradient(circle at 30% 50%, #ffc7cd 0%, #e85565 55%, transparent 75%);
    filter: blur(48px); animation: breathe-left 13s ease-in-out infinite;
    pointer-events: none; z-index: 1;
  }
`;
