"""KMBL image provider boundary: gating, OpenAI response normalization, gallery shape."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx

from kmbl_orchestrator.contracts.gallery_image_artifact_v1 import (
    GalleryStripImageArtifactV1,
    normalize_gallery_artifact_outputs_list,
)
from kmbl_orchestrator.image_provider.budget import GraphRunImageBudget
from kmbl_orchestrator.image_provider.contracts import ImageGenerationRequest
from kmbl_orchestrator.image_provider.openai_provider import OpenAIImageProvider
from kmbl_orchestrator.image_provider.service import ImageGenerationService


def _req(**kwargs: object) -> ImageGenerationRequest:
    gid = uuid4()
    tid = uuid4()
    base = {
        "prompt": "A calm abstract gradient for a gallery card",
        "graph_run_id": gid,
        "thread_id": tid,
    }
    base.update(kwargs)
    return ImageGenerationRequest.model_validate(base)


def test_service_skipped_when_legacy_disabled() -> None:
    """Production default: orchestrator does not call OpenAI Images (use KiloClaw kmbl-image-gen)."""
    from kmbl_orchestrator.config import Settings

    s = Settings.model_construct(
        kmb_legacy_orchestrator_openai_images=False,
        kmb_image_generation_enabled=False,
        kmb_openai_image_api_key="",
        kmb_max_images_per_graph_run=4,
    )
    budget = GraphRunImageBudget(4)
    svc = ImageGenerationService(settings=s, budget=budget)
    r = svc.generate(_req())
    assert r.status == "skipped"
    assert r.fallback_reason == "orchestrator_openai_images_disabled_use_kiloclaw_image_agent"
    assert r.gallery_artifact is None


def test_service_skipped_when_disabled_with_legacy_on() -> None:
    """Legacy path: kmb_image_generation_enabled=false skips."""
    from kmbl_orchestrator.config import Settings

    s = Settings.model_construct(
        kmb_legacy_orchestrator_openai_images=True,
        kmb_image_generation_enabled=False,
        kmb_openai_image_api_key="",
        kmb_max_images_per_graph_run=4,
    )
    budget = GraphRunImageBudget(4)
    svc = ImageGenerationService(settings=s, budget=budget)
    r = svc.generate(_req())
    assert r.status == "skipped"
    assert r.fallback_reason == "image_generation_disabled"
    assert r.gallery_artifact is None


def test_service_skipped_when_missing_api_key() -> None:
    from kmbl_orchestrator.config import Settings

    s = Settings.model_construct(
        kmb_legacy_orchestrator_openai_images=True,
        kmb_image_generation_enabled=True,
        kmb_openai_image_api_key="",
        kmb_max_images_per_graph_run=4,
    )
    budget = GraphRunImageBudget(4)
    svc = ImageGenerationService(settings=s, budget=budget)
    r = svc.generate(_req())
    assert r.status == "skipped"
    assert r.fallback_reason == "missing_openai_image_api_key"


class _FakeHttpxClientOk:
    def __init__(self, *a: object, **k: object) -> None:
        pass

    def __enter__(self) -> _FakeHttpxClientOk:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def post(self, *a: object, **k: object) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: {
            "data": [{"url": "https://cdn.example.com/a.png"}],
            "model": "dall-e-3",
        }
        return mock_resp


def test_budget_blocks_after_cap() -> None:
    from kmbl_orchestrator.config import Settings

    s = Settings.model_construct(
        kmb_legacy_orchestrator_openai_images=True,
        kmb_image_generation_enabled=True,
        kmb_openai_image_api_key="sk-test",
        kmb_max_images_per_graph_run=4,
    )
    budget = GraphRunImageBudget(1)
    svc = ImageGenerationService(settings=s, budget=budget, provider=OpenAIImageProvider(s))

    gid = uuid4()
    tid = uuid4()

    with patch(
        "kmbl_orchestrator.image_provider.openai_provider.httpx.Client",
        _FakeHttpxClientOk,
    ):
        r1 = svc.generate(
            ImageGenerationRequest(
                prompt="one",
                graph_run_id=gid,
                thread_id=tid,
            )
        )
        assert r1.status == "generated"

    with patch(
        "kmbl_orchestrator.image_provider.openai_provider.httpx.Client",
        _FakeHttpxClientOk,
    ):
        r2 = svc.generate(
            ImageGenerationRequest(
                prompt="two",
                graph_run_id=gid,
                thread_id=tid,
            )
        )
        assert r2.status == "fallback"
        assert r2.fallback_reason == "image_generation_budget_exhausted"


def test_openai_provider_normalizes_gallery_strip_image_v1() -> None:
    from kmbl_orchestrator.config import Settings

    s = Settings.model_construct(
        kmb_openai_image_api_key="sk-test",
        kmb_openai_image_model="dall-e-3",
    )
    prov = OpenAIImageProvider(s)

    class _Cl:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def __enter__(self) -> _Cl:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def post(self, *a: object, **k: object) -> MagicMock:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json = lambda: {
                "data": [{"url": "https://openai.example/img.png"}],
                "model": "dall-e-3",
                "usage": {"total_tokens": 1},
            }
            return mock_resp

    with patch("kmbl_orchestrator.image_provider.openai_provider.httpx.Client", _Cl):
        out = prov.generate(
            _req(
                artifact_key="strip_main",
                prompt="A red square",
            )
        )
    assert out.status == "generated"
    assert out.gallery_artifact is not None
    assert out.gallery_artifact["role"] == "gallery_strip_image_v1"
    assert out.gallery_artifact["key"] == "strip_main"
    assert out.gallery_artifact["url"] == "https://openai.example/img.png"
    assert out.gallery_artifact["source"] == "generated"
    assert out.gallery_artifact["kmbl_generation_status"] == "ok"
    assert out.gallery_artifact["kmbl_provider"] == "openai"
    assert out.gallery_artifact["kmbl_provider_model"] == "dall-e-3"

    GalleryStripImageArtifactV1.model_validate(out.gallery_artifact)
    normalized = normalize_gallery_artifact_outputs_list([out.gallery_artifact])
    assert len(normalized) == 1
    assert normalized[0]["key"] == "strip_main"


def test_openai_provider_http_error_fallback() -> None:
    from kmbl_orchestrator.config import Settings

    s = Settings.model_construct(
        kmb_openai_image_api_key="sk-test",
        kmb_openai_image_model="dall-e-3",
    )
    prov = OpenAIImageProvider(s)
    resp = MagicMock()
    resp.status_code = 429
    resp.text = "rate limit"

    class _ClErr:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def __enter__(self) -> _ClErr:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def post(self, *a: object, **k: object) -> MagicMock:
            raise httpx.HTTPStatusError("err", request=MagicMock(), response=resp)

    with patch("kmbl_orchestrator.image_provider.openai_provider.httpx.Client", _ClErr):
        out = prov.generate(_req())
    assert out.status == "fallback"
    assert out.gallery_artifact is None
    assert out.fallback_reason is not None
    assert "429" in out.fallback_reason


def test_gallery_artifact_optional_kmbl_fields_roundtrip() -> None:
    raw = {
        "role": "gallery_strip_image_v1",
        "key": "k1",
        "url": "https://example.com/i.png",
        "source": "generated",
        "kmbl_generation_status": "ok",
        "kmbl_provider": "openai",
        "kmbl_provider_model": "dall-e-3",
        "kmbl_fallback_reason": None,
    }
    out = normalize_gallery_artifact_outputs_list([raw])
    assert out[0]["kmbl_provider"] == "openai"
