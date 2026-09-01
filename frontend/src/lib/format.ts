/**
 * Persian number and money formatting, in one place.
 *
 * The app had four private copies of this and they disagreed: a card printed
 * "4.1 میلیارد" (Latin digits, Latin decimal point) next to "۴۲ میلیون"
 * (Persian), and raw fields like متراژ and سال ساخت went out untransliterated
 * altogether. Mixed numerals inside one Persian line read as two different
 * languages, so every number the UI shows goes through here.
 */

/** A count or a measurement: grouped, Persian digits. */
export const fa = (value: number): string => value.toLocaleString("fa-IR");

/** A year is an identifier, not a quantity: "۱٬۴۰۳" reads as one thousand
 * four hundred and three, which is not what ۱۴۰۳ means. */
export const faYear = (year: number): string => year.toLocaleString("fa-IR", { useGrouping: false });

/** Persian digits inside a string that is otherwise left alone -- advertiser
 * text arrives as Persian prose carrying Latin numerals. */
export const faDigits = (text: string): string =>
  text.replace(/[0-9]/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);

/** Money, at the scale a renter says it out loud.
 *
 * Tomans are large enough that the full figure is unreadable at a glance, so
 * anything from a million up is said in میلیون/میلیارد -- the way every price
 * in the Iranian market is quoted. `unit: false` drops the trailing "تومان"
 * for places where the currency is already named by a nearby label. */
export function formatToman(value: number, { unit = false }: { unit?: boolean } = {}): string {
  const suffix = unit ? " تومان" : "";
  if (value >= 1_000_000_000) {
    // toLocaleString rather than toFixed: the latter returns Latin digits and
    // a Latin decimal point, which read as a foreign number in the middle of
    // a Persian price.
    return `${(value / 1_000_000_000).toLocaleString("fa-IR", { maximumFractionDigits: 1 })} میلیارد${suffix}`;
  }
  if (value >= 1_000_000) return `${fa(Math.round(value / 1_000_000))} میلیون${suffix}`;
  return `${fa(value)}${suffix || " تومان"}`;
}

/** Minutes, rounded -- every duration in the product is an estimate. */
export const faMinutes = (minutes: number): string => `${fa(Math.round(minutes))} دقیقه`;
