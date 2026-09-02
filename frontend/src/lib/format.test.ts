import { describe, expect, it } from "vitest";

import { fa, faDigits, faMinutes, faYear, formatToman } from "./format";

describe("formatToman", () => {
  it("says a price the way a renter says it out loud", () => {
    expect(formatToman(45_000_000)).toBe("۴۵ میلیون");
    expect(formatToman(4_100_000_000)).toBe("۴٫۱ میلیارد");
  });

  it("uses Persian digits and a Persian decimal separator throughout", () => {
    // The bug this module was written for: toFixed produced "4.1", which reads
    // as a foreign number in the middle of a Persian price.
    expect(formatToman(4_100_000_000)).not.toMatch(/[0-9.]/);
  });

  it("names the currency when nothing nearby does", () => {
    expect(formatToman(45_000_000, { unit: true })).toBe("۴۵ میلیون تومان");
    // Below a million there is no scale word to lean on, so the unit comes
    // along regardless.
    expect(formatToman(500_000)).toContain("تومان");
  });

  it("rounds to the scale word rather than printing a long figure", () => {
    expect(formatToman(45_600_000)).toBe("۴۶ میلیون");
  });
});

describe("fa", () => {
  it("groups a quantity", () => {
    expect(fa(1403)).toBe("۱٬۴۰۳");
  });

  it("leaves a year ungrouped, because a year is an identifier", () => {
    expect(faYear(1403)).toBe("۱۴۰۳");
  });
});

describe("faDigits", () => {
  it("transliterates the numerals inside advertiser prose and nothing else", () => {
    expect(faDigits("واحد 3 طبقه 2")).toBe("واحد ۳ طبقه ۲");
  });
});

describe("faMinutes", () => {
  it("rounds, because every duration in the product is an estimate", () => {
    expect(faMinutes(7.4)).toBe("۷ دقیقه");
  });
});
