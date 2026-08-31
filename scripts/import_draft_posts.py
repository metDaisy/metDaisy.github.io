"""Import Markdown files from the private draft repository into Jekyll's notes collection."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


FRONT_MATTER = re.compile(r"\A---\r?\n(?P<body>.*?)(?:\r?\n)---\r?\n?", re.DOTALL)
TAGS_LINE = re.compile(r"^(?P<indent>\s*)tags:\s*(?P<value>.*?)\s*$", re.MULTILINE)
FENCE_LINE = re.compile(
    r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)(?P<newline>\r?\n|$)",
    re.MULTILINE,
)
CODE_LANGUAGE_ALIASES = {
    "plain text": "text",
    "plain-text": "text",
    "plaintext": "text",
}
EXCLUDED_MARKDOWN_NAMES = {"readme.md", "changelog.md", "agents.md"}


def normalize_fenced_code_info(content: str) -> str:
    """Convert common non-Kramdown fence aliases into valid language names."""

    def normalize_fence(match: re.Match[str]) -> str:
        info = match.group("info").strip()
        language = CODE_LANGUAGE_ALIASES.get(info.casefold())
        if language is None:
            return match.group(0)
        return (
            f"{match.group('indent')}{match.group('fence')}"
            f"{language}{match.group('newline')}"
        )

    return FENCE_LINE.sub(normalize_fence, content)


def normalize_front_matter(content: str, filename: str) -> str:
    match = FRONT_MATTER.match(content)
    if not match:
        title = Path(filename).stem
        return (
            "---\n"
            "layout: post\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n"
            f"permalink: /{Path(filename).stem}/\n"
            "---\n\n"
            + normalize_fenced_code_info(content)
        )

    body = match.group("body")

    def normalize_tags(tags_match: re.Match[str]) -> str:
        value = tags_match.group("value").strip()
        if not value or value.startswith("["):
            return tags_match.group(0)
        tags = [tag.strip() for tag in value.split(",") if tag.strip()]
        return f'{tags_match.group("indent")}tags: {json.dumps(tags, ensure_ascii=False)}'

    body = TAGS_LINE.sub(normalize_tags, body, count=1)

    if not re.search(r"^layout:\s*", body, re.MULTILINE):
        body = "layout: post\n" + body
    if not re.search(r"^permalink:\s*", body, re.MULTILINE):
        body += f"\npermalink: /{Path(filename).stem}/\n"

    return (
        f"---\n{body.rstrip()}\n---\n"
        + normalize_fenced_code_info(content[match.end() :])
    )


def markdown_files(source: Path) -> list[Path]:
    draft_root = source / "draft"
    if not draft_root.is_dir():
        raise RuntimeError(f"Draft directory not found in {source}")

    return sorted(
        path
        for path in draft_root.rglob("*.md")
        if path.is_file()
        and ".git" not in path.parts
        and path.name.lower() not in EXCLUDED_MARKDOWN_NAMES
    )


def import_posts(source: Path, destination: Path) -> int:
    files = markdown_files(source)
    if not files:
        raise RuntimeError(f"No Markdown posts found in {source / 'draft'}")

    destination.mkdir(parents=True, exist_ok=True)
    for existing in destination.glob("*.md"):
        existing.unlink()

    names = [path.name for path in files]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise RuntimeError(f"Duplicate Markdown filenames: {sorted(duplicates)}")

    for source_file in files:
        target = destination / source_file.name
        content = source_file.read_text(encoding="utf-8")
        target.write_text(
            normalize_front_matter(content, source_file.name), encoding="utf-8"
        )

    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()

    imported = import_posts(args.source, args.destination)
    print(f"Imported {imported} Markdown post(s) from {args.source}")


if __name__ == "__main__":
    main()
