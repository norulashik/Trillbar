import { useProjectStore } from '../store/projectStore'
import { usePlaybackStore } from '../store/playbackStore'

const SPEAKER_HUE: Record<string, string> = {}
const HUES = ['#4a9eff', '#a259ff', '#ff6b35', '#3dba7a', '#f0b429', '#e05fc4']
let hueIdx = 0
function speakerColor(id: string) {
  if (!SPEAKER_HUE[id]) {
    SPEAKER_HUE[id] = HUES[hueIdx % HUES.length]
    hueIdx++
  }
  return SPEAKER_HUE[id]
}

function fmt(t: number) {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function syncBadgeColor(score: number | undefined, paceOk: boolean | undefined) {
  if (score === undefined) return null
  if (score >= 0.9 && paceOk !== false) return '#3dba7a'  // green
  if (score >= 0.7 && paceOk !== false) return '#f0b429'  // yellow
  return '#ff4444'  // red
}

export default function Timeline() {
  const { segments, selectedSegmentId, setSelectedSegmentId, clips } = useProjectStore()
  const { currentTime, duration, requestSeek } = usePlaybackStore()

  const totalDur = duration || (segments.length > 0 ? segments[segments.length - 1].end + 2 : 60)
  const pct = (t: number) => `${(t / totalDur) * 100}%`

  const handleTrackClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = (e.clientX - rect.left) / rect.width
    requestSeek(ratio * totalDur)
  }

  const tickInterval = totalDur < 60 ? 5 : totalDur < 300 ? 30 : 60
  const ticks: number[] = []
  for (let t = 0; t <= totalDur; t += tickInterval) ticks.push(t)

  // Compute overall lip sync average (duration-weighted)
  let totalWeight = 0
  let weightedSum = 0
  for (const seg of segments) {
    if (seg.lip_sync_score !== undefined) {
      const w = seg.end - seg.start
      weightedSum += seg.lip_sync_score * w
      totalWeight += w
    }
  }
  const avgSync = totalWeight > 0 ? weightedSum / totalWeight : null

  return (
    <div className="border-t border-tb-border bg-tb-panel shrink-0" style={{ height: '220px' }}>
      <div className="panel-header flex items-center justify-between">
        <span>Timeline</span>
        <div className="flex items-center gap-3">
          {avgSync !== null && (
            <span
              className="text-xs font-mono normal-case tracking-normal"
              style={{ color: avgSync >= 0.9 ? '#3dba7a' : avgSync >= 0.7 ? '#f0b429' : '#ff4444' }}
            >
              Lip Sync avg: {Math.round(avgSync * 100)}%
            </span>
          )}
          {duration > 0 && (
            <span className="text-tb-border font-mono text-xs normal-case tracking-normal">
              {fmt(duration)}
            </span>
          )}
        </div>
      </div>

      <div className="px-3 pb-2 h-full overflow-hidden space-y-1">
        {/* Time ruler */}
        <div className="relative h-4">
          {ticks.map((t) => (
            <div key={t} className="absolute top-0 flex flex-col items-start" style={{ left: pct(t) }}>
              <div className="w-px h-2 bg-tb-border" />
              <span className="text-tb-border font-mono" style={{ fontSize: '9px' }}>{fmt(t)}</span>
            </div>
          ))}
        </div>

        {/* Source speech track (gray — original timing) */}
        <div>
          <div className="text-[9px] text-tb-muted mb-0.5 uppercase tracking-widest">Src</div>
          <div
            className="relative h-5 bg-tb-bg rounded cursor-crosshair overflow-hidden"
            onClick={handleTrackClick}
          >
            {segments.map((seg) => (
              <div
                key={seg.id}
                title={seg.source_text}
                className="absolute top-0.5 bottom-0.5 rounded-sm opacity-50"
                style={{
                  left: pct(seg.start),
                  width: pct(seg.end - seg.start),
                  backgroundColor: '#4a4a5a',
                  minWidth: '2px',
                }}
              />
            ))}
            {duration > 0 && (
              <div
                className="absolute top-0 bottom-0 w-px bg-white/80 z-10 pointer-events-none"
                style={{ left: pct(currentTime) }}
              />
            )}
          </div>
        </div>

        {/* Dubbed track (speaker colors, offset applied) */}
        <div>
          <div className="text-[9px] text-tb-muted mb-0.5 uppercase tracking-widest">Dub</div>
          <div
            className="relative h-6 bg-tb-bg rounded cursor-crosshair overflow-hidden"
            onClick={handleTrackClick}
          >
            {segments.map((seg) => {
              const clip = clips[seg.id]
              const offsetS    = (clip?.offset_ms    ?? 0) / 1000
              const trimInS    = (clip?.trim_in_ms   ?? 0) / 1000
              const trimOutS   = (clip?.trim_out_ms  ?? 0) / 1000
              const stretch    =  clip?.stretch_ratio ?? 1.0
              const rawDur     = seg.dubbed_duration_s ?? (seg.end - seg.start)
              const dubStart   = seg.start + offsetS + trimInS
              const dubDur     = Math.max(0, rawDur * stretch - trimInS - trimOutS)
              const badge = syncBadgeColor(seg.lip_sync_score, seg.pace_ok)
              const isQcFlagged = seg.qc_flagged

              return (
                <div
                  key={seg.id}
                  onClick={(e) => { e.stopPropagation(); setSelectedSegmentId(seg.id); requestSeek(seg.start) }}
                  title={seg.translated_text ?? seg.source_text}
                  className={`absolute top-0.5 bottom-0.5 rounded-sm cursor-pointer transition-opacity ${
                    selectedSegmentId === seg.id ? 'opacity-100 ring-1 ring-white/30' : 'opacity-70 hover:opacity-90'
                  }`}
                  style={{
                    left: pct(dubStart),
                    width: pct(dubDur),
                    backgroundColor: speakerColor(seg.speaker_id),
                    minWidth: '2px',
                  }}
                >
                  {/* Sync badge dot */}
                  {badge && (
                    <div
                      className={`absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full ${isQcFlagged ? 'animate-pulse' : ''}`}
                      style={{ backgroundColor: badge }}
                    />
                  )}
                </div>
              )
            })}
            {duration > 0 && (
              <div
                className="absolute top-0 bottom-0 w-px bg-white/80 z-10 pointer-events-none"
                style={{ left: pct(currentTime) }}
              />
            )}
          </div>
        </div>

        {/* Speaker legend */}
        {segments.length > 0 && (
          <div className="flex gap-3">
            {[...new Set(segments.map((s) => s.speaker_id))].map((id) => (
              <div key={id} className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-sm" style={{ backgroundColor: speakerColor(id) }} />
                <span className="text-tb-muted" style={{ fontSize: '10px' }}>{id}</span>
              </div>
            ))}
            <div className="flex items-center gap-1 ml-2">
              <div className="w-2 h-2 rounded-sm bg-[#4a4a5a]" />
              <span className="text-tb-muted" style={{ fontSize: '10px' }}>Source</span>
            </div>
          </div>
        )}

        {segments.length === 0 && (
          <div className="flex items-center justify-center h-8">
            <span className="text-tb-border text-xs">Timeline populates after dubbing completes</span>
          </div>
        )}
      </div>
    </div>
  )
}
