import { useRef, useEffect } from 'react'
import { ChevronLeft, ChevronRight, AlertTriangle } from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import { usePlaybackStore } from '../store/playbackStore'
import { EMOTION_COLORS } from '../types'

function fmt(t: number) {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

const SPEAKER_COLORS = [
  'bg-blue-500/20 text-blue-400',
  'bg-green-500/20 text-green-400',
  'bg-orange-500/20 text-orange-400',
  'bg-pink-500/20 text-pink-400',
  'bg-cyan-500/20 text-cyan-400',
]

export default function TranscriptPanel() {
  const { segments, selectedSegmentId, setSelectedSegmentId, updateSegment, status, qcMode } = useProjectStore()
  const { requestSeek, currentTime } = usePlaybackStore()
  const selectedRef = useRef<HTMLDivElement>(null)

  const speakers = [...new Set(segments.map((s) => s.speaker_id))]
  const speakerColor = (id: string) => SPEAKER_COLORS[speakers.indexOf(id) % SPEAKER_COLORS.length]

  const visibleSegments = qcMode ? segments.filter((s) => s.qc_flagged) : segments
  const flaggedIds = segments.filter((s) => s.qc_flagged).map((s) => s.id)
  const currentFlaggedIdx = flaggedIds.indexOf(selectedSegmentId ?? -1)

  function navigateQc(dir: -1 | 1) {
    const next = flaggedIds[currentFlaggedIdx + dir]
    if (next !== undefined) {
      const seg = segments.find((s) => s.id === next)
      if (seg) { setSelectedSegmentId(seg.id); requestSeek(seg.start) }
    }
  }

  useEffect(() => {
    const active = segments.find((s) => currentTime >= s.start && currentTime <= s.end)
    if (active && active.id !== selectedSegmentId) setSelectedSegmentId(active.id)
  }, [currentTime, segments, selectedSegmentId, setSelectedSegmentId])

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedSegmentId])

  const handleClick = (segId: number, start: number) => {
    setSelectedSegmentId(segId)
    requestSeek(start)
  }

  if (segments.length === 0) {
    return (
      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="panel-header">Transcript</div>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-tb-border text-xs">
            {status === 'done' ? 'No segments found.' : 'Transcript will appear after processing.'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-hidden flex flex-col min-h-0">
      <div className="panel-header flex items-center justify-between">
        <span>Transcript</span>
        {qcMode ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => navigateQc(-1)}
              disabled={currentFlaggedIdx <= 0}
              className="btn-ghost p-0.5 disabled:opacity-30"
            >
              <ChevronLeft size={12} />
            </button>
            <span className="text-orange-400 font-mono text-xs">
              {currentFlaggedIdx >= 0 ? `${currentFlaggedIdx + 1}/` : ''}{flaggedIds.length}
            </span>
            <button
              onClick={() => navigateQc(1)}
              disabled={currentFlaggedIdx >= flaggedIds.length - 1}
              className="btn-ghost p-0.5 disabled:opacity-30"
            >
              <ChevronRight size={12} />
            </button>
          </div>
        ) : (
          <span className="text-tb-border font-mono normal-case tracking-normal">{segments.length} segs</span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {visibleSegments.map((seg) => {
          const selected = seg.id === selectedSegmentId
          return (
            <div
              key={seg.id}
              ref={selected ? selectedRef : null}
              onClick={() => handleClick(seg.id, seg.start)}
              className={`segment-row ${selected ? 'selected' : ''} ${seg.qc_flagged && qcMode ? 'border-l-2 border-orange-500/50' : ''}`}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <span className={`text-xs px-1.5 py-0.5 rounded font-mono font-medium ${speakerColor(seg.speaker_id)}`}>
                  {seg.speaker_id.replace('SPEAKER_', 'SP')}
                </span>
                <span className="text-tb-border text-xs font-mono">
                  {fmt(seg.start)} → {fmt(seg.end)}
                </span>
                {seg.emotion && seg.emotion !== 'neutral' && (
                  <span className={`text-xs px-1.5 py-0.5 rounded ${EMOTION_COLORS[seg.emotion] ?? EMOTION_COLORS.neutral}`}>
                    {seg.emotion}
                  </span>
                )}
                {seg.qc_flagged && !qcMode && (
                  <AlertTriangle size={10} className="text-orange-400 ml-auto" />
                )}
              </div>

              <p className="text-tb-muted text-sm leading-relaxed mb-1">{seg.source_text}</p>

              {seg.translated_text !== undefined && (
                <textarea
                  className="tb-input resize-none text-tb-text text-sm leading-relaxed"
                  rows={2}
                  value={seg.translated_text ?? ''}
                  onChange={(e) => updateSegment(seg.id, { translated_text: e.target.value })}
                  onClick={(e) => e.stopPropagation()}
                />
              )}

              {seg.delivery_direction && (
                <p className="text-tb-emotion text-xs italic mt-1 opacity-70">{seg.delivery_direction}</p>
              )}
            </div>
          )
        })}
        {qcMode && visibleSegments.length === 0 && (
          <div className="flex items-center justify-center h-16">
            <p className="text-green-400 text-xs">No QC issues found</p>
          </div>
        )}
      </div>
    </div>
  )
}
