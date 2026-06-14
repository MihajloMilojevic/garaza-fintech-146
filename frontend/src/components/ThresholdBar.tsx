interface Props {
  t_review: number;
  t_block: number;
  match_score: number;
}

export function ThresholdBar({ t_review, t_block, match_score }: Props) {
  const greenW = `${t_review}%`;
  const amberW = `${Math.max(0, t_block - t_review)}%`;
  const redW = `${Math.max(0, 100 - t_block)}%`;
  const dot = `${Math.max(0, Math.min(100, match_score))}%`;

  return (
    <div className="space-y-2">
      <div className="relative h-6 w-full overflow-hidden rounded-full bg-slate-100">
        <div className="flex h-full w-full">
          <div className="h-full bg-emerald-400/70" style={{ width: greenW }} />
          <div className="h-full bg-amber-400/80" style={{ width: amberW }} />
          <div className="h-full bg-rose-500/80" style={{ width: redW }} />
        </div>
        <div
          className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 h-5 w-5 rounded-full border-2 border-white bg-slate-900 shadow-md"
          style={{ left: dot }}
          aria-label={`match score ${match_score.toFixed(1)}`}
        />
      </div>
      <div className="flex justify-between text-[10px] font-bold uppercase tracking-wider text-slate-500">
        <span>0</span>
        <span>t_review {t_review.toFixed(1)}</span>
        <span>t_block {t_block.toFixed(1)}</span>
        <span>100</span>
      </div>
      <div className="text-sm font-semibold text-slate-700">
        match score: <span className="font-mono">{match_score.toFixed(2)}</span>
      </div>
    </div>
  );
}