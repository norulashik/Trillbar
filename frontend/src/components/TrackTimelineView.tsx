import { useEffect, useRef, useState, useCallback } from 'react'
import type { Segment } from '../types'
import type { CutRegion } from './VideoPreviewPhase'
import { sortRegions, totalKeptDuration, localToOriginal, originalToLocal } from '../utils/timeline'

// ── Constants ─────────────────────────────────────────────────────────────────

const TRACK_H      = 34
const RULER_H      = 20
const HEADER_H     = 22
const TRACK_LABEL_W = 150

const SPEAKER_COLORS = [
  '#a259ff', '#4a9eff', '#ff6b35', '#4CAF50',
  '#FF9800', '#E91E63', '#00BCD4',
]

interface SystemTrack { id: string; label: string; color: string; colorDim: string }

const ALL_SYSTEM_TRACKS: SystemTrack[] = [
  { id: 'original', label: 'Original Audio',  color: '#4a9eff', colorDim: 'rgba(74,158,255,0.18)' },
  { id: 'vocals',   label: 'Vocals Isolated',  color: '#a259ff', colorDim: 'rgba(162,89,255,0.18)' },
  { id: 'music',    label: 'Music / SFX',       color: '#4CAF50', colorDim: 'rgba(76,175,80,0.18)'  },
]

