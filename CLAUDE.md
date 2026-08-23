# CLAUDE.md - AI Real Estate Discovery Platform (Tehran)

## Project Overview
Next-generation real estate rental discovery platform for Tehran inspired by Torob's aggregation intelligence and solving Divar's rigid filtering. Features Persian conversational intent discovery, multimodal transit-reachability scoring, and Pareto-optimal ranking.

## Core Invariants & Iranian Market Domain Logic
1. **Financial Logic (Tabdil / تبدیل)**:
   - Base Rule: 100,000,000 Tomans Deposit (ودیعه/رهن) ≈ 3,000,000 Tomans Monthly Rent (اجاره).
   - Effective Cost Formula: `C_eff = rent + (deposit * 0.03)`.
   - All financial numbers in code must use **Tomans** (not Rials) as integers (`int64`).
2. **Geospatial Bounds (Tehran)**:
   - Bounding Box: `min_lat: 35.5500, max_lat: 35.8500, min_lon: 51.1000, max_lon: 51.6000`.
   - Public Transit Reference Nodes: Metro Lines 1 to 7, BRT Corridors 1 to 10.
   - Walk Speed: 80 meters/minute (~4.8 km/h).
   - Driving in Congestion Zones: Penalize travel time by 1.4x if crossing into *Tarh-e Terafik*.
3. **Persian NLP & Character Encoding**:
   - Always normalize Persian characters (convert Arabic 'ي' and 'ك' to 'ی' and 'ک').
   - Clean Persian numbers (`۱۲۳۴۵۶۷۸۹۰` to `1234567890`) before parsing.
   - LLM System Prompts must enforce polite, concise, natural Persian responses.

## Tech Stack & External APIs
- **Backend**: Python 3.11+, FastAPI, Pydantic v2, Uvicorn, AsyncIO, NumPy, Scikit-learn.
- **Database / Vector**: SQLite with spatial extensions or PostgreSQL with PostGIS + pgvector (fallback to in-memory vectorized store for standalone MVP).
- **LLM Backbone**: `deepseek/deepseek-chat` (or `deepseek/deepseek-v3` / `deepseek/deepseek-r1-distill-llama-70b` / `deepseek-v4-flash`) via OpenRouter API.
- **Embeddings**: `openai/text-embedding-3-small` or `baai/bge-m3` via OpenRouter.
- **Frontend**: Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, Zustand, Neshan Map SDK / Leaflet.
- **Testing**: `pytest`, `pytest-asyncio`, `httpx` (Backend), `vitest` (Frontend).

## Architectural Rules
1. **Separation of Concerns**:
   - `app/core/`: Domain models, configs, pricing math, Persian normalizers.
   - `app/spatial/`: Transit station graph, distance engines, isochrone calculators.
   - `app/search/`: Multi-criteria utility ranking, Pareto-frontier filtering, vector search.
   - `app/llm/`: OpenRouter client, structured prompt templates, tool definitions.
   - `app/api/`: FastAPI route controllers, SSE streaming endpoints.
2. **Output Structure**:
   - All search queries must return `tier_1_results` (Utility >= 0.70) and `tier_2_results` (0.45 <= Utility < 0.70) to support progressive disclosure.
3. **Coding Standards**:
   - Strict typing with Pydantic v2 and Python type hints (`mypy` compliant).
   - Async-first for all network and DB I/O.
   - Zero hardcoded API keys; read from `.env`.

## Key Commands
- Install Backend: `pip install -r requirements.txt`
- Run Backend Dev: `uvicorn app.main:app --reload --port 8000`
- Run Tests: `pytest -v --tb=short`
- Install Frontend: `cd frontend && npm install`
- Run Frontend Dev: `cd frontend && npm run dev`
- Build Frontend: `cd frontend && npm run build`