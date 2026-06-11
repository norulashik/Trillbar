import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AppMode, UiPhase, Segment, TimelineClip, ProjectSnapshot, VoiceEntry, CutRegion } from '../types'

// ── helpers ───────────────────────────────────────────────────────────────────

const DEFAULT_CLIP = (id: number): TimelineClip => ({
  segment_id: id, offset_ms: 0, stretch_ratio: 1.0,
  trim_in_ms: 0, trim_out_ms: 0, gain_db: 0, muted: false, locked: false,
})

function newId(): string {
  return Math.random().toString(36).slice(2, 9) + Date.now().toString(36)
}

function blankSnapshot(id: string, name: string, mode: AppMode, targetLanguage: string): ProjectSnapshot {
  const now = Date.now()
  return {
    id, name, mode, createdAt: now, updatedAt: now,
    jobId: null, uiPhase: 'idle', status: '', stage: '', progress: 0, error: null,
    targetLanguage, segments: [], clips: {}, speakerVoiceAssignments: {},
    outputUrl: null, isVideo: false, previewUrl: null,
    lipSyncStatus: 'idle', lipSyncUrl: null,
    skipSeparation: false, skipProsody: false, qcMode: false,
    cutRegions: [], trimIn: 0, trimOut: 0,
  }
}

// Sync one field (or a few) into the current project's snapshot in the list
function patchProject(
  state: ProjectState,
  patch: Partial<ProjectSnapshot>,
): { projects: ProjectSnapshot[] } {
  if (!state.currentProjectId) return { projects: state.projects }
  return {
    projects: state.projects.map((p) =>
      p.id === state.currentProjectId
        ? { ...p, ...patch, updatedAt: Date.now() }
        : p,
    ),
  }
}

// ── state shape ──────────────────────────────────────────────────────────────

interface ProjectState {
  // ── Project list (persisted) ───────────────────────
  projects: ProjectSnapshot[]
  currentProjectId: string | null

  // ── Current working fields ─────────────────────────
  currentProjectName: string
  mode: AppMode
  uiPhase: UiPhase
  jobId: string | null
  status: string
  stage: string
  progress: number
  error: string | null
  segments: Segment[]
  selectedSegmentId: number | null
  outputUrl: string | null
  isVideo: boolean
  previewUrl: string | null
  clips: Record<number, TimelineClip>
  speakerVoiceAssignments: Record<string, string>
  voiceLibrary: VoiceEntry[]      // not persisted — fetched fresh
  resynthesizing: Set<number>     // not persisted
  reassembling: boolean            // not persisted
  qcMode: boolean
  lipSyncStatus: 'idle' | 'submitted' | 'processing' | 'done' | 'failed'
  lipSyncUrl: string | null
  targetLanguage: string
  skipSeparation: boolean
  skipProsody: boolean
  cutRegions: CutRegion[]
  trimIn: number
  trimOut: number

  // ── Project management ────────────────────────────
  createProject: (name: string, mode: AppMode, targetLanguage?: string) => void
  openProject: (id: string) => void
  closeProject: () => void
  deleteProject: (id: string) => void
  renameProject: (id: string, name: string) => void

  // ── Existing setters (also sync to snapshot) ──────
  setMode: (m: AppMode) => void
  setUiPhase: (p: UiPhase) => void
  setJobId: (id: string | null) => void
  setJobState: (s: { status: string; stage: string; progress: number; error?: string | null }) => void
  setSegments: (s: Segment[]) => void
  updateSegment: (id: number, patch: Partial<Segment>) => void
  setOutputUrl: (url: string | null) => void
  setIsVideo: (v: boolean) => void
  setPreviewUrl: (url: string | null) => void
  setSelectedSegmentId: (id: number | null) => void
  setResynthesizing: (id: number, active: boolean) => void
  setClip: (id: number, patch: Partial<TimelineClip>) => void
  resetClip: (id: number) => void
  setReassembling: (v: boolean) => void
  setQcMode: (v: boolean) => void
  setLipSyncStatus: (s: 'idle' | 'submitted' | 'processing' | 'done' | 'failed') => void
  setLipSyncUrl: (url: string | null) => void
  setTargetLanguage: (lang: string) => void
  setSkipSeparation: (v: boolean) => void
  setSkipProsody: (v: boolean) => void
  setCutRegions: (regions: CutRegion[]) => void
  setTrimIn: (v: number) => void
  setTrimOut: (v: number) => void
  setSpeakerVoiceAssignment: (speakerId: string, voiceLibraryId: string) => void
  setVoiceLibrary: (voices: VoiceEntry[]) => void
  reset: () => void
}

