import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .config import settings
from .db import connection, init_db, row, rows
from .services import analyze_transcript_with_ollama, burn_subtitles, extract_clip, ffprobe, integration_health, now, ollama_health, sha256_file, transcribe_video, validate_clip_output, write_srt

logger = logging.getLogger("viralflow.api")

app = FastAPI(title="ViralFlow AI API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def mutation_auth(request: Request, call_next):
    if settings.api_access_token and request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("authorization") != f"Bearer {settings.api_access_token}":
            return JSONResponse(status_code=401, content={"detail": "Bearer API access token required"})
    return await call_next(request)


@app.on_event("startup")
def startup():
    init_db()


class ChannelIn(BaseModel):
    channel_id: str = Field(min_length=2, max_length=200)
    url: str = Field(min_length=8, max_length=500)
    name: str | None = None
    monitoring_minutes: int = Field(default=60, ge=15, le=1440)


class TranscriptIn(BaseModel):
    text: str = Field(min_length=20, max_length=2_000_000)
    model: str = Field(default="manual-or-external", max_length=100)
    segments: list[dict] = Field(default_factory=list)


class TranscriptionIn(BaseModel):
    model: str | None = None
    language: str | None = Field(default=None, min_length=2, max_length=10)


class AnalysisIn(BaseModel):
    target_duration: int = Field(default=30)


class RetryIn(BaseModel):
    kind: str


class ClipExtractIn(BaseModel):
    duration_seconds: float = Field(default=30, ge=5, le=120)


class ReviewIn(BaseModel):
    status: str
    title: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None


class ScheduleIn(BaseModel):
    preferred_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    preferred_hours: list[int] = Field(default_factory=lambda: [9, 13, 18])
    daily_cap: int = Field(default=3, ge=1, le=20)
    minimum_interval_hours: int = Field(default=4, ge=1, le=168)
    timezone: str = "Asia/Kolkata"


class PublishIn(BaseModel):
    visibility: str = "private"


class ServiceControlIn(BaseModel):
    action: str
    message: str | None = None


class AnalyticsSnapshotIn(BaseModel):
    clip_id: int | None = None
    remote_video_id: str | None = None
    views: int = Field(ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    subscribers_gained: int = Field(default=0, ge=0)
    source: str = "manual-or-youtube-api"


@app.get("/health")
def health():
    return {"status": "ok", "service": "viralflow-api", "time": now()}


@app.get("/api/dashboard")
def dashboard():
    counts = {k: row("SELECT COUNT(*) AS count FROM " + table)["count"] for k, table in {"channels": "channels", "videos": "videos", "jobs": "jobs", "moments": "moments", "clips": "clips"}.items()}
    counts["pending_approval"] = row("SELECT COUNT(*) AS count FROM moments WHERE status='candidate'")["count"]
    counts["scheduled"] = row("SELECT COUNT(*) AS count FROM clips WHERE status='scheduled'")["count"]
    counts["published"] = row("SELECT COUNT(*) AS count FROM clips WHERE status='published'")["count"]
    counts["failures"] = row("SELECT COUNT(*) AS count FROM jobs WHERE status='failed'")["count"]
    return {"counts": counts, "activity": rows("SELECT * FROM activity ORDER BY id DESC LIMIT 20"), "jobs": rows("SELECT * FROM jobs ORDER BY id DESC LIMIT 10")}


SERVICE_NAMES = ["source_monitoring", "video_detection", "transcription", "ai_analysis", "clip_extraction", "subtitle_generation", "scheduler", "youtube_publishing"]


@app.get("/api/services")
def service_status():
    result = []
    for name in SERVICE_NAMES:
        state = row("SELECT * FROM service_state WHERE service_name=?", (name,))
        result.append(state or {"service_name": name, "status": "paused", "last_run_at": None, "next_run_at": None, "message": "Not started"})
    return result


@app.post("/api/services/{service_name}/control")
def control_service(service_name: str, payload: ServiceControlIn):
    if service_name not in SERVICE_NAMES:
        raise HTTPException(404, "Unknown service")
    if payload.action not in {"start", "pause", "resume", "stop", "retry"}:
        raise HTTPException(400, "Action must be start, pause, resume, stop, or retry")
    status = "running" if payload.action in {"start", "resume", "retry"} else "paused" if payload.action == "pause" else "stopped"
    message = payload.message or f"{service_name} {payload.action} requested"
    with connection() as con:
        con.execute("INSERT INTO service_state(service_name,status,last_run_at,message,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(service_name) DO UPDATE SET status=excluded.status,last_run_at=excluded.last_run_at,message=excluded.message,updated_at=excluded.updated_at", (service_name, status, now(), message, now()))
        con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("service_control", message, now()))
        return dict(con.execute("SELECT * FROM service_state WHERE service_name=?", (service_name,)).fetchone())


@app.get("/api/analytics")
def analytics():
    totals = row("SELECT COALESCE(SUM(views),0) views, COALESCE(SUM(likes),0) likes, COALESCE(SUM(comments),0) comments, COALESCE(SUM(subscribers_gained),0) subscribers_gained FROM analytics_snapshots")
    top = rows("SELECT c.id,c.title,c.published_url,MAX(a.views) views,MAX(a.likes) likes FROM analytics_snapshots a LEFT JOIN clips c ON c.id=a.clip_id GROUP BY c.id ORDER BY views DESC LIMIT 10")
    return {"status": "available" if totals["views"] or totals["likes"] or totals["comments"] else "no_data", "totals": totals, "top_clips": top, "note": "Metrics are zero only when no snapshots have been collected; unavailable YouTube API data is not converted to zero."}


@app.post("/api/analytics/snapshots", status_code=201)
def save_analytics_snapshot(payload: AnalyticsSnapshotIn):
    with connection() as con:
        cur = con.execute("INSERT INTO analytics_snapshots(clip_id,remote_video_id,views,likes,comments,subscribers_gained,captured_at,source) VALUES (?,?,?,?,?,?,?,?)", (payload.clip_id, payload.remote_video_id, payload.views, payload.likes, payload.comments, payload.subscribers_gained, now(), payload.source))
        return dict(con.execute("SELECT * FROM analytics_snapshots WHERE id=?", (cur.lastrowid,)).fetchone())


@app.get("/api/integrations")
async def integrations():
    health_state = integration_health()
    health_state["ollama"] = await ollama_health()
    return health_state


@app.get("/api/channels")
def list_channels():
    return rows("SELECT * FROM channels ORDER BY id DESC")


@app.post("/api/channels", status_code=201)
def add_channel(payload: ChannelIn):
    try:
        with connection() as con:
            cur = con.execute("INSERT INTO channels(channel_id,url,name,monitoring_minutes,created_at) VALUES (?,?,?,?,?)", (payload.channel_id, payload.url, payload.name, payload.monitoring_minutes, now()))
            con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("channel_added", f"Added source channel {payload.channel_id}", now()))
            return dict(con.execute("SELECT * FROM channels WHERE id=?", (cur.lastrowid,)).fetchone())
    except Exception as exc:
        raise HTTPException(409, f"Channel was not added: {exc}")


