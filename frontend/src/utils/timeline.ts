import type { CutRegion } from '../components/VideoPreviewPhase'

export function sortRegions(regions: CutRegion[]): CutRegion[] {
  return [...regions].sort((a, b) => a.start - b.start)
}

export function totalKeptDuration(regions: CutRegion[]): number {
  return regions.reduce((sum, r) => sum + (r.end - r.start), 0)
}

/**
 * Map local time (0 → totalKeptDuration) to original video timeline position.
 */
export function localToOriginal(localTime: number, sorted: CutRegion[]): number {
  let remaining = Math.max(0, localTime)
  for (const r of sorted) {
    const dur = r.end - r.start
    if (remaining <= dur + 0.001) return r.start + Math.max(0, remaining)
    remaining -= dur
  }
  return sorted.length > 0 ? sorted[sorted.length - 1].end : localTime
}

/**
 * Map original video timestamp to local time.
 * If the timestamp is in a gap between regions, returns the accumulated
 * local time up to the nearest prior region end.
 */
export function originalToLocal(origTime: number, sorted: CutRegion[]): number {
  let accumulated = 0
  for (const r of sorted) {
    if (origTime <= r.end + 0.001) {
      const clamped = Math.max(r.start, Math.min(r.end, origTime))
      return accumulated + (clamped - r.start)
    }
    accumulated += r.end - r.start
  }
  return accumulated
}
