import { Settings, Download, Zap, ShieldAlert, Sparkles, Loader2, ChevronLeft } from 'lucide-react'
import { useState, useEffect, useCallback } from 'react'
import { useProjectStore } from '../store/projectStore'
import SettingsModal from './SettingsModal'

const MODE_LABELS: Record<string, string> = {
  translation: 'Translation Dubbing',
  voice:       'Voice Mode',
}

export default function TopBar() {
  const {
    mode, outputUrl, segments, qcMode, setQcMode,
    jobId, status, isVideo, previewUrl,
    lipSyncStatus, setLipSyncStatus, setLipSyncUrl,
    currentProjectName, closeProject,
  } = useProjectStore()
  const [showSettings, setShowSettings] = useState(false)
  const qcCount = segments.filter((s) => s.qc_flagged).length
  const canLipSync = status === 'done' && isVideo && !!jobId

  const handleSyncAi = useCallback(async () => {
    if (!jobId || lipSyncStatus === 'submitted' || lipSyncStatus === 'processing') return
    setLipSyncStatus('submitted')
    try {
      const res = await fetch(`/api/lipsync/${jobId}`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      setLipSyncStatus('processing')
    } catch (e: unknown) {
      setLipSyncStatus('failed')
      alert(`Sync AI failed: ${e instanceof Error ? e.message : e}`)
    }
  }, [jobId, lipSyncStatus, setLipSyncStatus])

  useEffect(() => {
    if (lipSyncStatus !== 'processing' || !jobId) return
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/lipsync/${jobId}/status`)
        const data = await res.json() as { status: string; lipsync_url?: string }
        if (data.status === 'done') {
          setLipSyncStatus('done')
          setLipSyncUrl(data.lipsync_url ?? null)
          clearInterval(interval)
        } else if (data.status === 'failed') {
          setLipSyncStatus('failed')
          clearInterval(interval)
        }
      } catch { /* ignore transient fetch errors */ }
    }, 5000)
    return () => clearInterval(interval)
  }, [lipSyncStatus, jobId, setLipSyncStatus, setLipSyncUrl])

  return (
    <>
      <div className="h-10 bg-tb-header border-b border-tb-border flex items-center px-3 gap-3 shrink-0 select-none">
        {/* Back to projects */}
        <button
          onClick={closeProject}
          className="flex items-center gap-1 text-tb-muted hover:text-tb-text transition-colors text-xs"
          title="Back to Projects"
        >
          <ChevronLeft size={14} />
          <Zap size={13} className="text-tb-accent" />
          <span className="font-semibold text-tb-accent tracking-tight">TrillBar</span>
        </button>

        <div className="w-px h-4 bg-tb-border" />

        {/* Project name + mode */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-tb-text text-xs font-medium truncate max-w-[160px]">
            {currentProjectName || 'Project'}
          </span>
          <span className="text-xs text-tb-muted bg-tb-border/30 px-1.5 py-0.5 rounded shrink-0">
            {MODE_LABELS[mode] ?? mode}
          </span>
        </div>

        <div className="flex-1" />

        {/* Actions */}
        {qcCount > 0 && (
          <button
            onClick={() => setQcMode(!qcMode)}
            className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors ${
              qcMode
                ? 'bg-orange-500/20 border border-orange-500/40 text-orange-400'
                : 'btn-ghost border border-tb-border text-tb-muted hover:text-tb-text'
            }`}
          >
            <ShieldAlert size={12} />
            QC Mode
            <span className={`text-[10px] px-1 rounded ${qcMode ? 'bg-orange-500/30' : 'bg-tb-border'}`}>
              {qcCount}
            </span>
          </button>
        )}
        {canLipSync && (
          <button
            onClick={handleSyncAi}
            disabled={lipSyncStatus === 'submitted' || lipSyncStatus === 'processing'}
            title={
              lipSyncStatus === 'done'    ? 'Lip sync done — video loaded in monitor'
              : lipSyncStatus === 'failed'  ? 'Lip sync failed — click to retry'
              : lipSyncStatus === 'processing' ? 'Processing lip sync...'
              : 'AI Lip Sync via SyncLabs'
            }
            className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors ${
              lipSyncStatus === 'done'
                ? 'bg-green-500/20 border border-green-500/40 text-green-400'
                : lipSyncStatus === 'failed'
                ? 'bg-red-500/20 border border-red-500/40 text-red-400'
                : lipSyncStatus === 'processing' || lipSyncStatus === 'submitted'
                ? 'bg-tb-accent/10 border border-tb-accent/30 text-tb-accent'
                : 'btn-ghost border border-tb-border text-tb-muted hover:text-tb-text'
            }`}
          >
            {lipSyncStatus === 'processing' || lipSyncStatus === 'submitted'
              ? <Loader2 size={12} className="animate-spin" />
              : <Sparkles size={12} />
            }
            {lipSyncStatus === 'done' ? 'Synced' : lipSyncStatus === 'failed' ? 'Retry Sync' : 'Sync AI'}
          </button>
        )}
        {isVideo && previewUrl && status === 'done' && jobId && (
          <a
            href={`/api/export/mp4/${jobId}`}
            download
            className="btn-ghost border border-tb-border text-tb-muted hover:text-tb-text flex items-center gap-1.5 px-2 py-1 rounded text-xs"
          >
            <Download size={12} />
            Export MP4
          </a>
        )}
        {segments.length > 0 && status === 'done' && jobId && (
          <a
            href={`/api/export/srt/${jobId}`}
            download
            className="btn-ghost border border-tb-border text-tb-muted hover:text-tb-text flex items-center gap-1.5 px-2 py-1 rounded text-xs"
          >
            <Download size={12} />
            Export SRT
          </a>
        )}
        {outputUrl && (
          <a
            href={outputUrl}
            download
            className="btn-accent flex items-center gap-1.5"
          >
            <Download size={12} />
            Export WAV
          </a>
        )}
        <button onClick={() => setShowSettings(true)} className="btn-ghost p-1.5">
          <Settings size={14} />
        </button>
      </div>

      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </>
  )
}
