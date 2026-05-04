# Orbital Tracker

A real-time satellite tracking application powered by SGP4 orbital propagation. Track any object in the Celestrak catalog — visualize its ground track on a 2D map or render its full orbit in an interactive 3D globe, predict upcoming passes over any location on Earth, and replay historical TLE data with a timeline slider.

---

## Features

- **Live ground tracks** — 2D Leaflet map with polyline ground tracks, auto-refreshed against the Celestrak catalog every 4 hours
- **3D orbit view** — CesiumJS globe rendering one full orbital period in ECEF coordinates; toggle between 2D and 3D with a single button
- **Pass prediction** — upcoming rise/apex/set events over any observer location, with azimuth, elevation, and range data
- **TLE history** — PostgreSQL-backed snapshot store; a timeline slider lets you replay historical orbits as ghost tracks on the map
- **Full catalog search** — search by satellite name or NORAD ID across the entire active satellite catalog
- **ISS shortcut** — convenience endpoints for the International Space Station without needing its NORAD ID

---

## Architecture

```
┌─────────────┐     HTTP/JSON      ┌──────────────────────┐
│  React SPA  │ ◄────────────────► │  FastAPI + uvicorn   │
│  (Vite)     │                    │  SGP4 propagation    │
│  Leaflet    │                    │  APScheduler         │
│  CesiumJS   │                    └─────────┬────────────┘
└─────────────┘                              │ SQLAlchemy
    served by                                ▼
    nginx ──────────── /api/* proxy ──► PostgreSQL 16
```

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, Leaflet, CesiumJS / Resium, Zustand |
| Backend | Python 3.12, FastAPI, uvicorn, SGP4, pymap3d, astropy, APScheduler |
| Database | PostgreSQL 16, SQLAlchemy 2, Alembic |
| Infra | Docker Compose, nginx (static serve + API reverse proxy) |
| CI | GitHub Actions — pytest, Docker build verification |

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- A [Cesium Ion](https://cesium.com/ion/) account with an access token (free tier is sufficient)

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/zethdeluna/tlescope.git
cd tlescope
cp .env.example .env   # create this file — see below
```

### 2. Set required environment variables

Create a `.env` file in the project root:

```dotenv
# Required
POSTGRES_PASSWORD=changeme
VITE_CESIUM_TOKEN=your_cesium_ion_token_here

# Optional (these are the defaults)
POSTGRES_USER=tlescope
POSTGRES_DB=tlescope
CELESTRAK_TIMEOUT_S=30
```

> `VITE_CESIUM_TOKEN` is baked into the frontend bundle at build time. The backend will not start without `POSTGRES_PASSWORD`.

### 3. Build and run

```bash
docker compose up --build
```

The stack comes up in dependency order: PostgreSQL → backend (runs Alembic migrations, then starts uvicorn) → frontend (nginx). On first startup the backend fetches the full Celestrak catalog into memory; this may take a few seconds.

| Service | URL |
|---|---|
| Frontend | http://localhost |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

---

## Development Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start a local Postgres instance (or point DATABASE_URL at one)
export DATABASE_URL=postgresql://tlescope:changeme@localhost:5432/tlescope

alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install

# The dev server proxies /api/* to the backend automatically (see vite.config.ts)
VITE_CESIUM_TOKEN=your_token npm run dev
```

The Vite dev server runs on http://localhost:5173.

---

## API Reference

All endpoints return JSON. Full interactive docs are available at `/docs` when the backend is running.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/satellites` | Full active satellite catalog |
| `GET` | `/satellite/{norad_id}/groundtrack` | Ground track as GeoJSON LineString |
| `GET` | `/satellite/{norad_id}/orbit3d` | ECEF positions for one orbital period |
| `GET` | `/satellite/{norad_id}/passes` | Upcoming passes over a ground station |
| `GET` | `/satellite/{norad_id}/tle_history` | Stored TLE snapshots (filterable by date range) |
| `GET` | `/iss/position` | Current ISS position |
| `GET` | `/iss/groundtrack` | ISS ground track as GeoJSON |

**Pass prediction parameters** (`/satellite/{norad_id}/passes`):

| Parameter | Default | Description |
|---|---|---|
| `lat` | `0.0` | Observer latitude (°) |
| `lon` | `0.0` | Observer longitude (°) |
| `alt_m` | `0.0` | Observer altitude (m) |
| `days` | `3.0` | Prediction window (0.5 – 14) |
| `min_elevation_deg` | `10.0` | Minimum elevation to report (°) |

---

## TLE Caching

The backend maintains a three-layer cache so endpoints never block on network I/O:

1. **In-memory** (`dict`) — O(1) reads; populated every 4 hours by APScheduler
2. **Disk cache** (`.tle_cache.json`) — survives process restarts; bridges startup before the first refresh completes
3. **PostgreSQL** — append-only TLE snapshot history; not in the request path; powers the timeline slider

A database outage does not affect live tracking — the API continues serving from the in-memory and disk caches.

---

## Running Tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v --tb=short
```

CI runs the full test suite on every push and pull request to `main`, alongside Docker build verification for both images.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `POSTGRES_PASSWORD` | Yes | — | PostgreSQL password |
| `VITE_CESIUM_TOKEN` | Yes | — | Cesium Ion access token (build-time) |
| `POSTGRES_USER` | No | `tlescope` | PostgreSQL username |
| `POSTGRES_DB` | No | `tlescope` | PostgreSQL database name |
| `CELESTRAK_TIMEOUT_S` | No | `30` | HTTP timeout for Celestrak bulk fetches |
| `CORS_ORIGINS` | No | `http://localhost:5173,http://localhost` | Comma-separated allowed origins |
| `BACKEND_URL` | No | `http://backend:8000` | nginx upstream for API proxy |


