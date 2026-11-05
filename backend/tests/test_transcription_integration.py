import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


VIDEO = os.getenv("VIRALFLOW_TEST_VIDEO")


@pytest.mark.integration
def test_authorized_upload_to_transcription():
    if not VIDEO:
        pytest.skip("Set VIRALFLOW_TEST_VIDEO to an authorized local video")
    video_path = Path(VIDEO)
    if not video_path.is_file():
        pytest.fail(f"Authorized test video does not exist: {video_path}")

    from app.main import app

    with TestClient(app) as client:
        with video_path.open("rb") as stream:
            upload = client.post("/api/videos/upload?authorized=true", files={"file": ("authorized-test.mp4", stream, "video/mp4")})
        assert upload.status_code == 201, upload.text
        video_id = upload.json()["id"]

        transcription = client.post(f"/api/videos/{video_id}/transcribe", json={"model": "tiny"})
        assert transcription.status_code == 201, transcription.text
        body = transcription.json()
        assert body["language"]
        assert body["transcript"]["text"].strip()
        assert json.loads(body["transcript"]["segments_json"])
