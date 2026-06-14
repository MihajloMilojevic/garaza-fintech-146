import { Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { TRANSACTIONS, type TxRisk } from "@/data/transactions";
import { RISK_COLORS } from "./GraphPanel";

const RISK_LABEL: Record<TxRisk, string> = {
  low: "Low Risk",
  medium: "For Review",
  high: "High Risk",
};

export function TransactionsList() {
  const total = TRANSACTIONS.length;
  const highCount = TRANSACTIONS.filter((t) => t.risk === "high").length;
  const mediumCount = TRANSACTIONS.filter((t) => t.risk === "medium").length;
  const lowCount = TRANSACTIONS.filter((t) => t.risk === "low").length;
  const firstMedium = TRANSACTIONS.find((t) => t.risk === "medium");

  return (
    <div className="min-h-dvh w-full bg-slate-50 p-6 text-slate-900">
      <style>{LIST_STYLES}</style>
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
        <header className="ai-btn-premium relative overflow-hidden flex flex-col gap-6 rounded-2xl p-8 md:flex-row md:items-center md:justify-between">
          <div aria-hidden="true" className="ai-orb-top" />
          <div aria-hidden="true" className="ai-orb-left-mid" />
          <div className="relative z-20 space-y-3">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
              Dashboard
            </p>
            <h1 className="text-3xl font-bold tracking-tight text-white">Transactions</h1>
            <p className="text-base text-slate-300">
              {total} transactions · select one to inspect its risk graph.
            </p>
          </div>
          <div className="relative z-20 grid grid-cols-3 gap-3">
            <StatPill label="High" count={highCount} color={RISK_COLORS.high.solid} />
            <StatPill label="Medium" count={mediumCount} color={RISK_COLORS.medium.solid} />
            <StatPill label="Low" count={lowCount} color={RISK_COLORS.low.solid} />
          </div>
        </header>

        <section className="sokin-section relative overflow-hidden rounded-2xl p-8">
          <div aria-hidden="true" className="sokin-orb-top" />
          <div aria-hidden="true" className="sokin-orb-left" />
          <div className="relative z-20 flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
            <div className="space-y-3 max-w-xl">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
                AI Assistant
              </p>
              <h2 className="text-3xl font-bold tracking-tight text-white">
                Smart Transaction Approving
              </h2>
              <p className="text-base text-slate-300">
                Step through medium-risk transactions one by one. Nexus AI surfaces
                context, signals, and a recommended action for each — approve or
                block in seconds.
              </p>
            </div>
            {firstMedium ? (
              <Link
                to="/transactions/$id"
                params={{ id: firstMedium.id }}
                className="inline-flex items-center justify-center rounded-xl bg-white px-6 py-4 text-sm font-bold uppercase tracking-wider text-slate-900 transition-all hover:bg-slate-100 hover:shadow-[0_8px_32px_-8px_rgba(255,255,255,0.4)]"
              >
                Start Review →
              </Link>
            ) : (
              <span className="inline-flex items-center justify-center rounded-xl bg-white/10 px-6 py-4 text-sm font-bold uppercase tracking-wider text-slate-400">
                No medium-risk transactions
              </span>
            )}
          </div>
        </section>

        <div
          className="rounded-2xl border border-[#1b2642] bg-white p-6"
          style={{ boxShadow: "inset 0 2px 16px 0 rgba(0,68,254,0.13)" }}
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl font-bold text-slate-800">All transactions</h2>
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Showing {total}
            </span>
          </div>

          <div className="hidden md:grid grid-cols-12 gap-4 px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <div className="col-span-3">Transaction</div>
            <div className="col-span-3">Merchant</div>
            <div className="col-span-2">Amount</div>
            <div className="col-span-2">Country</div>
            <div className="col-span-2 text-right">Risk</div>
          </div>

          <motion.ul
            className="flex flex-col gap-2"
            initial="hidden"
            animate="visible"
            variants={{
              hidden: {},
              visible: {
                transition: {
                  staggerChildren: 0.04,
                },
              },
            }}
          >
            {TRANSACTIONS.map((t) => {
              const c = RISK_COLORS[t.risk];
              return (
                <motion.li
                  key={t.id}
                  variants={{
                    hidden: { opacity: 0, y: 12, scale: 0.98 },
                    visible: {
                      opacity: 1,
                      y: 0,
                      scale: 1,
                      transition: { duration: 0.35, ease: "easeOut" },
                    },
                  }}
                >
                  <Link
                    to="/transactions/$id"
                    params={{ id: t.id }}
                    className="grid grid-cols-12 gap-4 items-center rounded-xl border border-slate-200 bg-white px-4 py-4 transition-all hover:border-[#0044fe] hover:shadow-[0_8px_24px_-12px_rgba(0,68,254,0.35)]"
                  >
                    <div className="col-span-12 md:col-span-3">
                      <div className="font-mono text-sm font-bold text-slate-900">{t.id}</div>
                      <div className="text-xs text-slate-500">{t.timestamp}</div>
                    </div>
                    <div className="col-span-6 md:col-span-3 text-sm font-semibold text-slate-700">
                      {t.merchant}
                    </div>
                    <div className="col-span-6 md:col-span-2 text-base font-bold text-slate-900">
                      {t.amount}
                    </div>
                    <div className="col-span-6 md:col-span-2 text-sm text-slate-600">
                      {t.country}
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
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ background: c.solid }}
                        />
                        {RISK_LABEL[t.risk]} · {t.riskScore}
                      </span>
                    </div>
                  </Link>
                </motion.li>
              );
            })}
          </motion.ul>
        </div>
      </div>
    </div>
  );
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