/**
 * Premiere Pro-style source monitor with in/out trim handles.
 *
 * Two modes:
 *   - Normal mode (no cutRegions): full video scrubber with IN/OUT handles.
 *   - Cut mode (cutRegions.length > 0): scrubber collapses to the trimmed
 *     duration. All positions/timecodes are in local time (0 → totalKeptDuration).
 *     Playback maps local time ↔ original video time transparently.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Maximize2, Pause, Play, Volume2, VolumeX, Repeat, Scissors } from 'lucide-react'
import type { CutRegion } from './VideoPreviewPhase'
import {
  sortRegions, totalKeptDuration, localToOriginal, originalToLocal,
} from '../utils/timeline'

function fmt(t: number): string {
  if (!isFinite(t) || t < 0) t = 0
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  const f = Math.floor((t % 1) * 10)
  return `${m}:${s.toString().padStart(2, '0')}.${f}`
}

interface Props {
  src: string
  videoRef: React.RefObject<HTMLVideoElement>
  trimIn: number
  trimOut: number
  duration: number
  cutRegions?: CutRegion[]
  onTrimIn: (t: number) => void
  onTrimOut: (t: number) => void
  onDurationLoaded: (d: number) => void
  onAddCut?: (start: number, end: number) => void
  onRemoveCut?: (idx: number) => void
}

const HANDLE_HIT = 14

export default function SourceMonitorPlayer({
  src, videoRef, trimIn, trimOut, duration,
  cutRegions = [],
  onTrimIn, onTrimOut, onDurationLoaded,
  onAddCut, onRemoveCut: _onRemoveCut,
}: Props) {
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [muted, setMuted] = useState(false)
  const [loopInOut, setLoopInOut] = useState(false)
  const scrubRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<'in' | 'out' | 'head' | null>(null)
  const loopRef = useRef(false)
  const cutRegionsRef = useRef(cutRegions)
  useEffect(() => { cutRegionsRef.current = cutRegions }, [cutRegions])

  // ── Derived values ────────────────────────────────────────────────────────────

  const dur         = duration > 0 ? duration : 1
  const trimOutEff  = trimOut > 0 ? trimOut : dur
  const cutMode     = cutRegions.length > 0
  const sorted      = sortRegions(cutRegions)
  const effectiveDur = cutMode ? Math.max(0.001, totalKeptDuration(sorted)) : dur

  // Local time position of the playhead (0 → effectiveDur)
  const localT = cutMode ? originalToLocal(currentTime, sorted) : currentTime

  // % helpers — always in effective-duration space
  const pct  = (t: number) => `${((Math.max(0, Math.min(effectiveDur, t)) / effectiveDur) * 100).toFixed(5)}%`
  // % in full-duration space (normal mode only)
  const pctF = (t: number) => `${((Math.max(0, Math.min(dur, t)) / dur) * 100).toFixed(5)}%`

  useEffect(() => { loopRef.current = loopInOut }, [loopInOut])

  // ── Video event listeners ─────────────────────────────────────────────────────

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onTime = () => {
      const t = v.currentTime
      setCurrentTime(t)

      const regions = cutRegionsRef.current
      if (regions.length > 0) {
        const s = sortRegions(regions)
        const idx = s.findIndex(r => t >= r.start - 0.05 && t < r.end)
        if (idx === -1) {
          const next = s.find(r => r.start > t - 0.1)
          if (next) { v.currentTime = next.start }
          else {
            v.pause()
            if (loopRef.current) { v.currentTime = s[0].start; void v.play() }
          }
          return
        }
        if (t >= s[idx].end - 0.05) {
          const next = s[idx + 1]
          if (next) { v.currentTime = next.start }
          else {
            v.pause()
            if (loopRef.current) { v.currentTime = s[0].start; void v.play() }
          }
        }
      } else {
        if (loopRef.current && t >= trimOutEff - 0.05) {
          v.currentTime = trimIn
        }
      }
    }
    const onPlay  = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    const onMeta  = () => { onDurationLoaded(v.duration); setCurrentTime(0) }
    v.addEventListener('timeupdate',     onTime)
    v.addEventListener('play',           onPlay)
    v.addEventListener('pause',          onPause)
    v.addEventListener('loadedmetadata', onMeta)
    return () => {
      v.removeEventListener('timeupdate',     onTime)
      v.removeEventListener('play',           onPlay)
      v.removeEventListener('pause',          onPause)
      v.removeEventListener('loadedmetadata', onMeta)
    }
  }, [videoRef, onDurationLoaded, trimIn, trimOutEff])

  // ── Keyboard shortcuts ────────────────────────────────────────────────────────

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return
      if (!cutMode) {
        if (e.key === 'i' || e.key === 'I') { onTrimIn(Math.min(currentTime, trimOutEff - 0.5)); e.preventDefault() }
        if (e.key === 'o' || e.key === 'O') { onTrimOut(Math.max(currentTime, trimIn + 0.5)); e.preventDefault() }
        if ((e.key === 'Delete' || e.key === 'Backspace') && onAddCut) {
          if (trimOutEff - trimIn > 0.2) { onAddCut(trimIn, trimOutEff); e.preventDefault() }
        }
      }
      if (e.key === ' ') {
        const v = videoRef.current
        if (v) { playing ? v.pause() : v.play() }
        e.preventDefault()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [currentTime, trimIn, trimOutEff, playing, cutMode, videoRef, onTrimIn, onTrimOut, onAddCut])

  // ── Drag / scrub ──────────────────────────────────────────────────────────────

  /**
   * Convert a clientX position to original video time.
   * In cut mode: pixel → local time → original time via mapping.
   * In normal mode: pixel → time in full duration.
   */
  const xToTime = useCallback((clientX: number): number => {
    const rect = scrubRef.current?.getBoundingClientRect()
    if (!rect) return 0
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    if (cutMode) {
      const localTime = ratio * effectiveDur
      return localToOriginal(localTime, sorted)
    }
    return ratio * dur
  }, [dur, effectiveDur, cutMode, sorted])

  const startDrag = (type: 'in' | 'out' | 'head') => (e: React.PointerEvent) => {
    e.stopPropagation()
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = type

    const onMove = (me: PointerEvent) => {
      const t = xToTime(me.clientX)
      if (dragRef.current === 'in') {
        onTrimIn(Math.min(t, trimOutEff - 0.5))
      } else if (dragRef.current === 'out') {
        onTrimOut(Math.max(t, trimIn + 0.5))
      } else {
        const v = videoRef.current
        if (v) { v.currentTime = t; setCurrentTime(t) }
      }
    }
    const onUp = () => {
      dragRef.current = null
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup',   onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup',   onUp)
  }

  const handleScrubClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (dragRef.current) return
    const t = xToTime(e.clientX)
    const v = videoRef.current
    if (!v) return
    v.currentTime = t
    setCurrentTime(t)
  }

  // ── Transport ─────────────────────────────────────────────────────────────────

  const togglePlay = () => {
    const v = videoRef.current
    if (!v) return
    if (playing) {
      v.pause()
    } else {
      if (cutMode) {
        const inAny = sorted.some(r => v.currentTime >= r.start && v.currentTime < r.end)
        if (!inAny) v.currentTime = sorted[0].start
      } else if (loopInOut && v.currentTime >= trimOutEff) {
        v.currentTime = trimIn
      }
      v.play()
    }
  }

  const playInToOut = () => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = cutMode ? sorted[0].start : trimIn
    v.play()
  }

  const toggleMute   = () => { const v = videoRef.current; if (!v) return; v.muted = !v.muted; setMuted(v.muted) }
  const goFullscreen = () => videoRef.current?.requestFullscreen?.()

  const trimActive = !cutMode && duration > 0 && (trimIn > 0 || trimOutEff < dur)

  // ── Cut boundary positions (local time at each region join) ───────────────────
  const cutBoundaries: number[] = []
  if (cutMode && sorted.length > 1) {
    let acc = 0
    for (let i = 0; i < sorted.length - 1; i++) {
      acc += sorted[i].end - sorted[i].start
      cutBoundaries.push(acc)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col w-full h-full" style={{ background: '#0d0d0d' }}>

      {/* ── Video area ── */}
      <div className="flex-1 relative flex items-center justify-center overflow-hidden">

        {/* Monitor label bar */}
        <div
          className="absolute top-0 left-0 right-0 z-10 flex items-center px-3"
          style={{ height: 22, background: 'rgba(0,0,0,0.75)' }}
        >
          <span style={{ fontSize: 9, color: '#555', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
            Source Monitor
          </span>
          {cutMode && (
            <span style={{ fontSize: 9, color: '#4ade80', fontFamily: 'monospace', marginLeft: 8,
              background: 'rgba(74,222,128,0.12)', border: '1px solid rgba(74,222,128,0.3)',
              borderRadius: 2, padding: '1px 5px' }}>
              EDIT — {sorted.length} region{sorted.length !== 1 ? 's' : ''} · {fmt(effectiveDur)}
            </span>
          )}
          {!cutMode && duration > 0 && (
            <div className="ml-auto flex items-center gap-4">
              <span style={{ fontSize: 9, color: '#f59e0b', fontFamily: 'monospace' }}>IN&nbsp;&nbsp;{fmt(trimIn)}</span>
              <span style={{ fontSize: 9, color: '#f59e0b', fontFamily: 'monospace' }}>OUT&nbsp;{fmt(trimOutEff)}</span>
              <span style={{ fontSize: 9, color: '#777', fontFamily: 'monospace' }}>{fmt(trimOutEff - trimIn)}</span>
            </div>
          )}
        </div>

        <video
          key={src}
          ref={videoRef}
          src={src}
          className="max-h-full max-w-full object-contain"
          style={{ marginTop: 22, maxHeight: 'calc(100% - 22px)' }}
        />
      </div>

      {/* ── Controls bar ── */}
      <div className="shrink-0 flex flex-col" style={{ background: '#181818', borderTop: '1px solid #2a2a2a' }}>

        {/* ── Scrubber ── */}
        <div style={{ padding: '8px 10px 4px' }}>

          {/* Hint row — shown only in normal mode when no trim yet */}
          {!cutMode && duration > 0 && !trimActive && (
            <div className="flex items-center gap-2 pb-1.5">
              <span style={{ fontSize: 9, color: '#555', fontFamily: 'monospace' }}>Drag&nbsp;</span>
              <span style={{ fontSize: 10, color: '#f59e0b', fontFamily: 'monospace',
                background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.3)',
                borderRadius: 2, padding: '0 4px' }}>[</span>
              <span style={{ fontSize: 9, color: '#555', fontFamily: 'monospace' }}>&nbsp;/&nbsp;</span>
              <span style={{ fontSize: 10, color: '#f59e0b', fontFamily: 'monospace',
                background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.3)',
                borderRadius: 2, padding: '0 4px' }}>]</span>
              <span style={{ fontSize: 9, color: '#555', fontFamily: 'monospace' }}>&nbsp;handles to set trim points · Press&nbsp;</span>
              <span style={{ fontSize: 9, color: '#aaa', fontFamily: 'monospace', background: '#2a2a2a', borderRadius: 2, padding: '0 3px' }}>I</span>
              <span style={{ fontSize: 9, color: '#555' }}>/</span>
              <span style={{ fontSize: 9, color: '#aaa', fontFamily: 'monospace', background: '#2a2a2a', borderRadius: 2, padding: '0 3px' }}>O</span>
            </div>
          )}

          <div
            ref={scrubRef}
            className="relative"
            style={{ height: 20, cursor: 'crosshair', userSelect: 'none' }}
            onClick={handleScrubClick}
          >
            {/* Base bar */}
            <div className="absolute inset-0 rounded-sm" style={{ background: '#272727' }} />

            {/* ── CUT MODE: single green-tinted active bar + boundary marks ── */}
            {cutMode && (
              <>
                <div className="absolute inset-0 rounded-sm pointer-events-none" style={{
                  background: 'rgba(74,222,128,0.15)',
                  border: '1px solid rgba(74,222,128,0.4)',
                }} />
                {cutBoundaries.map((localBound, i) => (
                  <div key={i} className="absolute top-0 bottom-0 pointer-events-none" style={{
                    left: pct(localBound),
                    width: '2px',
                    background: 'rgba(255,255,255,0.45)',
                    zIndex: 3,
                  }} />
                ))}
              </>
            )}

            {/* ── NORMAL MODE: amber trim region + excluded overlays ── */}
            {!cutMode && (
              <>
                {trimIn > 0 && (
                  <div className="absolute top-0 bottom-0 rounded-l-sm pointer-events-none"
                    style={{ left: 0, width: pctF(trimIn), background: 'rgba(0,0,0,0.6)' }} />
                )}
                <div className="absolute top-0 bottom-0 pointer-events-none" style={{
                  left: pctF(trimIn),
                  width: pctF(trimOutEff - trimIn),
                  background: 'rgba(245,158,11,0.2)',
                  borderTop: '1.5px solid rgba(245,158,11,0.6)',
                  borderBottom: '1.5px solid rgba(245,158,11,0.6)',
                }} />
                {trimOutEff < dur && (
                  <div className="absolute top-0 bottom-0 rounded-r-sm pointer-events-none"
                    style={{ left: pctF(trimOutEff), right: 0, background: 'rgba(0,0,0,0.6)' }} />
                )}
              </>
            )}

            {/* Played progress */}
            <div className="absolute top-0 bottom-0 pointer-events-none" style={{
              left: 0, width: pct(localT),
              background: 'rgba(255,255,255,0.06)',
              borderRadius: '2px 0 0 2px',
            }} />

            {/* ── IN handle (normal mode only) ── */}
            {!cutMode && duration > 0 && (
              <div className="absolute top-0 bottom-0 cursor-ew-resize" style={{
                left: pctF(trimIn), width: HANDLE_HIT * 2,
                transform: `translateX(-${HANDLE_HIT}px)`, zIndex: 4,
              }} onPointerDown={startDrag('in')}>
                <div className="absolute top-0 bottom-0" style={{ left: HANDLE_HIT - 1, width: 3, background: '#f59e0b' }} />
                <div style={{ position: 'absolute', top: 0, left: HANDLE_HIT - 1, width: 8, height: 6, background: '#f59e0b', borderRadius: '0 2px 0 0' }} />
                <div style={{ position: 'absolute', bottom: 0, left: HANDLE_HIT - 1, width: 8, height: 6, background: '#f59e0b', borderRadius: '0 0 2px 0' }} />
                <div style={{ position: 'absolute', top: -14, left: HANDLE_HIT - 2, fontSize: 8, color: '#f59e0b', fontFamily: 'monospace', fontWeight: 700, whiteSpace: 'nowrap', pointerEvents: 'none' }}>IN</div>
              </div>
            )}

            {/* ── OUT handle (normal mode only) ── */}
            {!cutMode && duration > 0 && (
              <div className="absolute top-0 bottom-0 cursor-ew-resize" style={{
                left: pctF(trimOutEff), width: HANDLE_HIT * 2,
                transform: `translateX(-${HANDLE_HIT}px)`, zIndex: 4,
              }} onPointerDown={startDrag('out')}>
                <div className="absolute top-0 bottom-0" style={{ left: HANDLE_HIT - 1, width: 3, background: '#f59e0b' }} />
                <div style={{ position: 'absolute', top: 0, left: HANDLE_HIT - 9, width: 8, height: 6, background: '#f59e0b', borderRadius: '2px 0 0 0' }} />
                <div style={{ position: 'absolute', bottom: 0, left: HANDLE_HIT - 9, width: 6, height: 6, background: '#f59e0b', borderRadius: '0 0 0 2px' }} />
                <div style={{ position: 'absolute', top: -14, left: HANDLE_HIT - 12, fontSize: 8, color: '#f59e0b', fontFamily: 'monospace', fontWeight: 700, whiteSpace: 'nowrap', pointerEvents: 'none' }}>OUT</div>
              </div>
            )}

            {/* ── Playhead ── */}
            {(cutMode ? effectiveDur > 0 : duration > 0) && (
              <div className="absolute top-0 bottom-0 cursor-col-resize" style={{
                left: pct(localT), width: 12,
                transform: 'translateX(-6px)', zIndex: 5,
              }} onPointerDown={startDrag('head')}>
                <div className="absolute top-0 bottom-0" style={{ left: 5, width: 2, background: 'rgba(255,255,255,0.9)' }} />
                <div style={{ position: 'absolute', top: -4, left: 2, width: 8, height: 8, background: 'white', transform: 'rotate(45deg)', borderRadius: 1 }} />
              </div>
            )}
          </div>
        </div>

        {/* ── Transport row ── */}
        <div className="flex items-center gap-1 px-2 pb-2" style={{ height: 34 }}>

          <button onClick={togglePlay}
            className="flex items-center justify-center rounded hover:bg-white/5 transition-colors"
            style={{ width: 30, height: 26, color: '#c0c0c0' }}
            title="Play / Pause (Space)"
          >
            {playing ? <Pause size={14} /> : <Play size={14} />}
          </button>

          {/* Timecode — local time / effective duration */}
          <span className="font-mono text-tb-muted" style={{ fontSize: 11, minWidth: 110, letterSpacing: '0.02em' }}>
            {fmt(localT)}&nbsp;/&nbsp;{(cutMode ? effectiveDur : duration) > 0 ? fmt(cutMode ? effectiveDur : duration) : '--:--'}
          </span>

          <div className="flex-1" />

          {/* Play In→Out (only in normal mode with trim active) */}
          {trimActive && !cutMode && (
            <button onClick={playInToOut} title="Play In to Out"
              className="flex items-center gap-1 rounded transition-colors"
              style={{ height: 22, padding: '0 6px', fontSize: 9,
                background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)',
                color: '#f59e0b', fontFamily: 'monospace', fontWeight: 700, whiteSpace: 'nowrap' }}
            >
              <Play size={9} />IN→OUT
            </button>
          )}

          {/* Play from start (cut mode) */}
          {cutMode && (
            <button onClick={playInToOut} title="Play from start of edit"
              className="flex items-center gap-1 rounded transition-colors"
              style={{ height: 22, padding: '0 6px', fontSize: 9,
                background: 'rgba(74,222,128,0.12)', border: '1px solid rgba(74,222,128,0.35)',
                color: '#4ade80', fontFamily: 'monospace', fontWeight: 700, whiteSpace: 'nowrap' }}
            >
              <Play size={9} />PLAY EDIT
            </button>
          )}

          {/* Loop toggle */}
          {(trimActive || cutMode) && (
            <button onClick={() => setLoopInOut(!loopInOut)} title={loopInOut ? 'Loop: On' : 'Loop: Off'}
              className="flex items-center justify-center rounded transition-colors"
              style={{ width: 26, height: 22,
                background: loopInOut ? 'rgba(245,158,11,0.25)' : 'transparent',
                border: loopInOut ? '1px solid rgba(245,158,11,0.5)' : '1px solid #333',
                color: loopInOut ? '#f59e0b' : '#555' }}
            >
              <Repeat size={10} />
            </button>
          )}

          {/* CUT button — only in normal mode */}
          {!cutMode && onAddCut && duration > 0 && (
            <button
              onClick={() => { if (trimOutEff - trimIn > 0.2) onAddCut(trimIn, trimOutEff) }}
              title="Keep this region — everything else will be excluded (Delete)"
              disabled={trimOutEff - trimIn < 0.2}
              className="flex items-center gap-1 rounded transition-colors disabled:opacity-30"
              style={{ height: 22, padding: '0 7px',
                background: 'rgba(74,222,128,0.12)', border: '1px solid rgba(74,222,128,0.4)',
                color: '#4ade80' }}
            >
              <Scissors size={10} />
              <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'monospace' }}>CUT</span>
            </button>
          )}

          {/* IN/OUT point buttons (normal mode only) */}
          {!cutMode && (
            <>
              <button onClick={() => onTrimIn(Math.min(currentTime, trimOutEff - 0.5))}
                title="Set In Point (I)"
                className="flex items-center justify-center rounded font-bold transition-colors"
                style={{ width: 28, height: 22, fontSize: 13,
                  background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)',
                  color: '#f59e0b', fontFamily: 'monospace' }}>
                {'{'}
              </button>
              <button onClick={() => onTrimOut(Math.max(currentTime, trimIn + 0.5))}
                title="Set Out Point (O)"
                className="flex items-center justify-center rounded font-bold transition-colors"
                style={{ width: 28, height: 22, fontSize: 13,
                  background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)',
                  color: '#f59e0b', fontFamily: 'monospace', marginRight: 4 }}>
                {'}'}
              </button>
            </>
          )}

          <button onClick={toggleMute}
            className="flex items-center justify-center rounded hover:bg-white/5 transition-colors"
            style={{ width: 28, height: 26, color: muted ? '#ef4444' : '#9a9a9a' }}
            title="Mute"
          >
            {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
          </button>

          <button onClick={goFullscreen}
            className="flex items-center justify-center rounded hover:bg-white/5 transition-colors"
            style={{ width: 28, height: 26, color: '#9a9a9a' }}
            title="Fullscreen"
          >
            <Maximize2 size={12} />
          </button>
        </div>
      </div>
    </div>
  )
}
