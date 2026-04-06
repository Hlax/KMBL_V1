"""Supabase infrastructure error classification and formatting."""

from __future__ import annotations

from postgrest.exceptions import APIError

from kmbl_orchestrator.persistence.supabase_infra import (
    classify_supabase_exception,
    format_supabase_repository_error,
)


def test_classify_html_cloudflare_details() -> None:
    exc = APIError(
        {
            "code": "400",
            "message": "JSON could not be generated",
            "details": (
                "<html><head><title>400 Bad Request</title></head>"
                "<body><center>cloudflare</center></body></html>"
            ),
            "hint": None,
        }
    )
    c = classify_supabase_exception(exc)
    assert c["looks_like_html"] is True
    assert c["looks_like_cloudflare"] is True
    assert c["looks_like_non_json_upstream"] is True
    assert "400" in (c.get("http_status_hint") or "")


def test_format_supabase_repository_error_includes_hints() -> None:
    exc = APIError(
        {
            "code": "400",
            "message": "JSON could not be generated",
            "details": "<html>cloudflare</html>",
            "hint": None,
        }
    )
    msg = format_supabase_repository_error(
        "get_working_staging_for_thread",
        "working_staging",
        exc,
        thread_id="tid",
    )
    assert "non_json" in msg or "SUPABASE_URL" in msg
    assert "cloudflare" in msg.lower() or "Cloudflare" in msg


def test_classify_normal_postgrest_error_not_flagged_as_html_gateway() -> None:
    exc = APIError(
        {
            "code": "PGRST116",
            "message": "JSON object requested, multiple (or no) rows returned",
            "details": "The result contains 0 rows",
            "hint": None,
        }
    )
    c = classify_supabase_exception(exc)
    assert c["looks_like_html"] is False
    assert c["looks_like_cloudflare"] is False