function fmt(t: number): string {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function tickInterval(dur: number): number {
  if (dur < 30)  return 2
  if (dur < 120) return 5
  if (dur < 300) return 15
  if (dur < 600) return 30
  return 60
}

function speakerColor(idx: number): string {
  return SPEAKER_COLORS[idx % SPEAKER_COLORS.length]
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  videoRef: React.RefObject<HTMLVideoElement>
  duration: number
  segments: Segment[]
  analyzed: boolean
  trimIn: number
  trimOut: number
  cutRegions?: CutRegion[]
  onTrimIn: (t: number) => void
  onTrimOut: (t: number) => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function TrackTimelineView({
  videoRef, duration, segments, analyzed,
  trimIn, trimOut, cutRegions = [], onTrimIn, onTrimOut,
}: Props) {
  const [currentTime, setCurrentTime] = useState(0)
  const contentRef    = useRef<HTMLDivElement>(null)
  const draggingRef   = useRef<'in' | 'out' | null>(null)
  const cutRegionsRef = useRef(cutRegions)
  useEffect(() => { cutRegionsRef.current = cutRegions }, [cutRegions])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const onTime = () => setCurrentTime(video.currentTime)
    video.addEventListener('timeupdate', onTime)
    return () => video.removeEventListener('timeupdate', onTime)
  }, [videoRef])

  // ── Derived ───────────────────────────────────────────────────────────────────

  const cutMode = cutRegions.length > 0
  const sorted  = sortRegions(cutRegions)
  const keptDur = cutMode ? Math.max(0.001, totalKeptDuration(sorted)) : 0

  /** Effective timeline duration shown in the ruler */
  const totalDur   = cutMode ? keptDur : (duration > 0 ? duration : 60)
  const trimOutEff = trimOut > 0 ? trimOut : totalDur

  /**
   * Convert time in effective-timeline space → percentage string.
   * Always in 0→totalDur space.
   */
  const pct = (t: number) => `${((Math.max(0, Math.min(totalDur, t)) / totalDur) * 100).toFixed(5)}%`

  /**
   * Local timeline position for the playhead.
   * Cut mode: original → local time. Normal mode: same as currentTime.
   */
  const localPlayhead = cutMode ? originalToLocal(currentTime, sorted) : currentTime

  // ── Seek / drag helpers ───────────────────────────────────────────────────────

  /**
   * Maps a clientX pixel position to original video time.
   * Cut mode: pixel → local time → originalToLocal mapping.
   * Normal mode: pixel → raw time.
   */
  const xToOriginalTime = useCallback((clientX: number): number => {
    const content = contentRef.current
    if (!content) return 0
    const rect  = content.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    const localT = ratio * totalDur
    if (cutMode) return localToOriginal(localT, sorted)
    return localT
  }, [totalDur, cutMode, sorted])

  const seekTo = (e: React.MouseEvent<HTMLDivElement>) => {
    if (draggingRef.current) return
    const video = videoRef.current
    if (!video || !video.duration) return
    const origT = xToOriginalTime(e.clientX)
    video.currentTime = origT
    setCurrentTime(origT)
  }

  const startTrimDrag = (type: 'in' | 'out') => (e: React.PointerEvent) => {
    if (cutMode) return   // handles hidden in cut mode
    e.stopPropagation()
    e.currentTarget.setPointerCapture(e.pointerId)
    draggingRef.current = type
    const onMove = (me: PointerEvent) => {
      const t = xToOriginalTime(me.clientX)
      if (draggingRef.current === 'in') {
        onTrimIn(Math.min(t, trimOutEff - 0.5))
      } else {
        onTrimOut(Math.max(t, trimIn + 0.5))
      }
    }
    const onUp = () => {
      draggingRef.current = null
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup',   onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup',   onUp)
  }

  // ── Ruler ticks ───────────────────────────────────────────────────────────────

  const interval = tickInterval(totalDur)
  const ticks: number[] = []
  for (let t = 0; t <= totalDur + 0.001; t += interval) ticks.push(t)
  const minorInterval = interval / 5
  const minorTicks: number[] = []
  for (let t = 0; t <= totalDur; t += minorInterval) {
    if (t % interval > 0.001) minorTicks.push(t)
  }

  // ── Cut boundary locals (where regions join in local time) ────────────────────
  const cutBoundaryLocals: number[] = []
  if (cutMode && sorted.length > 1) {
    let acc = 0
    for (let i = 0; i < sorted.length - 1; i++) {
      acc += sorted[i].end - sorted[i].start
      cutBoundaryLocals.push(acc)
    }
  }

  // ── Track layout ──────────────────────────────────────────────────────────────

  const systemTracks  = analyzed ? ALL_SYSTEM_TRACKS : [ALL_SYSTEM_TRACKS[0]]
  const speakerIds    = analyzed ? [...new Set(segments.map((s) => s.speaker_id))].sort() : []
  const allTrackCount = systemTracks.length + speakerIds.length
  const contentH      = RULER_H + allTrackCount * TRACK_H

  return (
    <div
      className="shrink-0 border-t border-tb-border bg-tb-bg flex flex-col select-none"
      style={{ height: '200px' }}
    >
      {/* Header bar */}
      <div
        className="shrink-0 flex items-center justify-between px-3 border-b border-tb-border bg-tb-header"
        style={{ height: `${HEADER_H}px` }}
      >
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold text-tb-muted uppercase tracking-widest">Timeline</span>
          {cutMode && (
            <span style={{ fontSize: 9, color: '#4ade80', fontFamily: 'monospace',
              background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)',
              borderRadius: 2, padding: '1px 5px' }}>
              EDIT · {sorted.length} cut{sorted.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {duration > 0 && (
            <span className="text-[10px] text-tb-border font-mono">
              {fmt(cutMode ? originalToLocal(currentTime, sorted) : currentTime)}
              {' / '}
              {fmt(totalDur)}
              {cutMode && (
                <span style={{ color: '#666', marginLeft: 5 }}>
                  (src {fmt(currentTime)})
                </span>
              )}
            </span>
          )}
          {!analyzed && (
            <span className="text-[10px] text-tb-border italic">Run analysis to populate tracks</span>
          )}
        </div>
      </div>

      {/* Track area */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Label column */}
        <div
          className="shrink-0 flex flex-col border-r border-tb-border bg-tb-header overflow-hidden"
          style={{ width: `${TRACK_LABEL_W}px` }}
        >
          <div className="shrink-0 border-b border-tb-border" style={{ height: `${RULER_H}px` }} />
          {systemTracks.map((track) => (
            <div
              key={track.id}
              className="shrink-0 flex items-center gap-2 px-2 border-b border-tb-border/50"
              style={{ height: `${TRACK_H}px` }}
            >
              <div className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: track.color }} />
              <span className="text-[10px] text-tb-muted truncate">{track.label}</span>
            </div>
          ))}
          {speakerIds.map((id, idx) => (
            <div
              key={id}
              className="shrink-0 flex items-center gap-2 px-2 border-b border-tb-border/50"
              style={{ height: `${TRACK_H}px` }}
            >
              <div className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: speakerColor(idx) }} />
              <span className="text-[10px] text-tb-muted truncate">{id}</span>
            </div>
          ))}
        </div>

        {/* Scrollable content area */}
        <div
          ref={contentRef}
          className="flex-1 overflow-x-auto overflow-y-hidden"
          style={{ cursor: 'crosshair' }}
        >
          <div
            className="relative"
            style={{ minWidth: '100%', height: `${contentH}px` }}
            onClick={seekTo}
          >

            {/* ── Time ruler ── */}
            <div
              className="absolute top-0 left-0 right-0 border-b border-tb-border bg-tb-panel/80"
              style={{ height: `${RULER_H}px`, zIndex: 2 }}
            >
              {ticks.map((t) => (
                <div
                  key={`maj-${t}`}
                  className="absolute top-0 flex flex-col items-start pointer-events-none"
                  style={{ left: pct(t) }}
                >
                  <span
                    className="text-tb-border font-mono"
                    style={{ fontSize: '9px', marginTop: '2px', transform: 'translateX(-50%)', whiteSpace: 'nowrap' }}
                  >
                    {fmt(t)}
                  </span>
                  <div className="w-px bg-tb-border absolute bottom-0" style={{ height: '7px' }} />
                </div>
              ))}
              {minorTicks.map((t) => (
                <div
                  key={`min-${t}`}
                  className="absolute bottom-0 w-px"
                  style={{ left: pct(t), height: '4px', backgroundColor: '#3a3a3a' }}
                />
              ))}

              {/* Cut boundary markers on ruler */}
              {cutBoundaryLocals.map((b, i) => (
                <div
                  key={`cb-${i}`}
                  className="absolute top-0 bottom-0 pointer-events-none"
                  style={{ left: pct(b), width: '2px', background: 'rgba(255,255,255,0.35)', zIndex: 3 }}
                />
              ))}

              {/* Trim handles on ruler (normal mode only) */}
              {!cutMode && duration > 0 && (
                <>
                  <div className="absolute top-0 bottom-0 pointer-events-none"
                    style={{ left: pct(trimIn), width: '2px', backgroundColor: '#f59e0b', zIndex: 3 }} />
                  <div className="absolute top-0 bottom-0 pointer-events-none"
                    style={{ left: pct(trimOutEff), width: '2px', backgroundColor: '#f59e0b', zIndex: 3 }} />
                </>
              )}

              {/* Ruler playhead */}
              {(cutMode ? keptDur > 0 : duration > 0) && (
                <div
                  className="absolute top-0 bottom-0 pointer-events-none"
                  style={{ left: pct(localPlayhead), width: '1px', backgroundColor: 'rgba(255,255,255,0.9)', zIndex: 4 }}
                >
                  <div style={{
                    position: 'absolute', top: 0, left: '-4px',
                    width: 0, height: 0,
                    borderLeft: '4px solid transparent',
                    borderRight: '4px solid transparent',
                    borderTop: '6px solid rgba(255,255,255,0.9)',
                  }} />
                </div>
              )}
            </div>

            {/* ── Track rows ── */}
            <div className="absolute left-0 right-0" style={{ top: `${RULER_H}px`, bottom: 0 }}>

              {/* Vertical grid lines */}
              {ticks.map((t) => (
                <div
                  key={`grid-${t}`}
                  className="absolute top-0 bottom-0 pointer-events-none"
                  style={{ left: pct(t), width: '1px', backgroundColor: '#3a3a3a44' }}
                />
              ))}

              {/* Cut boundary full-height markers */}
              {cutBoundaryLocals.map((b, i) => (
                <div
                  key={`cbf-${i}`}
                  className="absolute top-0 bottom-0 pointer-events-none"
                  style={{ left: pct(b), width: '2px', background: 'rgba(255,255,255,0.18)', zIndex: 3 }}
                />
              ))}

              {/* System tracks */}
              {systemTracks.map((track, trackIdx) => (
                <div
                  key={track.id}
                  className="absolute left-0 right-0 border-b border-tb-border/30 overflow-hidden"
                  style={{ top: trackIdx * TRACK_H, height: `${TRACK_H}px`, backgroundColor: `${track.color}08` }}
                >
                  <div className="absolute rounded-sm" style={{
                    top: '6px', bottom: '6px', left: 0, right: 0,
                    background: `linear-gradient(180deg, ${track.colorDim} 0%, ${track.color}55 30%, ${track.color}88 50%, ${track.color}55 70%, ${track.colorDim} 100%)`,
                  }} />
                </div>
              ))}

              {/* Speaker tracks */}
              {speakerIds.map((speakerId, spIdx) => {
                const top   = systemTracks.length * TRACK_H + spIdx * TRACK_H
                const color = speakerColor(spIdx)
                const speakerSegs = segments.filter((s) => s.speaker_id === speakerId)
                return (
                  <div
                    key={speakerId}
                    className="absolute left-0 right-0 border-b border-tb-border/30 overflow-hidden"
                    style={{ top, height: `${TRACK_H}px`, backgroundColor: `${color}06` }}
                  >
                    {speakerSegs.map((seg) => {
                      // In cut mode, position and width are in local time
                      const segLocalStart = cutMode ? originalToLocal(seg.start, sorted) : seg.start
                      const segLocalEnd   = cutMode ? originalToLocal(seg.end,   sorted) : seg.end
                      const segW = segLocalEnd - segLocalStart
                      if (segW < 0.05) return null
                      return (
                        <div
                          key={seg.id}
                          className="absolute rounded-sm overflow-hidden"
                          style={{
                            top: '5px', bottom: '5px',
                            left:  pct(segLocalStart),
                            width: pct(segW),
                            minWidth: '3px',
                            background: `linear-gradient(180deg, ${color}cc 0%, ${color}88 50%, ${color}cc 100%)`,
                            border: `1px solid ${color}60`,
                          }}
                          title={`${speakerId}: ${seg.source_text} (${fmt(segLocalStart)}–${fmt(segLocalEnd)})`}
                          onClick={(e) => {
                            e.stopPropagation()
                            if (videoRef.current) {
                              videoRef.current.currentTime = seg.start
                              setCurrentTime(seg.start)
                            }
                          }}
                        >
                          <span className="absolute inset-0 flex items-center px-1 text-white/70 pointer-events-none"
                            style={{ fontSize: '8px', whiteSpace: 'nowrap' }}>
                            {seg.source_text.slice(0, 20)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )
              })}

              {/* ── NORMAL MODE overlays ── */}
              {!cutMode && duration > 0 && (
                <>
                  {/* Darken excluded regions */}
                  {trimIn > 0 && (
                    <div className="absolute top-0 bottom-0 pointer-events-none"
                      style={{ left: 0, width: pct(trimIn), backgroundColor: 'rgba(0,0,0,0.55)', zIndex: 5 }} />
                  )}
                  {trimOutEff < totalDur && (
                    <div className="absolute top-0 bottom-0 pointer-events-none"
                      style={{ left: pct(trimOutEff), right: 0, backgroundColor: 'rgba(0,0,0,0.55)', zIndex: 5 }} />
                  )}
                  {/* Trim In handle */}
                  <div
                    className="absolute top-0 bottom-0 cursor-ew-resize"
                    style={{ left: pct(trimIn), width: '14px', transform: 'translateX(-7px)', zIndex: 6 }}
                    onPointerDown={startTrimDrag('in')}
                  >
                    <div className="absolute top-0 bottom-0" style={{ left: '6px', width: '2px', backgroundColor: '#f59e0b' }} />
                    <div className="absolute" style={{
                      top: 0, left: '2px', width: '10px', height: '10px',
                      backgroundColor: '#f59e0b', borderRadius: '2px 2px 0 0',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <span style={{ fontSize: '7px', color: '#000', fontWeight: 700, lineHeight: 1 }}>I</span>
                    </div>
                  </div>
                  {/* Trim Out handle */}
                  <div
                    className="absolute top-0 bottom-0 cursor-ew-resize"
                    style={{ left: pct(trimOutEff), width: '14px', transform: 'translateX(-7px)', zIndex: 6 }}
                    onPointerDown={startTrimDrag('out')}
                  >
                    <div className="absolute top-0 bottom-0" style={{ left: '6px', width: '2px', backgroundColor: '#f59e0b' }} />
                    <div className="absolute" style={{
                      top: 0, left: '2px', width: '10px', height: '10px',
                      backgroundColor: '#f59e0b', borderRadius: '2px 2px 0 0',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <span style={{ fontSize: '7px', color: '#000', fontWeight: 700, lineHeight: 1 }}>O</span>
                    </div>
                  </div>
                </>
              )}

              {/* ── CUT MODE: subtle active-region tint (the whole timeline = kept) ── */}
              {cutMode && (
                <div className="absolute inset-0 pointer-events-none" style={{
                  background: 'rgba(74,222,128,0.04)',
                  border: '1px solid rgba(74,222,128,0.18)',
                  zIndex: 5,
                }} />
              )}

              {/* Playhead across all track rows */}
              {(cutMode ? keptDur > 0 : duration > 0) && (
                <div
                  className="absolute top-0 bottom-0 pointer-events-none"
                  style={{ left: pct(localPlayhead), width: '1px', backgroundColor: 'rgba(255,255,255,0.7)', zIndex: 7 }}
                />
              )}
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
