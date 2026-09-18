"""Generate an MkDocs nav tree from Markdown front matter."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml


FRONT_MATTER = re.compile(r"\A---\r?\n(?P<body>.*?)(?:\r?\n)---\r?\n?", re.DOTALL)


def parse_front_matter(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(content)
    if match is None:
        raise ValueError(f"Missing front matter: {path}")

    metadata = yaml.safe_load(match.group("body")) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"Front matter must be a mapping: {path}")
    return metadata


def page_metadata(path: Path, docs_dir: Path) -> tuple[tuple[str, ...], str, int, str]:
    metadata = parse_front_matter(path)
    title = metadata.get("title")
    nav = metadata.get("nav", [])
    order = metadata.get("order", 1000)

    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Front matter title must be a non-empty string: {path}")
    if not isinstance(nav, list) or not all(isinstance(item, str) for item in nav):
        raise ValueError(f"Front matter nav must be a list of strings: {path}")
    if not isinstance(order, int):
        raise ValueError(f"Front matter order must be an integer: {path}")

    relative_path = path.relative_to(docs_dir).as_posix()
    return tuple(nav), title.strip(), order, relative_path


def new_node() -> dict[str, Any]:
    return {"pages": [], "children": {}}


def add_page(
    root: dict[str, Any],
    nav: tuple[str, ...],
    title: str,
    order: int,
    relative_path: str,
) -> None:
    node = root
    for section in nav:
        node = node["children"].setdefault(section, new_node())

    if any(page["title"] == title for page in node["pages"]):
        raise ValueError(f"Duplicate navigation title under {' / '.join(nav)}: {title}")
    node["pages"].append(
        {"title": title, "order": order, "path": relative_path}
    )


def minimum_order(node: dict[str, Any]) -> int:
    orders = [page["order"] for page in node["pages"]]
    orders.extend(minimum_order(child) for child in node["children"].values())
    return min(orders, default=1000)


def render_node(node: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[tuple[int, str, dict[str, Any]]] = []

    for page in node["pages"]:
        entries.append((page["order"], page["title"], {page["title"]: page["path"]}))

    for section, child in node["children"].items():
        entries.append((minimum_order(child), section, {section: render_node(child)}))

    return [item for _, _, item in sorted(entries, key=lambda entry: (entry[0], entry[1]))]


def generate(config_path: Path, docs_dir: Path, output_path: Path) -> None:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise ValueError(f"MkDocs config must be a mapping: {config_path}")

    root = new_node()
    pages = sorted(path for path in docs_dir.rglob("*.md") if path.is_file())
    if not pages:
        raise ValueError(f"No Markdown documents found: {docs_dir}")

    for page in pages:
        add_page(root, *page_metadata(page, docs_dir))

    config["nav"] = render_node(root)
    output_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--docs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.config, args.docs_dir, args.output)
    print(f"Generated MkDocs navigation for {args.docs_dir}")


if __name__ == "__main__":
    main()
