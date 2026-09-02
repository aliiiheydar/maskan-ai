import { describe, expect, it } from "vitest";

import { matchBadgeStyle, matchColor } from "./matchColor";

/** Pull the hue back out of an `hsl(...)` string. */
const hue = (color: string): number => Number(color.match(/hsl\((\d+)/)![1]);

describe("matchColor", () => {
  it("spends the whole spectrum on the band results actually occupy", () => {
    // The Tier 2 floor and up: a search never returns anything below 0.45,
    // and 0.9 is as good as this ranking produces.
    expect(hue(matchColor(0.45).fill)).toBe(0);
    expect(hue(matchColor(0.9).fill)).toBe(128);
  });

  it("clamps rather than running off either end of the ramp", () => {
    expect(hue(matchColor(0).fill)).toBe(0);
    expect(hue(matchColor(1).fill)).toBe(128);
  });

  it("moves monotonically with the score", () => {
    const scores = [0.45, 0.55, 0.65, 0.75, 0.85];
    const hues = scores.map((score) => hue(matchColor(score).fill));
    expect(hues).toStrictEqual([...hues].sort((a, b) => a - b));
    expect(new Set(hues).size).toBe(hues.length);
  });

  it("lets a weak match recede", () => {
    expect(matchColor(0.45).opacity).toBeLessThan(matchColor(0.85).opacity);
    expect(matchColor(0.9).opacity).toBeCloseTo(1);
  });

  it("gives the badge the same hue as the pin", () => {
    expect(hue(matchBadgeStyle(0.7).color)).toBe(hue(matchColor(0.7).fill));
  });
});
