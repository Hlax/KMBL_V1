"""
HTML/CSS/JS sanitization for habitat raw injection sections.

Provides safety for Layer 3 (raw injection) by:
- Removing dangerous HTML tags and attributes
- Scoping CSS selectors to section containers
- Wrapping JS in IIFE scoped to section containers
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

BLOCKED_TAGS: set[str] = {
    "script",
    "iframe",
    "object",
    "embed",
    "applet",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "base",
    "link",
    "meta",
}

BLOCKED_ATTRS: set[str] = {
    "onclick",
    "ondblclick",
    "onmousedown",
    "onmouseup",
    "onmouseover",
    "onmousemove",
    "onmouseout",
    "onmouseenter",
    "onmouseleave",
    "onkeydown",
    "onkeypress",
    "onkeyup",
    "onfocus",
    "onblur",
    "onchange",
    "onsubmit",
    "onreset",
    "onload",
    "onunload",
    "onerror",
    "onabort",
    "onresize",
    "onscroll",
    "formaction",
    "xlink:href",
    "xmlns",
}

ALLOWED_URL_SCHEMES: set[str] = {"http", "https", "data", "mailto", "tel"}


class HTMLSanitizer(HTMLParser):
    """HTML parser that strips dangerous elements and attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.output: list[str] = []
        self._skip_depth = 0
        self._in_blocked_tag = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()

        if tag_lower in BLOCKED_TAGS:
            self._skip_depth += 1
            self._in_blocked_tag = True
            return

        if self._skip_depth > 0:
            return

        safe_attrs = self._filter_attrs(attrs)
        if safe_attrs:
            attr_str = " ".join(f'{k}="{html.escape(v or "")}"' for k, v in safe_attrs)
            self.output.append(f"<{tag} {attr_str}>")
        else:
            self.output.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower in BLOCKED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            if self._skip_depth == 0:
                self._in_blocked_tag = False
            return

        if self._skip_depth > 0:
            return

        self.output.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()

        if tag_lower in BLOCKED_TAGS or self._skip_depth > 0:
            return

        safe_attrs = self._filter_attrs(attrs)
        if safe_attrs:
            attr_str = " ".join(f'{k}="{html.escape(v or "")}"' for k, v in safe_attrs)
            self.output.append(f"<{tag} {attr_str} />")
        else:
            self.output.append(f"<{tag} />")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        self.output.append(html.escape(data))

    def handle_comment(self, data: str) -> None:
        pass

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth > 0:
            return
        self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth > 0:
            return
        self.output.append(f"&#{name};")

    def _filter_attrs(self, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
        """Filter out dangerous attributes."""
        safe: list[tuple[str, str | None]] = []

        for name, value in attrs:
            name_lower = name.lower()

            if name_lower in BLOCKED_ATTRS:
                continue

            if name_lower.startswith("on"):
                continue

            if name_lower in ("href", "src", "action", "data"):
                if value and not self._is_safe_url(value):
                    continue

            safe.append((name, value))

        return safe

    def _is_safe_url(self, url: str) -> bool:
        """Check if URL uses an allowed scheme."""
        url_lower = url.lower().strip()

        if url_lower.startswith("javascript:"):
            return False
        if url_lower.startswith("vbscript:"):
            return False

        if ":" in url_lower:
            scheme = url_lower.split(":")[0]
            if scheme not in ALLOWED_URL_SCHEMES:
                return False

        return True

    def get_result(self) -> str:
        return "".join(self.output)


def sanitize_raw_html(html_content: str) -> str:
    """
    Sanitize raw HTML by removing dangerous tags and attributes.

    Args:
        html_content: Raw HTML string to sanitize

    Returns:
        Sanitized HTML string
    """
    if not html_content:
        return ""

    sanitizer = HTMLSanitizer()
    try:
        sanitizer.feed(html_content)
        return sanitizer.get_result()
    except Exception:
        return html.escape(html_content)


def sanitize_custom_css(css: str, section_id: str) -> str:
    """
    Scope CSS selectors to a section container.

    Args:
        css: Raw CSS string
        section_id: ID of the section container for scoping

    Returns:
        CSS with all selectors prefixed with #{section_id}
    """
    if not css:
        return ""

    selector_re = re.compile(
        r"([^\{\}]+)\{",
        re.MULTILINE,
    )

    def prefix_selector(match: re.Match[str]) -> str:
        selector = match.group(1).strip()

        if selector.startswith("@"):
            return match.group(0)

        if selector.startswith(":root"):
            return match.group(0)

        parts = [s.strip() for s in selector.split(",")]
        prefixed = [f"#{section_id} {p}" if p else p for p in parts]

        return ", ".join(prefixed) + " {"

    return selector_re.sub(prefix_selector, css)


def sanitize_custom_js(js: str, section_id: str) -> str:
    """
    Wrap JavaScript in an IIFE scoped to a section container.

    Args:
        js: Raw JavaScript string
        section_id: ID of the section container

    Returns:
        JavaScript wrapped in a scoped IIFE
    """
    if not js:
        return ""

    return f"""(function() {{
  'use strict';
  const container = document.getElementById('{section_id}');
  if (!container) {{
    console.warn('Habitat section container not found: {section_id}');
    return;
  }}
  
  {js}
}})();"""


def escape_template_string(s: str) -> str:
    """Escape a string for use in a JavaScript template literal."""
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")


def validate_css_property(prop: str, value: str) -> bool:
    """Basic validation that a CSS property/value pair is safe."""
    prop_lower = prop.lower().strip()

    dangerous_props = {
        "behavior",
        "-moz-binding",
        "expression",
    }

    if prop_lower in dangerous_props:
        return False

    value_lower = value.lower()
    if "expression(" in value_lower:
        return False
    if "javascript:" in value_lower:
        return False
    if "url(" in value_lower:
        url_match = re.search(r"url\s*\(\s*['\"]?([^'\")\s]+)", value_lower)
        if url_match:
            url = url_match.group(1)
            if url.startswith("javascript:") or url.startswith("data:text/html"):
                return False

    return True