@app.get("/api/videos")
def list_videos():
    return rows("SELECT * FROM videos ORDER BY id DESC")


@app.get("/api/clips")
def list_clips():
    return rows("SELECT * FROM clips ORDER BY id DESC")


@app.post("/api/videos/upload", status_code=201)
async def upload_video(file: UploadFile = File(...), authorized: bool = False):
    if not authorized:
        raise HTTPException(400, "Confirm that you own or are authorized to process this file.")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
        raise HTTPException(400, "Unsupported video type.")
    target = Path(settings.upload_dir) / f"{now().replace(':', '-')}_{Path(file.filename).name}"
    total = 0
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                target.unlink(missing_ok=True)
                raise HTTPException(413, "File exceeds MAX_UPLOAD_BYTES.")
            out.write(chunk)
    digest = sha256_file(target)
    probe = ffprobe(target)
    if probe.get("available") and not probe.get("valid"):
        target.unlink(missing_ok=True)
        raise HTTPException(400, probe["message"])
    try:
        with connection() as con:
            cur = con.execute("INSERT INTO videos(filename,storage_path,sha256,size_bytes,duration_seconds,width,height,authorized,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (Path(file.filename).name, str(target), digest, total, probe.get("duration_seconds"), probe.get("width"), probe.get("height"), 1, now()))
            con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("video_imported", f"Imported authorized video {file.filename}", now()))
            return dict(con.execute("SELECT * FROM videos WHERE id=?", (cur.lastrowid,)).fetchone())
    except Exception:
        target.unlink(missing_ok=True)
        raise HTTPException(409, "A video with identical content already exists or could not be stored.")


