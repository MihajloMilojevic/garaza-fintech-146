import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";
import { useSuspenseQuery, useQuery, useMutation } from "@tanstack/react-query";
import { GraphPanel, RISK_COLORS, type GraphNode, type Edge } from "./GraphPanel";
import { TopNav } from "./TopNav";
import { qk } from "@/lib/api/queries";
import { verdictToRisk, type TransactionGraphNode, type LlmReview, type Verdict, type ScreeningTransaction, type ScreeningSender, apiClient } from "@/lib/api/client";

// ─── Risk helpers ────────────────────────────────────────────────────────────

function riskBandToLevel(band?: string): "low" | "medium" | "high" {
  if (!band) return "low";
  const b = band.toUpperCase();
  if (b === "CRITICAL" || b === "HIGH") return "high";
  if (b === "MEDIUM") return "medium";
  return "low";
}

function mapBackendNode(
  n: TransactionGraphNode,
  x: number,
  y: number,
  radius: number,
): GraphNode {
  let risk: "low" | "medium" | "high";
  let riskScore: number;
  let country: string;
  let value: string;
  let type: string;

  switch (n.type) {
    case "source":
      risk = riskBandToLevel(n.risk_band);
      riskScore = Math.round(n.overall_risk_score ?? 0);
      country = n.country_residence ?? "—";
      value = n.id;
      type = "Source Account";
      break;
    case "account":
      risk = n.latest_verdict ? verdictToRisk(n.latest_verdict) : riskBandToLevel(n.risk_band);
      riskScore = Math.round(n.overall_risk_score ?? 0);
      country = n.country_residence ?? "—";
      value = n.id;
      type = "Account";
      break;
    case "wallet":
      risk = n.is_sanctioned ? "high" : "low";
      riskScore = n.is_sanctioned ? 90 : 20;
      country = n.chain ?? "—";
      value = n.id;
      type = "Wallet";
      break;
    case "external":
    default:
      risk = "medium";
      riskScore = 50;
      country = n.country ?? "—";
      value = n.id;
      type = "External";
      break;
  }

  return {
    id: n.id,
    label: n.label,
    x,
    y,
    radius,
    risk,
    type,
    value,
    country,
    riskScore,
    flags: [],
    description: n.transaction_count
      ? `${n.transaction_count} txns · ${n.total_amount?.toFixed(2) ?? "?"} total`
      : n.label,
  };
}

function buildGraphNodes(backendNodes: TransactionGraphNode[]): GraphNode[] {
  if (backendNodes.length === 0) return [];

  const source = backendNodes.find((n) => n.type === "source") ?? backendNodes[0];
  const rest = backendNodes.filter((n) => n.id !== source.id);

  const innerCount = Math.min(5, rest.length);
  const inner = rest.slice(0, innerCount);
  const outer = rest.slice(innerCount);

  const place = (
    list: TransactionGraphNode[],
    rx: number,
    ry: number,
    radius: number,
    phase: number,
  ): GraphNode[] =>
    list.map((n, i) => {
      const angle = (i / list.length) * Math.PI * 2 - Math.PI / 2 + phase;
      return mapBackendNode(n, 50 + Math.cos(angle) * rx, 50 + Math.sin(angle) * ry, radius);
    });

  const center = mapBackendNode(source, 50, 50, 28);
  const innerNodes = place(inner, 22, 20, 22, 0);
  const outerNodes =
    outer.length > 0
      ? place(outer, 40, 38, 18, Math.PI / outer.length)
      : [];

  return [center, ...innerNodes, ...outerNodes];
}

function buildGraphEdges(
  nodes: GraphNode[],
  innerCount: number,
): Edge[] {
  if (nodes.length === 0) return [];
  const center = nodes[0];
  const innerNodes = nodes.slice(1, 1 + innerCount);
  const outerNodes = nodes.slice(1 + innerCount);
  const edges: Edge[] = [];

  innerNodes.forEach((n) => edges.push({ from: center.id, to: n.id }));
  for (let i = 0; i < innerNodes.length; i++) {
    edges.push({ from: innerNodes[i].id, to: innerNodes[(i + 1) % innerNodes.length].id });
  }
  outerNodes.forEach((n, i) => {
    if (innerNodes.length === 0) return;
    edges.push({ from: innerNodes[i % innerNodes.length].id, to: n.id });
    edges.push({ from: innerNodes[(i + 1) % innerNodes.length].id, to: n.id });
  });
  for (let i = 0; i < outerNodes.length; i++) {
    edges.push({ from: outerNodes[i].id, to: outerNodes[(i + 1) % outerNodes.length].id });
  }
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      if (nodes[i].country === nodes[j].country && nodes[i].country && nodes[i].country !== "—") {
        edges.push({ from: nodes[i].id, to: nodes[j].id });
      }
    }
  }
  return edges;
}

