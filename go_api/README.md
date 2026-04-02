# Go API — High-Performance Gateway (Future)

> **Status:** 🔮 Planned — Not yet implemented  
> **Current System:** Uses Python Flask (`api_v2.py`) for all API serving

## Purpose

This module is reserved for a future **Go-based API gateway** to provide:
- Ultra-low latency request routing
- WebSocket connection pooling
- Rate limiting and authentication middleware
- Load balancing across Python backend workers

## Structure

```
go_api/
├── cmd/           # Application entry points
├── internal/
│   ├── handlers/  # HTTP request handlers
│   ├── middleware/ # Auth, rate limiting, logging
│   ├── models/    # Data models
│   └── ws/        # WebSocket handlers
```

## Current Alternative

All API functionality is fully handled by:
- `api_v2.py` — Main Flask API (14 registered route modules, 263+ endpoints)
- `api_sync.py` — Frontend-backend synchronization routes

**No action required** — the Python backend is production-ready.
