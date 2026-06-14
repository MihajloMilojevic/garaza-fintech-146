import type { ModelOutput } from '../api'
import { VerdictBadge } from './VerdictBadge'

interface Props {
  audit: ModelOutput
  tBlock?: number
  tReview?: number
}

const PCT_COLOR = (pct: number) =>
  pct >= 30 ? 'bg-red-400' : pct >= 15 ? 'bg-amber-400' : 'bg-blue-400'

export function AuditPanel({ audit, tBlock, tReview }: Props) {
  const { verdict, block_probability, class_probabilities, audit_narrative, audit_factors, feature_contributions } = audit

  const probs: { label: string; key: 'BLOCK' | 'REVIEW' | 'CLEAR'; color: string }[] = [
    { label: 'BLOCK',  key: 'BLOCK',  color: 'bg-red-500' },
    { label: 'REVIEW', key: 'REVIEW', color: 'bg-amber-500' },
    { label: 'CLEAR',  key: 'CLEAR',  color: 'bg-green-500' },
  ]

  return (
    <div className="space-y-5">
      {/* Verdict */}
      <div className="flex items-center gap-3">
        <VerdictBadge verdict={verdict} large />
        {tBlock !== undefined && tReview !== undefined && (
          <span className="text-sm text-gray-500">
            t_block = {tBlock.toFixed(2)} · t_review = {tReview.toFixed(2)}
          </span>
        )}
      </div>

      {/* Narrative */}
      <p className="text-sm text-gray-700 leading-relaxed border-l-4 border-gray-200 pl-3">
        {audit_narrative}
      </p>

      {/* Factors */}
      {audit_factors.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Key factors</h4>
          <ul className="space-y-1">
            {audit_factors.map((f, i) => (
              <li key={i} className="text-sm text-gray-700 flex gap-2">
                <span className="text-gray-400 mt-0.5">•</span>
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Probability bars */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Model probabilities
          <span className="ml-2 text-gray-400 font-normal normal-case">
            (binary P(BLOCK) = {(block_probability * 100).toFixed(1)}%)
          </span>
        </h4>
        <div className="space-y-1.5">
          {probs.map(({ label, key, color }) => {
            const pct = (class_probabilities[key] ?? 0) * 100
            return (
              <div key={key} className="flex items-center gap-2 text-sm">
                <span className="w-14 text-right text-gray-600">{label}</span>
                <div className="flex-1 bg-gray-100 rounded h-4 overflow-hidden">
                  <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
                </div>
                <span className="w-12 text-gray-700 font-medium">{pct.toFixed(1)}%</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Feature contributions */}
      {feature_contributions.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Feature contributions</h4>
          <div className="space-y-1.5">
            {feature_contributions.slice(0, 6).map(fc => (
              <div key={fc.feature} className="flex items-center gap-2 text-sm">
                <span className="w-44 truncate text-gray-600 text-xs font-mono">{fc.feature}</span>
                <div className="flex-1 bg-gray-100 rounded h-3 overflow-hidden">
                  <div
                    className={`h-full ${PCT_COLOR(fc.contribution_pct)} transition-all`}
                    style={{ width: `${Math.min(fc.contribution_pct, 100)}%` }}
                  />
                </div>
                <span className="w-14 text-right text-gray-500 text-xs">{fc.contribution_pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
