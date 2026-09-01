# System Architecture & Component Design

## 1. High-Level System Architecture

The platform is designed as an asynchronous, event-driven decoupled architecture optimized for low-latency Persian semantic retrieval and spatial calculations.

```
                           +-------------------------------------+
                           |         Client (Next.js 14)         |
                           |  - Dual View: Chat + Neshan Map SDK |
                           |  - Shared Zustand State Store       |
                           +-------------------------------------+
                                      |               |
                         SSE Stream   |               | REST (JSON)
                        (Text Tokens) |               | (/api/v1/search)
                                      v               v
                           +-------------------------------------+
                           |       FastAPI Application Gateway   |
                           +-------------------------------------+
                                      |               |
                +---------------------+               +---------------------+
                |                                                           |
                v                                                           v
+-------------------------------+                           +-------------------------------+
|     LLM Orchestration Layer   |                           |    Geospatial Transit Layer   |
| - DeepSeek V4 Flash           |                           | - Station Graph (Metro/BRT)   |
|   (via OpenRouter)            |                           | - Haversine / Isochrone Math  |
| - Async JSON Intent Extractor |                           | - Tarh-e Terafik Masking      |
| - Persian Dialogue Generator  |                           | - H3 Spatial Hex Index        |
+-------------------------------+                           +-------------------------------+
                \                                                           /
                 \                                                         /
                  v                                                       v
        +-----------------------------------------------------------------------+
        |                 Search, Ranking & Pareto Engine                       |
        | - Hard Constraint Pruning                                             |
        | - Continuous Price & Transit Decay Scoring                            |
        | - Semantic Dense Retrieval (OpenRouter Embeddings)                    |
        | - Pareto Frontier Identification (Tier 1 vs Tier 2)                   |
        +-----------------------------------------------------------------------+
                                            |
                                            v
        +-----------------------------------------------------------------------+
        |                       Data Repository Layer                           |
        | - In-Memory Spatial Repository / PostgreSQL + PostGIS                 |
        | - Pre-computed Station Proximity & Effective Cost Indexes             |
        +-----------------------------------------------------------------------+
```

## 2. Component Boundaries & Responsibilities

### 2.1 Backend Modules (`app/`)
* **`app/core/`**: Single source of truth for application configuration, domain schemas, Persian string normalizers, and financial calculation functions (*Tabdil*).
* **`app/spatial/`**: Contains the station graph for Tehran Metro (Lines 1–7) and BRT corridors. Computes transit walking buffers, spatial bounds, and congestion zone detection (*Tarh-e Terafik* and *Tarh-e Aloodegi*).
* **`app/llm/`**: Manages communication with OpenRouter. Handles tool calling, JSON schema enforcement, few-shot Persian prompt engineering, and conversational streaming.
* **`app/search/`**: Executes multi-criteria heuristic scoring, Pareto-tradeoff discovery, and ranking tier stratification.
* **`app/data/`**: Listing storage and the data behind it — the SQLite gateway, the in-process repository, and the synthetic generator. Offline builders live in `app/data/pipelines/`, and every data file they read or write in `app/data/assets/` (addressed through `app.core.paths`).
* **`app/api/v1/`**: Exposes FastAPI routes, CORS configuration, dependency injection, and SSE streaming handlers.

### 2.2 Frontend Modules (`frontend/src/`)
* **`components/Chat/`**: Persian chat window with real-time SSE token rendering and inline recommendation previews.
* **`components/Filters/`**: Classic Divar-style filter controls (deposit/rent range sliders, amenity checkboxes, neighborhood tags).
* **`components/Map/`**: Neshan Map SDK / Leaflet container rendering Tier 1 (green/gold) and Tier 2 (blue/gray) pins with dynamic viewport syncing.
* **`components/Listings/`**: Responsive grid of listing cards with hover-state sync and expandable Tier 2 accordion.
* **`store/useSearchStore.ts`**: Zustand state container guaranteeing bidirectional synchronization between Chat inputs and Filter sliders.