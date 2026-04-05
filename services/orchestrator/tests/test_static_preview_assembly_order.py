"""Preview assembly: JS order and module flags for multi-file bundles."""

from __future__ import annotations

from kmbl_orchestrator.staging.static_preview_assembly import assemble_static_preview_html


def _payload(
    *,
    roles: tuple[str, str, str],
    entry_html: str,
    a_js: str,
    b_js: str,
    wsp: dict | None = None,
) -> dict:
    bid = "t1"
    return {
        "artifacts": {
            "artifact_refs": [
                {
                    "role": roles[0],
                    "path": "component/preview/index.html",
                    "language": "html",
                    "content": entry_html,
                    "bundle_id": bid,
                    "entry_for_preview": True,
                },
                {
                    "role": roles[1],
                    "path": "component/preview/a.js",
                    "language": "js",
                    "content": a_js,
                    "bundle_id": bid,
                },
                {
                    "role": roles[2],
                    "path": "component/preview/b.js",
                    "language": "js",
                    "content": b_js,
                    "bundle_id": bid,
                },
            ],
        },
        "metadata": {"working_state_patch": wsp or {}},
    }


def test_js_injection_follows_dom_order_not_alphabetical() -> None:
    """Alphabetical would be a.js then b.js; DOM says b then a."""
    html, err = assemble_static_preview_html(
        _payload(
            roles=(
                "interactive_frontend_app_v1",
                "interactive_frontend_app_v1",
                "interactive_frontend_app_v1",
            ),
            entry_html=(
                '<!DOCTYPE html><html><head></head><body>'
                '<script src="b.js"></script><script src="a.js"></script></body></html>'
            ),
            a_js = "window.order = 'a';",
            b_js = "window.order = 'b';",
        ),
        entry_path="component/preview/index.html",
    )
    assert err == ""
    assert html is not None
    pos_b = html.index("window.order = 'b'")
    pos_a = html.index("window.order = 'a'")
    assert pos_b < pos_a


def test_module_script_preserved_on_injected_chunk() -> None:
    html, err = assemble_static_preview_html(
        _payload(
            roles=(
                "interactive_frontend_app_v1",
                "interactive_frontend_app_v1",
                "static_frontend_file_v1",
            ),
            entry_html=(
                "<!DOCTYPE html><html><body>"
                '<script type="module" src="a.js"></script>'
                "</body></html>"
            ),
            a_js = "export const x = 1;",
            b_js = "// unused",
        ),
        entry_path="component/preview/index.html",
    )
    assert err == ""
    assert html is not None
    assert 'type="module"' in html
    assert "export const x = 1;" in html


def test_explicit_js_path_order_overrides_dom() -> None:
    wsp = {
        "kmbl_preview_assembly_hints_v1": {
            "js_path_order": [
                "component/preview/a.js",
                "component/preview/b.js",
            ],
        },
    }
    html, err = assemble_static_preview_html(
        _payload(
            roles=(
                "static_frontend_file_v1",
                "static_frontend_file_v1",
                "static_frontend_file_v1",
            ),
            entry_html=(
                "<!DOCTYPE html><html><body>"
                '<script src="b.js"></script><script src="a.js"></script></body></html>'
            ),
            a_js = "window.o=1;",
            b_js = "window.o=2;",
            wsp=wsp,
        ),
        entry_path="component/preview/index.html",
    )
    assert err == ""
    assert html is not None
    p1 = html.index("window.o=1")
    p2 = html.index("window.o=2")
    assert p1 < p2