@app.get("/api/videos/{video_id}/moments")
def moments(video_id: int):
    if not row("SELECT id FROM videos WHERE id=?", (video_id,)):
        raise HTTPException(404, "Video not found")
    return rows("SELECT * FROM moments WHERE video_id=? ORDER BY score DESC", (video_id,))


@app.get("/api/videos/{video_id}/status")
def video_processing_status(video_id: int):
    video = row("SELECT * FROM videos WHERE id=?", (video_id,))
    if not video:
        raise HTTPException(404, "Video not found")
    return {"video": video, "jobs": rows("SELECT * FROM jobs WHERE video_id=? ORDER BY id DESC", (video_id,)), "moments": rows("SELECT * FROM moments WHERE video_id=? ORDER BY score DESC", (video_id,)), "clips": rows("SELECT * FROM clips WHERE video_id=? ORDER BY id DESC", (video_id,))}


@app.post("/api/videos/{video_id}/transcript", status_code=201)
def save_transcript(video_id: int, payload: TranscriptIn):
    if not row("SELECT id FROM videos WHERE id=?", (video_id,)):
        raise HTTPException(404, "Video not found")
    with connection() as con:
        con.execute("INSERT INTO transcripts(video_id,text,model,segments_json,created_at) VALUES (?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET text=excluded.text, model=excluded.model, segments_json=excluded.segments_json, created_at=excluded.created_at", (video_id, payload.text, payload.model, json.dumps(payload.segments), now()))
        con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("transcript_saved", f"Transcript saved for video {video_id} using {payload.model}", now()))
        return dict(con.execute("SELECT * FROM transcripts WHERE video_id=?", (video_id,)).fetchone())


@app.post("/api/videos/{video_id}/transcribe", status_code=201)
def transcribe_uploaded_video(video_id: int, payload: TranscriptionIn | None = None):
    """Extract audio and transcribe an authorized, locally stored video."""
    video = row("SELECT * FROM videos WHERE id=?", (video_id,))
    if not video:
        raise HTTPException(404, "Video not found")
    if not video["authorized"]:
        raise HTTPException(403, "Only authorized videos can be transcribed")
    source = Path(video["storage_path"])
    if not source.is_file():
        raise HTTPException(404, "Stored video file is missing")
    probe = ffprobe(source)
    if not probe.get("available"):
        raise HTTPException(503, probe.get("message", "ffprobe is required"))
    if not probe.get("valid"):
        raise HTTPException(422, probe.get("message", "video must contain both video and audio streams"))

    request = payload or TranscriptionIn()
    stamp = now()
    with connection() as con:
        cur = con.execute("INSERT INTO jobs(video_id,kind,status,progress,message,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (video_id, "transcription", "running", 10, "Extracting audio and loading Faster-Whisper", stamp, stamp))
        job_id = cur.lastrowid
        con.execute("UPDATE videos SET status='transcribing' WHERE id=?", (video_id,))
    try:
        result = transcribe_video(source, model_name=request.model, language=request.language)
        if not result["text"]:
            raise ValueError("No speech was detected in the audio")
        model_name = request.model or settings.whisper_model
        completed = now()
        with connection() as con:
            con.execute("INSERT INTO transcripts(video_id,text,model,segments_json,created_at) VALUES (?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET text=excluded.text, model=excluded.model, segments_json=excluded.segments_json, created_at=excluded.created_at", (video_id, result["text"], model_name, json.dumps(result["segments"]), completed))
            con.execute("UPDATE jobs SET status='completed',progress=100,message=?,updated_at=? WHERE id=?", (f"Transcription complete; detected language {result['language']}", completed, job_id))
            con.execute("UPDATE videos SET status='transcribed' WHERE id=?", (video_id,))
            con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("transcription_completed", f"Transcribed video {video_id}; language={result['language']}", completed))
            saved = dict(con.execute("SELECT * FROM transcripts WHERE video_id=?", (video_id,)).fetchone())
        return {"job_id": job_id, "video_id": video_id, "language": result["language"], "language_probability": result["language_probability"], "transcript": saved}
    except ValueError as exc:
        message = str(exc)
        logger.warning("Transcription rejected for video_id=%s: %s", video_id, message)
        with connection() as con:
            con.execute("UPDATE jobs SET status='failed',progress=0,message=?,updated_at=? WHERE id=?", (message, now(), job_id))
            con.execute("UPDATE videos SET status='failed' WHERE id=?", (video_id,))
        raise HTTPException(422, message)
    except Exception as exc:
        logger.exception("Transcription failed for video_id=%s", video_id)
        with connection() as con:
            con.execute("UPDATE jobs SET status='failed',progress=0,message=?,updated_at=? WHERE id=?", (str(exc), now(), job_id))
            con.execute("UPDATE videos SET status='failed' WHERE id=?", (video_id,))
        raise HTTPException(502, f"Transcription failed: {exc}")