// ── store ─────────────────────────────────────────────────────────────────────

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      // Project list
      projects: [],
      currentProjectId: null,

      // Working fields (defaults)
      currentProjectName: '',
      mode: 'translation',
      uiPhase: 'idle',
      jobId: null,
      status: '',
      stage: '',
      progress: 0,
      error: null,
      segments: [],
      selectedSegmentId: null,
      outputUrl: null,
      isVideo: false,
      previewUrl: null,
      clips: {},
      speakerVoiceAssignments: {},
      voiceLibrary: [],
      resynthesizing: new Set<number>(),
      reassembling: false,
      qcMode: false,
      lipSyncStatus: 'idle',
      lipSyncUrl: null,
      targetLanguage: 'hindi',
      skipSeparation: false,
      skipProsody: false,
      cutRegions: [],
      trimIn: 0,
      trimOut: 0,

      // ── Project management ──────────────────────────

      createProject: (name, mode, targetLanguage = 'hindi') => {
        const id = newId()
        const snap = blankSnapshot(id, name, mode, targetLanguage)
        set((s) => ({
          projects: [...s.projects, snap],
          currentProjectId: id,
          currentProjectName: name,
          mode,
          uiPhase: 'idle',
          targetLanguage,
          jobId: null, status: '', stage: '', progress: 0, error: null,
          segments: [], clips: {}, speakerVoiceAssignments: {},
          outputUrl: null, isVideo: false, previewUrl: null,
          lipSyncStatus: 'idle', lipSyncUrl: null,
          skipSeparation: false, skipProsody: false,
          cutRegions: [], trimIn: 0, trimOut: 0,
          selectedSegmentId: null, reassembling: false, qcMode: false,
          resynthesizing: new Set<number>(),
        }))
      },

      openProject: (id) => {
        set((s) => {
          const proj = s.projects.find((p) => p.id === id)
          if (!proj) return {}
          return {
            currentProjectId: id,
            currentProjectName: proj.name,
            mode: proj.mode,
            uiPhase: proj.uiPhase ?? 'idle',
            jobId: proj.jobId,
            status: proj.status,
            stage: proj.stage,
            progress: proj.progress,
            error: proj.error,
            targetLanguage: proj.targetLanguage,
            segments: proj.segments,
            clips: proj.clips,
            speakerVoiceAssignments: proj.speakerVoiceAssignments ?? {},
            outputUrl: proj.outputUrl,
            isVideo: proj.isVideo,
            previewUrl: proj.previewUrl,
            lipSyncStatus: proj.lipSyncStatus,
            lipSyncUrl: proj.lipSyncUrl,
            skipSeparation: proj.skipSeparation,
            skipProsody: proj.skipProsody,
            qcMode: proj.qcMode,
            cutRegions: proj.cutRegions ?? [],
            trimIn: proj.trimIn ?? 0,
            trimOut: proj.trimOut ?? 0,
            selectedSegmentId: null,
            reassembling: false,
            resynthesizing: new Set<number>(),
          }
        })
      },

      closeProject: () => {
        set({
          currentProjectId: null,
          currentProjectName: '',
          mode: 'translation',
          uiPhase: 'idle',
          jobId: null, status: '', stage: '', progress: 0, error: null,
          segments: [], clips: {}, speakerVoiceAssignments: {},
          outputUrl: null, isVideo: false, previewUrl: null,
          lipSyncStatus: 'idle', lipSyncUrl: null,
          cutRegions: [], trimIn: 0, trimOut: 0,
          selectedSegmentId: null, reassembling: false, qcMode: false,
          resynthesizing: new Set<number>(),
        })
      },

      deleteProject: (id) => {
        set((s) => {
          const next = s.projects.filter((p) => p.id !== id)
          const closing = s.currentProjectId === id
          return {
            projects: next,
            ...(closing ? {
              currentProjectId: null, currentProjectName: '',
              uiPhase: 'idle' as const,
              jobId: null, status: '', stage: '', progress: 0, error: null,
              segments: [], clips: {}, speakerVoiceAssignments: {},
              outputUrl: null, isVideo: false, previewUrl: null,
              lipSyncStatus: 'idle' as const, lipSyncUrl: null,
              cutRegions: [], trimIn: 0, trimOut: 0,
              selectedSegmentId: null, reassembling: false, qcMode: false,
              resynthesizing: new Set<number>(),
            } : {}),
          }
        })
      },

      renameProject: (id, name) => {
        set((s) => ({
          projects: s.projects.map((p) => p.id === id ? { ...p, name, updatedAt: Date.now() } : p),
          ...(s.currentProjectId === id ? { currentProjectName: name } : {}),
        }))
      },

      // ── Setters (sync to snapshot) ───────────────────

      setMode: (mode) => set((s) => ({ mode, ...patchProject(s, { mode }) })),

      setJobId: (jobId) => set((s) => ({ jobId, ...patchProject(s, { jobId }) })),

      setJobState: ({ status, stage, progress, error = null }) =>
        set((s) => ({ status, stage, progress, error, ...patchProject(s, { status, stage, progress, error }) })),

      setSegments: (segments) => set((s) => ({ segments, ...patchProject(s, { segments }) })),

      updateSegment: (id, patch) =>
        set((s) => {
          const segments = s.segments.map((seg) => (seg.id === id ? { ...seg, ...patch } : seg))
          return { segments, ...patchProject(s, { segments }) }
        }),

      setOutputUrl: (outputUrl) => set((s) => ({ outputUrl, ...patchProject(s, { outputUrl }) })),

      setIsVideo: (isVideo) => set((s) => ({ isVideo, ...patchProject(s, { isVideo }) })),

      setPreviewUrl: (previewUrl) => set((s) => ({ previewUrl, ...patchProject(s, { previewUrl }) })),

      setSelectedSegmentId: (selectedSegmentId) => set({ selectedSegmentId }),

      setResynthesizing: (id, active) =>
        set((s) => {
          const next = new Set(s.resynthesizing)
          active ? next.add(id) : next.delete(id)
          return { resynthesizing: next }
        }),

      setClip: (id, patch) =>
        set((s) => {
          const clips = {
            ...s.clips,
            [id]: { ...(s.clips[id] ?? DEFAULT_CLIP(id)), ...patch },
          }
          return { clips, ...patchProject(s, { clips }) }
        }),

      resetClip: (id) =>
        set((s) => {
          const clips = { ...s.clips }
          delete clips[id]
          return { clips, ...patchProject(s, { clips }) }
        }),

      setReassembling: (reassembling) => set({ reassembling }),

      setQcMode: (qcMode) => set((s) => ({ qcMode, ...patchProject(s, { qcMode }) })),

      setLipSyncStatus: (lipSyncStatus) =>
        set((s) => ({ lipSyncStatus, ...patchProject(s, { lipSyncStatus }) })),

      setLipSyncUrl: (lipSyncUrl) => set((s) => ({ lipSyncUrl, ...patchProject(s, { lipSyncUrl }) })),

      setTargetLanguage: (targetLanguage) =>
        set((s) => ({ targetLanguage, ...patchProject(s, { targetLanguage }) })),

      setSkipSeparation: (skipSeparation) =>
        set((s) => ({ skipSeparation, ...patchProject(s, { skipSeparation }) })),

      setSkipProsody: (skipProsody) =>
        set((s) => ({ skipProsody, ...patchProject(s, { skipProsody }) })),

      setCutRegions: (cutRegions) =>
        set((s) => ({ cutRegions, ...patchProject(s, { cutRegions }) })),

      setTrimIn: (trimIn) =>
        set((s) => ({ trimIn, ...patchProject(s, { trimIn }) })),

      setTrimOut: (trimOut) =>
        set((s) => ({ trimOut, ...patchProject(s, { trimOut }) })),

      setUiPhase: (uiPhase) => set((s) => ({ uiPhase, ...patchProject(s, { uiPhase }) })),

      setSpeakerVoiceAssignment: (speakerId, voiceLibraryId) =>
        set((s) => {
          const speakerVoiceAssignments = { ...s.speakerVoiceAssignments, [speakerId]: voiceLibraryId }
          return { speakerVoiceAssignments, ...patchProject(s, { speakerVoiceAssignments }) }
        }),

      setVoiceLibrary: (voiceLibrary) => set({ voiceLibrary }),

      reset: () =>
        set((s) => {
          const jobReset = {
            uiPhase: 'idle' as const,
            jobId: null, status: '', stage: '', progress: 0, error: null,
            segments: [], outputUrl: null, selectedSegmentId: null,
            isVideo: false, previewUrl: null, clips: {},
            speakerVoiceAssignments: {},
            reassembling: false, qcMode: false,
            lipSyncStatus: 'idle' as const, lipSyncUrl: null,
            cutRegions: [] as CutRegion[], trimIn: 0, trimOut: 0,
            resynthesizing: new Set<number>(),
          }
          return { ...jobReset, ...patchProject({ ...s, ...jobReset }, jobReset) }
        }),
    }),
    {
      name: 'trillbar-projects-v1',
      // Only persist the project list + currentProjectId.
      // Working state is loaded from the project on openProject/hydration.
      partialize: (state) => ({
        projects: state.projects,
        currentProjectId: state.currentProjectId,
      }),
      // On page reload, restore working state from the saved current project
      onRehydrateStorage: () => (state) => {
        if (!state) return
        const proj = state.projects.find((p) => p.id === state.currentProjectId)
        if (proj) {
          state.currentProjectName = proj.name
          state.mode = proj.mode
          state.uiPhase = proj.uiPhase ?? 'idle'
          state.jobId = proj.jobId
          state.status = proj.status
          state.stage = proj.stage
          state.progress = proj.progress
          state.error = proj.error
          state.targetLanguage = proj.targetLanguage
          state.segments = proj.segments
          state.clips = proj.clips
          state.speakerVoiceAssignments = proj.speakerVoiceAssignments ?? {}
          state.outputUrl = proj.outputUrl
          state.isVideo = proj.isVideo
          state.previewUrl = proj.previewUrl
          state.lipSyncStatus = proj.lipSyncStatus
          state.lipSyncUrl = proj.lipSyncUrl
          state.skipSeparation = proj.skipSeparation
          state.skipProsody = proj.skipProsody
          state.qcMode = proj.qcMode
          state.cutRegions = proj.cutRegions ?? []
          state.trimIn = proj.trimIn ?? 0
          state.trimOut = proj.trimOut ?? 0
        }
      },
    },
  ),
)
