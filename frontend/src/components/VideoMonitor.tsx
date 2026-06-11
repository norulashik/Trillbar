import { useEffect, useRef, useState } from 'react'
import { Play, Pause, Square, Volume2, VolumeX, Loader2 } from 'lucide-react'
import WaveSurfer from 'wavesurfer.js'
import { useProjectStore } from '../store/projectStore'
import { usePlaybackStore } from '../store/playbackStore'

const PIPELINE_STEPS = ['Transcribe', 'Translate', 'Synthesize', 'Mix']
const STEP_STAGES: Record<string, number> = {
  analyzing: 0, analyzed: 0,
  transcribing: 0,
  translating: 1,
  synthesizing: 2,
  assembling: 3, mixing: 3,
  done: 4,
}

function fmt(t: number) {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

// ── Audio-only mode (WaveSurfer) ──────────────────────────────────────────────

function WaveformPlayer({ outputUrl }: { outputUrl: string }) {
  const { isPlaying, setIsPlaying, setCurrentTime, setDuration, seekTo, clearSeek } = usePlaybackStore()
  const containerRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WaveSurfer | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    wsRef.current?.destroy()
    setReady(false)
    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: '#4a4a5a', progressColor: '#a259ff',
      cursorColor: '#ffffff60', barWidth: 2, barGap: 1, barRadius: 2,
      height: 72, normalize: true,
    })
    ws.load(outputUrl)
    ws.on('ready', () => { setReady(true); setDuration(ws.getDuration()) })
    ws.on('timeupdate', (t) => setCurrentTime(t))
    ws.on('play', () => setIsPlaying(true))
    ws.on('pause', () => setIsPlaying(false))
    ws.on('finish', () => setIsPlaying(false))
    wsRef.current = ws
    return () => { ws.destroy(); wsRef.current = null }
  }, [outputUrl, setCurrentTime, setDuration, setIsPlaying])

  useEffect(() => {
    if (seekTo !== null && wsRef.current && ready) {
      wsRef.current.seekTo(seekTo / wsRef.current.getDuration())
      clearSeek()
    }
  }, [seekTo, ready, clearSeek])

  return (
    <div className="flex flex-col items-center gap-4 w-full">
      <div ref={containerRef} className={`w-full rounded overflow-hidden transition-opacity ${ready ? 'opacity-100' : 'opacity-0'}`} />
      {ready && (
        <div className="flex items-center gap-2">
          <button onClick={() => { wsRef.current?.stop(); setIsPlaying(false) }} className="btn-ghost p-1.5">
            <Square size={12} />
          </button>
          <button
            onClick={() => wsRef.current?.playPause()}
            className="w-8 h-8 rounded-full bg-tb-accent hover:bg-tb-accent-dim flex items-center justify-center transition-colors"
          >
            {isPlaying ? <Pause size={14} /> : <Play size={14} />}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Video mode ────────────────────────────────────────────────────────────────

function VideoPlayer({ jobId, lipSyncUrl }: { jobId: string; previewUrl: string; lipSyncUrl: string | null }) {
  const { isPlaying, setIsPlaying, setCurrentTime, setDuration, seekTo, clearSeek, activeTrack, setActiveTrack } = usePlaybackStore()
  const videoRef = useRef<HTMLVideoElement>(null)
  const [muted, setMuted] = useState(false)
  const seekingRef = useRef(false)

  // Sync video timeupdate → store
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const onTime = () => { if (!seekingRef.current) setCurrentTime(video.currentTime) }
    const onDuration = () => setDuration(video.duration || 0)
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)
    const onEnded = () => setIsPlaying(false)
    video.addEventListener('timeupdate', onTime)
    video.addEventListener('loadedmetadata', onDuration)
    video.addEventListener('durationchange', onDuration)
    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)
    video.addEventListener('ended', onEnded)
    return () => {
      video.removeEventListener('timeupdate', onTime)
      video.removeEventListener('loadedmetadata', onDuration)
      video.removeEventListener('durationchange', onDuration)
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
      video.removeEventListener('ended', onEnded)
    }
  }, [setCurrentTime, setDuration, setIsPlaying])

  // Handle external seek requests (from transcript / timeline click)
  useEffect(() => {
    if (seekTo !== null && videoRef.current) {
      seekingRef.current = true
      videoRef.current.currentTime = seekTo
      setTimeout(() => { seekingRef.current = false }, 100)
      clearSeek()
    }
  }, [seekTo, clearSeek])

  // Toggle play/pause from store changes driven by transport buttons
  const togglePlay = () => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) { video.play().catch(() => {}) } else { video.pause() }
  }

  const stop = () => {
    const video = videoRef.current
    if (!video) return
    video.pause()
    video.currentTime = 0
    setIsPlaying(false)
  }

  // 'lipsync' track only available when lipSyncUrl is set
  const srcForTrack =
    activeTrack === 'lipsync' && lipSyncUrl
      ? lipSyncUrl
      : activeTrack === 'dubbed'
      ? `/api/preview/${jobId}`
      : `/api/video/${jobId}`

  const tracks = [
    { id: 'dubbed' as const, label: 'Dubbed' },
    { id: 'original' as const, label: 'Original' },
    ...(lipSyncUrl ? [{ id: 'lipsync' as const, label: '✦ Synced' }] : []),
  ]

  return (
    <div className="flex flex-col items-center gap-2 w-full">
      {/* Video frame */}
      <div className="w-full bg-black rounded overflow-hidden" style={{ aspectRatio: '16/9', maxHeight: '240px' }}>
        <video
          ref={videoRef}
          src={srcForTrack}
          muted={muted}
          className="w-full h-full object-contain"
          preload="metadata"
        />
      </div>

      {/* Transport controls */}
      <div className="flex items-center gap-3 w-full justify-center">
        <button onClick={stop} className="btn-ghost p-1.5"><Square size={12} /></button>
        <button
          onClick={togglePlay}
          className="w-8 h-8 rounded-full bg-tb-accent hover:bg-tb-accent-dim flex items-center justify-center transition-colors"
        >
          {isPlaying ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <button onClick={() => setMuted(!muted)} className="btn-ghost p-1.5">
          {muted ? <VolumeX size={12} /> : <Volume2 size={12} />}
        </button>

        {/* Track toggle */}
        <div className="flex gap-1 ml-2">
          {tracks.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTrack(t.id)}
              className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                activeTrack === t.id
                  ? t.id === 'lipsync'
                    ? 'bg-green-500/20 border-green-500/40 text-green-400'
                    : 'bg-tb-accent/20 border-tb-accent/40 text-tb-accent'
                  : 'border-tb-border text-tb-muted hover:text-tb-text'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function VideoMonitor() {
  const { outputUrl, status, stage, progress, isVideo, previewUrl, jobId, lipSyncStatus, lipSyncUrl } = useProjectStore()
  const { currentTime, duration } = usePlaybackStore()

  const done = status === 'done'
  const isProcessing = !done && status !== '' && status !== 'error'

  const activeStep = STEP_STAGES[stage?.toLowerCase() ?? ''] ?? (isProcessing ? 0 : -1)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="panel-header flex items-center justify-between">
        <span>Program Monitor</span>
        <div className="flex items-center gap-2">
          {lipSyncStatus === 'processing' && (
            <span className="text-[10px] text-tb-accent animate-pulse">Lip sync processing...</span>
          )}
          {lipSyncStatus === 'done' && (
            <span className="text-[10px] text-green-400">✦ Lip sync ready</span>
          )}
          {duration > 0 && (
            <span className="text-tb-border font-mono text-xs normal-case tracking-normal">
              {fmt(currentTime)} / {fmt(duration)}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center p-4 gap-4 overflow-hidden">
        {done && isVideo && previewUrl && jobId ? (
          <VideoPlayer jobId={jobId} previewUrl={previewUrl} lipSyncUrl={lipSyncUrl} />
        ) : done && outputUrl ? (
          <WaveformPlayer outputUrl={outputUrl} />
        ) : isProcessing ? (
          <div className="flex flex-col items-center gap-5 w-full max-w-xs">
            <Loader2 size={28} className="text-tb-accent animate-spin" />
            <div className="text-tb-text text-sm font-medium capitalize">
              {stage || status}
            </div>
            <div className="w-full h-1 bg-tb-border rounded overflow-hidden">
              <div
                className="h-full bg-tb-accent transition-all duration-500 rounded"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="flex items-center gap-3">
              {PIPELINE_STEPS.map((step, i) => (
                <div key={step} className="flex items-center gap-3">
                  {i > 0 && <div className="w-4 h-px bg-tb-border" />}
                  <span
                    className="text-[10px] transition-colors"
                    style={{
                      color: i < activeStep ? '#3dba7a'
                           : i === activeStep ? '#a259ff'
                           : undefined,
                    }}
                  >
                    {i < activeStep ? '✓ ' : ''}{step}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
