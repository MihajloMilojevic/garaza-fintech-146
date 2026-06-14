interface Props {
  tBlock: number
  tReview: number
  matchScore: number
}

export function ThresholdBar({ tBlock, tReview, matchScore }: Props) {
  const greenW  = `${tReview}%`
  const amberW  = `${tBlock - tReview}%`
  const redW    = `${100 - tBlock}%`
  const dotLeft = `${matchScore}%`

  return (
    <div className="w-full space-y-2">
      {/* Bar */}
      <div className="relative h-8 flex rounded-lg overflow-visible">
        <div className="h-full bg-green-400 rounded-l-lg" style={{ width: greenW }} />
        <div className="h-full bg-amber-400" style={{ width: amberW }} />
        <div className="h-full bg-red-400 rounded-r-lg" style={{ width: redW }} />

        {/* match_score marker */}
        <div
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 z-10"
          style={{ left: dotLeft }}
        >
          <div className="w-4 h-4 bg-white border-2 border-gray-800 rounded-full shadow-lg" />
        </div>

        {/* t_review line */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-gray-700 z-10"
          style={{ left: `${tReview}%` }}
        />

        {/* t_block line */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-gray-700 z-10"
          style={{ left: `${tBlock}%` }}
        />
      </div>

      {/* Labels row */}
      <div className="relative h-5 text-xs text-gray-500">
        <span className="absolute left-0">0</span>

        <span
          className="absolute -translate-x-1/2 text-gray-700 font-medium"
          style={{ left: `${tReview}%` }}
        >
          t_review {tReview.toFixed(1)}
        </span>

        <span
          className="absolute -translate-x-1/2 text-gray-700 font-medium"
          style={{ left: `${tBlock}%` }}
        >
          t_block {tBlock.toFixed(1)}
        </span>

        <span
          className="absolute -translate-x-1/2 font-semibold text-gray-800"
          style={{ left: dotLeft }}
          title={`match_score = ${matchScore.toFixed(1)}`}
        >
          ▲ {matchScore.toFixed(1)}
        </span>

        <span className="absolute right-0">100</span>
      </div>

      {/* Zone legend */}
      <div className="flex gap-4 text-xs mt-1">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded-sm bg-green-400" />
          CLEAR (0 – {tReview.toFixed(1)})
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded-sm bg-amber-400" />
          REVIEW ({tReview.toFixed(1)} – {tBlock.toFixed(1)})
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded-sm bg-red-400" />
          BLOCK ({tBlock.toFixed(1)} – 100)
        </span>
      </div>
    </div>
  )
}
