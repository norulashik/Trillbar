import { useEffect, useRef, useState } from 'react'
import { Play, RefreshCw, RotateCcw, Zap, AlertTriangle, CheckCircle, RotateCw } from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import { EMOTION_COLORS } from '../types'
import type { PedalboardParams } from '../types'

const EMOTIONS = ['neutral', 'happy', 'angry', 'sad', 'excited', 'fear', 'surprise', 'calm', 'disgust']

const DEFAULT_PEDAL: PedalboardParams = {
  hp_cutoff: 80, low_shelf_hz: 200, low_shelf_db: -2,
  presence_hz: 3000, presence_db: 3, presence_q: 0.8,
  comp_threshold: -18, comp_ratio: 3, comp_attack_ms: 5,
  comp_release_ms: 100, reverb_room_size: 0.3, reverb_wet: 0, limiter_db: -1,
}

const QC_FLAG_LABELS: Record<string, string> = {
  sync_drift: 'Timing drift',
  pace_long: 'Dub too long',
  pace_short: 'Dub too short',
  low_mos: 'Low audio quality',
  needs_regen: 'Re-synthesis recommended',
  overlap: 'Overlaps next segment',
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface SliderRowProps {
  label: string; value: number; min: number; max: number; step: number
  unit?: string; onChange: (v: number) => void
}

function SliderRow({ label, value, min, max, step, unit = '', onChange }: SliderRowProps) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-tb-muted">
        <span>{label}</span>
        <span className="font-mono tabular-nums">
          {value % 1 === 0 ? value.toFixed(0) : value.toFixed(2)}{unit}
        </span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1 accent-tb-accent cursor-pointer"
      />
    </div>
  )
}

function MosMeter({ score }: { score: number }) {
  const filled = Math.round(score)
  const colors = ['bg-red-500', 'bg-orange-500', 'bg-yellow-500', 'bg-lime-500', 'bg-green-500']
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className={`w-5 h-2 rounded-sm ${i <= filled ? colors[Math.min(filled - 1, 4)] : 'bg-tb-border'}`} />
        ))}
      </div>
      <span className="text-xs font-mono text-tb-text tabular-nums">{score.toFixed(1)} / 5</span>
    </div>
  )
}

