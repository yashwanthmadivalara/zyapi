import pytest

from app.services import _json_from_model_response, validate_moment_candidates


def test_qwen_json_parser_accepts_code_fence():
    assert _json_from_model_response("```json\n[{\"ok\": true}]\n```") == [{"ok": True}]


def test_candidate_validation_aligns_to_real_segments_and_removes_overlap():
    segments = [{"start": 0, "end": 15, "text": "Opening"}, {"start": 15, "end": 32, "text": "Main point"}, {"start": 40, "end": 55, "text": "Conclusion"}]
    raw = [{"start_seconds": 1, "end_seconds": 31, "suggested_title": "A", "opening_hook": "Hook", "explanation": "Why", "content_category": "education", "suggested_caption": "Caption", "quality_score": 8}, {"start_seconds": 14, "end_seconds": 30, "suggested_title": "Overlap", "opening_hook": "Hook", "explanation": "Why", "content_category": "education", "suggested_caption": "Caption", "quality_score": 7}]
    result = validate_moment_candidates(raw, segments, 60, 30)
    assert len(result) == 1
    assert result[0]["start_seconds"] == 0
    assert result[0]["end_seconds"] == 32


def test_candidate_validation_rejects_out_of_range_candidates():
    with pytest.raises(ValueError):
        validate_moment_candidates([{"start_seconds": 80, "end_seconds": 90, "title": "Bad"}], [{"start": 0, "end": 20, "text": "Text"}], 30, 15)
