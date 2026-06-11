import { useCallback, useRef, useState } from 'react'
import { Upload, FileVideo, FileAudio, X, Play } from 'lucide-react'
import { useProjectStore } from '../store/projectStore'

export default function UploadView() {
  const { setJobId, setUiPhase, reset, currentProjectName } = useProjectStore()

  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) setFile(f)
  }, [])

  const submit = () => {
    if (!file || submitting) return
    setSubmitting(true)
    setUploadProgress(0)
    setError(null)
    reset()

    const fd = new FormData()
    fd.append('file', file)

    const xhr = new XMLHttpRequest()

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) setUploadProgress(Math.round((e.loaded / e.total) * 100))
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const data = JSON.parse(xhr.responseText) as { job_id: string }
        setJobId(data.job_id)
        setUiPhase('video-preview')
      } else {
        let detail = `Server error ${xhr.status}`
        try { detail = (JSON.parse(xhr.responseText) as { detail?: string }).detail ?? detail } catch { /* ignore */ }
        setError(detail)
        setSubmitting(false)
      }
    }

    xhr.onerror = () => {
      setError('Upload failed — is the backend running on port 8005?')
      setSubmitting(false)
    }

    xhr.ontimeout = () => {
      setError('Upload timed out. Try a shorter clip (trim in the timeline after upload).')
      setSubmitting(false)
    }

    xhr.timeout = 300_000  // 5 minutes
    xhr.open('POST', '/api/upload')
    xhr.send(fd)
  }

  const isVideo = file?.type.startsWith('video/')

  return (
    <div className="flex-1 flex items-center justify-center bg-tb-bg overflow-hidden">
      <div className="flex flex-col items-center gap-5 w-full max-w-md px-8">

        {currentProjectName && (
          <div className="text-center">
            <p className="text-tb-text text-base font-semibold">{currentProjectName}</p>
            <p className="text-tb-muted text-xs mt-0.5">Drop a source file to begin</p>
          </div>
        )}

        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => !file && !submitting && inputRef.current?.click()}
          className={`w-full border-2 border-dashed rounded-xl transition-all ${
            dragging
              ? 'border-tb-accent bg-tb-accent/5 scale-[1.01]'
              : file
              ? 'border-tb-accent/40 bg-tb-accent/5 cursor-default'
              : 'border-tb-border hover:border-tb-accent/50 hover:bg-white/[0.02] cursor-pointer'
          }`}
          style={{ padding: file ? '16px 20px' : '40px 20px' }}
        >
          {file ? (
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                {isVideo
                  ? <FileVideo size={22} className="text-tb-accent shrink-0" />
                  : <FileAudio size={22} className="text-tb-accent shrink-0" />
                }
                <div className="text-left min-w-0">
                  <p className="text-tb-text text-sm font-medium truncate">{file.name}</p>
                  <p className="text-tb-muted text-xs mt-0.5">
                    {(file.size / (1024 * 1024)).toFixed(1)} MB · {isVideo ? 'Video' : 'Audio'}
                  </p>
                </div>
              </div>
              {!submitting && (
                <button
                  onClick={(e) => { e.stopPropagation(); setFile(null) }}
                  className="text-tb-muted hover:text-tb-text shrink-0 p-1 rounded hover:bg-white/10 transition-colors"
                >
                  <X size={15} />
                </button>
              )}
            </div>
          ) : (
            <div className="text-center">
              <Upload size={28} className="mx-auto mb-3 text-tb-muted" />
              <p className="text-tb-text text-sm font-medium mb-1">Drop your video or audio here</p>
              <p className="text-tb-muted text-xs">MP4, MKV, MOV, WAV, MP3 · or click to browse</p>
            </div>
          )}
          <input
            ref={inputRef}
            type="file"
            accept="video/*,audio/*"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
          />
        </div>

        {error && (
          <div className="w-full bg-red-950/40 border border-red-500/30 rounded-lg px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}

        <div className="w-full flex flex-col gap-2">
          <button
            onClick={submit}
            disabled={!file || submitting}
            className="w-full btn-accent flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ padding: '10px 0', fontSize: '13px' }}
          >
            <Play size={13} />
            {submitting
              ? uploadProgress < 100 ? `Uploading… ${uploadProgress}%` : 'Saving on server…'
              : 'Upload & Preview'}
          </button>

          {/* Upload progress bar */}
          {submitting && (
            <div className="w-full h-1 rounded-full bg-tb-border overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{
                  width: `${uploadProgress}%`,
                  background: uploadProgress < 100 ? '#a259ff' : '#4CAF50',
                }}
              />
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
