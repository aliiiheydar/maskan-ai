/**
 * The one match-colour scale, shared by the map pins and the feed's ٪ badge.
 *
 * The spectrum is spent where the decisions are: a result under 50٪ is simply
 * a poor match, and giving those half the hue range only made the map read as
 * a gradient of oranges with no clear "here are the good ones". So the ramp
 * runs red -> amber -> green across 50..100٪, and everything below 50٪ is flat
 * red. Both surfaces call this, so a pin can never disagree with the
 * percentage printed on its card.
 */
const FLOOR = 0.5;

/** 0 at the floor, 1 at a perfect match; everything below the floor is 0. */
function ramp(score: number): number {
  const clamped = Math.min(1, Math.max(0, score));
  return clamped <= FLOOR ? 0 : (clamped - FLOOR) / (1 - FLOOR);
}

/** Pin fill: the hue itself, plus the fade that lets weak matches recede. */
export function matchColor(score: number): { fill: string; opacity: number } {
  const t = ramp(score);
  return {
    // 0 -> red, 1 -> green, through amber at 75٪.
    fill: `hsl(${Math.round(t * 128)}, 72%, ${Math.round(46 - t * 8)}%)`,
    opacity: 0.45 + t * 0.55,
  };
}

/** The same hue as a badge: a saturated label on a tinted ground. */
export function matchBadgeStyle(score: number): { color: string; backgroundColor: string } {
  const hue = Math.round(ramp(score) * 128);
  return {
    color: `hsl(${hue}, 68%, 34%)`,
    backgroundColor: `hsl(${hue}, 72%, 95%)`,
  };
}

/**
 * The scale the current result set is displayed on.
 *
 * A search's raw utility is an absolute statement -- "this listing satisfies
 * 87٪ of what you asked for" -- and against a wide filter every survivor
 * lands in the same narrow band, so the feed reads as a wall of ٪88 and the
 * map as a wall of one green. Inside a bounded search (a rectangle, a set of
 * neighborhoods) that is exactly the comparison the user is making: which of
 * *these* is the better one.
 *
 * So the displayed value is stretched across the set's own range -- but only
 * partly, and never far. `ADAPT` moves a listing at most this fraction of the
 * way toward the stretched value, and `MAX_LIFT` caps how much better than its
 * true score any listing may be made to look. A genuinely weak match keeps
 * looking weak; what changes is that the good ones separate from each other.
 */
const ADAPT = 0.55;
const MAX_LIFT = 0.08;
const MAX_DROP = 0.2;
/** Below this spread there is nothing to separate, so nothing is stretched. */
const MIN_SPREAD = 0.02;

export type DisplayScale = (score: number) => number;

export function adaptiveScale(scores: number[]): DisplayScale {
  const usable = scores.filter((score) => score > 0);
  const lo = Math.min(...usable);
  const hi = Math.max(...usable);
  if (usable.length < 3 || hi - lo < MIN_SPREAD) return (score) => score;

  return (score) => {
    // The set's own range, replayed over the half of the scale the colours
    // actually use, so the weakest of a good crop still reads as a match.
    const stretched = FLOOR + (1 - FLOOR) * ((Math.min(hi, Math.max(lo, score)) - lo) / (hi - lo));
    const moved = score + (stretched - score) * ADAPT;
    return Math.min(score + MAX_LIFT, Math.max(score - MAX_DROP, moved));
  };
}
