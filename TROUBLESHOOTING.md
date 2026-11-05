# Troubleshooting

## Backend dependencies

```powershell
cd backend
..\backend\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use the project virtual environment. Faster-Whisper downloads its selected model the first time it runs.

## FFmpeg / FFprobe

Verify:

```powershell
ffmpeg -version
ffprobe -version
```

The upload requires a video and audio stream for transcription. A video-only file receives a clear validation error.

## Ollama / Qwen

Start Ollama, confirm the model is present, then test:

```powershell
Invoke-WebRequest http://127.0.0.1:11434/api/tags
ollama list
```

Set `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in `backend/.env`. The API retries malformed JSON a limited number of times and records failures in `jobs` and `activity`.

## Processing failures

Check `/api/videos/{video_id}/status` for the video state, job messages, moments, and clips. Retry transcription or analysis with `POST /api/videos/{video_id}/retry` and JSON `{"kind":"transcription"}` or `{"kind":"analysis"}`.

## Resource limits

The default Whisper configuration is CPU/INT8. Use the `tiny` model for a quick smoke test and `base` for better quality after confirming memory and processing time on the laptop. The local API currently processes one request at a time by operator usage; a durable background worker is still a future task.