@app.post("/api/videos/{video_id}/analyze", status_code=201)
async def analyze_video(video_id: int, payload: AnalysisIn | None = None):
    """Use Ollama/Qwen to identify validated moments from the saved transcript."""
    video = row("SELECT * FROM videos WHERE id=?", (video_id,))
    if not video:
        raise HTTPException(404, "Video not found")
    transcript = row("SELECT * FROM transcripts WHERE video_id=?", (video_id,))
    if not transcript:
        raise HTTPException(409, "Transcribe the video before analysis")
    segments = json.loads(transcript["segments_json"] or "[]")
    request = payload or AnalysisIn()
    if request.target_duration not in {15, 30, 45, 60}:
        raise HTTPException(400, "target_duration must be 15, 30, 45, or 60")
    stamp = now()
    with connection() as con:
        cur = con.execute("INSERT INTO jobs(video_id,kind,status,progress,message,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (video_id, "analysis", "running", 10, "Sending timestamped transcript to Ollama", stamp, stamp))
        job_id = cur.lastrowid
        con.execute("UPDATE videos SET status='analyzing' WHERE id=?", (video_id,))
    try:
        candidates = await analyze_transcript_with_ollama(segments, float(video.get("duration_seconds") or 0), request.target_duration)
        completed = now()
        with connection() as con:
            con.execute("DELETE FROM moments WHERE video_id=? AND status='candidate'", (video_id,))
            for candidate in candidates:
                con.execute("INSERT INTO moments(video_id,start_seconds,end_seconds,title,rationale,hook,category,caption,score,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (video_id, candidate["start_seconds"], candidate["end_seconds"], candidate["title"], candidate["rationale"], candidate["hook"], candidate["category"], candidate["caption"], candidate["score"], "candidate", completed))
            con.execute("UPDATE jobs SET status='completed',progress=100,message=?,updated_at=? WHERE id=?", (f"Qwen identified {len(candidates)} moments", completed, job_id))
            con.execute("UPDATE videos SET status='analyzed' WHERE id=?", (video_id,))
            con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("analysis_completed", f"Analyzed video {video_id} with Ollama/Qwen", completed))
        return {"job_id": job_id, "video_id": video_id, "target_duration": request.target_duration, "moments": rows("SELECT * FROM moments WHERE video_id=? AND status='candidate' ORDER BY score DESC", (video_id,))}
    except Exception as exc:
        logger.exception("Analysis failed for video_id=%s", video_id)
        with connection() as con:
            con.execute("UPDATE jobs SET status='failed',progress=0,message=?,updated_at=? WHERE id=?", (str(exc), now(), job_id))
            con.execute("UPDATE videos SET status='failed' WHERE id=?", (video_id,))
            con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("analysis_failed", f"Analysis failed for video {video_id}: {exc}", now()))
        raise HTTPException(502, f"AI analysis failed: {exc}")


@app.post("/api/videos/{video_id}/retry")
async def retry_video_processing(video_id: int, payload: RetryIn):
    if payload.kind == "transcription":
        return transcribe_uploaded_video(video_id, None)
    if payload.kind == "analysis":
        return await analyze_video(video_id, None)
    raise HTTPException(400, "kind must be transcription or analysis")