function SyncMeter({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = score >= 0.9 ? '#3dba7a' : score >= 0.7 ? '#f0b429' : '#ff4444'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-tb-border rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-xs font-mono tabular-nums" style={{ color }}>{pct}%</span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function VoiceControlsPanel() {
  const {
    segments, selectedSegmentId, updateSegment, jobId,
    resynthesizing, setResynthesizing,
    clips, setClip, resetClip,
    reassembling, setReassembling,
    qcMode,
  } = useProjectStore()

  const seg = segments.find((s) => s.id === selectedSegmentId)

  const [pedal, setPedal] = useState<PedalboardParams>(DEFAULT_PEDAL)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    if (seg?.pedalboard_params) {
      setPedal({ ...DEFAULT_PEDAL, ...seg.pedalboard_params })
    } else {
      setPedal(DEFAULT_PEDAL)
    }
  }, [seg?.id])

  if (!seg) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="panel-header">Segment Properties</div>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-tb-border text-xs text-center px-4">
            Select a segment from the transcript to edit its properties.
          </p>
        </div>
      </div>
    )
  }

  const s = seg
  const emotion = s.emotion ?? 'neutral'
  const intensity = s.emotion_intensity ?? 0.5
  const isBusy = resynthesizing.has(s.id)
  const clip = clips[s.id] ?? { offset_ms: 0, stretch_ratio: 1.0, trim_in_ms: 0, trim_out_ms: 0, gain_db: 0 }
  const offsetMs = clip.offset_ms ?? 0
  const stretchRatio = clip.stretch_ratio ?? 1.0
  const trimIn = clip.trim_in_ms ?? 0
  const trimOut = clip.trim_out_ms ?? 0
  const gainDb = clip.gain_db ?? 0

  function updatePedal(key: keyof PedalboardParams, value: number) {
    const next = { ...pedal, [key]: value }
    setPedal(next)
    updateSegment(s.id, { pedalboard_params: next })
  }

  function resetPedal() {
    setPedal(DEFAULT_PEDAL)
    updateSegment(s.id, { pedalboard_params: DEFAULT_PEDAL })
  }

  async function handlePreview() {
    if (!jobId) return
    const url = `/api/segment-audio/${jobId}/${s.id}`
    if (audioRef.current) audioRef.current.pause()
    audioRef.current = new Audio(url)
    audioRef.current.play().catch(() => {})
  }

  async function handleResynthesize() {
    if (!jobId || isBusy) return
    setResynthesizing(s.id, true)
    try {
      const res = await fetch(`/api/resynthesize/${jobId}/${s.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          emotion: s.emotion, emotion_intensity: s.emotion_intensity,
          translated_text: s.translated_text, pedalboard_params: pedal,
        }),
      })
      if (res.ok) {
        const data = await res.json() as { mos_score?: number; quality_notes?: string }
        updateSegment(s.id, { mos_score: data.mos_score, quality_notes: data.quality_notes, pedalboard_params: pedal })
      }
    } catch { /* non-critical */ } finally {
      setResynthesizing(s.id, false)
    }
  }

  async function handleReassemble() {
    if (!jobId || reassembling) return
    setReassembling(true)
    try {
      // Build clips payload from all segments
      const allSegments = segments
      const clipsPayload: Record<string, { offset_ms: number; muted: boolean; gain_db: number; stretch_ratio: number; trim_in_ms: number; trim_out_ms: number }> = {}
      for (const seg of allSegments) {
        const c = clips[seg.id]
        if (c) clipsPayload[String(seg.id)] = {
          offset_ms:     c.offset_ms     ?? 0,
          muted:         c.muted         ?? false,
          gain_db:       c.gain_db       ?? 0,
          stretch_ratio: c.stretch_ratio ?? 1.0,
          trim_in_ms:    c.trim_in_ms    ?? 0,
          trim_out_ms:   c.trim_out_ms   ?? 0,
        }
      }
      const res = await fetch(`/api/reassemble/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clips: clipsPayload }),
      })
      if (res.ok) {
        // Re-fetch transcript to get updated sync scores
        const txRes = await fetch(`/api/transcript/${jobId}`)
        if (txRes.ok) {
          const json = await txRes.json() as { segments: typeof segments }
          const { setSegments } = useProjectStore.getState()
          setSegments(json.segments)
        }
      }
    } catch { /* non-critical */ } finally {
      setReassembling(false)
    }
  }

  const paceRatio = s.pace_ratio
  const paceColor = paceRatio === undefined ? undefined
    : paceRatio >= 0.9 && paceRatio <= 1.1 ? '#3dba7a'
    : paceRatio >= 0.8 && paceRatio <= 1.2 ? '#f0b429'
    : '#ff4444'

  const qcFlags = s.qc_flags ?? []

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="panel-header">Segment Properties</div>
      <div className="flex-1 overflow-y-auto p-3 space-y-4 text-sm">

        {/* ── QC Summary (shown when qcMode is on and segment has flags) ── */}
        {qcMode && qcFlags.length > 0 && (
          <div className="rounded border border-orange-500/30 bg-orange-500/10 p-2 space-y-1">
            <div className="text-xs text-orange-400 font-semibold uppercase tracking-widest mb-1">QC Issues</div>
            {qcFlags.map((f) => (
              <div key={f} className="flex items-center gap-1 text-xs text-orange-300">
                <AlertTriangle size={9} />
                {QC_FLAG_LABELS[f] ?? f}
              </div>
            ))}
          </div>
        )}
        {qcMode && qcFlags.length === 0 && (
          <div className="rounded border border-green-500/30 bg-green-500/10 p-2 flex items-center gap-1.5">
            <CheckCircle size={12} className="text-green-400" />
            <span className="text-xs text-green-400">No issues</span>
          </div>
        )}

        {/* ── Speaker info ── */}
        <div>
          <div className="text-xs text-tb-muted mb-0.5">Speaker</div>
          <div className="font-medium text-tb-text">{s.speaker_id}</div>
          <div className="text-xs text-tb-muted font-mono">
            {s.start.toFixed(2)}s – {s.end.toFixed(2)}s
            &nbsp;·&nbsp;{(s.end - s.start).toFixed(2)}s
          </div>
        </div>

        <div className="h-px bg-tb-border" />

        {/* ── Vocal Analysis ── */}
        <div className="space-y-3">
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-tb-muted uppercase tracking-widest font-semibold">Vocal Analysis</span>
            {(s.vocal_character || s.speaking_rate_wpm) && (
              <span className="text-[10px] px-1 rounded bg-tb-accent/15 text-tb-accent border border-tb-accent/30">AI</span>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="text-xs text-tb-muted">Emotion</div>
            <div className="flex flex-wrap gap-1">
              {EMOTIONS.map((e) => (
                <button
                  key={e}
                  onClick={() => updateSegment(s.id, { emotion: e })}
                  className={`text-xs px-2 py-0.5 rounded transition-colors ${
                    emotion === e
                      ? (EMOTION_COLORS[e] ?? EMOTION_COLORS.neutral)
                      : 'bg-tb-bg text-tb-muted hover:text-tb-text border border-tb-border'
                  }`}
                >
                  {e}
                </button>
              ))}
            </div>
          </div>

          <SliderRow
            label="Intensity" value={intensity} min={0} max={1} step={0.01}
            onChange={(v) => updateSegment(s.id, { emotion_intensity: v })}
          />

          {s.vocal_character && (
            <div className="text-xs text-tb-muted">
              Character&nbsp;<span className="text-tb-text">{s.vocal_character}</span>
            </div>
          )}
          {s.speaking_rate_wpm && (
            <div className="text-xs text-tb-muted">
              Rate&nbsp;<span className="text-tb-text font-mono">{Math.round(s.speaking_rate_wpm)} wpm</span>
            </div>
          )}
        </div>

        {/* ── Acting Direction ── */}
        {s.delivery_direction && (
          <>
            <div className="h-px bg-tb-border" />
            <div className="space-y-1.5">
              <div className="text-sm text-tb-muted uppercase tracking-widest font-semibold">Acting Direction</div>
              <p className="text-xs text-tb-emotion italic leading-relaxed">{s.delivery_direction}</p>
            </div>
          </>
        )}

        <div className="h-px bg-tb-border" />

        {/* ── EQ & Dynamics ── */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-tb-muted uppercase tracking-widest font-semibold">EQ &amp; Dynamics</span>
              <span className="text-[10px] px-1 rounded bg-tb-accent/15 text-tb-accent border border-tb-accent/30">AI</span>
            </div>
            <button
              onClick={resetPedal}
              title="Reset to AI defaults"
              className="flex items-center gap-1 text-[10px] text-tb-muted hover:text-tb-text transition-colors"
            >
              <RotateCcw size={10} />
              reset
            </button>
          </div>

          <SliderRow label="High-pass" value={pedal.hp_cutoff} min={20} max={500} step={1} unit=" Hz"
            onChange={(v) => updatePedal('hp_cutoff', v)} />
          <SliderRow label="Low Shelf" value={pedal.low_shelf_db} min={-6} max={3} step={0.1} unit=" dB"
            onChange={(v) => updatePedal('low_shelf_db', v)} />
          <SliderRow label="Presence" value={pedal.presence_db} min={-3} max={6} step={0.1} unit=" dB"
            onChange={(v) => updatePedal('presence_db', v)} />
          <SliderRow label="Comp Thresh" value={pedal.comp_threshold} min={-40} max={0} step={0.5} unit=" dB"
            onChange={(v) => updatePedal('comp_threshold', v)} />
          <SliderRow label="Comp Ratio" value={pedal.comp_ratio} min={1} max={10} step={0.1} unit=":1"
            onChange={(v) => updatePedal('comp_ratio', v)} />
          <SliderRow label="Reverb Wet" value={pedal.reverb_wet} min={0} max={0.5} step={0.01}
            onChange={(v) => updatePedal('reverb_wet', v)} />
        </div>

        {/* ── Quality Score ── */}
        {s.mos_score !== undefined && (
          <>
            <div className="h-px bg-tb-border" />
            <div className="space-y-2">
              <div className="text-sm text-tb-muted uppercase tracking-widest font-semibold">Quality Score</div>
              <MosMeter score={s.mos_score} />
              {s.quality_notes && <p className="text-xs text-tb-muted italic">{s.quality_notes}</p>}
              {s.needs_regen && (
                <div className="flex items-center gap-1 text-xs text-orange-400">
                  <Zap size={10} />
                  Re-synthesis recommended
                </div>
              )}
            </div>
          </>
        )}

        <div className="h-px bg-tb-border" />

        {/* ── Sync Correction ── */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-tb-muted uppercase tracking-widest font-semibold">Sync Correction</span>
            {offsetMs !== 0 && (
              <button
                onClick={() => resetClip(s.id)}
                className="flex items-center gap-1 text-[10px] text-tb-muted hover:text-tb-text transition-colors"
              >
                <RotateCcw size={10} />
                reset
              </button>
            )}
          </div>

          {/* Timing offset slider */}
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-tb-muted">
              <span>Timing Offset</span>
              <span className="font-mono tabular-nums" style={{ color: offsetMs !== 0 ? '#f0b429' : undefined }}>
                {offsetMs > 0 ? '+' : ''}{offsetMs} ms
              </span>
            </div>
            <div className="relative">
              <input
                type="range" min={-500} max={500} step={10} value={offsetMs}
                onChange={(e) => setClip(s.id, { offset_ms: parseInt(e.target.value) })}
                className="w-full h-1 accent-tb-accent cursor-pointer"
              />
              {/* Ghost marker for suggested offset */}
              {s.suggested_offset_ms !== undefined && s.suggested_offset_ms !== 0 && (
                <button
                  onClick={() => setClip(s.id, { offset_ms: s.suggested_offset_ms! })}
                  title={`Apply suggested offset: ${s.suggested_offset_ms > 0 ? '+' : ''}${s.suggested_offset_ms}ms`}
                  className="absolute top-1/2 -translate-y-1/2 w-1 h-3 rounded-sm bg-tb-accent/50 cursor-pointer hover:bg-tb-accent transition-colors"
                  style={{ left: `${((s.suggested_offset_ms + 500) / 1000) * 100}%` }}
                />
              )}
            </div>
          </div>

          {/* Volume, Stretch, Trim */}
          <SliderRow
            label="Volume" value={gainDb} min={-12} max={6} step={0.5} unit=" dB"
            onChange={(v) => setClip(s.id, { gain_db: v })}
          />
          <SliderRow
            label="Speed" value={stretchRatio} min={0.7} max={1.3} step={0.01} unit="×"
            onChange={(v) => setClip(s.id, { stretch_ratio: v })}
          />
          <SliderRow
            label="Trim In" value={trimIn} min={0} max={500} step={10} unit=" ms"
            onChange={(v) => setClip(s.id, { trim_in_ms: v })}
          />
          <SliderRow
            label="Trim Out" value={trimOut} min={0} max={500} step={10} unit=" ms"
            onChange={(v) => setClip(s.id, { trim_out_ms: v })}
          />

          {/* Pace ratio */}
          {paceRatio !== undefined && (
            <div className="flex justify-between text-xs">
              <span className="text-tb-muted">Pace Ratio</span>
              <span className="font-mono tabular-nums" style={{ color: paceColor }}>
                {paceRatio.toFixed(2)}x
                {paceRatio > 1.2 ? ' — too long' : paceRatio < 0.8 ? ' — too short' : ''}
              </span>
            </div>
          )}

          {/* Lip sync score bar */}
          {s.lip_sync_score !== undefined && (
            <div className="space-y-1">
              <div className="text-xs text-tb-muted">Lip Sync</div>
              <SyncMeter score={s.lip_sync_score} />
            </div>
          )}

          {/* Re-Assemble button */}
          <button
            onClick={handleReassemble}
            disabled={!jobId || reassembling}
            className="w-full flex items-center justify-center gap-1.5 btn-ghost border border-tb-border text-tb-muted hover:text-tb-text py-1.5 rounded text-xs disabled:opacity-40"
          >
            <RotateCw size={11} className={reassembling ? 'animate-spin' : ''} />
            {reassembling ? 'Re-Assembling…' : 'Re-Assemble'}
          </button>
        </div>

        <div className="h-px bg-tb-border" />

        {/* ── Actions ── */}
        <div className="flex gap-2">
          <button
            onClick={handlePreview}
            disabled={!jobId}
            className="flex-1 flex items-center justify-center gap-1.5 btn-ghost border border-tb-border text-tb-muted hover:text-tb-text py-2 rounded text-xs disabled:opacity-40"
          >
            <Play size={11} />
            Preview
          </button>
          <button
            onClick={handleResynthesize}
            disabled={!jobId || isBusy}
            className="flex-1 flex items-center justify-center gap-1.5 btn-ghost border border-tb-accent/40 text-tb-accent hover:bg-tb-accent/10 py-2 rounded text-xs disabled:opacity-40"
          >
            <RefreshCw size={11} className={isBusy ? 'animate-spin' : ''} />
            {isBusy ? 'Synthesizing…' : 'Re-Synthesize'}
          </button>
        </div>

      </div>
    </div>
  )
}
