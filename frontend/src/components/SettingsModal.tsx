import { X } from 'lucide-react'
import { useState, useEffect } from 'react'

interface Props { onClose: () => void }

const KEYS = [
  { key: 'ASSEMBLYAI_API_KEY', label: 'AssemblyAI API Key', hint: 'assemblyai.com' },
  { key: 'ELEVENLABS_API_KEY', label: 'ElevenLabs API Key', hint: 'elevenlabs.io' },
  { key: 'GEMINI_API_KEY', label: 'Google Gemini API Key', hint: 'aistudio.google.com' },
]

export default function SettingsModal({ onClose }: Props) {
  const [vals, setVals] = useState<Record<string, string>>({})

  useEffect(() => {
    const stored: Record<string, string> = {}
    KEYS.forEach(({ key }) => {
      stored[key] = localStorage.getItem(key) ?? ''
    })
    setVals(stored)
  }, [])

  const save = () => {
    KEYS.forEach(({ key }) => {
      if (vals[key]) localStorage.setItem(key, vals[key])
    })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-tb-panel border border-tb-border rounded-lg w-[420px] shadow-2xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-tb-border">
          <span className="text-sm font-semibold">Settings</span>
          <button onClick={onClose} className="btn-ghost p-1"><X size={14} /></button>
        </div>
        <div className="p-4 space-y-4">
          <p className="text-tb-muted text-xs leading-relaxed">
            API keys are stored locally in your browser and sent directly to backend requests.
            They are never stored server-side.
          </p>
          {KEYS.map(({ key, label, hint }) => (
            <div key={key}>
              <label className="block text-xs text-tb-muted mb-1">
                {label} <span className="text-tb-border">— {hint}</span>
              </label>
              <input
                type="password"
                className="tb-input font-mono"
                placeholder="sk-..."
                value={vals[key] ?? ''}
                onChange={(e) => setVals({ ...vals, [key]: e.target.value })}
              />
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2 px-4 py-3 border-t border-tb-border">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} className="btn-accent">Save</button>
        </div>
      </div>
    </div>
  )
}