@app.post("/api/videos/{video_id}/moments/detect", status_code=201)
def detect_moments(video_id: int):
    """Create transparent heuristic candidates from an already stored transcript.

    This endpoint intentionally does not claim that a segment is viral. The Qwen adapter can
    replace this selection later after Ollama is configured and its JSON is validated.
    """
    if not row("SELECT id FROM videos WHERE id=?", (video_id,)):
        raise HTTPException(404, "Video not found")
    transcript = row("SELECT * FROM transcripts WHERE video_id=?", (video_id,))
    if not transcript:
        raise HTTPException(409, "No transcript is stored. Configure Faster-Whisper or save an authorized transcript first.")
    chunks = [part.strip() for part in transcript["text"].replace("\n", " ").split(".") if len(part.strip()) >= 40]
    if not chunks:
        raise HTTPException(422, "Transcript does not contain enough text to make a candidate.")
    candidates = []
    for index, chunk in enumerate(chunks[:3]):
        start = float(index * 30)
        end = start + 30.0
        score = round(min(0.95, 0.55 + min(len(chunk), 220) / 1000), 3)
        candidates.append((video_id, start, end, "Deterministic transcript-length heuristic; validate context before approval.", chunk[:110], score, now()))
    with connection() as con:
        con.execute("DELETE FROM moments WHERE video_id=? AND status='candidate'", (video_id,))
        con.executemany("INSERT INTO moments(video_id,start_seconds,end_seconds,rationale,hook,score,created_at) VALUES (?,?,?,?,?,?,?)", candidates)
        con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("moments_detected", f"Detected {len(candidates)} reviewable candidates for video {video_id}", now()))
    return rows("SELECT * FROM moments WHERE video_id=? ORDER BY score DESC", (video_id,))


@app.post("/api/moments/{moment_id}/extract", status_code=201)
def extract_moment(moment_id: int, payload: ClipExtractIn):
    moment = row("SELECT * FROM moments WHERE id=?", (moment_id,))
    if not moment:
        raise HTTPException(404, "Moment not found")
    video = row("SELECT * FROM videos WHERE id=?", (moment["video_id"],))
    if not video or not video["authorized"]:
        raise HTTPException(403, "Only authorized videos can be extracted")
    start = max(0.0, float(moment["start_seconds"]))
    available = float(video.get("duration_seconds") or 0)
    duration = min(payload.duration_seconds, max(0.1, float(moment["end_seconds"]) - start))
    if available:
        duration = min(duration, max(0.1, available - start))
    stamp = now()
    target = Path(settings.clip_dir) / f"video-{video['id']}-moment-{moment_id}-{stamp.replace(':', '-')}.mp4"
    try:
        source_probe = ffprobe(Path(video["storage_path"]))
        if not source_probe.get("valid"):
            raise ValueError("source video must contain both video and audio streams")
        extract_clip(Path(video["storage_path"]), target, start, duration)
        clip_probe = validate_clip_output(target, bool(source_probe.get("has_audio")), duration)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(422, f"Clip extraction failed: {exc}")
    with connection() as con:
        cur = con.execute("INSERT INTO clips(video_id,moment_id,storage_path,start_seconds,duration_seconds,width,height,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (video["id"], moment_id, str(target), start, duration, clip_probe["width"], clip_probe["height"], "generated", stamp, stamp))
        con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("clip_extracted", f"Extracted clip from moment {moment_id}", stamp))
        return dict(con.execute("SELECT * FROM clips WHERE id=?", (cur.lastrowid,)).fetchone())


@app.post("/api/clips/{clip_id}/metadata")
def generate_metadata(clip_id: int):
    clip = row("SELECT c.*, m.hook FROM clips c JOIN moments m ON m.id=c.moment_id WHERE c.id=?", (clip_id,))
    if not clip:
        raise HTTPException(404, "Clip not found")
    hook = (clip.get("hook") or "Interesting moment").strip()
    title = hook[:90].rstrip(".!?")
    description = f"A short excerpt from an authorized source video.\n\n{hook}"
    hashtags = ["#shorts", "#viralflow"]
    with connection() as con:
        con.execute("UPDATE clips SET title=?,description=?,hashtags=?,updated_at=? WHERE id=?", (title, description, json.dumps(hashtags), now(), clip_id))
        con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("metadata_generated", f"Generated editable metadata for clip {clip_id}", now()))
        return dict(con.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())


