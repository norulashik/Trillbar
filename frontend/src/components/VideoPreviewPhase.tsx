import { useRef, useState, useEffect, useMemo, type ReactNode } from 'react'
import {
  Play, Loader2, ChevronDown, ChevronRight,
  Film, Users, Settings2, Zap, Scissors, X,
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import type { CutRegion } from '../types'
import VoiceAssignmentPanel from './VoiceAssignmentPanel'
import TrackTimelineView from './TrackTimelineView'
import SourceMonitorPlayer from './SourceMonitorPlayer'

const LANGUAGES = ['hindi', 'tamil', 'telugu', 'kannada', 'malayalam', 'bengali', 'marathi']

const SPEAKER_COLORS = [
  '#a259ff', '#4a9eff', '#ff6b35', '#4CAF50', '#FF9800', '#E91E63', '#00BCD4',
]

export type { CutRegion }

// ── Inspector helpers ─────────────────────────────────────────────────────────

function SectionHeader({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 pb-1.5 border-b border-tb-border">
      <span className="text-tb-accent opacity-80">{icon}</span>
      <span className="text-[10px] font-semibold text-tb-muted uppercase tracking-widest">{label}</span>
    </div>
  )
}

function PropRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-[10px] text-tb-muted">{label}</span>
      <span className="text-[10px] text-tb-text font-mono">{value}</span>
    </div>
  )
}

