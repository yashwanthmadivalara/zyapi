import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_upload_transcribe_analyze_extract_and_subtitle_pipeline():
    video = os.getenv("VIRALFLOW_TEST_VIDEO")
    if not video:
        pytest.skip("Set VIRALFLOW_TEST_VIDEO to an authorized local video")
    path = Path(video)
    if not path.is_file():
        pytest.fail(f"Authorized test video does not exist: {path}")
    from app.main import app

    with TestClient(app) as client:
        with path.open("rb") as stream:
            upload = client.post("/api/videos/upload?authorized=true", files={"file": ("pipeline-test.mp4", stream, "video/mp4")})
        assert upload.status_code == 201, upload.text
        video_id = upload.json()["id"]
        assert client.post(f"/api/videos/{video_id}/transcribe", json={"model": "tiny"}).status_code == 201
        analysis = client.post(f"/api/videos/{video_id}/analyze", json={"target_duration": 30})
        assert analysis.status_code == 201, analysis.text
        moment_id = analysis.json()["moments"][0]["id"]
        extraction = client.post(f"/api/moments/{moment_id}/extract", json={"duration_seconds": 30})
        assert extraction.status_code == 201, extraction.text
        clip = extraction.json()
        assert Path(clip["storage_path"]).is_file()
        assert clip["width"] == 1080 and clip["height"] == 1920
        subtitles = client.post(f"/api/clips/{clip['id']}/subtitles?subtitle_format=srt&burn_in=true")
        assert subtitles.status_code == 201, subtitles.text
        subtitle = subtitles.json()
        assert Path(subtitle["storage_path"]).is_file()
        assert Path(subtitle["burned_video_path"]).is_file()
        assert client.get(f"/api/clips/{clip['id']}/file").status_code == 200
        assert json.loads(client.get(f"/api/clips/{clip['id']}/subtitles").text)