@app.post("/api/clips/{clip_id}/subtitles", status_code=201)
def generate_subtitles(clip_id: int, subtitle_format: str = "srt", burn_in: bool = False):
    clip = row("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not clip:
        raise HTTPException(404, "Clip not found")
    if subtitle_format not in {"srt", "ass"}:
        raise HTTPException(400, "subtitle_format must be srt or ass")
    transcript = row("SELECT * FROM transcripts WHERE video_id=(SELECT video_id FROM clips WHERE id=?)", (clip_id,))
    if not transcript or not transcript["segments_json"]:
        raise HTTPException(409, "Word or segment timestamps are required for synchronized subtitles.")
    segments = json.loads(transcript["segments_json"])
    target = Path(settings.clip_dir) / f"clip-{clip_id}.{subtitle_format}"
    if subtitle_format == "srt":
        write_srt(target, segments, float(clip["start_seconds"]), float(clip["start_seconds"]) + float(clip["duration_seconds"]))
    else:
        temp = Path(settings.clip_dir) / f"clip-{clip_id}.srt"
        write_srt(temp, segments, float(clip["start_seconds"]), float(clip["start_seconds"]) + float(clip["duration_seconds"]))
        lines = temp.read_text(encoding="utf-8").splitlines()
        dialogues = []
        for i in range(0, len(lines), 4):
            if i + 2 < len(lines):
                start, end = lines[i + 1].replace(",", ".").split(" --> ")
                dialogues.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{lines[i + 2]}")
        target.write_text("[Script Info]\n[V4+ Styles]\n[Events]\nFormat: Layer, Start, End, Style, Text\n" + "\n".join(dialogues), encoding="utf-8")
    burned_path = None
    if burn_in:
        if subtitle_format != "ass" and subtitle_format != "srt":
            raise HTTPException(400, "burn_in requires srt or ass subtitles")
        burned = Path(settings.clip_dir) / f"clip-{clip_id}-subtitled.mp4"
        try:
            burn_subtitles(Path(clip["storage_path"]), target, burned)
            validate_clip_output(burned, True, float(clip["duration_seconds"]))
            burned_path = str(burned)
        except Exception as exc:
            raise HTTPException(422, f"Subtitle burn-in failed: {exc}")
    with connection() as con:
        cur = con.execute("INSERT INTO subtitles(clip_id,format,storage_path,created_at) VALUES (?,?,?,?)", (clip_id, subtitle_format, str(target), now()))
        subtitle = dict(con.execute("SELECT * FROM subtitles WHERE id=?", (cur.lastrowid,)).fetchone())
        subtitle["burned_video_path"] = burned_path
        return subtitle


@app.get("/api/clips/{clip_id}/subtitles")
def list_subtitles(clip_id: int):
    if not row("SELECT id FROM clips WHERE id=?", (clip_id,)):
        raise HTTPException(404, "Clip not found")
    return rows("SELECT * FROM subtitles WHERE clip_id=? ORDER BY id DESC", (clip_id,))


@app.get("/api/clips/{clip_id}/file")
def get_clip_file(clip_id: int):
    clip = row("SELECT clips.storage_path AS storage_path, videos.filename AS filename FROM clips JOIN videos ON videos.id=clips.video_id WHERE clips.id=?", (clip_id,))
    if not clip or not Path(clip["storage_path"]).is_file():
        raise HTTPException(404, "Clip file not found")
    return FileResponse(clip["storage_path"], media_type="video/mp4", filename=f"viralflow-clip-{clip_id}.mp4")


@app.post("/api/clips/{clip_id}/review")
def review_clip(clip_id: int, payload: ReviewIn):
    if payload.status not in {"approved", "rejected"}:
        raise HTTPException(400, "Review status must be approved or rejected")
    if not row("SELECT id FROM clips WHERE id=?", (clip_id,)):
        raise HTTPException(404, "Clip not found")
    with connection() as con:
        con.execute("UPDATE clips SET status=?,title=COALESCE(?,title),description=COALESCE(?,description),hashtags=COALESCE(?,hashtags),updated_at=? WHERE id=?", (payload.status, payload.title, payload.description, json.dumps(payload.hashtags) if payload.hashtags is not None else None, now(), clip_id))
        con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("clip_reviewed", f"Clip {clip_id} marked {payload.status}", now()))
        return dict(con.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())


