"""OpenAI Images API — server-side only; API key from Settings."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import httpx

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.contracts.gallery_image_artifact_v1 import GalleryStripImageArtifactV1
from kmbl_orchestrator.image_provider.contracts import ImageGenerationRequest, ImageGenerationResult

_LOG = logging.getLogger(__name__)

_OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"


def _default_key(req: ImageGenerationRequest) -> str:
    if req.artifact_key and req.artifact_key.strip():
        return req.artifact_key.strip()
    return f"gen_{uuid4().hex[:12]}"


class OpenAIImageProvider:
    """Calls OpenAI ``images/generations``; returns normalized ``ImageGenerationResult``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
        key = _default_key(req)
        api_key = (self._settings.kmb_openai_image_api_key or "").strip()
        if not api_key:
            return ImageGenerationResult(
                status="skipped",
                provider="openai",
                provider_model=None,
                gallery_artifact=None,
                fallback_reason="missing_openai_image_api_key",
            )

        model = (self._settings.kmb_openai_image_model or "dall-e-3").strip()
        body: dict[str, Any] = {
            "model": model,
            "prompt": req.prompt,
            "n": 1,
            "size": (req.size or "1024x1024").strip(),
            "response_format": "url",
        }
        if req.quality:
            body["quality"] = req.quality.strip()
        if req.style:
            body["style"] = req.style.strip()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(_OPENAI_IMAGES_URL, json=body, headers=headers)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.text[:500]
            except Exception:
                detail = str(e)
            _LOG.warning("OpenAI images HTTP error: %s", detail)
            return ImageGenerationResult(
                status="fallback",
                provider="openai",
                provider_model=model,
                gallery_artifact=None,
                fallback_reason=f"http_{e.response.status_code}:{detail[:400]}",
            )
        except Exception as e:
            _LOG.warning("OpenAI images request failed: %s", e)
            return ImageGenerationResult(
                status="fallback",
                provider="openai",
                provider_model=model,
                gallery_artifact=None,
                fallback_reason=f"provider_error:{str(e)[:400]}",
            )

        try:
            items = data.get("data")
            if not isinstance(items, list) or not items:
                return ImageGenerationResult(
                    status="fallback",
                    provider="openai",
                    provider_model=model,
                    gallery_artifact=None,
                    fallback_reason="openai_response_missing_data",
                )
            img_url = items[0].get("url")
            if not isinstance(img_url, str) or not img_url.strip():
                return ImageGenerationResult(
                    status="fallback",
                    provider="openai",
                    provider_model=model,
                    gallery_artifact=None,
                    fallback_reason="openai_response_missing_url",
                )
        except Exception as e:
            return ImageGenerationResult(
                status="fallback",
                provider="openai",
                provider_model=model,
                gallery_artifact=None,
                fallback_reason=f"parse_error:{str(e)[:200]}",
            )

        alt = req.prompt[:500] if len(req.prompt) <= 500 else req.prompt[:497] + "..."
        art = GalleryStripImageArtifactV1(
            role="gallery_strip_image_v1",
            key=key,
            url=img_url.strip(),
            thumb_url=None,
            alt=alt,
            source="generated",
            kmbl_generation_status="ok",
            kmbl_provider="openai",
            kmbl_provider_model=model,
            kmbl_fallback_reason=None,
        )
        usage: dict[str, Any] = {}
        if isinstance(data.get("usage"), dict):
            usage = dict(data["usage"])
        resp_model = data.get("model")
        if isinstance(resp_model, str):
            usage.setdefault("response_model", resp_model)

        return ImageGenerationResult(
            status="generated",
            provider="openai",
            provider_model=model,
            gallery_artifact=art.model_dump(mode="json"),
            fallback_reason=None,
            usage=usage or None,
        )


__all__ = ["OpenAIImageProvider"]
