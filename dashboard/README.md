# BybitBot Dashboard

Modern React control panel for the BybitBot trading agent.

## Quick start

From the repo root, run:

```bat
start.bat
```

This starts:

| Service | URL |
|---------|-----|
| Dashboard UI | http://127.0.0.1:5173 |
| Dashboard API | http://127.0.0.1:8765/api/health |
| Trading bot | logs in `.run/bot.log` |

Stop everything with `stop.bat`.

## Manual dev

**API** (Python, port 8765):

```bat
.venv\Scripts\python.exe scripts\run_dashboard_api.py
```

**UI** (Vite, port 5173):

```bat
cd dashboard
npm install
npm run dev
```

Production build:

```bat
cd dashboard
npm run build
npm run preview
```

Set `VITE_API_URL=http://127.0.0.1:8765` if the API runs on a different host.

## Pages

- **Dashboard** — bot status, stats, equity curve, live log
- **Settings** — edit `data/settings.json` (hot-reload on bot)
- **Strategies** — pipeline toggles + success ranking
- **Trades** — full trade journal
- **Analytics** — charts (equity, source, symbols)
- **Learning** — pattern stats, calibration, recommendations
- **Analysis** — rejections and scanner log tail

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/status` | Bot running state, activity |
| GET | `/api/status/logs` | Tail of `.run/bot.log` |
| GET/PUT | `/api/settings` | Read/write settings.json |
| GET | `/api/trades` | Trade journal |
| GET | `/api/trades/strategies/ranking` | Strategy performance |
| GET | `/api/trades/charts` | Chart data |
| GET | `/api/learning` | Learning report + config |
| GET | `/api/analysis` | Rejections + signals |
| GET | `/api/events` | SSE real-time updates |

## Requirements

- Node.js 18+ (for dashboard UI)
- Python venv with `requirements.txt` (includes FastAPI + uvicorn)
