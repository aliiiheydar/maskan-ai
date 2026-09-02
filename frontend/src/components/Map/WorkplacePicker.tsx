"use client";

// Captures the map click that sets the workplace/commute-hub pin. Only
// listens while isPickingWorkplace is armed (toggled from
// FilterPanel's commute-hub section), so it never interferes with
// normal map panning/marker clicks otherwise.
import { useMapEvents } from "react-leaflet";

import { useSearchStore } from "@/store/useSearchStore";

export default function WorkplacePicker() {
  const isPickingWorkplace = useSearchStore((state) => state.isPickingWorkplace);
  const setWorkplaceFromMapClick = useSearchStore((state) => state.setWorkplaceFromMapClick);

  useMapEvents({
    click: (e) => {
      if (!isPickingWorkplace) return;
      setWorkplaceFromMapClick(e.latlng.lat, e.latlng.lng);
    },
  });

  return null;
}
