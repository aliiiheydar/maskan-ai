# Frontend State Architecture & UI Synchronization

## 1. Unified State Store (`useSearchStore.ts`)

The React/Next.js frontend maintains a single state store with Zustand. Both the Chat and Filter panels dispatch actions to this store.

```typescript
import { create } from 'zustand';

export interface FilterState {
  // Mode Selection
  mode: 'intelligent' | 'classic';
  setMode: (mode: 'intelligent' | 'classic') => void;

  // Search State
  queryText: string;
  depositToman: number;
  rentToman: number;
  minAreaSqm: number;
  hasElevator: boolean;
  hasParking: boolean;
  hasBalcony: boolean;
  selectedNeighborhoods: string[];
  
  // Work/Commute Hub
  workplaceLocation: { lat: number; lon: number; name: string } | null;
  maxCommuteMins: number;

  // Map & Viewport State
  mapBBox: { minLat: number; minLon: number; maxLat: number; maxLon: number } | null;
  selectedListingId: string | null;
  hoveredListingId: string | null;
  showTier2: boolean;

  // Result Set
  tier1Results: ListingCard[];
  tier2Results: ListingCard[];
  isLoading: boolean;

  // Actions
  setFilters: (filters: Partial<FilterState>) => void;
  setSelectedListingId: (id: string | null) => void;
  setHoveredListingId: (id: string | null) => void;
  toggleTier2: () => void;
  syncFromExtractedIntent: (intent: any) => void;
}
```

## 2. Bidirectional Synchronization Flow

```
[ User in Chat ] ---> "ودیعه تا ۳۰۰ میلیون با آسانسور"
                          │
                          ▼ (LLM extracts JSON via SSE)
               syncFromExtractedIntent()
                          │
                          ▼
           ┌─────────────────────────────┐
           │     Zustand Store Updates   │
           │ depositToman: 300,000,000   │
           │ hasElevator: true           │
           └──────────────┬──────────────┘
                          │
                          ▼ (Reactivity)
           ┌─────────────────────────────┐
           │ Classic Filter UI Updates   │
           │ - Range Slider -> 300M      │
           │ - Checkbox -> [x] آسانسور    │
           └─────────────────────────────┘
```

## 3. Neshan Map SDK Integration Rules

1. **Map Container Initialization**:
   - Center on Tehran: `[35.6997, 51.3380]`, Zoom: `12`.
   - Use Persian vector map tiles from Neshan Platform (`@neshan-maps-platform/mapbox-gl`).

2. **Pin Rendering Logic**:
   - **Tier 1 Pins**: Rendered in green/gold with a star icon. Clicking scrolls the listing feed directly to the card.
   - **Tier 2 Pins**: Rendered in secondary blue. Clicking expands the Tier 2 accordion and selects the card.
   - **Hover Sync**: Hovering over a listing card in the right feed triggers `setHoveredListingId(id)`, causing the corresponding map pin to pulse and scale to `1.3x`.

3. **Viewport Debouncing**:
   - When the user drags or zooms the map in Zero-Query mode, listen to `moveend` and debounce API calls by `300ms` before querying the new bounding box.
