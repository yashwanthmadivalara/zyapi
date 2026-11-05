import subprocess

from fastapi.testclient import TestClient


def test_upload_rejects_unsupported_file():
    from app.main import app

    with TestClient(app) as client:
        response = client.post("/api/videos/upload?authorized=true", files={"file": ("notes.txt", b"not a video", "text/plain")})
    assert response.status_code == 400
    assert "Unsupported video type" in response.json()["detail"]


def test_upload_rejects_video_without_audio(tmp_path):
    silent_video = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1", "-an", str(silent_video)], check=True, capture_output=True)
    from app.main import app

    with TestClient(app) as client:
        with silent_video.open("rb") as stream:
            response = client.post("/api/videos/upload?authorized=true", files={"file": ("silent.mp4", stream, "video/mp4")})
    assert response.status_code == 400
    assert "audio" in response.json()["detail"].lower()
