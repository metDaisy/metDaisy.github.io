"""Parser delegates for Notion blocks and enhanced Markdown content.

The Notion API returns a tree of blocks.  This module keeps the tree traversal
in one registry and delegates each node to the parser that owns its block type.
Container parsers call the same registry for their children, so new nested
block types do not require another special case in the synchronizer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import re
from dataclasses import dataclass
from html import escape
from typing import Callable


BlockLoader = Callable[[str], list[dict]]


def plain_text(rich_text: list[dict] | None) -> str:
    return "".join(item.get("plain_text", "") for item in rich_text or [])


def markdown_text(rich_text: list[dict] | None) -> str:
    chunks: list[str] = []
    for item in rich_text or []:
        text = item.get("plain_text", "")
        annotations = item.get("annotations", {})
        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"
        if annotations.get("underline"):
            text = f'<span class="notion-underline">{text}</span>'
        href = item.get("href")
        if href:
            text = f"[{text}]({href})"
        chunks.append(text)
    return "".join(chunks)


def block_text(block: dict) -> str:
    data = block.get(block.get("type", ""), {})
    return markdown_text(data.get("rich_text"))


def notion_color(value: str | None) -> str:
    return value if value and value != "default" else ""


@dataclass
class ParserContext:
    """Shared dependencies passed to every parser delegate."""

    child_loader: BlockLoader
    parse_blocks: Callable[[list[dict], int], list[str]]

    def children(self, block: dict) -> list[dict]:
        if not block.get("has_children"):
            return []
        return self.child_loader(block["id"])

    def parse_children(self, block: dict, depth: int) -> list[str]:
        """Delegate nested blocks back to the parser registry."""
        return self.parse_blocks(self.children(block), depth + 1)


class AbstractBlockParser(ABC):
    """Template for every Notion block parser delegate."""

    @abstractmethod
    def can_handle(self, block: dict) -> bool:
        """Return whether this parser owns the supplied block."""

    @abstractmethod
    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        """Convert a supported block into Markdown/HTML lines."""

    def handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        if not self.can_handle(block):
            raise ValueError(f"{self.__class__.__name__} cannot handle {block.get('type', '')!r}")
        return self.do_handle(block, context, depth)


class BlockParserRegistry:
    """Dispatch blocks to delegates and recursively parse their children."""

    def __init__(self, child_loader: BlockLoader, parsers: list[AbstractBlockParser] | None = None):
        self.context = ParserContext(child_loader, self.parse_blocks)
        self.parsers: list[AbstractBlockParser] = (
            list(parsers)
            if parsers is not None
            else [
                TextParser(),
                ListParser(),
                CodeParser(),
                TableParser(),
                ToggleParser(),
                QuoteParser(),
                CalloutParser(),
                EquationParser(),
                DividerParser(),
                MediaParser(),
                FallbackParser(),
            ]
        )

    def parse_blocks(self, blocks: list[dict], depth: int = 0) -> list[str]:
        output: list[str] = []
        for block in blocks:
            output.extend(self.parse_block(block, depth))
            output.append("")
        return output

    def parse_block(self, block: dict, depth: int = 0) -> list[str]:
        parser = next((candidate for candidate in self.parsers if candidate.can_handle(block)), None)
        if parser is None:
            raise RuntimeError(f"No parser registered for Notion block {block.get('type', '')!r}")
        return parser.handle(block, self.context, depth)


def indent(depth: int) -> str:
    # Four spaces are required for reliable nested Markdown lists in Kramdown.
    return "    " * depth


class TextParser(AbstractBlockParser):
    _block_types = frozenset({"paragraph", "heading_1", "heading_2", "heading_3", "heading_4"})

    def can_handle(self, block: dict) -> bool:
        return block.get("type") in self._block_types

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        block_type = block["type"]
        text = block_text(block)
        data = block.get(block_type, {})
        color = notion_color(data.get("color"))
        if block_type == "paragraph":
            line = f"{indent(depth)}{text}" if text else ""
        else:
            level = int(block_type[-1])
            line = f"{indent(depth)}{'#' * level} {text}"
        if color:
            line = f'<div class="notion-color notion-color--{escape(color)}">{line.strip()}</div>'
        return [line]


class ListParser(AbstractBlockParser):
    _block_types = frozenset({"bulleted_list_item", "numbered_list_item", "to_do"})

    def can_handle(self, block: dict) -> bool:
        return block.get("type") in self._block_types

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        block_type = block["type"]
        data = block.get(block_type, {})
        text = block_text(block)
        prefix = "- "
        if block_type == "numbered_list_item":
            prefix = "1. "
        elif block_type == "to_do":
            prefix = f"- [{'x' if data.get('checked') else ' '}] "

        lines = [f"{indent(depth)}{prefix}{text}"]
        lines.extend(context.parse_children(block, depth))
        return lines


class CodeParser(AbstractBlockParser):
    def can_handle(self, block: dict) -> bool:
        return block.get("type") == "code"

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        data = block.get("code", {})
        language = data.get("language", "text") or "text"
        # Code is intentionally a leaf: a table-looking string inside code is
        # source text, not a nested Notion table to be parsed.
        return [
            f"{indent(depth)}```{language}",
            plain_text(data.get("rich_text")),
            f"{indent(depth)}```",
        ]


class TableParser(AbstractBlockParser):
    def can_handle(self, block: dict) -> bool:
        return block.get("type") == "table"

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        rows: list[list[str]] = []
        for row in context.children(block):
            if row.get("type") != "table_row":
                continue
            cells = row.get("table_row", {}).get("cells", [])
            rows.append([markdown_text(cell) for cell in cells])
        if not rows:
            return []

        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        prefix = indent(depth)
        output = [f"{prefix}| " + " | ".join(normalized[0]) + " |"]
        output.append(f"{prefix}| " + " | ".join("---" for _ in range(width)) + " |")
        output.extend(f"{prefix}| " + " | ".join(row) + " |" for row in normalized[1:])
        return output


class ToggleParser(AbstractBlockParser):
    def can_handle(self, block: dict) -> bool:
        return block.get("type") == "toggle"

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        data = block.get("toggle", {})
        title = escape(plain_text(data.get("rich_text")))
        prefix = indent(depth)
        return [
            f'{prefix}<details markdown="1" open>',
            f"{prefix}<summary>{title}</summary>",
            *context.parse_children(block, depth),
            f"{prefix}</details>",
        ]


class QuoteParser(AbstractBlockParser):
    def can_handle(self, block: dict) -> bool:
        return block.get("type") == "quote"

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        prefix = indent(depth)
        lines = [f"{prefix}> {block_text(block)}"]
        lines.extend(context.parse_children(block, depth))
        return lines


class CalloutParser(AbstractBlockParser):
    def can_handle(self, block: dict) -> bool:
        return block.get("type") == "callout"

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        data = block.get("callout", {})
        color = notion_color(data.get("color"))
        color_attr = f' color="{escape(color)}"' if color else ""
        icon = data.get("icon") or {}
        icon_value = icon.get("emoji", "") if isinstance(icon, dict) else ""
        icon_attr = f' icon="{escape(icon_value)}"' if icon_value else ""
        prefix = indent(depth)
        return [
            f"{prefix}<callout{icon_attr}{color_attr}>",
            f"{prefix}\t{block_text(block)}",
            *context.parse_children(block, depth),
            f"{prefix}</callout>",
        ]


class EquationParser(AbstractBlockParser):
    def can_handle(self, block: dict) -> bool:
        return block.get("type") == "equation"

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        expression = block.get("equation", {}).get("expression", "")
        prefix = indent(depth)
        return [f"{prefix}$$", expression, f"{prefix}$$"]


class DividerParser(AbstractBlockParser):
    def can_handle(self, block: dict) -> bool:
        return block.get("type") == "divider"

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        return [f"{indent(depth)}---"]


class MediaParser(AbstractBlockParser):
    _block_types = frozenset({"image", "bookmark", "link_preview", "embed", "video", "file", "pdf", "audio"})

    def can_handle(self, block: dict) -> bool:
        return block.get("type") in self._block_types

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        block_type = block["type"]
        data = block.get(block_type, {})
        media = data.get("external") or data.get("file") or data
        url = media.get("url", "") if isinstance(media, dict) else ""
        if not url:
            return []
        text = block_text(block) or ("image" if block_type == "image" else "file")
        if block_type == "image":
            return [f"{indent(depth)}![{text}]({url})"]
        return [f"{indent(depth)}[{text}]({url})"]


class FallbackParser(AbstractBlockParser):
    """Last-resort delegate for block types without a dedicated parser."""

    def can_handle(self, block: dict) -> bool:
        return True

    def do_handle(self, block: dict, context: ParserContext, depth: int) -> list[str]:
        text = block_text(block)
        prefix = indent(depth)
        if text:
            lines = [f"{prefix}{text}"]
        else:
            block_type = escape(block.get("type", "unknown"))
            block_id = escape(block.get("id", ""))
            link = (
                f' <a href="https://www.notion.so/{block_id}">Notion에서 열기</a>'
                if block_id
                else ""
            )
            lines = [
                f'{prefix}<div class="notion-fallback" data-block-type="{block_type}">'
                f"지원되지 않는 Notion 블록: {block_type}{link}</div>"
            ]
        lines.extend(context.parse_children(block, depth))
        return lines


def render_blocks(blocks: list[dict], child_loader: BlockLoader) -> str:
    """Render a Notion block tree through the delegate registry."""
    return "\n".join(BlockParserRegistry(child_loader).parse_blocks(blocks)).strip()


class EnhancedMarkdownParser:
    """Normalize Notion's enhanced Markdown before Jekyll/Kramdown parses it."""

    def __init__(self, unknown_loader: Callable[[str], str] | None = None):
        self.unknown_loader = unknown_loader

    def parse(self, markdown: str, unknown_ids: list[str] | None = None) -> str:
        markdown = self._resolve_unknown(markdown, unknown_ids or [])
        markdown = re.sub(
            r'^(?P<text>.+?)\s+\{color="(?P<color>[^"]+)"\}\s*$',
            r'<div class="notion-color notion-color--\g<color>">\g<text></div>',
            markdown,
            flags=re.MULTILINE,
        )
        markdown = markdown.replace('{toggle="true"}', "")
        markdown = self._normalize_toggles(markdown)
        markdown = re.sub(r"^\t(?=- )", "    ", markdown, flags=re.MULTILINE)
        markdown = re.sub(r"\n---\n(?!\n)", "\n\n---\n\n", markdown)
        return markdown.strip()

    def _resolve_unknown(self, markdown: str, unknown_ids: list[str]) -> str:
        for block_id in unknown_ids:
            replacement = ""
            if self.unknown_loader:
                replacement = self.unknown_loader(block_id).strip()
            replacement = replacement or f"[Notion {block_id} 블록 열기](https://www.notion.so/{block_id})"
            markdown = re.sub(r"<unknown\b[^>]*/?>", replacement, markdown, count=1)
        return markdown

    @staticmethod
    def _normalize_toggles(markdown: str) -> str:
        def normalize(match: re.Match[str]) -> str:
            body = re.sub(r"^(?:\t| {4})", "", match.group("body"), flags=re.MULTILINE)
            return (
                '<details markdown="1" open>\n'
                f"{match.group('summary')}\n\n"
                f"{body.strip()}\n\n"
                "</details>"
            )

        return re.sub(
            r"<details>\n(?P<summary><summary>.*?</summary>)\n(?P<body>.*?)\n</details>",
            normalize,
            markdown,
            flags=re.DOTALL,
        )


def parse_enhanced_markdown(
    markdown: str,
    unknown_ids: list[str] | None = None,
    unknown_loader: Callable[[str], str] | None = None,
) -> str:
    return EnhancedMarkdownParser(unknown_loader).parse(markdown, unknown_ids)
