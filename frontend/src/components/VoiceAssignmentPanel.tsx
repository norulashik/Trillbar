import { useEffect, useRef, useState } from 'react'
import { Mic, Upload, CheckCircle, Loader2, Play } from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import type { VoiceEntry } from '../types'

interface Props {
  jobId: string
}

interface Speaker {
  id: string
  totalSeconds: number
  segmentCount: number
}

export default function VoiceAssignmentPanel({ jobId }: Props) {
  const {
    segments, voiceLibrary, setVoiceLibrary,
    speakerVoiceAssignments, setSpeakerVoiceAssignment,
    setUiPhase, setJobState,
  } = useProjectStore()

  const [cloning, setCloning] = useState<Record<string, boolean>>({})
  const [cloneNames, setCloneNames] = useState<Record<string, string>>({})
  const [cloneFileList, setCloneFileList] = useState<Record<string, File[]>>({})
  const [dialogueFiles, setDialogueFiles] = useState<Record<string, File>>({})
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dialogueRefs = useRef<Record<string, HTMLInputElement | null>>({})

  // Derive unique speakers from segments
  const speakers: Speaker[] = Object.values(
    segments.reduce<Record<string, Speaker>>((acc, seg) => {
      if (!acc[seg.speaker_id]) {
        acc[seg.speaker_id] = { id: seg.speaker_id, totalSeconds: 0, segmentCount: 0 }
      }
      acc[seg.speaker_id].totalSeconds += (seg.end - seg.start)
      acc[seg.speaker_id].segmentCount += 1
      return acc
    }, {})
  )

  // Fetch voice library on mount
  useEffect(() => {
    fetch('/api/voice-library')
      .then((r) => r.json())
      .then((data: unknown) => { if (Array.isArray(data)) setVoiceLibrary(data as VoiceEntry[]) })
      .catch(() => {})
  }, [setVoiceLibrary])

  const cloneFromJob = async (speakerId: string) => {
    const name = cloneNames[speakerId]?.trim()
    if (!name) return
    setCloning((c) => ({ ...c, [speakerId]: true }))
    try {
      const fd = new FormData()
      fd.append('name', name)
      fd.append('job_id', jobId)
      fd.append('speaker_id', speakerId)
      const res = await fetch('/api/voice-library', { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? 'Clone failed')
      }
      const voice = await res.json() as VoiceEntry
      setVoiceLibrary([voice, ...voiceLibrary])
      setSpeakerVoiceAssignment(speakerId, voice.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clone failed')
    } finally {
      setCloning((c) => ({ ...c, [speakerId]: false }))
    }
  }

  const cloneFromFiles = async (speakerId: string, selectedFiles: File[]) => {
    const name = cloneNames[speakerId]?.trim()
    if (!name || selectedFiles.length === 0) return
    setCloning((c) => ({ ...c, [speakerId]: true }))
    try {
      const fd = new FormData()
      fd.append('name', name)
      selectedFiles.forEach((f) => fd.append('files', f))
      const res = await fetch('/api/voice-library', { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? 'Clone failed')
      }
      const voice = await res.json() as VoiceEntry
      setVoiceLibrary([voice, ...voiceLibrary])
      setSpeakerVoiceAssignment(speakerId, voice.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clone failed')
    } finally {
      setCloning((c) => ({ ...c, [speakerId]: false }))
    }
  }

  const allAssigned = speakers.every(
    (sp) => speakerVoiceAssignments[sp.id] && dialogueFiles[sp.id]
  )

  const startVoiceDub = async () => {
    if (!allAssigned || submitting) return
    setSubmitting(true)
    setError(null)

    try {
      const fd = new FormData()
      const assignments: Record<string, string> = {}
      speakers.forEach((sp) => {
        assignments[sp.id] = speakerVoiceAssignments[sp.id]
        const file = dialogueFiles[sp.id]
        const ext = file.name.substring(file.name.lastIndexOf('.'))
        fd.append('dialogue_files', new File([file], `${sp.id}${ext}`, { type: file.type }))
      })
      fd.append('speaker_assignments', JSON.stringify(assignments))
      const res = await fetch(`/api/voice-dub/${jobId}`, { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? 'Voice dub failed to start')
      }
      setUiPhase('dubbing')
      setJobState({ status: 'dubbing', stage: 'Starting voice dub…', progress: 0 })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start voice dub')
      setSubmitting(false)
    }
  }

  if (speakers.length === 0) {
    return (
      <div className="text-xs text-tb-muted text-center py-4">
        No speakers detected in analysis.
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {speakers.map((sp) => {
        const assignedVoice = voiceLibrary.find((v) => v.id === speakerVoiceAssignments[sp.id])
        const isCloningThis = cloning[sp.id]
        const enoughAudio = sp.totalSeconds >= 5

        return (
          <div
            key={sp.id}
            className="border border-tb-border rounded-lg p-3 flex flex-col gap-2.5 bg-tb-bg/50"
          >
            {/* Speaker header */}
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-tb-accent shrink-0" />
              <span className="text-sm font-medium text-tb-text">{sp.id}</span>
              <span className="text-xs text-tb-muted ml-auto">
                {Math.round(sp.totalSeconds)}s · {sp.segmentCount} segments
              </span>
            </div>

            {/* Clone section */}
            <div className="flex flex-col gap-1.5">
              <p className="text-xs text-tb-muted font-medium">Clone voice</p>
              <input
                type="text"
                placeholder="Voice name…"
                value={cloneNames[sp.id] ?? ''}
                onChange={(e) => setCloneNames((n) => ({ ...n, [sp.id]: e.target.value }))}
                className="tb-input w-full text-xs"
              />
              {enoughAudio ? (
                <button
                  onClick={() => cloneFromJob(sp.id)}
                  disabled={isCloningThis || !cloneNames[sp.id]?.trim()}
                  className="flex items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 bg-tb-accent/10 border border-tb-accent/30 text-tb-accent hover:bg-tb-accent/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {isCloningThis ? <Loader2 size={11} className="animate-spin" /> : <Mic size={11} />}
                  {isCloningThis ? 'Cloning…' : 'Clone from video audio'}
                </button>
              ) : (
                <>
                  <p className="text-[10px] text-tb-muted">Not enough audio — upload reference files</p>
                  <input
                    type="file"
                    accept="audio/*,video/*"
                    multiple
                    className="hidden"
                    ref={(el) => { dialogueRefs.current[`clone-${sp.id}`] = el }}
                    onChange={(e) => {
                      const selected = Array.from(e.target.files ?? [])
                      if (selected.length > 0) {
                        setCloneFileList((fl) => ({ ...fl, [sp.id]: selected }))
                        cloneFromFiles(sp.id, selected)
                      }
                    }}
                  />
                  <button
                    onClick={() => dialogueRefs.current[`clone-${sp.id}`]?.click()}
                    disabled={isCloningThis || !cloneNames[sp.id]?.trim()}
                    className="flex items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 bg-tb-accent/10 border border-tb-accent/30 text-tb-accent hover:bg-tb-accent/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {isCloningThis ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
                    {isCloningThis
                      ? `Cloning${cloneFileList[sp.id]?.length > 1 ? ` (${cloneFileList[sp.id].length} files)` : ''}…`
                      : cloneFileList[sp.id]?.length
                        ? `Re-select files (${cloneFileList[sp.id].length} selected)`
                        : 'Upload & Clone'}
                  </button>
                </>
              )}
              {assignedVoice && (
                <div className="flex items-center gap-1.5 text-xs text-green-400">
                  <CheckCircle size={11} />
                  Cloned: {assignedVoice.name}
                </div>
              )}
            </div>

            {/* Voice picker */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-tb-muted font-medium">Use voice</label>
              <select
                value={speakerVoiceAssignments[sp.id] ?? ''}
                onChange={(e) => setSpeakerVoiceAssignment(sp.id, e.target.value)}
                className="tb-input w-full text-xs"
              >
                <option value="">Select library voice…</option>
                {voiceLibrary.map((v) => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
            </div>

            {/* Dialogue upload */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-tb-muted font-medium">Dialogue audio</label>
              <input
                type="file"
                accept="audio/*"
                className="hidden"
                ref={(el) => { dialogueRefs.current[sp.id] = el }}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) setDialogueFiles((d) => ({ ...d, [sp.id]: f }))
                }}
              />
              <button
                onClick={() => dialogueRefs.current[sp.id]?.click()}
                className="flex items-center gap-1.5 text-xs rounded px-2 py-1.5 border border-tb-border text-tb-muted hover:text-tb-text hover:border-tb-accent/40 transition-colors"
              >
                <Upload size={11} />
                {dialogueFiles[sp.id] ? dialogueFiles[sp.id].name : 'Upload dialogue WAV/MP3'}
              </button>
            </div>
          </div>
        )
      })}

      {error && (
        <div className="bg-red-950/40 border border-red-500/30 rounded-lg px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      <button
        onClick={startVoiceDub}
        disabled={!allAssigned || submitting}
        className="btn-accent flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
        style={{ padding: '9px 0', fontSize: '13px' }}
      >
        <Play size={13} />
        {submitting ? 'Starting…' : 'Start Voice Dub'}
      </button>
    </div>
  )
}
