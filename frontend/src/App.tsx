import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { useJobSSE } from './hooks/useJobSSE'
import { useProjectStore } from './store/projectStore'
import TopBar from './components/TopBar'
import ProjectsHome from './components/ProjectsHome'
import UploadView from './components/UploadView'
import VideoPreviewPhase from './components/VideoPreviewPhase'
import VideoMonitor from './components/VideoMonitor'
import TranscriptPanel from './components/TranscriptPanel'
import VoiceControlsPanel from './components/VoiceControlsPanel'
import Timeline from './components/Timeline'
import StatusBar from './components/StatusBar'

export default function App() {
  useKeyboardShortcuts()
  const { jobId, uiPhase, currentProjectId } = useProjectStore()
  useJobSSE(jobId)

  if (!currentProjectId) {
    return <ProjectsHome />
  }

  const renderPhase = () => {
    switch (uiPhase) {
      case 'idle':
        return <UploadView />

      case 'video-preview':
      case 'analyzing':
      case 'analyzed':
        return <VideoPreviewPhase />

      case 'dubbing':
      case 'done':
      case 'error':
      default:
        return (
          <>
            <div className="flex-1 flex min-h-0 border-b border-tb-border">
              <div
                className="flex flex-col border-r border-tb-border overflow-hidden"
                style={{ width: '220px', minWidth: '180px' }}
              >
                <TranscriptPanel />
              </div>
              <div className="flex-1 overflow-hidden panel">
                <VideoMonitor />
              </div>
              <div
                className="border-l border-tb-border overflow-hidden"
                style={{ width: '220px', minWidth: '180px' }}
              >
                <VoiceControlsPanel />
              </div>
            </div>
            <Timeline />
          </>
        )
    }
  }

  return (
    <div className="h-screen flex flex-col bg-tb-bg text-tb-text overflow-hidden select-none">
      <TopBar />
      {renderPhase()}
      <StatusBar />
    </div>
  )
}
