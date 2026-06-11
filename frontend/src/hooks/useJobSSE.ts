import { useEffect } from 'react'
import { useProjectStore } from '../store/projectStore'

export function useJobSSE(jobId: string | null) {
  const { setJobState, setUiPhase, setSegments, setOutputUrl, setIsVideo, setPreviewUrl } = useProjectStore()

  useEffect(() => {
    if (!jobId) return

    const es = new EventSource(`/api/events/${jobId}`)

    es.onmessage = async (e: MessageEvent) => {
      const data = JSON.parse(e.data as string) as {
        heartbeat?: boolean
        status?: string
        stage?: string
        progress?: number
        error?: string | null
      }

      if (data.heartbeat) return

      setJobState({
        status: data.status ?? '',
        stage: data.stage ?? '',
        progress: data.progress ?? 0,
        error: data.error ?? null,
      })

      if (data.status === 'analyzing') {
        setUiPhase('analyzing')
      }

      if (data.status === 'analyzed') {
        try {
          const res = await fetch(`/api/transcript/${jobId}`)
          if (res.ok) {
            const json = await res.json() as { segments: unknown[] }
            setSegments(json.segments as Parameters<typeof setSegments>[0])
          }
        } catch { /* best-effort */ }
        setUiPhase('analyzed')
        // keep SSE open — dubbing will continue on the same job
      }

      if (data.status === 'dubbing') {
        setUiPhase('dubbing')
      }

      if (data.status === 'done') {
        try {
          const statusRes = await fetch(`/api/status/${jobId}`)
          if (statusRes.ok) {
            const statusJson = await statusRes.json() as { is_video?: boolean; preview_url?: string | null }
            setIsVideo(statusJson.is_video ?? false)
            setPreviewUrl(statusJson.preview_url ?? null)
          }
        } catch { /* non-critical */ }

        try {
          const res = await fetch(`/api/transcript/${jobId}`)
          if (res.ok) {
            const json = await res.json() as { segments: unknown[] }
            setSegments(json.segments as Parameters<typeof setSegments>[0])
          }
        } catch { /* best-effort */ }

        setOutputUrl(`/api/download/${jobId}`)
        setUiPhase('done')
        es.close()
      }

      if (data.status === 'error') {
        setUiPhase('error')
        es.close()
      }
    }

    es.onerror = () => es.close()

    return () => es.close()
  }, [jobId, setJobState, setUiPhase, setSegments, setOutputUrl, setIsVideo, setPreviewUrl])
}
