import type L from "leaflet";

/**
 * Runs a map movement as soon as the map actually has a size on screen.
 *
 * On a phone the map lives on a tab that is `display:none` while the feed or
 * the filter panel is showing (see app/page.tsx), and Leaflet divides by the
 * container size when it animates: `flyTo`/`fitBounds` against a 0x0 container
 * computes (NaN, NaN) and throws out of render, which is what tapping a card
 * in the feed used to do. So the move is held until the container has been
 * laid out, and the map is re-measured first -- Leaflet cached the zero while
 * it was hidden.
 *
 * Returns a cleanup, so an effect that is superseded before the map becomes
 * visible drops its pending move instead of replaying a stale one.
 */
export function whenMapIsVisible(map: L.Map, move: () => void): () => void {
  const container = map.getContainer();
  const hasSize = () => container.clientWidth > 0 && container.clientHeight > 0;

  if (hasSize()) {
    move();
    return () => undefined;
  }

  const observer = new ResizeObserver(() => {
    if (!hasSize()) return;
    observer.disconnect();
    map.invalidateSize({ animate: false });
    move();
  });
  observer.observe(container);
  return () => observer.disconnect();
}
