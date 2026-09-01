"use client";

// Captures the map click that adds a محله to the search area by pointing at
// it, rather than by finding its name in a list of 258. Only listens while
// isPickingNeighborhood is armed (toggled from the filter panel), so it never
// interferes with normal panning or with clicking a listing pin.
import { useMapEvents } from "react-leaflet";

import { useSearchStore } from "@/store/useSearchStore";

export default function NeighborhoodMapPicker({ onNotice }: { onNotice: (message: string) => void }) {
  const isPickingNeighborhood = useSearchStore((state) => state.isPickingNeighborhood);
  const toggleNeighborhoodAt = useSearchStore((state) => state.toggleNeighborhoodAt);

  useMapEvents({
    click: (event) => {
      if (!isPickingNeighborhood) return;
      void toggleNeighborhoodAt(event.latlng.lat, event.latlng.lng).then((title) => {
        // The polygons cover about two thirds of the city, so a click on a
        // park, a highway or an unmapped pocket genuinely belongs to no
        // محله. Saying so is the difference between "nothing happened" and
        // "the picker is broken".
        onNotice(title ? `محله «${title}» به محدوده جستجو اضافه یا از آن حذف شد.` : "این نقطه داخل هیچ محله‌ی شناخته‌شده‌ای نیست. کمی آن‌طرف‌تر را امتحان کنید.");
      });
    },
  });

  return null;
}
