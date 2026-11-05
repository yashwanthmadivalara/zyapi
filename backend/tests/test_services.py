from pathlib import Path

from app.services import write_srt


def test_write_srt_clips_timestamped_segments(tmp_path: Path):
    output = tmp_path / "clip.srt"
    write_srt(output, [{"start": 0, "end": 3, "text": "Hello"}, {"start": 4, "end": 8, "text": "World"}], 0, 6)
    text = output.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:03,000" in text
    assert "Hello" in text
    assert "World" in text


def test_write_srt_ignores_segments_outside_clip(tmp_path: Path):
    output = tmp_path / "clip.srt"
    write_srt(output, [{"start": 10, "end": 12, "text": "Outside"}], 0, 5)
    assert output.read_text(encoding="utf-8") == ""
