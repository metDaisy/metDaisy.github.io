"""MkDocs hooks for compatibility with upstream Docusaurus Markdown."""

from __future__ import annotations

import json
import re


_OPEN = re.compile(
    r"^ {0,3}:::\s*(?P<kind>[A-Za-z][\w-]*)(?:[ \t]+(?P<title>.*?))?[ \t]*$"
)
_CLOSE = re.compile(r"^ {0,3}:::\s*$")
_FENCE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})")


def _indent(line: str, depth: int) -> str:
    if depth == 0 or not line.strip():
        return line
    return f"{'    ' * depth}{line}"


def _convert_docusaurus_admonitions(markdown: str) -> str:
    """Convert :::type blocks to MkDocs Material !!! blocks."""
    output: list[str] = []
    depth = 0
    fence: str | None = None

    for line in markdown.splitlines():
        fence_match = _FENCE.match(line)
        if fence is not None:
            output.append(_indent(line, depth))
            if fence_match and fence_match.group("marker")[0] == fence[0]:
                marker = fence_match.group("marker")
                if len(marker) >= len(fence):
                    fence = None
            continue

        if fence_match:
            output.append(_indent(line, depth))
            fence = fence_match.group("marker")
            continue

        if _CLOSE.match(line) and depth:
            depth -= 1
            continue

        open_match = _OPEN.match(line)
        if open_match:
            kind = open_match.group("kind").lower()
            title = open_match.group("title")
            title_suffix = f" {json.dumps(title, ensure_ascii=False)}" if title else ""
            output.append(_indent(f"!!! {kind}{title_suffix}", depth))
            depth += 1
            continue

        output.append(_indent(line, depth))

    return "\n".join(output)


def on_page_markdown(markdown, page, config, files):
    """Normalize upstream Docusaurus admonitions before Markdown parsing."""
    return _convert_docusaurus_admonitions(markdown)
