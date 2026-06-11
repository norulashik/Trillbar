export interface CutRegion { start: number; end: number }

export interface PedalboardParams {
  hp_cutoff: number
  low_shelf_hz: number
  low_shelf_db: number
  presence_hz: number
  presence_db: number
  presence_q: number
  comp_threshold: number
  comp_ratio: number
  comp_attack_ms: number
  comp_release_ms: number
  reverb_room_size: number
  reverb_wet: number
  limiter_db: number
}

export interface TimelineClip {
  segment_id: number
  offset_ms: number       // -500 to +500 ms — shift start time
  stretch_ratio: number   // 0.7–1.3 — speed/duration control
  trim_in_ms: number      // trim head of dubbed audio
  trim_out_ms: number     // trim tail of dubbed audio
  gain_db: number         // per-segment volume (-12 to +6 dB)
  muted: boolean
  locked: boolean
}

export interface Segment {
  id: number
  speaker_id: string
  start: number
  end: number
  source_text: string
  translated_text?: string
  emotion?: string
  emotion_intensity?: number
  delivery_direction?: string
  // Studio-quality fields
  vocal_character?: string
  speaking_rate_wpm?: number
  source_f0_mean?: number
  voice_id?: string
  pedalboard_params?: PedalboardParams
  mos_score?: number
  quality_notes?: string
  needs_regen?: boolean
  // Lip sync & timing
  dubbed_duration_s?: number
  lip_sync_score?: number   // 0.0–1.0 temporal overlap
  pace_ratio?: number        // dub_duration / src_duration
  pace_ok?: boolean          // 0.8–1.2 range
  suggested_offset_ms?: number
  // QC
  qc_flags?: string[]
  qc_flagged?: boolean
}

export interface JobStatus {
  id: string
  status: 'queued' | 'running' | 'done' | 'error' | 'analyzing' | 'analyzed' | 'synthesizing'
  stage: string
  progress: number
  target_language?: string
  input_file?: string
  source_lang?: string
  duration?: number
  elapsed?: number
  error?: string | null
  ready?: boolean
  is_video?: boolean
  preview_url?: string | null
}

export type AppMode = 'translation' | 'voice'

export type UiPhase =
  | 'idle'
  | 'video-preview'
  | 'analyzing'
  | 'analyzed'
  | 'dubbing'
  | 'done'
  | 'error'

export interface VoiceEntry {
  id: string
  name: string
  elevenlabs_id: string
  ref_audio_path?: string
  created_at: number
}

export interface ProjectSnapshot {
  id: string
  name: string
  mode: AppMode
  createdAt: number
  updatedAt: number
  // Job state
  jobId: string | null
  uiPhase: UiPhase
  status: string
  stage: string
  progress: number
  error: string | null
  targetLanguage: string
  segments: Segment[]
  clips: Record<number, TimelineClip>
  speakerVoiceAssignments: Record<string, string>
  outputUrl: string | null
  isVideo: boolean
  previewUrl: string | null
  lipSyncStatus: 'idle' | 'submitted' | 'processing' | 'done' | 'failed'
  lipSyncUrl: string | null
  skipSeparation: boolean
  skipProsody: boolean
  qcMode: boolean
  cutRegions: CutRegion[]
  trimIn: number
  trimOut: number
}

export const EMOTION_COLORS: Record<string, string> = {
  happy:    'bg-yellow-500/15 text-yellow-400 border border-yellow-500/30',
  excited:  'bg-orange-500/15 text-orange-400 border border-orange-500/30',
  angry:    'bg-red-500/15 text-red-400 border border-red-500/30',
  sad:      'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  fear:     'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  surprise: 'bg-teal-500/15 text-teal-400 border border-teal-500/30',
  disgust:  'bg-green-500/15 text-green-400 border border-green-500/30',
  calm:     'bg-sky-500/15 text-sky-400 border border-sky-500/30',
  neutral:  'bg-gray-500/15 text-gray-400 border border-gray-500/30',
}
