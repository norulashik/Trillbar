import { useEffect, useRef, useState } from 'react'
import { Play, Pause, Square } from 'lucide-react'
import WaveSurfer from 'wavesurfer.js'
import { useProjectStore } from '../store/projectStore'
import { usePlaybackStore } from '../store/playbackStore'

function fmt(t: number) {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function ProgramMonitor() {
  const { outputUrl, status } = useProjectStore()
  const { isPlaying, setIsPlaying, currentTime, setCurrentTime, duration, setDuration, seekTo, clearSeek } = usePlaybackStore()

  const containerRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WaveSurfer | null>(null)
  const [ready, setReady] = useState(false)

  // Init WaveSurfer when output URL becomes available
  useEffect(() => {
    if (!containerRef.current || !outputUrl) return

    wsRef.current?.destroy()
    setReady(false)

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: '#4a4a5a',
      progressColor: '#a259ff',
      cursorColor: '#ffffff60',
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: 72,
      normalize: true,
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

  // Handle external seek requests (from transcript click)
  useEffect(() => {
    if (seekTo !== null && wsRef.current && ready) {
      wsRef.current.seekTo(seekTo / wsRef.current.getDuration())
      clearSeek()
    }
  }, [seekTo, ready, clearSeek])

  const togglePlay = () => {
    if (!wsRef.current || !ready) return
    wsRef.current.playPause()
  }

  const stop = () => {
    if (!wsRef.current || !ready) return
    wsRef.current.stop()
    setIsPlaying(false)
  }

  const done = status === 'done'

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="panel-header flex items-center justify-between">
        <span>Program Monitor</span>
        {ready && (
          <span className="text-tb-border font-mono text-xs normal-case tracking-normal">
            {fmt(currentTime)} / {fmt(duration)}
          </span>
        )}
      </div>

      <div className="flex-1 flex flex-col items-center justify-center p-4 gap-4">
        {/* Waveform */}
        <div
          ref={containerRef}
          className={`w-full rounded overflow-hidden transition-opacity ${ready ? 'opacity-100' : 'opacity-0'}`}
        />

        {!done && !ready && (
          <div className="text-center text-tb-muted text-xs space-y-2">
            <div className="w-10 h-10 rounded-full border border-tb-border flex items-center justify-center mx-auto">
              <Play size={16} className="text-tb-border" />
            </div>
            <p>Dubbed audio will appear here</p>
          </div>
        )}

        {/* Playback controls */}
        {ready && (
          <div className="flex items-center gap-2">
            <button onClick={stop} className="btn-ghost p-1.5">
              <Square size={12} />
            </button>
            <button
              onClick={togglePlay}
              className="w-8 h-8 rounded-full bg-tb-accent hover:bg-tb-accent-dim flex items-center justify-center transition-colors"
            >
              {isPlaying ? <Pause size={14} /> : <Play size={14} />}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