function fmtDur(s: number): string {
  if (s <= 0) return '--'
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

function fmtTs(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

// ── Main component ────────────────────────────────────────────────────────────

export default function VideoPreviewPhase() {
  const {
    jobId, mode, uiPhase,
    targetLanguage, setTargetLanguage,
    skipSeparation, setSkipSeparation,
    skipProsody, setSkipProsody,
    setUiPhase, setJobState,
    segments,
    cutRegions, setCutRegions,
    trimIn, setTrimIn,
    trimOut, setTrimOut,
  } = useProjectStore()

  const [showAdvanced, setShowAdvanced] = useState(false)
  const [dubbing, setDubbing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)
  const [videoDuration, setVideoDuration] = useState(0)

  const videoRef = useRef<HTMLVideoElement>(null)

  // Set trimOut to full duration on first load
  useEffect(() => {
    if (videoDuration > 0 && trimOut === 0) setTrimOut(videoDuration)
  }, [videoDuration, trimOut])

  const isAnalyzing = uiPhase === 'analyzing'
  const isAnalyzed  = uiPhase === 'analyzed'
  const speakerIds  = [...new Set(segments.map((s) => s.speaker_id))].sort()
  const trimOutEff  = trimOut > 0 ? trimOut : videoDuration

  // ── Cut region management ─────────────────────────────────────────────────────

  const addCut = (start: number, end: number) => {
    if (end - start < 0.2) return
    const next = [...cutRegions, { start, end }].sort((a, b) => a.start - b.start)
    const merged: CutRegion[] = []
    for (const r of next) {
      if (merged.length > 0 && r.start <= merged[merged.length - 1].end) {
        merged[merged.length - 1].end = Math.max(merged[merged.length - 1].end, r.end)
      } else {
        merged.push({ ...r })
      }
    }
    setCutRegions(merged)
  }

  const removeCut = (idx: number) => {
    setCutRegions(cutRegions.filter((_, i) => i !== idx))
  }

  // Keep ranges: the cut regions themselves — CUT means "extract/keep this portion"
  const keepRanges = useMemo<CutRegion[] | null>(() => {
    if (cutRegions.length === 0) return null
    return cutRegions
      .map(r => ({ start: Math.max(r.start, trimIn), end: Math.min(r.end, trimOutEff) }))
      .filter(r => r.end - r.start > 0.1)
  }, [cutRegions, trimIn, trimOutEff])

  const totalKeptDuration = useMemo(() => {
    if (!keepRanges) return trimOutEff - trimIn
    return keepRanges.reduce((acc, r) => acc + r.end - r.start, 0)
  }, [keepRanges, trimIn, trimOutEff])

  // ── Handlers ─────────────────────────────────────────────────────────────────

  const runAnalysis = async () => {
    if (!jobId || isAnalyzing) return
    setAnalyzeError(null)
    setUiPhase('analyzing')
    setJobState({ status: 'analyzing', stage: 'Starting analysis…', progress: 0 })
    try {
      const fd = new FormData()
      fd.append('skip_separation', String(skipSeparation))
      if (keepRanges && keepRanges.length > 0) {
        fd.append('keep_ranges', JSON.stringify(keepRanges))
      } else {
        fd.append('trim_in',  String(trimIn))
        fd.append('trim_out', String(trimOutEff))
      }
      const res = await fetch(`/api/analyze/${jobId}`, { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? `Server error ${res.status}`)
      }
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : 'Analysis failed')
      setUiPhase('video-preview')
    }
  }

  const runTranslateDub = async () => {
    if (!jobId || dubbing) return
    setDubbing(true)
    setUiPhase('dubbing')
    setJobState({ status: 'dubbing', stage: 'Starting dubbing…', progress: 0 })
    try {
      const fd = new FormData()
      fd.append('target_language', targetLanguage)
      fd.append('skip_prosody', String(skipProsody))
      const res = await fetch(`/api/dub/${jobId}`, { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? `Server error ${res.status}`)
      }
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : 'Dubbing failed')
      setUiPhase('analyzed')
      setDubbing(false)
    }
  }

  // ── Inspector ─────────────────────────────────────────────────────────────────

  const inspector = (
    <div
      className="flex flex-col border-l border-tb-border bg-tb-panel shrink-0 overflow-hidden"
      style={{ width: 280, minWidth: 240 }}
    >
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-tb-border shrink-0 flex items-center gap-2 bg-tb-header">
        <Zap size={12} className="text-tb-accent shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-tb-text truncate">
            {mode === 'translation' ? 'Translation Dubbing' : 'Voice Mode'}
          </p>
          <p className="text-[10px] text-tb-muted mt-0.5">
            {isAnalyzed ? 'Analysis complete' : isAnalyzing ? 'Analysing…' : 'Edit clips, then analyse'}
          </p>
        </div>
        {isAnalyzed && (
          <span className="shrink-0 text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-green-500/15 text-green-400 border border-green-500/30">
            READY
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-4">

        {/* Source info */}
        {jobId && (
          <div className="flex flex-col gap-1.5">
            <SectionHeader icon={<Film size={10} />} label="Source" />
            <PropRow label="Job ID"   value={jobId.slice(0, 8) + '…'} />
            <PropRow label="Duration" value={fmtDur(videoDuration)} />
            <PropRow label="Pipeline" value={mode === 'translation' ? 'Translate' : 'Voice'} />
          </div>
        )}

        {/* Keep regions list */}
        {!isAnalyzing && !isAnalyzed && cutRegions.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <SectionHeader icon={<Scissors size={10} />} label="Cuts" />
            <p className="text-[10px] text-tb-muted">
              {cutRegions.length} region{cutRegions.length !== 1 ? 's' : ''} kept ·{' '}
              <span className="text-green-400 font-mono">{fmtDur(totalKeptDuration)}</span> will be analysed
            </p>
            <div className="flex flex-col gap-1">
              {cutRegions.map((cut, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between rounded px-2 py-1"
                  style={{ background: 'rgba(74,222,128,0.08)', border: '1px solid rgba(74,222,128,0.2)' }}
                >
                  <span className="text-[10px] font-mono text-green-400">
                    {fmtTs(cut.start)} → {fmtTs(cut.end)}
                  </span>
                  <button
                    onClick={() => removeCut(idx)}
                    className="text-green-400/60 hover:text-green-400 transition-colors"
                  >
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Analysing spinner */}
        {isAnalyzing && (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <Loader2 size={22} className="text-tb-accent animate-spin" />
            <div>
              <p className="text-sm font-medium text-tb-text">Analysing…</p>
              <p className="text-[10px] text-tb-muted mt-1">Transcribing, diarizing &amp; separating stems</p>
            </div>
          </div>
        )}

        {/* Speakers (post-analysis) */}
        {isAnalyzed && speakerIds.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <SectionHeader icon={<Users size={10} />} label="Speakers" />
            <PropRow label="Detected"  value={String(speakerIds.length)} />
            <PropRow label="Segments"  value={String(segments.length)} />
            <div className="flex flex-wrap gap-1 pt-1">
              {speakerIds.map((id, i) => {
                const c = SPEAKER_COLORS[i % SPEAKER_COLORS.length]
                return (
                  <span
                    key={id}
                    className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                    style={{ backgroundColor: c + '22', color: c, border: `1px solid ${c}44` }}
                  >
                    {id}
                  </span>
                )
              })}
            </div>
          </div>
        )}

        {/* Settings */}
        {!isAnalyzing && (
          <div className="flex flex-col gap-2">
            <SectionHeader icon={<Settings2 size={10} />} label="Settings" />

            {mode === 'translation' && (
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-tb-muted">Target Language</label>
                <select
                  value={targetLanguage}
                  onChange={(e) => setTargetLanguage(e.target.value)}
                  disabled={isAnalyzing || dubbing}
                  className="tb-input w-full"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>
                  ))}
                </select>
              </div>
            )}

            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1.5 text-[10px] text-tb-muted hover:text-tb-text transition-colors"
            >
              {showAdvanced ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
              Advanced Options
            </button>
            {showAdvanced && (
              <div className="pl-3 border-l border-tb-border space-y-2">
                {!isAnalyzed && (
                  <label className="flex items-center gap-2 cursor-pointer text-[10px] text-tb-muted">
                    <input
                      type="checkbox" checked={skipSeparation}
                      onChange={(e) => setSkipSeparation(e.target.checked)}
                      disabled={isAnalyzing} className="accent-tb-accent"
                    />
                    Skip vocal isolation
                  </label>
                )}
                {isAnalyzed && mode === 'translation' && (
                  <label className="flex items-center gap-2 cursor-pointer text-[10px] text-tb-muted">
                    <input
                      type="checkbox" checked={skipProsody}
                      onChange={(e) => setSkipProsody(e.target.checked)}
                      disabled={dubbing} className="accent-tb-accent"
                    />
                    Skip prosody transfer
                  </label>
                )}
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-col gap-2 mt-auto pt-2">

          {!isAnalyzed && !isAnalyzing && (
            <button
              onClick={runAnalysis}
              disabled={!jobId}
              className="btn-accent flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed w-full"
              style={{ padding: '10px 0' }}
            >
              <Play size={13} />
              {cutRegions.length > 0
                ? `Analyse (${fmtDur(totalKeptDuration)} kept)`
                : videoDuration > 0 && (trimIn > 0 || trimOutEff < videoDuration)
                  ? 'Analyse Selection'
                  : 'Run Analysis'}
            </button>
          )}

          {isAnalyzed && mode === 'translation' && (
            <button
              onClick={runTranslateDub}
              disabled={dubbing}
              className="btn-accent flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed w-full"
              style={{ padding: '10px 0' }}
            >
              <Play size={13} />
              {dubbing ? 'Dubbing…' : 'Translate & Dub'}
            </button>
          )}

          {isAnalyzed && mode === 'voice' && jobId && (
            <VoiceAssignmentPanel jobId={jobId} />
          )}

          {analyzeError && (
            <div className="bg-red-950/40 border border-red-500/30 rounded-lg px-3 py-2 text-xs text-red-400">
              {analyzeError}
            </div>
          )}
        </div>

      </div>
    </div>
  )

  // ── Layout ────────────────────────────────────────────────────────────────────

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">

      {/* Top row: source monitor + inspector */}
      <div className="flex flex-1 min-h-0">

        {/* Source monitor (custom player) */}
        <div className="flex-1 min-w-0 overflow-hidden">
          {jobId ? (
            <SourceMonitorPlayer
              src={`/api/video/${jobId}`}
              videoRef={videoRef}
              trimIn={trimIn}
              trimOut={trimOutEff}
              duration={videoDuration}
              cutRegions={cutRegions}
              onTrimIn={setTrimIn}
              onTrimOut={setTrimOut}
              onDurationLoaded={setVideoDuration}
              onAddCut={addCut}
              onRemoveCut={removeCut}
            />
          ) : (
            <div className="h-full flex items-center justify-center bg-black text-tb-muted text-sm">
              No video loaded
            </div>
          )}
        </div>

        {/* Inspector panel */}
        {inspector}
      </div>

      {/* Bottom: multi-track timeline */}
      <TrackTimelineView
        videoRef={videoRef}
        duration={videoDuration}
        segments={segments}
        analyzed={isAnalyzed}
        trimIn={trimIn}
        trimOut={trimOutEff}
        cutRegions={cutRegions}
        onTrimIn={setTrimIn}
        onTrimOut={setTrimOut}
      />

    </div>
  )
}
