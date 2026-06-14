import { useState, useCallback, useRef } from 'react'
import { screen as runScreen, type ScreenRequest, type ScreenResponse } from '../api'
import { ThresholdBar } from '../components/ThresholdBar'
import { AuditPanel } from '../components/AuditPanel'
import { Spinner } from '../components/Spinner'

const DEFAULT: ScreenRequest = {
  account_type: 'individual',
  kyc_completeness: 0.85,
  kyc_status: 'complete',
  is_pep: 0,
  has_complex_ownership: 0,
  shell_company_flag: 0,
  activity_tier: 'low',
  account_status: 'active',
  match_score: 55,
  shares_address_with_sanctioned: 0,
  pep_exposure_score: 0,
  country_risk_score: 20,
  geographic_risk: 20,
  identity_kyc_risk: 15,
  pep_sanctions_risk: 10,
  behavioural_risk: 15,
  relationship_network_risk: 5,
  overall_risk_score: 20,
  override_applied: 0,
}

function Slider({ label, name, min, max, step, value, onChange }: {
  label: string; name: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void
}) {
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-600 mb-1">
        <label htmlFor={name}>{label}</label>
        <span className="font-semibold tabular-nums">{value}</span>
      </div>
      <input
        id={name}
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full accent-blue-600"
      />
    </div>
  )
}

function Select({ label, name, options, value, onChange }: {
  label: string; name: string; options: string[]; value: string; onChange: (v: string) => void
}) {
  return (
    <div>
      <label htmlFor={name} className="text-xs text-gray-600 block mb-1">{label}</label>
      <select
        id={name}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  )
}

