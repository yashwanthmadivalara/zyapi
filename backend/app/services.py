import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
import httpx
from .config import settings

logger = logging.getLogger("viralflow")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ffprobe(path: Path):
    if not shutil.which("ffprobe"):
        return {"available": False, "message": "ffprobe is not installed or not on PATH"}
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            return {"available": True, "valid": False, "message": p.stderr.strip() or "ffprobe rejected the file"}
        data = json.loads(p.stdout)
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        has_video = bool(video)
        has_audio = bool(audio)
        return {"available": True, "valid": bool(video and audio), "has_video": has_video, "has_audio": has_audio, "duration_seconds": float(data.get("format", {}).get("duration", 0) or 0), "width": video.get("width") if video else None, "height": video.get("height") if video else None, "message": "ok" if video and audio else "file must contain both video and audio streams"}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "valid": False, "message": str(exc)}


def extract_audio_for_transcription(video_path: Path) -> Path:
    """Extract mono 16 kHz PCM audio to a temporary WAV for Faster-Whisper."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed or not on PATH")
    temp = tempfile.NamedTemporaryFile(prefix="viralflow-audio-", suffix=".wav", dir=settings.upload_dir, delete=False)
    temp_path = Path(temp.name)
    temp.close()
    command = ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temp_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(result.stderr[-1200:] or "ffmpeg could not extract audio")
    return temp_path


def transcribe_video(video_path: Path, model_name: str | None = None, language: str | None = None) -> dict:
    """Transcribe a locally stored video using Faster-Whisper on CPU by default."""
    probe = ffprobe(video_path)
    if not probe.get("available"):
        raise RuntimeError(probe.get("message", "ffprobe is required"))
    if not probe.get("valid"):
        raise ValueError(probe.get("message", "video must contain both video and audio streams"))
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed in the active Python environment") from exc

    audio_path = extract_audio_for_transcription(video_path)
    try:
        import numpy as np
        selected_model = model_name or settings.whisper_model
        logger.info("Loading Faster-Whisper model=%s device=%s compute_type=%s", selected_model, settings.whisper_device, settings.whisper_compute_type)
        model = WhisperModel(selected_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type)
        with wave.open(str(audio_path), "rb") as wav:
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = model.transcribe(audio, language=language, vad_filter=True, beam_size=5)
        segment_list = []
        text_parts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                text_parts.append(text)
                segment_list.append({"start": round(float(segment.start), 3), "end": round(float(segment.end), 3), "text": text})
        return {"text": " ".join(text_parts).strip(), "segments": segment_list, "language": info.language, "language_probability": float(info.language_probability)}
    finally:
        audio_path.unlink(missing_ok=True)


async def ollama_health():
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            names = [m.get("name") for m in models]
            return {"status": "connected", "model": settings.ollama_model, "model_available": settings.ollama_model in names, "models": names}
    except Exception as exc:
        return {"status": "unavailable", "message": str(exc)}


def _json_from_model_response(content: str):
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = min([i for i in (cleaned.find("["), cleaned.find("{")) if i >= 0], default=-1)
        if start < 0:
            raise ValueError("Qwen response did not contain JSON")
        end = max(cleaned.rfind("]"), cleaned.rfind("}"))
        if end <= start:
            raise ValueError("Qwen response contained incomplete JSON")
        return json.loads(cleaned[start:end + 1])


def validate_moment_candidates(raw, transcript_segments: list[dict], video_duration: float, target_duration: int) -> list[dict]:
    """Validate and align model output to real Whisper segment timestamps."""
    if not isinstance(raw, list):
        raise ValueError("Qwen response must be a JSON array")
    valid_segments = [s for s in transcript_segments if float(s.get("end", 0)) > float(s.get("start", 0)) and str(s.get("text", "")).strip()]
    if not valid_segments:
        raise ValueError("No timestamped transcript segments are available")
    results = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            proposed_start = float(item["start_seconds"])
            proposed_end = float(item["end_seconds"])
            if proposed_end <= proposed_start:
                continue
            overlapping = [s for s in valid_segments if float(s["end"]) > proposed_start and float(s["start"]) < proposed_end]
            if not overlapping:
                continue
            start = max(0.0, min(float(s["start"]) for s in overlapping))
            end = min(float(video_duration), max(float(s["end"]) for s in overlapping))
            length = end - start
            if length < 10 or length > 65:
                continue
            score = float(item.get("quality_score", item.get("score", 0)))
            if not 1 <= score <= 10:
                continue
            title = str(item.get("suggested_title", item.get("title", ""))).strip()
            hook = str(item.get("opening_hook", item.get("hook", ""))).strip()
            explanation = str(item.get("explanation", "")).strip()
            category = str(item.get("content_category", item.get("category", "general"))).strip()
            caption = str(item.get("suggested_caption", item.get("caption", ""))).strip()
            if not title or not hook or not explanation:
                continue
            results.append({"start_seconds": round(start, 3), "end_seconds": round(end, 3), "title": title[:160], "hook": hook[:500], "rationale": explanation[:1000], "category": category[:80], "caption": caption[:500], "score": round(score, 2), "target_duration": target_duration})
        except (KeyError, TypeError, ValueError):
            continue
    results.sort(key=lambda x: (-x["score"], x["start_seconds"]))
    non_overlapping = []
    for candidate in results:
        if any(candidate["start_seconds"] < existing["end_seconds"] and candidate["end_seconds"] > existing["start_seconds"] for existing in non_overlapping):
            continue
        non_overlapping.append(candidate)
    if not non_overlapping:
        raise ValueError("Qwen returned no valid self-contained moments")
    return non_overlapping[:3]


async def analyze_transcript_with_ollama(transcript_segments: list[dict], video_duration: float, target_duration: int = 30, retries: int = 2) -> list[dict]:
    if target_duration not in {15, 30, 45, 60}:
        raise ValueError("target_duration must be 15, 30, 45, or 60")
    transcript = json.dumps(transcript_segments, ensure_ascii=False)
    prompt = f"""Analyze this timestamped transcript for up to three self-contained YouTube Shorts moments.\n\nVideo duration: {video_duration:.3f} seconds. Target duration: {target_duration} seconds.\nUse only timestamps present in the transcript segments. Never invent dialogue or timestamps. Keep each moment between 10 and 65 seconds, within the video, and avoid overlap. Return JSON only as an array with objects containing: start_seconds, end_seconds, suggested_title, opening_hook, explanation, content_category, suggested_caption, quality_score (1-10).\n\nTranscript segments:\n{transcript}"""
    last_error = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(f"{settings.ollama_base_url.rstrip('/')}/api/chat", json={"model": settings.ollama_model, "messages": [{"role": "system", "content": "You are a precise transcript editor. Output valid JSON only."}, {"role": "user", "content": prompt}], "stream": False, "options": {"temperature": 0.15}})
                response.raise_for_status()
                payload = response.json()
                content = payload.get("message", {}).get("content", "")
                parsed = _json_from_model_response(content)
                return validate_moment_candidates(parsed, transcript_segments, video_duration, target_duration)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
            last_error = exc
            logger.warning("Ollama analysis attempt %s/%s failed: %s", attempt + 1, retries + 1, exc)
    raise RuntimeError(f"Ollama analysis failed after {retries + 1} attempts: {last_error}")


def integration_health():
    return {"ffmpeg": {"status": "connected" if shutil.which("ffmpeg") else "unavailable"}, "ffprobe": {"status": "connected" if shutil.which("ffprobe") else "unavailable"}, "youtube_oauth": {"status": "configured" if settings.youtube_client_id and settings.youtube_client_secret else "not_configured"}, "database": {"status": "connected", "type": "sqlite"}, "whisper": {"status": "not_configured", "model": settings.whisper_model}}


def extract_clip(source: Path, target: Path, start: float, duration: float) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed or not on PATH")
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}", "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920", "-c:v", "libx264", "-preset", settings.clip_preset, "-crf", str(settings.clip_crf), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(target)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1000:] or "ffmpeg failed to extract the clip")


def validate_clip_output(path: Path, source_has_audio: bool, expected_duration: float) -> dict:
    probe = ffprobe(path)
    if not probe.get("available"):
        raise RuntimeError("ffprobe is required to validate generated clips")
    if not probe.get("has_video"):
        raise ValueError("generated clip has no video stream")
    if source_has_audio and not probe.get("has_audio"):
        raise ValueError("generated clip lost the source audio stream")
    if not probe.get("width") or not probe.get("height") or probe["width"] <= 0 or probe["height"] <= 0:
        raise ValueError("generated clip has invalid dimensions")
    actual = float(probe.get("duration_seconds") or 0)
    if actual <= 0 or abs(actual - expected_duration) > 1.5:
        raise ValueError(f"generated clip duration {actual:.2f}s differs from expected {expected_duration:.2f}s")
    return probe


def burn_subtitles(clip_path: Path, subtitle_path: Path, target_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed or not on PATH")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    subtitle_filter_path = str(subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    command = ["ffmpeg", "-y", "-i", str(clip_path), "-vf", f"subtitles='{subtitle_filter_path}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=80'", "-c:v", "libx264", "-preset", settings.clip_preset, "-crf", str(settings.clip_crf), "-c:a", "copy", "-movflags", "+faststart", str(target_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1500:] or "ffmpeg failed to burn subtitles")


def write_srt(target: Path, segments: list[dict], clip_start: float, clip_end: float) -> None:
    lines = []
    number = 1
    for segment in segments:
        start = max(float(segment.get("start", 0)), clip_start)
        end = min(float(segment.get("end", 0)), clip_end)
        text = str(segment.get("text", "")).strip()
        if end <= start or not text:
            continue
        def stamp(seconds):
            ms = int(round((seconds - int(seconds)) * 1000))
            whole = int(seconds)
            return f"{whole // 3600:02}:{(whole % 3600) // 60:02}:{whole % 60:02},{ms:03}"
        lines.extend([str(number), f"{stamp(start - clip_start)} --> {stamp(end - clip_start)}", text, ""])
        number += 1
    target.write_text("\n".join(lines), encoding="utf-8")
