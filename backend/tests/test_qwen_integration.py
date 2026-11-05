import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_authorized_upload_transcription_and_qwen_analysis():
    video = os.getenv("VIRALFLOW_TEST_VIDEO")
    if not video:
        pytest.skip("Set VIRALFLOW_TEST_VIDEO to an authorized local video")
    path = Path(video)
    if not path.is_file():
        pytest.fail(f"Authorized test video does not exist: {path}")
    from app.main import app

    with TestClient(app) as client:
        with path.open("rb") as stream:
            upload = client.post("/api/videos/upload?authorized=true", files={"file": ("qwen-test.mp4", stream, "video/mp4")})
        assert upload.status_code == 201, upload.text
        video_id = upload.json()["id"]
        transcription = client.post(f"/api/videos/{video_id}/transcribe", json={"model": "tiny"})
        assert transcription.status_code == 201, transcription.text
        analysis = client.post(f"/api/videos/{video_id}/analyze", json={"target_duration": 30})
        assert analysis.status_code == 201, analysis.text
        moments = analysis.json()["moments"]
        assert moments
        for moment in moments:
            assert 0 <= moment["start_seconds"] < moment["end_seconds"]
            assert moment["end_seconds"] <= upload.json()["duration_seconds"] + 0.01
            assert 1 <= moment["score"] <= 10
            assert moment["title"] and moment["hook"] and moment["rationale"]
