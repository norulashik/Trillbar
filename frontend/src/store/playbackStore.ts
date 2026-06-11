import { create } from 'zustand'

interface PlaybackState {
  currentTime: number
  setCurrentTime: (t: number) => void
  isPlaying: boolean
  setIsPlaying: (p: boolean) => void
  duration: number
  setDuration: (d: number) => void
  activeTrack: 'original' | 'dubbed' | 'lipsync'
  setActiveTrack: (t: 'original' | 'dubbed' | 'lipsync') => void
  seekTo: number | null
  requestSeek: (t: number) => void
  clearSeek: () => void
}

export const usePlaybackStore = create<PlaybackState>((set) => ({
  currentTime: 0,
  setCurrentTime: (currentTime) => set({ currentTime }),
  isPlaying: false,
  setIsPlaying: (isPlaying) => set({ isPlaying }),
  duration: 0,
  setDuration: (duration) => set({ duration }),
  activeTrack: 'dubbed',
  setActiveTrack: (activeTrack) => set({ activeTrack }),
  seekTo: null,
  requestSeek: (t) => set({ seekTo: t }),
  clearSeek: () => set({ seekTo: null }),
}))

export type { PlaybackState }
