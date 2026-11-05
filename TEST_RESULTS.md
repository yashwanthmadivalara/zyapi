# ViralFlow AI test results

Date: 2026-11-05

## Automated tests

Run with:

```powershell
$env:PYTHONPATH='backend'
backend\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp=tmp\pytest
```

The non-network/unit and validation tests pass in the project virtual environment. Integration tests are marked and require `VIRALFLOW_TEST_VIDEO`.

## Real integrations verified

- Faster-Whisper: passed against `How to Create Stickman Stand Up Videos.mp4`; English transcript persisted with 12 timestamped segments.
- Ollama/Qwen: passed with local `qwen2.5:3b`; validated moments persisted with timestamps and quality fields.
- FFmpeg/FFprobe: passed for audio extraction, vertical clip generation, stream/duration/dimension validation, SRT generation, subtitle burn-in, and preview retrieval.
- Frontend: `npm run build` passed.

## Known warnings

- FastAPI's existing `on_event` startup hook is deprecated but still functional.
- Next.js 14.2.21 reports a dependency security advisory during `npm install`; upgrading it is a separate maintenance task.
