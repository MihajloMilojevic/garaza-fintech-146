import { createFileRoute } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { TopNav } from "@/components/TopNav";
import { ThresholdBar } from "@/components/ThresholdBar";
import { AuditPanel } from "@/components/AuditPanel";
import { apiClient, type ScreenRequest, type ScreenResponse } from "@/lib/api/client";

export const Route = createFileRoute("/screen")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Nexus — Live Screener" },
      { name: "description", content: "Run a live AI screening decision against the model." },
      { property: "og:title", content: "Nexus — Live Screener" },
      { property: "og:description", content: "Run a live AI screening decision against the model." },
    ],
  }),
  component: LiveScreenerPage,
});

function LiveScreenerPage() {
  const [form, setForm] = useState<ScreenRequest>({
    match_score: 72.5,
    overall_risk_score: 30,
    account_type: "individual",
    kyc_status: "complete",
    kyc_completeness: 0.85,
    is_pep: 0,
    has_complex_ownership: 0,
    shell_company_flag: 0,
    activity_tier: "low",
    account_status: "active",
    pep_sanctions_risk: 55,
    geographic_risk: 35,
    identity_kyc_risk: 15,
    behavioural_risk: 20,
    relationship_network_risk: 5,
    override_applied: 0,
  });
  const [result, setResult] = useState<ScreenResponse | null>(null);

  const mutation = useMutation({
    mutationFn: (body: ScreenRequest) => apiClient.screen(body),
    onSuccess: (data) => setResult(data),
  });

  // Debounce live updates
  const formKey = useMemo(() => JSON.stringify(form), [form]);
  useEffect(() => {
    const id = window.setTimeout(() => mutation.mutate(form), 300);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formKey]);

  const update = <K extends keyof ScreenRequest>(k: K, v: ScreenRequest[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  return (
    <div className="min-h-dvh w-full bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
        <TopNav />
        <header>
          <h1 className="text-3xl font-bold tracking-tight">Live Screener</h1>
          <p className="text-sm text-slate-500">
            Drag the sliders — the verdict updates as the match score crosses t_review and t_block.
          </p>
        </header>

        <div className="grid grid-cols-12 gap-6">
          <section className="col-span-12 lg:col-span-5 space-y-5 rounded-2xl border border-slate-200 bg-white p-6">
            <Slider
              label="Match score"
              value={form.match_score}
              min={0}
              max={100}
              step={0.5}
              onChange={(v) => update("match_score", v)}
            />
            <Slider
              label="Overall risk score"
              value={form.overall_risk_score ?? 30}
              min={0}
              max={100}
              step={0.5}
              onChange={(v) => update("overall_risk_score", v)}
            />
            <div className="grid grid-cols-2 gap-3">
              <NumField label="PEP sanctions risk" value={form.pep_sanctions_risk ?? 0} onChange={(v) => update("pep_sanctions_risk", v)} />
              <NumField label="Geographic risk" value={form.geographic_risk ?? 0} onChange={(v) => update("geographic_risk", v)} />
              <NumField label="Identity/KYC risk" value={form.identity_kyc_risk ?? 0} onChange={(v) => update("identity_kyc_risk", v)} />
              <NumField label="Behavioural risk" value={form.behavioural_risk ?? 0} onChange={(v) => update("behavioural_risk", v)} />
              <NumField label="Relationship risk" value={form.relationship_network_risk ?? 0} onChange={(v) => update("relationship_network_risk", v)} />
              <NumField label="KYC completeness (0-1)" value={form.kyc_completeness ?? 0} step={0.05} max={1} onChange={(v) => update("kyc_completeness", v)} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Select label="Account type" value={form.account_type ?? "individual"} options={["individual", "business"]} onChange={(v) => update("account_type", v as "individual" | "business")} />
              <Select label="KYC status" value={form.kyc_status ?? "complete"} options={["complete", "partial", "pending", "expired"]} onChange={(v) => update("kyc_status", v as ScreenRequest["kyc_status"])} />
              <Select label="Activity tier" value={form.activity_tier ?? "low"} options={["low", "medium", "high"]} onChange={(v) => update("activity_tier", v as ScreenRequest["activity_tier"])} />
              <Select label="Account status" value={form.account_status ?? "active"} options={["active", "suspended", "closed"]} onChange={(v) => update("account_status", v as ScreenRequest["account_status"])} />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Toggle label="PEP" value={!!form.is_pep} onChange={(v) => update("is_pep", v ? 1 : 0)} />
              <Toggle label="Complex ownership" value={!!form.has_complex_ownership} onChange={(v) => update("has_complex_ownership", v ? 1 : 0)} />
              <Toggle label="Shell flag" value={!!form.shell_company_flag} onChange={(v) => update("shell_company_flag", v ? 1 : 0)} />
            </div>
            {mutation.isError && (
              <p className="text-sm text-rose-600">{(mutation.error as Error).message}</p>
            )}
          </section>

          <section className="col-span-12 lg:col-span-7 space-y-6 rounded-2xl border border-slate-200 bg-white p-6">
            {result ? (
              <>
                <ThresholdBar
                  t_review={result.t_review}
                  t_block={result.t_block}
                  match_score={result.match_score}
                />
                <AuditPanel
                  verdict={result.verdict}
                  audit_narrative={result.audit_narrative}
                  audit_factors={result.audit_factors}
                  class_probabilities={result.class_probabilities}
                  feature_contributions={result.feature_contributions}
                  block_probability={result.block_probability}
                />
              </>
            ) : (
              <p className="text-sm text-slate-500">
                {mutation.isPending ? "Running model…" : "Adjust the inputs to see the AI decision."}
              </p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-sm">
        <span className="font-semibold text-slate-700">{label}</span>
        <span className="font-mono text-slate-900">{value.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
    </div>
  );
}

function NumField({
  label,
  value,
  step = 1,
  max = 100,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  max?: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
      {label}
      <input
        type="number"
        value={value}
        step={step}
        min={0}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm font-mono text-slate-900"
      />
    </label>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm font-semibold text-slate-900"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700">
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}