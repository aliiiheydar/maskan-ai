/**
 * The one match scale, shared by the map pins and the feed's ٪ badge.
 *
 * The percentage on a card is the listing's own utility score, printed as it
 * was computed. It used to be stretched across the range of whatever results
 * happened to be loaded, which sounded fairer than it was: the top sixty of a
 * wide search sit within about three points of each other, so the stretch
 * spent thirty display points separating those three -- and then had nothing
 * left for the thousands of results below them, where the badge crawled a
 * point at a time while the real score fell from 0.84 to 0.70. Going down the
 * list, the number stopped meaning anything.
 *
 * So the number belongs to the listing now, not to the page it is on. It says
 * the same thing on card 3 and card 300, it does not move when more results
 * load, and it falls down the list at the rate the ranking actually falls.
 *
 * The colour is what separates near-equal results instead, and it is spent on
 * the band results actually occupy: a search never returns anything below the
 * Tier 2 floor, and anything at RAMP_HI or above is as good a match as this
 * ranking produces. Running the ramp over a nominal 0..100٪ would give most of
 * the spectrum to scores that cannot occur.
 */
const RAMP_LO = 0.45;
const RAMP_HI = 0.9;

/** 0 at the weakest match a search can return, 1 at the strongest. */
function ramp(score: number): number {
  return Math.min(1, Math.max(0, (score - RAMP_LO) / (RAMP_HI - RAMP_LO)));
}

/** Pin fill: the hue itself, plus the fade that lets weak matches recede. */
export function matchColor(score: number): { fill: string; opacity: number } {
  const t = ramp(score);
  return {
    // 0 -> red, 1 -> green, through amber in the middle.
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
