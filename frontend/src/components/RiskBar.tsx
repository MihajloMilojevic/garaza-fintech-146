interface Props { label: string; value: number; max?: number }

const color = (v: number) =>
  v >= 75 ? 'bg-red-500' : v >= 50 ? 'bg-amber-500' : v >= 25 ? 'bg-yellow-400' : 'bg-green-500'

export function RiskBar({ label, value, max = 100 }: Props) {
  const pct = Math.min((value / max) * 100, 100)
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-44 text-gray-600 shrink-0">{label}</span>
      <div className="flex-1 bg-gray-100 rounded h-3 overflow-hidden">
        <div className={`h-full ${color(value)} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-10 text-right text-gray-700 font-medium tabular-nums">{value.toFixed(1)}</span>
    </div>
  )
}
