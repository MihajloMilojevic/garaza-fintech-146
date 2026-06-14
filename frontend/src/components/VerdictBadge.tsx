import type { Verdict } from '../api'

const STYLES: Record<Verdict, string> = {
  BLOCK:  'bg-red-100 text-red-800 border border-red-300',
  REVIEW: 'bg-amber-100 text-amber-800 border border-amber-300',
  CLEAR:  'bg-green-100 text-green-800 border border-green-300',
}

export function VerdictBadge({ verdict, large }: { verdict: Verdict; large?: boolean }) {
  return (
    <span className={`inline-flex items-center font-semibold rounded-md px-2.5 py-0.5 ${large ? 'text-lg px-4 py-1.5' : 'text-xs'} ${STYLES[verdict]}`}>
      {verdict}
    </span>
  )
}
