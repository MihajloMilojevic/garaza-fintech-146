import type {
  ClassProbabilities,
  FeatureContribution,
  Verdict,
} from "@/lib/api/client";
import { verdictColor } from "@/lib/api/client";

interface Props {
  verdict: Verdict;
  audit_narrative: string;
  audit_factors: string[];
  class_probabilities: ClassProbabilities;
  feature_contributions: FeatureContribution[];
  block_probability?: number;
}

export function AuditPanel({
  verdict,
  audit_narrative,
  audit_factors,
  class_probabilities,
  feature_contributions,
  block_probability,
}: Props) {
  const top = feature_contributions.slice(0, 5);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-bold uppercase tracking-wider text-white"
          style={{ background: verdictColor(verdict) }}
        >
          <span className="h-2 w-2 animate-pulse rounded-full bg-white/90" />
          {verdict}
        </span>
        {typeof block_probability === "number" && (
          <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
            P(BLOCK) {(block_probability * 100).toFixed(1)}%
          </span>
        )}
      </div>

      <section>
        <h3 className="mb-2 text-base font-bold text-slate-900">Audit narrative</h3>
        <p className="text-sm leading-relaxed text-slate-700">{audit_narrative}</p>
      </section>

      {audit_factors.length > 0 && (
        <section>
          <h3 className="mb-2 text-base font-bold text-slate-900">Key factors</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            {audit_factors.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-base font-bold text-slate-900">Class probabilities</h3>
        <div className="grid grid-cols-3 gap-2">
          {(["BLOCK", "REVIEW", "CLEAR"] as const).map((v) => {
            const p = class_probabilities[v] ?? 0;
            return (
              <div
                key={v}
                className="rounded-lg border p-3 text-center"
                style={{ borderColor: `${verdictColor(v)}55` }}
              >
                <div
                  className="text-[10px] font-bold uppercase tracking-wider"
                  style={{ color: verdictColor(v) }}
                >
                  {v}
                </div>
                <div className="text-lg font-bold text-slate-900">{(p * 100).toFixed(1)}%</div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full"
                    style={{ width: `${p * 100}%`, background: verdictColor(v) }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {top.length > 0 && (
        <section>
          <h3 className="mb-2 text-base font-bold text-slate-900">Top feature contributions</h3>
          <ul className="space-y-2">
            {top.map((f) => (
              <li key={f.feature} className="space-y-1">
                <div className="flex items-center justify-between text-xs font-semibold">
                  <span className="font-mono text-slate-700">{f.feature}</span>
                  <span className="text-slate-500">
                    val {f.value.toFixed(2)} · {f.contribution_pct.toFixed(1)}%
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full bg-[#c8102e]"
                    style={{ width: `${Math.min(100, f.contribution_pct)}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}