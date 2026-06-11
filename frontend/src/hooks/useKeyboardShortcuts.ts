import { useEffect } from 'react'
import { useProjectStore } from '../store/projectStore'
import { usePlaybackStore } from '../store/playbackStore'

export function useKeyboardShortcuts() {
  const { segments, selectedSegmentId, setSelectedSegmentId, clips, setClip } = useProjectStore()
  const { isPlaying, setIsPlaying, currentTime, requestSeek } = usePlaybackStore()

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      // Never intercept when typing in an input or textarea
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.metaKey || e.ctrlKey || e.altKey) return

      switch (e.code) {
        case 'Space': {
          e.preventDefault()
          setIsPlaying(!isPlaying)
          break
        }
        case 'KeyK': {
          e.preventDefault()
          setIsPlaying(false)
          requestSeek(0)
          break
        }
        case 'KeyJ': {
          e.preventDefault()
          requestSeek(Math.max(0, currentTime - 5))
          break
        }
        case 'KeyL': {
          e.preventDefault()
          requestSeek(currentTime + 5)
          break
        }
        case 'ArrowLeft': {
          e.preventDefault()
          const idx = segments.findIndex((s) => s.id === selectedSegmentId)
          const prev = segments[idx - 1]
          if (prev) { setSelectedSegmentId(prev.id); requestSeek(prev.start) }
          break
        }
        case 'ArrowRight': {
          e.preventDefault()
          const idx = segments.findIndex((s) => s.id === selectedSegmentId)
          const next = segments[idx + 1]
          if (next) { setSelectedSegmentId(next.id); requestSeek(next.start) }
          break
        }
        case 'KeyM': {
          e.preventDefault()
          if (selectedSegmentId !== null) {
            const current = clips[selectedSegmentId]?.muted ?? false
            setClip(selectedSegmentId, { muted: !current })
          }
          break
        }
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isPlaying, currentTime, segments, selectedSegmentId, clips, setIsPlaying, requestSeek, setSelectedSegmentId, setClip])
}
