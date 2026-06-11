import { useProjectStore } from '../store/projectStore'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

const STAGE_LABELS: Record<string, string> = {
  queued:       'Queued',
  running:      'Processing',
  analyzing:    'Analyzing',
  analyzed:     'Analysis complete',
  synthesizing: 'Synthesizing voices',
  done:         'Complete',
  error:        'Error',
}

export default function StatusBar() {
  const { status, stage, progress, error } = useProjectStore()

  if (!status) {
    return (
      <div className="h-7 border-t border-tb-border bg-tb-header flex items-center px-3">
        <span className="text-tb-border text-xs">Ready — upload a file to begin.</span>
      </div>
    )
  }

  const isError = status === 'error'
  const isDone = status === 'done'
  const isRunning = !isError && !isDone

  return (
    <div className={`h-7 border-t shrink-0 flex items-center px-3 gap-3 text-xs ${
      isError ? 'border-red-500/30 bg-red-950/20' :
      isDone  ? 'border-green-500/30 bg-green-950/20' :
                'border-tb-border bg-tb-header'
    }`}>
      {/* Status icon */}
      {isRunning && <Loader2 size={12} className="text-tb-accent animate-spin shrink-0" />}
      {isDone    && <CheckCircle2 size={12} className="text-green-400 shrink-0" />}
      {isError   && <AlertCircle size={12} className="text-red-400 shrink-0" />}

      {/* Stage name */}
      <span className={`${isError ? 'text-red-400' : isDone ? 'text-green-400' : 'text-tb-text'}`}>
        {isError ? (error ?? 'An error occurred') : isDone ? 'Dubbing complete!' : (stage || STAGE_LABELS[status] || status)}
      </span>

      {/* Progress bar */}
      {isRunning && (
        <>
          <div className="flex-1 h-1 bg-tb-border rounded overflow-hidden">
            <div
              className="h-full bg-tb-accent transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-tb-muted font-mono tabular-nums w-8 text-right">{progress}%</span>
        </>
      )}
    </div>
  )
}
