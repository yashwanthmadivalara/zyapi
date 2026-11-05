# ViralFlow AI development status

## Current milestone

The local AI video-processing path is operational through subtitle burn-in and preview retrieval:

`authorized upload → FFprobe → FFmpeg audio extraction → Faster-Whisper → Ollama/Qwen analysis → validated moments → vertical FFmpeg clip → SRT → burned-in subtitles → preview`

## Implemented in this milestone

- Faster-Whisper CPU/INT8 transcription with language detection and timestamped segments.
- Ollama `qwen2.5:3b` analysis with JSON parsing, limited retries, timestamp alignment, range checks, and overlap filtering.
- Persisted AI candidate fields: title, hook, explanation, category, caption, score, and timestamps.
- FFmpeg clip validation for dimensions, duration, video stream, and source audio preservation.
- SRT generation and FFmpeg burned-in subtitles.
- Processing status, job records, retry endpoints, preview endpoint, and frontend workflow controls.

## Deliberately not in this milestone

YouTube OAuth/publishing, analytics, cloud deployment, and autonomous background workers remain outside the local AI pipeline task.
