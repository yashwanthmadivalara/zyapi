# ViralFlow AI

ViralFlow AI is a local-first MVP for turning videos you own or are authorized to process into reviewable short-form clip candidates.

## Current scope: phases 1–5

- Phase 1: Next.js dashboard, FastAPI API, SQLite persistence, migrations, real metrics, activity feed.
- Phase 2: source-channel records and a safe YouTube OAuth connection boundary. No credentials are included.
- Phase 3: authorized local video upload/library with duplicate detection and FFprobe validation when available.
- Phase 4: local transcription and Ollama adapters with truthful connection health checks.
- Phase 5: transcript-based moment detection with deterministic fallback heuristics and persisted candidates.
- Phase 6: FFmpeg vertical 9:16 extraction from candidate moments.
- Phase 7: SRT/ASS subtitle generation from timestamped transcript segments and editable metadata.
- Phase 8: manual approve/reject workflow with metadata edits.
- Phase 9: rule-based IST-aware scheduling with daily caps and minimum intervals.
- Phase 10: guarded resumable YouTube upload adapter with private/unlisted/public visibility.
- Phase 11: analytics snapshot API and top-clip summaries that distinguish no data from unavailable data.
- Phase 12: automation control-center service states with start/pause/resume/stop/retry commands.
- Phase 13: optional bearer protection for mutations, restrictive CORS, storage boundaries, migration-safe schema, and failure records.
- Phase 14: repeatable unit tests and container smoke-test scaffolding.
- Phase 15: Docker deployment scaffolding and a documented safe path to PostgreSQL/object storage/cloud hosting.

The implementation deliberately does not download videos from monitored YouTube channels. Monitoring metadata and acquiring authorized media are separate workflows.

## Run locally

### Backend

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. The API is expected at `http://localhost:8000`.

Copy `backend/.env.example` to `backend/.env`. External integrations remain disabled until configured and tested.

## Safety boundaries

- Only upload or process files you own, licensed, or explicitly authorized to use.
- Never put Google client secrets, OAuth refresh tokens, Ollama credentials, or Supabase service keys in browser code.
- A green integration status is only shown after a real health check succeeds.
- The default worker concurrency is one heavy job at a time for a 16 GB laptop.

See [EXTERNAL_SETUP_GUIDE.md](EXTERNAL_SETUP_GUIDE.md) before connecting YouTube, Ollama, Faster-Whisper, or Supabase.
