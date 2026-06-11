import { useState } from 'react'
import { Zap, Plus, Folder, Trash2, ChevronRight, Languages, Mic, Settings, Library } from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import type { AppMode } from '../types'
import SettingsModal from './SettingsModal'
import VoiceLibraryModal from './VoiceLibraryModal'

const MODES: { id: AppMode; label: string; sublabel: string; icon: React.ReactNode }[] = [
  {
    id: 'translation',
    label: 'Translation Dubbing',
    sublabel: 'Transcribe, translate & synthesize with a cloned voice',
    icon: <Languages size={20} />,
  },
  {
    id: 'voice',
    label: 'Voice Mode',
    sublabel: 'Assign library voices to each speaker, dub with your dialogue',
    icon: <Mic size={20} />,
  },
]

const MODE_LABELS: Record<AppMode, string> = {
  translation: 'Translation',
  voice: 'Voice Mode',
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'Just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function statusColor(status: string) {
  if (status === 'done') return 'text-green-400'
  if (status === 'error') return 'text-red-400'
  if (status === '' || !status) return 'text-tb-border'
  return 'text-tb-accent'
}

function statusLabel(status: string) {
  if (status === 'done') return '✓ Done'
  if (status === 'error') return '✗ Error'
  if (status === '' || !status) return '— Idle'
  return '↻ Processing'
}

