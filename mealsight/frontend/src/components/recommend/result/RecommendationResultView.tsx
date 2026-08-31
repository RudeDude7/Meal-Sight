import { CookableResult } from '@/components/recommend/result/CookableResult'
import { NoCookableResult } from '@/components/recommend/result/NoCookableResult'
import type { RecommendationResult } from '@/types/recommendation'

interface RecommendationResultViewProps {
  result: RecommendationResult
}

/**
 * Dispatches on top_recommendation.available — the backend's own real
 * signal (mealsight/agent/nodes/reason.py) for whether anything
 * cookable was found this run. Nothing in this view (or anything it
 * renders) animates: the run is over by the time this shows at all, and
 * this system's own motion rule permits animation only while something
 * is genuinely happening.
 */
export function RecommendationResultView({ result }: RecommendationResultViewProps) {
  if (result.top_recommendation?.available) {
    return <CookableResult result={result} />
  }
  return <NoCookableResult result={result} />
}
