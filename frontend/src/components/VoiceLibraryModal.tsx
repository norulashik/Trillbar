import { useEffect, useRef, useState } from 'react'
import { X, Trash2, Upload, Loader2, Mic } from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import type { VoiceEntry } from '../types'

interface Props {
  onClose: () => void
}

export default function VoiceLibraryModal({ onClose }: Props) {
  const { voiceLibrary, setVoiceLibrary } = useProjectStore()
  const [addName, setAddName] = useState('')
  const [addFiles, setAddFiles] = useState<File[]>([])
  const [cloning, setCloning] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setLoading(true)
    fetch('/api/voice-library')
      .then((r) => {
        if (!r.ok) throw new Error(`Server error ${r.status}`)
        return r.json()
      })
      .then((data: unknown) => {
        // Guard against API returning an error object instead of an array
        if (Array.isArray(data)) setVoiceLibrary(data as VoiceEntry[])
        else setVoiceLibrary([])
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load voice library')
        setVoiceLibrary([])
      })
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const addVoice = async () => {
    if (!addName.trim() || addFiles.length === 0 || cloning) return
    setCloning(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('name', addName.trim())
      addFiles.forEach((f) => fd.append('files', f))
      const res = await fetch('/api/voice-library', { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? 'Clone failed')
      }
      const voice = await res.json() as VoiceEntry
      setVoiceLibrary([voice, ...voiceLibrary])
      setAddName('')
      setAddFiles([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clone failed')
    } finally {
      setCloning(false)
    }
  }

  const deleteVoice = async (id: string) => {
    setDeleting(id)
    setError(null)
    try {
      const res = await fetch(`/api/voice-library/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Delete failed (${res.status})`)
      setVoiceLibrary(voiceLibrary.filter((v) => v.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-tb-panel border border-tb-border rounded-xl shadow-2xl flex flex-col"
        style={{ width: '480px', maxHeight: '80vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-tb-border">
          <div className="flex items-center gap-2">
            <Mic size={16} className="text-tb-accent" />
            <span className="text-sm font-semibold text-tb-text">Voice Library</span>
          </div>
          <button
            onClick={onClose}
            className="text-tb-muted hover:text-tb-text p-1 rounded hover:bg-white/10 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Add Voice form */}
        <div className="px-5 py-4 border-b border-tb-border flex flex-col gap-3 shrink-0">
          <p className="text-[10px] text-tb-muted font-semibold uppercase tracking-widest">Add Voice</p>
          <input
            type="text"
            placeholder="Voice name…"
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
            disabled={cloning}
            className="tb-input w-full"
          />
          <div className="flex items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept="audio/*,video/*"
              multiple
              className="hidden"
              onChange={(e) => setAddFiles(Array.from(e.target.files ?? []))}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={cloning}
              className="flex-1 flex items-center gap-1.5 text-xs rounded px-3 py-2 border border-tb-border text-tb-muted hover:text-tb-text hover:border-tb-accent/40 transition-colors disabled:opacity-40 truncate"
            >
              <Upload size={12} className="shrink-0" />
              <span className="truncate">
                {addFiles.length === 0
                  ? 'Choose audio / video…'
                  : addFiles.length === 1
                    ? addFiles[0].name
                    : `${addFiles.length} files selected`}
              </span>
            </button>
            <button
              onClick={addVoice}
              disabled={!addName.trim() || addFiles.length === 0 || cloning}
              className="btn-accent flex items-center gap-1.5 text-xs disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
              style={{ padding: '8px 14px' }}
            >
              {cloning ? <Loader2 size={12} className="animate-spin" /> : <Mic size={12} />}
              {cloning ? 'Cloning…' : 'Clone & Save'}
            </button>
          </div>
          {error && (
            <p className="text-xs text-red-400 bg-red-950/30 border border-red-500/20 rounded px-2 py-1">{error}</p>
          )}
        </div>

        {/* Voice list */}
        <div className="flex-1 overflow-y-auto px-5 py-3 flex flex-col gap-2 min-h-0">
          {loading && (
            <div className="flex items-center justify-center py-8 gap-2 text-tb-muted text-xs">
              <Loader2 size={14} className="animate-spin" />
              Loading voices…
            </div>
          )}
          {!loading && voiceLibrary.length === 0 && (
            <p className="text-xs text-tb-muted text-center py-6">
              No voices saved yet. Clone a voice above to get started.
            </p>
          )}
          {!loading && voiceLibrary.map((voice) => (
            <div
              key={voice.id}
              className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg border border-tb-border bg-tb-bg/40"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="w-7 h-7 rounded-full bg-tb-accent/15 flex items-center justify-center shrink-0">
                  <Mic size={13} className="text-tb-accent" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm text-tb-text truncate">{voice.name}</p>
                  <p className="text-[10px] text-tb-muted">
                    {new Date(voice.created_at * 1000).toLocaleDateString()}
                  </p>
                </div>
              </div>
              <button
                onClick={() => deleteVoice(voice.id)}
                disabled={deleting === voice.id}
                className="text-tb-muted hover:text-red-400 p-1.5 rounded hover:bg-red-500/10 transition-colors disabled:opacity-40 shrink-0"
              >
                {deleting === voice.id
                  ? <Loader2 size={14} className="animate-spin" />
                  : <Trash2 size={14} />
                }
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
