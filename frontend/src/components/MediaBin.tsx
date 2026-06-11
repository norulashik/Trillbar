import { useCallback, useRef, useState } from 'react'
import { Upload, FileAudio, X, Play } from 'lucide-react'
import { useProjectStore } from '../store/projectStore'

const LANGUAGES = ['hindi', 'tamil', 'telugu']

export default function MediaBin() {
  const {
    jobId, setJobId, targetLanguage, setTargetLanguage,
    skipSeparation, setSkipSeparation, skipProsody, setSkipProsody,
    status, reset,
  } = useProjectStore()

  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const isRunning = ['queued', 'running', 'analyzing'].includes(status)

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) setFile(f)
  }, [])

  const submit = async () => {
    if (!file) return
    reset()

    const fd = new FormData()
    fd.append('file', file)
    fd.append('target_language', targetLanguage)
    fd.append('skip_separation', String(skipSeparation))
    fd.append('skip_prosody', String(skipProsody))
    fd.append('skip_acoustic', 'false')

    try {
      const res = await fetch('/api/dub', { method: 'POST', body: fd })
      const data = await res.json() as { job_id: string }
      setJobId(data.job_id)
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="panel-header">Media Bin</div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">

        {/* Drop zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors ${
            dragging ? 'border-tb-accent bg-tb-accent/5' : 'border-tb-border hover:border-tb-accent/40'
          }`}
        >
          <Upload size={20} className="mx-auto mb-2 text-tb-muted" />
          <p className="text-xs text-tb-muted">Drop video or audio</p>
          <p className="text-xs text-tb-border mt-0.5">MP4, MKV, WAV, MP3</p>
          <input
            ref={inputRef}
            type="file"
            accept="video/*,audio/*"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
          />
        </div>

        {/* Selected file */}
        {file && (
          <div className="flex items-center gap-2 bg-tb-bg border border-tb-border rounded px-2 py-1.5">
            <FileAudio size={13} className="text-tb-accent shrink-0" />
            <span className="flex-1 text-xs truncate text-tb-text">{file.name}</span>
            <button onClick={() => setFile(null)} className="text-tb-muted hover:text-tb-text">
              <X size={12} />
            </button>
          </div>
        )}

        {/* Settings */}
        <div className="space-y-2">
          <label className="block text-xs text-tb-muted">Target Language</label>
          <select
            value={targetLanguage}
            onChange={(e) => setTargetLanguage(e.target.value)}
            className="tb-input capitalize"
          >
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>
            ))}
          </select>
        </div>

        <div className="space-y-1.5">
          <label className="flex items-center gap-2 cursor-pointer text-xs text-tb-muted">
            <input
              type="checkbox"
              checked={skipSeparation}
              onChange={(e) => setSkipSeparation(e.target.checked)}
              className="accent-tb-accent"
            />
            Skip vocal isolation (faster)
          </label>
          <label className="flex items-center gap-2 cursor-pointer text-xs text-tb-muted">
            <input
              type="checkbox"
              checked={skipProsody}
              onChange={(e) => setSkipProsody(e.target.checked)}
              className="accent-tb-accent"
            />
            Skip prosody transfer
          </label>
        </div>

        <button
          onClick={submit}
          disabled={!file || isRunning}
          className="w-full btn-accent flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Play size={12} />
          {isRunning ? 'Processing…' : 'Start Dubbing'}
        </button>

        {/* Job ID */}
        {jobId && (
          <div className="text-tb-border text-xs font-mono truncate">
            job: {jobId}
          </div>
        )}
      </div>
    </div>
  )
}