function NewProjectModal({ onClose, languages }: { onClose: () => void; languages: string[] }) {
  const { createProject } = useProjectStore()
  const [name, setName] = useState('')
  const [mode, setMode] = useState<AppMode>('translation')
  const [lang, setLang] = useState('hindi')

  const handleCreate = () => {
    createProject(name.trim() || 'Untitled Project', mode, lang)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div
        className="bg-tb-panel border border-tb-border rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 pt-5 pb-4 border-b border-tb-border">
          <h2 className="text-tb-text font-semibold text-sm">New Project</h2>
        </div>

        <div className="px-5 py-4 space-y-5">
          <div>
            <label className="block text-xs text-tb-muted mb-1.5">Project Name</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="e.g. Asuran Dub — Telugu"
              className="tb-input w-full"
            />
          </div>

          <div>
            <label className="block text-xs text-tb-muted mb-2">Pipeline</label>
            <div className="space-y-2">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setMode(m.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors ${
                    mode === m.id
                      ? 'border-tb-accent/50 bg-tb-accent/10 text-tb-text'
                      : 'border-tb-border hover:border-tb-accent/30 hover:bg-white/[0.02] text-tb-muted'
                  }`}
                >
                  <div className={mode === m.id ? 'text-tb-accent' : 'text-tb-border'}>{m.icon}</div>
                  <div className="min-w-0">
                    <div className="text-xs font-medium">{m.label}</div>
                    <div className="text-[10px] text-tb-border mt-0.5">{m.sublabel}</div>
                  </div>
                  {mode === m.id && <ChevronRight size={14} className="text-tb-accent ml-auto shrink-0" />}
                </button>
              ))}
            </div>
          </div>

          {mode === 'translation' && (
            <div className="flex items-center gap-3">
              <label className="text-xs text-tb-muted shrink-0">Dub into</label>
              <select
                value={lang}
                onChange={(e) => setLang(e.target.value)}
                className="tb-input flex-1"
              >
                {(languages.length > 0 ? languages : ['hindi', 'tamil', 'telugu', 'kannada', 'malayalam', 'bengali', 'marathi']).map((l) => (
                  <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div className="px-5 pb-5 flex gap-2 justify-end">
          <button onClick={onClose} className="btn-ghost px-4 py-1.5 text-xs">Cancel</button>
          <button onClick={handleCreate} className="btn-accent px-4 py-1.5 text-xs flex items-center gap-1.5">
            <Plus size={12} />
            Create Project
          </button>
        </div>
      </div>
    </div>
  )
}

function ProjectCard({
  project, onOpen, onDelete,
}: {
  project: { id: string; name: string; mode: AppMode; status: string; targetLanguage: string; updatedAt: number }
  onOpen: () => void
  onDelete: () => void
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)

  return (
    <div
      className="group relative bg-tb-panel border border-tb-border rounded-xl overflow-hidden hover:border-tb-accent/40 transition-colors cursor-pointer"
      onClick={onOpen}
    >
      <div className="h-1.5 bg-tb-accent/30" />
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-tb-accent/15 flex items-center justify-center shrink-0">
              <Folder size={14} className="text-tb-accent" />
            </div>
            <span className="text-tb-text text-sm font-medium truncate">{project.name}</span>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (confirmDelete) { onDelete() } else { setConfirmDelete(true); setTimeout(() => setConfirmDelete(false), 3000) }
            }}
            className={`shrink-0 p-1 rounded transition-colors opacity-0 group-hover:opacity-100 ${
              confirmDelete
                ? 'bg-red-500/20 text-red-400'
                : 'hover:bg-white/10 text-tb-border hover:text-tb-muted'
            }`}
            title={confirmDelete ? 'Click again to confirm delete' : 'Delete project'}
          >
            <Trash2 size={12} />
          </button>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-tb-muted">{MODE_LABELS[project.mode] ?? project.mode}</span>
            <span className={statusColor(project.status)}>{statusLabel(project.status)}</span>
          </div>
          <div className="flex items-center justify-between text-[10px] text-tb-border">
            <span className="capitalize">{project.targetLanguage}</span>
            <span>{timeAgo(project.updatedAt)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function ProjectsHome() {
  const { projects, openProject, deleteProject } = useProjectStore()
  const [showNew, setShowNew] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showVoiceLibrary, setShowVoiceLibrary] = useState(false)
  const [languages, setLanguages] = useState<string[]>([])

  const fetchLanguages = () => {
    if (languages.length > 0) return
    fetch('/api/languages')
      .then((r) => r.json())
      .then((d: { languages: string[] }) => setLanguages(d.languages))
      .catch(() => {})
  }

  const sorted = [...projects].sort((a, b) => b.updatedAt - a.updatedAt)

  return (
    <>
      <div className="flex-1 flex flex-col bg-tb-bg overflow-hidden">
        <div className="px-8 pt-10 pb-6 flex items-end justify-between border-b border-tb-border shrink-0">
          <div>
            <div className="flex items-center gap-2 text-tb-accent mb-1">
              <Zap size={16} />
              <span className="text-sm font-semibold tracking-tight">TrillBar</span>
            </div>
            <h1 className="text-tb-text text-xl font-semibold">Projects</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowVoiceLibrary(true)}
              className="btn-ghost flex items-center gap-1.5 px-3 py-1.5 text-xs"
              title="Voice Library"
            >
              <Library size={13} />
              Voice Library
            </button>
            <button onClick={() => setShowSettings(true)} className="btn-ghost p-1.5">
              <Settings size={14} />
            </button>
            <button
              onClick={() => { fetchLanguages(); setShowNew(true) }}
              className="btn-accent flex items-center gap-1.5 px-3 py-1.5 text-xs"
            >
              <Plus size={13} />
              New Project
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-8 py-6">
          {sorted.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
              <div className="w-14 h-14 rounded-2xl bg-tb-accent/10 flex items-center justify-center">
                <Folder size={24} className="text-tb-accent/60" />
              </div>
              <div>
                <p className="text-tb-text text-sm font-medium mb-1">No projects yet</p>
                <p className="text-tb-muted text-xs">Create a project to start dubbing</p>
              </div>
              <button
                onClick={() => { fetchLanguages(); setShowNew(true) }}
                className="btn-accent flex items-center gap-1.5 px-4 py-2 text-xs mt-1"
              >
                <Plus size={13} />
                New Project
              </button>
            </div>
          ) : (
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
              {sorted.map((p) => (
                <ProjectCard
                  key={p.id}
                  project={p}
                  onOpen={() => openProject(p.id)}
                  onDelete={() => deleteProject(p.id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {showNew && <NewProjectModal languages={languages} onClose={() => setShowNew(false)} />}
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
      {showVoiceLibrary && <VoiceLibraryModal onClose={() => setShowVoiceLibrary(false)} />}
    </>
  )
}
