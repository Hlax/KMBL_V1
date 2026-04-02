"""KiloClaw stub transport — deterministic test double."""

from __future__ import annotations

import logging
from typing import Any, Literal

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.providers.kiloclaw_protocol import RoleType
from kmbl_orchestrator.providers.kiloclaw_parsing import _apply_role_contract

_log = logging.getLogger(__name__)


class KiloClawStubClient:
    """
    Deterministic placeholder responses for planner → generator → evaluator loop.

    Used when transport is ``stub`` (local development without OpenClaw).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        _ = self._settings
        _log.warning(
            "KILOCLAW_STUB_TRANSPORT invoke_role role=%s config_key=%s — NOT a real OpenClaw/KiloClaw call",
            role_type,
            provider_config_key,
        )
        _ = provider_config_key
        if role_type == "planner":
            raw = {
                "build_spec": {
                    "type": "stub",
                    "title": "stub_spec",
                    "steps": [],
                    # Contract smoke: archetype-aware planning (see kmbl-planner SOUL)
                    "site_archetype": "editorial",
                },
                "constraints": {"scope": "minimal"},
                "success_criteria": ["loop_reaches_evaluator"],
                "evaluation_targets": ["smoke_check"],
            }
            return _apply_role_contract(role_type, raw)
        if role_type == "generator":
            raw = {
                "proposed_changes": {
                    "files": [
                        {
                            "path": "component/preview/index.html",
                            "language": "html",
                            "content": (
                                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                                "<title>Stub Portfolio</title>"
                                "<link rel='stylesheet' href='styles.css'>"
                                "</head><body>"
                                "<canvas id='scene'></canvas>"
                                "<div id='overlay'><h1>Stub Portfolio</h1>"
                                "<p>Immersive 3D portfolio experience</p></div>"
                                "<script src='https://cdn.jsdelivr.net/npm/three@0.160/build/three.min.js'></script>"
                                "<script src='scene.js'></script>"
                                "</body></html>"
                            ),
                        },
                        {
                            "path": "component/preview/scene.js",
                            "language": "js",
                            "content": (
                                "(function(){"
                                "var s=new THREE.Scene();"
                                "var c=new THREE.PerspectiveCamera(60,innerWidth/innerHeight,0.1,100);"
                                "c.position.set(0,0,5);"
                                "var r=new THREE.WebGLRenderer({canvas:document.getElementById('scene'),antialias:true});"
                                "r.setSize(innerWidth,innerHeight);"
                                "s.add(new THREE.AmbientLight(0x404040));"
                                "s.add(new THREE.DirectionalLight(0xffffff,0.8));"
                                "var g=new THREE.BoxGeometry(1,1,1);"
                                "var m=new THREE.MeshStandardMaterial({color:0x6644ff});"
                                "var cube=new THREE.Mesh(g,m);s.add(cube);"
                                "function a(){requestAnimationFrame(a);cube.rotation.y+=0.01;r.render(s,c);}"
                                "a();"
                                "})()"
                            ),
                        },
                        {
                            "path": "component/preview/styles.css",
                            "language": "css",
                            "content": (
                                "body{margin:0;background:#0a0a0f;overflow:hidden}"
                                "#scene{position:fixed;top:0;left:0;width:100%;height:100%}"
                                "#overlay{position:relative;z-index:1;color:#fff;"
                                "font-family:system-ui;text-align:center;padding-top:40vh}"
                                "h1{font-size:3rem;text-shadow:0 0 40px rgba(100,100,255,0.5)}"
                            ),
                        },
                    ]
                },
                "artifact_outputs": [
                    {
                        "role": "static_frontend_file_v1",
                        "path": "component/preview/index.html",
                        "language": "html",
                        "content": (
                            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                            "<title>Stub Portfolio</title>"
                            "<link rel='stylesheet' href='styles.css'>"
                            "</head><body>"
                            "<canvas id='scene'></canvas>"
                            "<div id='overlay'><h1>Stub Portfolio</h1>"
                            "<p>Immersive 3D portfolio experience</p></div>"
                            "<script src='https://cdn.jsdelivr.net/npm/three@0.160/build/three.min.js'></script>"
                            "<script src='scene.js'></script>"
                            "</body></html>"
                        ),
                        "entry_for_preview": True,
                        "bundle_id": "stub-bundle-001",
                    },
                    {
                        "role": "static_frontend_file_v1",
                        "path": "component/preview/scene.js",
                        "language": "js",
                        "content": (
                            "(function(){"
                            "var s=new THREE.Scene();"
                            "var c=new THREE.PerspectiveCamera(60,innerWidth/innerHeight,0.1,100);"
                            "c.position.set(0,0,5);"
                            "var r=new THREE.WebGLRenderer({canvas:document.getElementById('scene'),antialias:true});"
                            "r.setSize(innerWidth,innerHeight);"
                            "s.add(new THREE.AmbientLight(0x404040));"
                            "s.add(new THREE.DirectionalLight(0xffffff,0.8));"
                            "var g=new THREE.BoxGeometry(1,1,1);"
                            "var m=new THREE.MeshStandardMaterial({color:0x6644ff});"
                            "var cube=new THREE.Mesh(g,m);s.add(cube);"
                            "function a(){requestAnimationFrame(a);cube.rotation.y+=0.01;r.render(s,c);}"
                            "a();"
                            "})()"
                        ),
                        "bundle_id": "stub-bundle-001",
                    },
                    {
                        "role": "static_frontend_file_v1",
                        "path": "component/preview/styles.css",
                        "language": "css",
                        "content": (
                            "body{margin:0;background:#0a0a0f;overflow:hidden}"
                            "#scene{position:fixed;top:0;left:0;width:100%;height:100%}"
                            "#overlay{position:relative;z-index:1;color:#fff;"
                            "font-family:system-ui;text-align:center;padding-top:40vh}"
                            "h1{font-size:3rem;text-shadow:0 0 40px rgba(100,100,255,0.5)}"
                        ),
                        "bundle_id": "stub-bundle-001",
                    },
                ],
                "updated_state": {"revision": 1},
                "sandbox_ref": "stub-sandbox",
                "preview_url": "http://localhost:3000/stub-preview",
                # Bounded-iteration smoke (see kmbl-generator SOUL)
                "_kmbl_primary_move": {
                    "mode": "refine",
                    "move_type": "composition",
                    "primary_surface": "hero",
                },
            }
            return _apply_role_contract(role_type, raw)
        if role_type == "evaluator":
            iteration = payload.get("iteration_hint", 0)
            # Return partial on first iteration to test multi-iteration loop,
            # then pass on subsequent iterations
            if iteration == 0:
                status: Literal["pass", "partial", "fail", "blocked"] = "partial"
                issues = [{"severity": "warning", "message": "First pass incomplete, needs refinement"}]
            else:
                status = "pass"
                issues = []
            raw = {
                "status": status,
                "summary": f"stub evaluation (iteration {iteration})",
                "issues": issues,
                "artifacts": [],
                "metrics": {
                    "stub": True,
                    "iteration": iteration,
                    "alignment_report": {
                        "must_mention_hit_rate": 0.75 if status == "pass" else 0.4,
                        "palette_used": True if status == "pass" else False,
                        "tone_reflected": True if status == "pass" else False,
                        "structural_present": True,
                    },
                },
            }
            return _apply_role_contract(role_type, raw)
        raise ValueError(f"unknown role_type: {role_type}")
