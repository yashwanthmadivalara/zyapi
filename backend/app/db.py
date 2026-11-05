import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT UNIQUE NOT NULL,
  url TEXT NOT NULL, name TEXT, thumbnail_url TEXT, subscriber_count INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1, monitoring_minutes INTEGER NOT NULL DEFAULT 60,
  last_checked_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, storage_path TEXT UNIQUE NOT NULL,
  sha256 TEXT UNIQUE NOT NULL, size_bytes INTEGER NOT NULL, duration_seconds REAL,
  width INTEGER, height INTEGER, status TEXT NOT NULL DEFAULT 'imported', authorized INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER, kind TEXT NOT NULL,
  status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, message TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY(video_id) REFERENCES videos(id)
);
CREATE TABLE IF NOT EXISTS moments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER NOT NULL, start_seconds REAL NOT NULL,
  end_seconds REAL NOT NULL, title TEXT, rationale TEXT NOT NULL, hook TEXT NOT NULL,
  category TEXT, caption TEXT, score REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT NOT NULL,
  FOREIGN KEY(video_id) REFERENCES videos(id)
);
CREATE TABLE IF NOT EXISTS transcripts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER NOT NULL, text TEXT NOT NULL,
  model TEXT NOT NULL, segments_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, UNIQUE(video_id),
  FOREIGN KEY(video_id) REFERENCES videos(id)
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, message TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER NOT NULL, moment_id INTEGER NOT NULL,
  storage_path TEXT UNIQUE NOT NULL, start_seconds REAL NOT NULL DEFAULT 0, duration_seconds REAL NOT NULL, width INTEGER, height INTEGER,
  title TEXT, description TEXT, hashtags TEXT, status TEXT NOT NULL DEFAULT 'generated',
  visibility TEXT NOT NULL DEFAULT 'private', scheduled_at TEXT, published_video_id TEXT,
  published_url TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY(video_id) REFERENCES videos(id), FOREIGN KEY(moment_id) REFERENCES moments(id)
);
CREATE TABLE IF NOT EXISTS subtitles (
  id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id INTEGER NOT NULL, format TEXT NOT NULL,
  storage_path TEXT NOT NULL, style TEXT NOT NULL DEFAULT 'default', created_at TEXT NOT NULL,
  FOREIGN KEY(clip_id) REFERENCES clips(id)
);
CREATE TABLE IF NOT EXISTS publishing_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id INTEGER NOT NULL, status TEXT NOT NULL,
  message TEXT NOT NULL, remote_video_id TEXT, created_at TEXT NOT NULL,
  FOREIGN KEY(clip_id) REFERENCES clips(id)
);
CREATE TABLE IF NOT EXISTS service_state (
  service_name TEXT PRIMARY KEY, status TEXT NOT NULL, last_run_at TEXT, next_run_at TEXT,
  message TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analytics_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id INTEGER, remote_video_id TEXT,
  views INTEGER, likes INTEGER, comments INTEGER, subscribers_gained INTEGER,
  captured_at TEXT NOT NULL, source TEXT NOT NULL,
  FOREIGN KEY(clip_id) REFERENCES clips(id)
);
"""


@contextmanager
def connection():
    con = sqlite3.connect(settings.database_path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with connection() as con:
        con.executescript(SCHEMA)
        try:
            con.execute("ALTER TABLE transcripts ADD COLUMN segments_json TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass
        try:
            con.execute("ALTER TABLE clips ADD COLUMN start_seconds REAL NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        for statement in (
            "ALTER TABLE moments ADD COLUMN title TEXT",
            "ALTER TABLE moments ADD COLUMN category TEXT",
            "ALTER TABLE moments ADD COLUMN caption TEXT",
        ):
            try:
                con.execute(statement)
            except sqlite3.OperationalError:
                pass


def rows(sql, params=()):
    with connection() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def row(sql, params=()):
    with connection() as con:
        result = con.execute(sql, params).fetchone()
        return dict(result) if result else None
