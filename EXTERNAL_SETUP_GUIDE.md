# External setup guide

No external account is required to start the dashboard and local library. Do not paste secrets into source files or chat.

## Optional integrations

1. **FFmpeg / FFprobe**: install FFmpeg and ensure both `ffmpeg` and `ffprobe` are on PATH. The API reports unavailable until it can execute them.
2. **Ollama**: install Ollama locally, pull a model such as `qwen2.5:3b`, then set `OLLAMA_BASE_URL` and `OLLAMA_MODEL`. The health check calls `/api/tags`.
3. **Faster-Whisper**: install the package and choose a model only after benchmarking your laptop. The initial API keeps the adapter optional so the app still starts without it.
4. **YouTube OAuth**: create OAuth credentials in Google Cloud only after deciding the exact destination channel and redirect URL. Set the client ID/secret on the backend only. No upload is enabled by this scaffold.
5. **Supabase**: the local MVP uses SQLite. Move to Supabase only after the local workflow is stable; use a server-only connection string and database policies.

## Phase 6–10 workflow

1. Store a transcript with timestamped `segments`.
2. Detect moments, extract a clip, generate metadata, and generate SRT/ASS subtitles.
3. Manually approve the clip before scheduling.
4. Schedule with preferred weekdays/hours, a daily cap, and minimum interval.
5. Configure Google OAuth and place an authorized token at `YOUTUBE_TOKEN_PATH` before publishing. The publishing endpoint uses a resumable upload and records success or failure.

## What still requires your confirmation

- Which authorized source-video folder should be used for long-running processing.
- Whether you want local SQLite to remain the development database or to connect Supabase.
- The Google OAuth redirect URL and destination channel before enabling publishing.

The application will show `not_configured`, `unavailable`, or `connected` based on checks. It never assumes an integration works.

Until Faster-Whisper is installed, a transcript can be supplied through the protected backend API for development and review. Moment candidates created from that transcript are clearly marked as deterministic heuristics and still require manual approval.

Publishing remains blocked unless the clip is approved or scheduled, YouTube client credentials are present, an OAuth token exists, and the Google client libraries are installed. No upload is simulated.