// ─── Score/badge helpers ──────────────────────────────────────────────────────

function getVerdictBadgeStyle(verdict: Verdict): { label: string; bg: string } {
  if (verdict === "BLOCK") return { label: "High Risk", bg: "linear-gradient(135deg, #f87171, #dc2626)" };
  if (verdict === "REVIEW") return { label: "For Review", bg: "linear-gradient(135deg, #fbbf24, #d97706)" };
  return { label: "Low Risk", bg: "linear-gradient(135deg, #34d399, #059669)" };
}

function getDecisionBadgeStyle(decision: "approve" | "block"): { label: string; bg: string } {
  return decision === "approve"
    ? { label: "Approved", bg: "linear-gradient(135deg, #34d399, #059669)" }
    : { label: "Blocked", bg: "linear-gradient(135deg, #f87171, #dc2626)" };
}

// ─── Main component ───────────────────────────────────────────────────────────

export function Dashboard({ screeningId }: { screeningId: string }) {
  const { data: screening } = useSuspenseQuery(qk.screening(screeningId));

  const txQ = useQuery(qk.accountTxs(screening.account_id, { limit: 20 }));
  const reviewListQ = useQuery(qk.screeningList({ verdict: "REVIEW", limit: 50 }));

  const backendNodes = txQ.data?.transaction_graph?.nodes ?? [];
  const innerCountRef = useMemo(() => Math.min(5, Math.max(0, backendNodes.length - 1)), [backendNodes.length]);

  const { nodes, edges } = useMemo(() => {
    const nodes = buildGraphNodes(backendNodes);
    const edges = buildGraphEdges(nodes, innerCountRef);
    return { nodes, edges };
  }, [backendNodes, innerCountRef]);

  const sourceId = nodes[0]?.id ?? screeningId;
  const [selectedId, setSelectedId] = useState<string | null>(sourceId);
  useEffect(() => {
    setSelectedId(sourceId);
  }, [sourceId]);

  const activeId =
    selectedId && nodes.some((n) => n.id === selectedId) ? selectedId : sourceId;
  const node = nodes.find((n) => n.id === activeId) ?? null;
  const connections = node
    ? edges.filter((e) => e.from === node.id || e.to === node.id).map((e) =>
        e.from === node.id ? e.to : e.from,
      )
    : [];
  const connectedNodes = connections
    .map((id) => nodes.find((n) => n.id === id))
    .filter((n): n is NonNullable<typeof n> => Boolean(n));

  const risk = node ? RISK_COLORS[node.risk] : null;

  const reviewList = reviewListQ.data?.results ?? [];
  const nextReview = useMemo(() => {
    const idx = reviewList.findIndex((s) => s.screening_id === screeningId);
    if (reviewList.length === 0) return null;
    return reviewList[(idx + 1) % reviewList.length] ?? null;
  }, [reviewList, screeningId]);

  const navigate = useNavigate();
  const [decisions, setDecisions] = useState<Record<string, "approve" | "block">>({});
  const decisionForScreening = decisions[screeningId];

  const handleDecision = (action: "approve" | "block") => {
    if (action === "approve") {
      toast.success(`${screeningId} approved`, {
        description: `Screening for ${screening.account_id} cleared.`,
      });
    } else {
      toast.error(`${screeningId} blocked`, {
        description: `Screening for ${screening.account_id} blocked.`,
      });
    }
    setDecisions((d) => ({ ...d, [screeningId]: action }));
    if (nextReview) {
      window.setTimeout(() => {
        navigate({ to: "/transactions/$id", params: { id: nextReview.screening_id } });
      }, 650);
    }
  };

  const llmMutation = useMutation({
    mutationFn: () => apiClient.llmReview(screeningId),
  });

  const isReview = screening.verdict === "REVIEW";

  return (
    <div className="h-dvh w-full bg-slate-50 p-6 text-slate-900">
      <style>{AI_PANEL_STYLES}</style>
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6 h-full">
        <TopNav />
        <header className="ai-btn-premium relative overflow-hidden flex flex-col gap-6 rounded-2xl p-8 md:flex-row md:items-center md:justify-between">
          <div aria-hidden="true" className="ai-orb-top" />
          <div aria-hidden="true" className="ai-orb-left-mid" />
          <div className="relative z-20 space-y-3">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
              Screening Risk Analysis
            </p>
            <div className="flex flex-wrap items-baseline gap-4">
              <h1 className="font-mono text-3xl font-bold tracking-tight text-white">
                {screening.screening_id}
              </h1>
              <span className="text-base text-slate-300">
                {new Date(screening.screened_at).toLocaleString()}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <RiskBadge verdict={screening.verdict} matchScore={screening.match_score} decision={decisionForScreening} />
              <Link
                to="/accounts/$id"
                params={{ id: screening.account_id }}
                className="font-mono text-base font-semibold text-slate-300 hover:text-white transition-colors"
              >
                {screening.account_id} &rarr;
              </Link>
            </div>
          </div>

          <div className="relative z-20 flex flex-wrap items-center gap-3">
            {decisionForScreening === "approve" || (screening.verdict === "CLEAR" && !decisionForScreening) ? (
              <RiskBadge verdict={screening.verdict} matchScore={screening.match_score} decision="approve" />
            ) : decisionForScreening === "block" || screening.verdict === "BLOCK" ? (
              <RiskBadge verdict={screening.verdict} matchScore={screening.match_score} decision="block" />
            ) : nextReview ? (
              <Link
                to="/transactions/$id"
                params={{ id: nextReview.screening_id }}
                className="inline-flex items-center gap-2 rounded-xl bg-amber-500/15 px-6 py-3 text-base font-bold text-amber-400 ring-1 ring-amber-500/30 transition-colors hover:bg-amber-500/25"
              >
                Next &rarr;
              </Link>
            ) : null}
          </div>
        </header>

        {/* Transaction Details strip */}
        {screening.transaction ? (
          <TransactionDetails tx={screening.transaction} sender={screening.sender} />
        ) : screening.sender && (
          <SenderDetails sender={screening.sender} />
        )}

        <div className="grid grid-cols-12 gap-6 flex-1 min-h-0">
          <aside className="col-span-12 lg:col-span-3">
            <div className="sokin-panel-dark h-full flex flex-col rounded-2xl p-6">
              <div aria-hidden="true" className="sokin-orb-bottom-dark" />
              <div aria-hidden="true" className="sokin-orb-top-dark" />
              <div aria-hidden="true" className="sokin-orb-left-mid-dark" />
              {node && risk ? (
                <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-6 no-scrollbar">
                  <div className="relative z-20">
                    <h3 className="text-2xl font-bold text-white">{node.label}</h3>
                    <p className="text-base text-slate-300">{node.type}</p>
                  </div>

                  <div className="relative z-20 grid grid-cols-2 gap-3">
                    <Metric label="Risk Score" value={`${node.riskScore} / 100`} />
                    <Metric label="Country" value={node.country} />
                    <Metric label="Type" value={node.type} />
                    <Metric label="Identifier" value={String(node.value)} />
                  </div>

                  <div className="relative z-20">
                    <p className="mb-3 text-xs font-bold uppercase tracking-wider text-[#ff6b7a]">
                      Connections · {connectedNodes.length}
                    </p>
                    <ul className="space-y-1">
                      {connectedNodes.map((c) => (
                        <li key={c.id}>
                          <button
                            onClick={() => setSelectedId(c.id)}
                            className="flex w-full items-center justify-between rounded-lg px-3 py-3 text-left transition-colors hover:bg-white/5"
                          >
                            <span className="flex items-center gap-3 text-base font-medium">
                              <span
                                className="h-2.5 w-2.5 rounded-full"
                                style={{ background: RISK_COLORS[c.risk].solid }}
                              />
                              <span className="text-slate-100">{c.label}</span>
                            </span>
                            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                              {c.type}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {screening.audit_factors.length > 0 && (
                    <div className="relative z-20">
                      <p className="mb-3 text-xs font-bold uppercase tracking-wider text-[#ff6b7a]">
                        Risk Factors
                      </p>
                      <ul className="space-y-1.5">
                        {screening.audit_factors.map((f, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
                            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#ff6b7a]" />
                            {f}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ) : (
                <div className="relative z-20 py-12 text-center">
                  <div className="mx-auto mb-4 h-12 w-12 rounded-full bg-gradient-to-br from-[#ff8a96] to-[#c8102e]" />
                  <p className="text-base font-semibold text-white">No entity selected</p>
                  <p className="mt-1 text-sm text-slate-300">
                    Click any entity in the graph to inspect it.
                  </p>
                </div>
              )}
            </div>
          </aside>

          <div className="col-span-12 lg:col-span-9 flex gap-6 min-h-0">
            <main className="flex-1 min-w-0 min-h-0">
              <div
                className="flex h-full flex-col rounded-2xl border border-[#c8102e] bg-white p-6"
                style={{ boxShadow: "inset 0 2px 16px 0 rgba(200,16,46,0.13)" }}
              >
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-xl font-bold text-slate-800">Risk Graph</h2>
                  <div className="flex gap-4 text-xs font-bold uppercase tracking-wider text-slate-500">
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: RISK_COLORS.low.solid }} />
                      Low
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: RISK_COLORS.medium.solid }} />
                      Medium
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: RISK_COLORS.high.solid }} />
                      High
                    </span>
                  </div>
                </div>
                <div className="relative flex-1 overflow-hidden rounded-xl">
                  {nodes.length > 0 ? (
                    <GraphPanel selectedId={activeId} onSelect={setSelectedId} nodes={nodes} edges={edges} />
                  ) : (
                    <div className="flex h-full items-center justify-center text-sm text-slate-400">
                      {txQ.isLoading ? "Loading graph…" : "No graph data available"}
                    </div>
                  )}
                </div>
              </div>
            </main>

            <AnimatePresence mode="wait">
              {isReview && !decisionForScreening && (
                <motion.aside
                  key={screeningId}
                  initial={{ width: 0, opacity: 0 }}
                  animate={{ width: "33.3333%", opacity: 1 }}
                  exit={{
                    opacity: 0,
                    width: 0,
                    transition: { duration: 0.5, ease: "easeIn" },
                  }}
                  transition={{
                    width: { duration: 0.7, delay: 1, ease: "easeOut" },
                    opacity: { duration: 0.5, delay: 1, ease: "easeOut" },
                  }}
                  className="shrink-0 overflow-hidden"
                >
                  <div className="h-full w-full pl-0">
                    <AiSummaryPanel
                      narrative={screening.audit_narrative}
                      factors={screening.audit_factors}
                      blockProbability={screening.block_probability}
                      matchScore={screening.match_score}
                      llmReview={llmMutation.data ?? null}
                      llmLoading={llmMutation.isPending}
                      onLlmReview={() => llmMutation.mutate()}
                      onApprove={() => handleDecision("approve")}
                      onBlock={() => handleDecision("block")}
                    />
                  </div>
                </motion.aside>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="sokin-btn-premium rounded-xl px-4 py-3.5 flex flex-col justify-between">
      <div className="relative z-10 text-[10px] font-bold uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className="relative z-10 mt-1 text-base font-bold text-white tracking-wide truncate">
        {value}
      </div>
    </div>
  );
}

function RiskBadge({
  verdict,
  matchScore,
  decision,
}: {
  verdict: Verdict;
  matchScore: number;
  decision?: "approve" | "block";
}) {
  const { label, bg } = decision ? getDecisionBadgeStyle(decision) : getVerdictBadgeStyle(verdict);
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-bold uppercase tracking-wider text-white"
      style={{ background: bg, boxShadow: "inset 0 1px 8px 0 rgba(0,68,254,0.22)" }}
    >
      <span className="h-2 w-2 rounded-full bg-white/90 animate-pulse" />
      {decision ? label : `${label} \u00b7 ${matchScore.toFixed(1)}`}
    </span>
  );
}

const REC_COLORS = {
  APPROVE: { bg: "#10b981", text: "#065f46", pill: "#d1fae5" },
  ESCALATE: { bg: "#f59e0b", text: "#92400e", pill: "#fef3c7" },
  BLOCK:    { bg: "#ef4444", text: "#991b1b", pill: "#fee2e2" },
} as const;

function AiSummaryPanel({
  narrative,
  factors,
  blockProbability,
  matchScore,
  llmReview,
  llmLoading,
  onLlmReview,
  onApprove,
  onBlock,
}: {
  narrative: string;
  factors: string[];
  blockProbability: number;
  matchScore: number;
  llmReview: LlmReview | null;
  llmLoading: boolean;
  onLlmReview: () => void;
  onApprove: () => void;
  onBlock: () => void;
}) {
  const blockPct = Math.round(blockProbability * 100);
  const recColor = llmReview ? REC_COLORS[llmReview.recommendation] : null;

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-2xl border border-[#c8102e] bg-white">
      <div aria-hidden="true" className="sokin-orb-bottom" />
      <div aria-hidden="true" className="sokin-orb-top" />
      <div aria-hidden="true" className="sokin-orb-left-mid" />

      <div className="relative z-20 p-6 pb-4 flex items-start justify-between gap-3">
        <div>
          <p className="mb-2 text-s font-bold uppercase tracking-[0.18em] text-[#c8102e]">
            AI Assistant
          </p>
          <h2 className="text-xl font-bold text-slate-900">Screening Summary</h2>
        </div>
        {!llmReview && (
          <button
            onClick={onLlmReview}
            disabled={llmLoading}
            className="mt-1 shrink-0 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold uppercase tracking-wider text-slate-600 transition-all hover:border-[#c8102e] hover:text-[#c8102e] disabled:opacity-50"
          >
            {llmLoading ? (
              <span className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-full border-2 border-[#c8102e] border-t-transparent animate-spin" />
                Thinking…
              </span>
            ) : (
              "LLM Review"
            )}
          </button>
        )}
      </div>

      <div className="relative z-20 flex-1 overflow-hidden rounded-b-2xl flex flex-col justify-between">
        <div className="overflow-y-auto p-6 pt-2 space-y-6 mb-36 no-scrollbar">

          {/* LLM Review result */}
          {llmReview && recColor && (
            <section className="rounded-xl border p-4 space-y-4" style={{ borderColor: `${recColor.bg}40`, background: `${recColor.bg}08` }}>
              <div className="flex items-center justify-between">
                <span
                  className="rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider"
                  style={{ background: recColor.pill, color: recColor.text }}
                >
                  {llmReview.recommendation}
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Confidence: {llmReview.confidence}
                  </span>
                  {llmReview.llm_powered ? (
                    <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-violet-700">
                      LLM
                    </span>
                  ) : (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-slate-500">
                      Rule
                    </span>
                  )}
                </div>
              </div>
              <p className="text-sm leading-relaxed text-slate-700">{llmReview.summary}</p>

              {llmReview.key_concerns.length > 0 && (
                <div>
                  <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Key Concerns</p>
                  <ul className="space-y-1.5">
                    {llmReview.key_concerns.map((c, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-slate-600">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: recColor.bg }} />
                        {c}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {llmReview.mitigating_factors.length > 0 && (
                <div>
                  <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Mitigating Factors</p>
                  <ul className="space-y-1.5">
                    {llmReview.mitigating_factors.map((f, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-slate-600">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
                        {f}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {llmReview.required_actions.length > 0 && (
                <div>
                  <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Required Actions</p>
                  <ul className="space-y-1.5">
                    {llmReview.required_actions.map((a, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs font-semibold text-slate-700">
                        <span className="mt-0.5 shrink-0 font-mono text-[10px] text-slate-400">{i + 1}.</span>
                        {a}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {llmReview.compliance_notes && (
                <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-500 italic">
                  {llmReview.compliance_notes}
                </p>
              )}
            </section>
          )}

          {/* Block probability */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900">Block Probability</h3>
              <span className="text-sm font-bold" style={{ color: blockPct >= 70 ? "#dc2626" : blockPct >= 40 ? "#d97706" : "#059669" }}>
                {blockPct}%
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${blockPct}%`,
                  background: blockPct >= 70 ? "#dc2626" : blockPct >= 40 ? "#f59e0b" : "#10b981",
                }}
              />
            </div>
            <p className="mt-1 text-xs text-slate-500">Match score: {matchScore.toFixed(3)}</p>
          </section>

          <section>
            <h3 className="mb-3 text-sm font-bold text-slate-900">AI Narrative</h3>
            <p className="text-sm leading-relaxed text-slate-600">{narrative}</p>
          </section>

          {factors.length > 0 && (
            <section>
              <h3 className="mb-3 text-sm font-bold text-slate-900">Risk Factors</h3>
              <ul className="space-y-2">
                {factors.map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#c8102e]" />
                    {f}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-white via-white/95 to-transparent p-6 pt-10 space-y-3">
          <button
            onClick={onApprove}
            className="sokin-btn-premium w-full rounded-xl py-3.5 text-center text-base font-bold text-white tracking-wide"
          >
            Approve
          </button>
          <button
            onClick={onBlock}
            className="w-full rounded-xl border border-[#c8102e]/30 bg-white py-3.5 text-center text-base font-bold text-[#c8102e] tracking-wide transition-colors hover:bg-[#c8102e]/5 hover:border-[#c8102e]/50"
          >
            Block
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Transaction / Sender detail strips ──────────────────────────────────────

const RAIL_LABELS: Record<string, string> = {
  wire: "Wire Transfer",
  ach: "ACH",
  card: "Card",
  crypto: "Crypto",
  check: "Check",
  internal: "Internal",
};

function TxField({ label, value, mono = false, highlight = false }: {
  label: string;
  value: string | number | null | undefined;
  mono?: boolean;
  highlight?: boolean;
}) {
  if (value === null || value === undefined || value === "" || value === "nan") return null;
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
      <span
        className={`text-sm font-semibold truncate ${mono ? "font-mono" : ""} ${highlight ? "text-amber-600" : "text-slate-800"}`}
      >
        {value}
      </span>
    </div>
  );
}

function TransactionDetails({ tx, sender }: { tx: ScreeningTransaction; sender: ScreeningSender }) {
  const amountFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: tx.currency || "USD",
    maximumFractionDigits: 2,
  }).format(tx.amount);

  const vel30Fmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: tx.currency || "USD",
    maximumFractionDigits: 0,
    notation: "compact",
  }).format(tx.velocity_30d_amount);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-4" style={{ boxShadow: "inset 0 2px 12px 0 rgba(0,68,254,0.06)" }}>
      {/* Flow: Sender -> Amount -> Recipient */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:gap-6">
        {/* Sender */}
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Sender</span>
          <span className="text-base font-bold text-slate-900 truncate">{sender.full_name ?? sender.account_id}</span>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-slate-500">{sender.account_id}</span>
            {sender.is_pep === 1 && (
              <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-rose-700">PEP</span>
            )}
            {sender.country_residence && (
              <span className="text-xs text-slate-500">{sender.country_residence}</span>
            )}
          </div>
        </div>

        {/* Arrow + Amount */}
        <div className="flex shrink-0 flex-col items-center gap-1 px-2 md:px-4">
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-900">{amountFmt}</span>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-bold uppercase tracking-wider text-slate-500">
              {tx.currency}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-px w-10 bg-slate-300" />
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
              {RAIL_LABELS[tx.payment_rail] ?? tx.payment_rail}
            </span>
            <div className="h-px w-10 bg-slate-300" />
          </div>
        </div>

        {/* Recipient */}
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Recipient</span>
          <span className="text-base font-bold text-slate-900 truncate">
            {tx.recipient_name ?? tx.recipient_account_id ?? "Unknown"}
          </span>
          <div className="flex items-center gap-2">
            <span className="text-xs capitalize text-slate-500">{tx.recipient_type?.replace(/_/g, " ")}</span>
            {tx.recipient_country && tx.recipient_country !== "XX" && (
              <span className="text-xs font-semibold text-slate-600">{tx.recipient_country}</span>
            )}
            {tx.recipient_account_id && (
              <span className="font-mono text-xs text-slate-400">{tx.recipient_account_id}</span>
            )}
          </div>
        </div>

        {/* Divider */}
        <div className="hidden md:block h-12 w-px bg-slate-200 mx-2" />

        {/* Stats grid */}
        <div className="grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-4">
          <TxField label="Timestamp" value={new Date(tx.timestamp).toLocaleString()} />
          <TxField label="30d Txns" value={tx.velocity_30d_count} />
          <TxField label="30d Volume" value={vel30Fmt} />
          <TxField
            label="First-time Recipient"
            value={tx.is_first_time_recipient ? "Yes" : "No"}
            highlight={tx.is_first_time_recipient === 1}
          />
          <TxField label="Acct Age (days)" value={tx.sender_account_age_days} />
          <TxField label="Transaction ID" value={tx.transaction_id} mono />
          {tx.recipient_wallet_id && (
            <TxField label="Wallet ID" value={tx.recipient_wallet_id} mono />
          )}
        </div>
      </div>
    </div>
  );
}

function SenderDetails({ sender }: { sender: ScreeningSender }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-4" style={{ boxShadow: "inset 0 2px 12px 0 rgba(0,68,254,0.06)" }}>
      <div className="flex flex-wrap items-center gap-6">
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Account Holder</span>
          <span className="text-base font-bold text-slate-900">{sender.full_name ?? sender.account_id}</span>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-slate-500">{sender.account_id}</span>
            {sender.is_pep === 1 && (
              <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-rose-700">PEP</span>
            )}
          </div>
        </div>
        <div className="hidden md:block h-10 w-px bg-slate-200" />
        <div className="grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-4">
          <TxField label="Type" value={sender.account_type} />
          <TxField label="KYC Status" value={sender.kyc_status} />
          <TxField label="Country" value={sender.country_residence} />
          <TxField label="Risk Band" value={sender.risk_band} />
        </div>
      </div>
    </div>
  );
}

const AI_PANEL_STYLES = `
  @keyframes breathe-bottom {
    0%   { transform: scale(1)    translate(0%, 0%);    opacity: 0.35; }
    33%  { transform: scale(1.08) translate(-3%, -4%);  opacity: 0.25; }
    66%  { transform: scale(1.04) translate(2%, -2%);   opacity: 0.40; }
    100% { transform: scale(1)    translate(0%, 0%);    opacity: 0.35; }
  }
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
  @keyframes noise-drift {
    0%   { transform: translate(0, 0); }
    100% { transform: translate(-10%, -10%); }
  }

  .ai-orb-bottom {
    position: absolute; bottom: -20%; right: -20%;
    width: 75%; height: 75%; border-radius: 50%;
    background: radial-gradient(circle at 60% 60%, #a4baff 0%, #4d7cff 45%, transparent 75%);
    filter: blur(38px); animation: breathe-bottom 9s ease-in-out infinite;
    pointer-events: none; z-index: 10;
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

  .ai-orb-bottom::before,
  .ai-orb-top::before,
  .ai-orb-left-mid::before,
  .ai-btn-premium::before,
  .sokin-orb-bottom::before,
  .sokin-orb-top::before,
  .sokin-orb-left-mid::before,
  .sokin-btn-premium::before {
    content: "";
    position: absolute;
    inset: 0;
    opacity: 0.65;
    filter: contrast(190%);
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.95' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)' opacity='1'/%3E%3C/svg%3E");
    mix-blend-mode: overlay;
    pointer-events: none;
  }

  .ai-orb-bottom::before,
  .ai-orb-top::before,
  .ai-orb-left-mid::before,
  .sokin-orb-bottom::before,
  .sokin-orb-top::before,
  .sokin-orb-left-mid::before {
    border-radius: 50%;
    animation: noise-drift 8s linear infinite alternate;
  }

  .ai-btn-premium {
    position: relative; overflow: hidden;
    background: #0f172a; border: 1px solid #334155;
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.1),
      inset 0 -12px 24px -4px rgba(0,68,254,0.2),
      0 4px 20px -2px rgba(15,23,42,0.3);
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .ai-btn-premium::before { border-radius: 12px; opacity: 0.45; }
  .sokin-btn-premium::before { border-radius: 12px; opacity: 0.35; }

  button.ai-btn-premium:hover {
    background: #1e293b; border-color: #475569;
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.15),
      inset 0 -12px 28px 0px rgba(0,68,254,0.35),
      0 8px 24px -2px rgba(0,68,254,0.15);
    transform: translateY(-1px);
  }
  button.ai-btn-premium:active { transform: translateY(0px); }

  .sokin-panel {
    position: relative; overflow: hidden;
    background: #ffffff;
    border: 1px solid rgba(200,16,46,0.18);
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.9),
      0 12px 32px -8px rgba(200,16,46,0.18);
  }
  .sokin-orb-bottom {
    position: absolute; bottom: -20%; right: -20%;
    width: 75%; height: 75%; border-radius: 50%;
    background: radial-gradient(circle at 60% 60%, #ffd4d8 0%, #ff8a96 45%, transparent 75%);
    filter: blur(38px); animation: breathe-bottom 9s ease-in-out infinite;
    pointer-events: none; z-index: 10;
  }
  .sokin-orb-top {
    position: absolute; top: -15%; right: -15%;
    width: 60%; height: 60%; border-radius: 50%;
    background: radial-gradient(circle at 60% 40%, #ffdde0 0%, #ffa3ad 50%, transparent 75%);
    filter: blur(44px); animation: breathe-top 11s ease-in-out infinite;
    pointer-events: none; z-index: 10;
  }
  .sokin-orb-left-mid {
    position: absolute; top: 15%; left: -25%;
    width: 65%; height: 65%; border-radius: 50%;
    background: radial-gradient(circle at 30% 50%, #ffe5e8 0%, #ffb8c0 55%, transparent 75%);
    filter: blur(40px); animation: breathe-left 13s ease-in-out infinite;
    pointer-events: none; z-index: 10;
  }
  .sokin-btn-premium {
    position: relative; overflow: hidden;
    background: #4a0610; border: 1px solid #8e1322;
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.1),
      inset 0 -12px 24px -4px rgba(200,16,46,0.35),
      0 4px 20px -2px rgba(74,6,16,0.3);
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  }
  button.sokin-btn-premium:hover {
    background: #6a0d18; border-color: #a91529;
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.15),
      inset 0 -12px 28px 0px rgba(200,16,46,0.55),
      0 8px 24px -2px rgba(200,16,46,0.25);
    transform: translateY(-1px);
  }
  button.sokin-btn-premium:active { transform: translateY(0px); }

  .sokin-panel-dark {
    position: relative; overflow: hidden;
    background: radial-gradient(120% 90% at 80% 10%, #e23048 0%, #c8102e 28%, #8e1322 55%, #4a0610 100%);
    border: 1px solid rgba(226,48,72,0.55);
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.12),
      inset 0 -12px 24px -4px rgba(226,48,72,0.35),
      0 12px 32px -8px rgba(200,16,46,0.45);
  }
  .sokin-orb-bottom-dark {
    position: absolute; bottom: -20%; right: -20%;
    width: 75%; height: 75%; border-radius: 50%;
    background: radial-gradient(circle at 60% 60%, #ff8a96 0%, #c8102e 45%, transparent 75%);
    filter: blur(38px); animation: breathe-bottom 9s ease-in-out infinite;
    pointer-events: none; z-index: 10; opacity: 0.55;
  }
  .sokin-orb-top-dark {
    position: absolute; top: -15%; right: -15%;
    width: 60%; height: 60%; border-radius: 50%;
    background: radial-gradient(circle at 60% 40%, #ffa3ad 0%, #a91529 50%, transparent 75%);
    filter: blur(44px); animation: breathe-top 11s ease-in-out infinite;
    pointer-events: none; z-index: 10; opacity: 0.5;
  }
  .sokin-orb-left-mid-dark {
    position: absolute; top: 15%; left: -25%;
    width: 65%; height: 65%; border-radius: 50%;
    background: radial-gradient(circle at 30% 50%, #ffb8c0 0%, #8e1322 55%, transparent 75%);
    filter: blur(40px); animation: breathe-left 13s ease-in-out infinite;
    pointer-events: none; z-index: 10; opacity: 0.45;
  }

  .no-scrollbar::-webkit-scrollbar { display: none; }
  .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
`;