export function LiveScreener() {
  const [form, setForm]       = useState<ScreenRequest>(DEFAULT)
  const [result, setResult]   = useState<ScreenResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const debounceRef           = useRef<ReturnType<typeof setTimeout> | null>(null)

  const call = useCallback((req: ScreenRequest) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setLoading(true)
      runScreen(req).then(setResult).finally(() => setLoading(false))
    }, 300)
  }, [])

  const set = (key: keyof ScreenRequest, val: string | number) => {
    const next = { ...form, [key]: val }
    setForm(next)
    call(next)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setLoading(true)
    runScreen(form).then(setResult).finally(() => setLoading(false))
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Live Screener</h1>
      <p className="text-sm text-gray-500">Adjust the sliders and see the AI verdict update in real time. The match score slider is the main control — drag it across the threshold boundaries to watch the verdict flip.</p>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Form */}
        <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-gray-200 p-5 space-y-5">
          {/* Match score — most important */}
          <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
            <Slider
              label="Match score (from name-matching engine)"
              name="match_score"
              min={0} max={100} step={0.5}
              value={form.match_score}
              onChange={v => set('match_score', v)}
            />
          </div>

          {/* Overall risk */}
          <div className="bg-orange-50 rounded-lg p-4 border border-orange-200">
            <Slider
              label="Overall risk score (drives thresholds)"
              name="overall_risk_score"
              min={0} max={100} step={0.5}
              value={form.overall_risk_score}
              onChange={v => set('overall_risk_score', v)}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Select label="Account type" name="account_type" options={['individual', 'business']} value={form.account_type} onChange={v => set('account_type', v)} />
            <Select label="KYC status" name="kyc_status" options={['complete', 'partial', 'pending', 'expired']} value={form.kyc_status} onChange={v => set('kyc_status', v)} />
            <Select label="Activity tier" name="activity_tier" options={['low', 'medium', 'high']} value={form.activity_tier} onChange={v => set('activity_tier', v)} />
            <Select label="Account status" name="account_status" options={['active', 'suspended', 'closed']} value={form.account_status} onChange={v => set('account_status', v)} />
          </div>

          <Slider label="KYC completeness" name="kyc_completeness" min={0} max={1} step={0.01} value={form.kyc_completeness} onChange={v => set('kyc_completeness', v)} />

          {/* Risk components */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Risk components</p>
            <Slider label="PEP & Sanctions risk (weight 30%)" name="pep_sanctions_risk" min={0} max={100} step={1} value={form.pep_sanctions_risk} onChange={v => set('pep_sanctions_risk', v)} />
            <Slider label="Behavioural risk (weight 20%)" name="behavioural_risk" min={0} max={100} step={1} value={form.behavioural_risk} onChange={v => set('behavioural_risk', v)} />
            <Slider label="Geographic risk (weight 25%)" name="geographic_risk" min={0} max={100} step={1} value={form.geographic_risk} onChange={v => set('geographic_risk', v)} />
            <Slider label="Identity / KYC risk (weight 15%)" name="identity_kyc_risk" min={0} max={100} step={1} value={form.identity_kyc_risk} onChange={v => set('identity_kyc_risk', v)} />
            <Slider label="Relationship network risk (weight 10%)" name="relationship_network_risk" min={0} max={100} step={1} value={form.relationship_network_risk} onChange={v => set('relationship_network_risk', v)} />
          </div>

          {/* Flags */}
          <div className="grid grid-cols-2 gap-3">
            {([
              ['Is PEP', 'is_pep'],
              ['Complex ownership', 'has_complex_ownership'],
              ['Shell company', 'shell_company_flag'],
              ['Shares address with sanctioned', 'shares_address_with_sanctioned'],
            ] as [string, keyof ScreenRequest][]).map(([label, key]) => (
              <label key={key} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!form[key]}
                  onChange={e => set(key, e.target.checked ? 1 : 0)}
                  className="rounded"
                />
                {label}
              </label>
            ))}
          </div>

          <button
            type="submit"
            className="w-full bg-blue-600 text-white py-2 rounded-lg font-medium hover:bg-blue-700 transition-colors"
          >
            Screen →
          </button>
        </form>

        {/* Result */}
        <div className="space-y-4">
          {loading && (
            <div className="bg-white rounded-xl border border-gray-200 p-10 flex flex-col items-center gap-3">
              <Spinner size="lg" />
              <p className="text-sm text-gray-400">Running model…</p>
            </div>
          )}

          {!loading && result && (
            <>
              {/* Threshold bar */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <ThresholdBar
                  tBlock={result.t_block}
                  tReview={result.t_review}
                  matchScore={result.match_score}
                />
              </div>

              {/* Threshold formula */}
              <div className="bg-white rounded-xl border border-gray-200 p-5 text-xs space-y-2">
                <p className="font-semibold text-gray-700 text-sm">Threshold formula</p>
                <div className="font-mono text-gray-600 space-y-0.5 bg-gray-50 rounded p-3">
                  <p>risk = {result.overall_risk_score.toFixed(2)}</p>
                  <p>adj = ({result.overall_risk_score.toFixed(2)} − 50) × 0.5 = {((result.overall_risk_score - 50) * 0.5).toFixed(4)}</p>
                  <p>t_block  = clamp(75 − {((result.overall_risk_score - 50) * 0.5).toFixed(4)}, 40, 95) = <strong>{result.t_block}</strong></p>
                  <p>t_review = clamp(50 − {((result.overall_risk_score - 50) * 0.5).toFixed(4)}, 20, 70) = <strong>{result.t_review}</strong></p>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {Object.entries({
                    BLOCK:  `≥ ${result.t_block}`,
                    REVIEW: `${result.t_review} – ${result.t_block}`,
                    CLEAR:  `< ${result.t_review}`,
                  }).map(([v, zone]) => (
                    <div key={v} className={`rounded p-2 text-center ${v === result.verdict ? 'bg-blue-50 border border-blue-200' : 'bg-gray-50'}`}>
                      <p className="font-semibold text-gray-700 text-xs">{v}</p>
                      <p className="text-gray-400 text-xs">{zone}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Audit panel */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h2 className="text-sm font-semibold text-gray-700 mb-4">AI audit</h2>
                <AuditPanel
                  audit={result}
                  tBlock={result.t_block}
                  tReview={result.t_review}
                />
              </div>
            </>
          )}

          {!loading && !result && (
            <div className="bg-gray-50 rounded-xl border border-dashed border-gray-300 p-10 text-center text-gray-400 text-sm">
              Adjust a slider to see the result, or click Screen →
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