@app.post("/api/clips/{clip_id}/schedule")
def schedule_clip(clip_id: int, payload: ScheduleIn):
    clip = row("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not clip:
        raise HTTPException(404, "Clip not found")
    if clip["status"] != "approved":
        raise HTTPException(409, "Only manually approved clips can be scheduled")
    try:
        zone = ZoneInfo(payload.timezone)
    except Exception:
        raise HTTPException(400, "Invalid timezone")
    days = set(payload.preferred_days); hours = set(payload.preferred_hours)
    candidate = datetime.now(zone).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    chosen = None
    for _ in range(24 * 370):
        day_start = candidate.replace(hour=0)
        count = row("SELECT COUNT(*) AS count FROM clips WHERE status='scheduled' AND scheduled_at >= ? AND scheduled_at < ?", (day_start.astimezone(timezone.utc).isoformat(), (day_start + timedelta(days=1)).astimezone(timezone.utc).isoformat()))["count"]
        if candidate.weekday() in days and candidate.hour in hours and count < payload.daily_cap:
            previous = row("SELECT scheduled_at FROM clips WHERE status IN ('scheduled','published') AND scheduled_at IS NOT NULL ORDER BY scheduled_at DESC LIMIT 1")
            if not previous or candidate.astimezone(timezone.utc) - datetime.fromisoformat(previous["scheduled_at"]) >= timedelta(hours=payload.minimum_interval_hours):
                chosen = candidate; break
        candidate += timedelta(hours=1)
    if not chosen:
        raise HTTPException(422, "No scheduling slot found in the next year")
    iso = chosen.astimezone(timezone.utc).isoformat()
    with connection() as con:
        con.execute("UPDATE clips SET status='scheduled',scheduled_at=?,updated_at=? WHERE id=?", (iso, now(), clip_id))
        con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("clip_scheduled", f"Clip {clip_id} scheduled for {iso}", now()))
        return dict(con.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())


@app.post("/api/clips/{clip_id}/publish")
def publish_clip(clip_id: int, payload: PublishIn):
    clip = row("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not clip:
        raise HTTPException(404, "Clip not found")
    if clip["status"] not in {"approved", "scheduled"}:
        raise HTTPException(409, "Only approved or scheduled clips can be published")
    if payload.visibility not in {"private", "unlisted", "public"}:
        raise HTTPException(400, "Visibility must be private, unlisted, or public")
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise HTTPException(409, "YouTube OAuth is not configured. Set backend credentials and complete authorization first.")
    if not Path(settings.youtube_token_path).exists():
        raise HTTPException(409, "No YouTube OAuth token is present. Complete authorization first.")
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        credentials = Credentials.from_authorized_user_file(settings.youtube_token_path, ["https://www.googleapis.com/auth/youtube.upload"])
        youtube = build("youtube", "v3", credentials=credentials)
        tags = json.loads(clip["hashtags"] or "[]")
        body = {"snippet": {"title": clip["title"] or "ViralFlow clip", "description": clip["description"] or "", "tags": tags}, "status": {"privacyStatus": payload.visibility}}
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(clip["storage_path"], chunksize=8 * 1024 * 1024, resumable=True))
        response = None
        while response is None:
            _, response = request.next_chunk()
        remote_id = response["id"]
    except ImportError:
        raise HTTPException(503, "YouTube client dependencies are not installed")
    except Exception as exc:
        with connection() as con:
            con.execute("INSERT INTO publishing_events(clip_id,status,message,created_at) VALUES (?,?,?,?)", (clip_id, "failed", str(exc), now()))
        raise HTTPException(502, f"YouTube upload failed: {exc}")
    with connection() as con:
        con.execute("UPDATE clips SET status='published',visibility=?,published_video_id=?,published_url=?,updated_at=? WHERE id=?", (payload.visibility, remote_id, f"https://www.youtube.com/watch?v={remote_id}", now(), clip_id))
        con.execute("INSERT INTO publishing_events(clip_id,status,message,remote_video_id,created_at) VALUES (?,?,?,?,?)", (clip_id, "published", "Upload completed", remote_id, now()))
        con.execute("INSERT INTO activity(event_type,message,created_at) VALUES (?,?,?)", ("clip_published", f"Clip {clip_id} published as {remote_id}", now()))
        return dict(con.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())
