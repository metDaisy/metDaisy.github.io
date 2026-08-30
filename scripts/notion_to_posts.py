"""Export published Notion database pages to temporary Jekyll posts."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from .notion_parser import parse_enhanced_markdown, plain_text, render_blocks
except ImportError:  # Script execution: python scripts/notion_to_posts.py
    from notion_parser import parse_enhanced_markdown, plain_text, render_blocks


API_VERSION = "2025-09-03"
API_ROOT = "https://api.notion.com/v1"
POSTS_DIR = Path("_notes")
LEGACY_POSTS_DIR = Path("_posts")
STATE_FILE = Path(".notion-sync.json")
MARKER = "<!-- notion-page-id:"
STATE_VERSION = 4


def load_dotenv() -> None:
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def notion_request(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    token = os.environ.get("NOTION_API_TOKEN")
    if not token:
        raise RuntimeError("NOTION_API_TOKEN is not configured")

    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": API_VERSION,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Notion API request failed with HTTP {error.code}") from error


def paged_request(path: str, payload: dict | None = None) -> list[dict]:
    results: list[dict] = []
    cursor = None
    while True:
        request_payload = dict(payload or {})
        request_payload["page_size"] = 100
        if cursor:
            request_payload["start_cursor"] = cursor
        response = notion_request(path, "POST", request_payload)
        results.extend(response.get("results", []))
        if not response.get("has_more"):
            return results
        cursor = response.get("next_cursor")


def paged_get(path: str) -> list[dict]:
    results: list[dict] = []
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        query = urllib.parse.urlencode(params)
        response = notion_request(f"{path}?{query}")
        results.extend(response.get("results", []))
        if not response.get("has_more"):
            return results
        cursor = response.get("next_cursor")


def property_value(properties: dict, name: str, kind: str | None = None):
    candidates = [properties.get(name)] if name else list(properties.values())
    for prop in candidates:
        if not prop or (kind and prop.get("type") != kind):
            continue
        prop_type = prop.get("type")
        if prop_type == "title":
            return plain_text(prop.get("title"))
        if prop_type == "rich_text":
            return plain_text(prop.get("rich_text"))
        if prop_type in ("select", "status"):
            selected = prop.get(prop_type)
            return selected.get("name", "") if selected else ""
        if prop_type == "date":
            date = prop.get("date")
            return date.get("start", "") if date else ""
        if prop_type == "multi_select":
            return [item.get("name", "") for item in prop.get("multi_select", [])]
        if prop_type == "checkbox":
            return prop.get("checkbox", False)
    return None


def page_title(page: dict) -> str:
    title = property_value(page.get("properties", {}), None, "title")
    return title or "Untitled note"


def page_date(page: dict) -> str:
    properties = page.get("properties", {})
    configured_name = os.environ.get("NOTION_DATE_PROPERTY", "")
    value = property_value(properties, configured_name, "date")
    value = value or page.get("created_time", "")
    return value[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def page_tags(page: dict) -> list[str]:
    properties = page.get("properties", {})
    configured_name = os.environ.get("NOTION_TAG_PROPERTY", "")
    values = property_value(properties, configured_name, "multi_select")
    return values or []


def is_published(page: dict) -> bool:
    property_name = os.environ.get("NOTION_PUBLISH_PROPERTY", "").strip()
    if not property_name:
        return True
    value = property_value(page.get("properties", {}), property_name)
    expected = os.environ.get("NOTION_PUBLISH_VALUE", "").strip() or "Published"
    return value is True or str(value).strip().lower() == expected.strip().lower()


def child_blocks(block_id: str) -> list[dict]:
    return paged_get(f"/blocks/{block_id}/children")


def page_content_markdown(page_id: str) -> str:
    try:
        response = notion_request(f"/pages/{page_id}/markdown?include_transcript=true")
        markdown = response.get("markdown", "")
        if isinstance(markdown, str):
            def load_unknown(block_id: str) -> str:
                try:
                    unknown = notion_request(f"/pages/{block_id}/markdown?include_transcript=true")
                    value = unknown.get("markdown", "")
                    return value if isinstance(value, str) else ""
                except RuntimeError:
                    return ""

            return parse_enhanced_markdown(
                markdown,
                response.get("unknown_block_ids", []),
                load_unknown,
            )
    except RuntimeError:
        pass

    # Compatibility fallback for connections that do not expose the markdown endpoint.
    return render_blocks(child_blocks(page_id), child_blocks)


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).strip().lower()
    return re.sub(r"[-\s]+", "-", value) or "note"


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def page_markdown(page: dict, body: str) -> str:
    title = page_title(page)
    date = page_date(page)
    tags = json.dumps(page_tags(page), ensure_ascii=False)
    description = " ".join(body.split())[:180]
    page_url = page.get("url", "")
    return "\n".join(
        [
            "---",
            "layout: post",
            f"title: {yaml_string(title)}",
            f"date: {date} 09:00:00 +0900",
            f"tags: {tags}",
            f"description: {yaml_string(description)}",
            f"notion_url: {yaml_string(page_url)}",
            "---",
            "",
            f"{MARKER} {page['id']} -->",
            "",
            body.strip(),
            "",
        ]
    )


def query_pages(filter_value: dict | None = None) -> list[dict]:
    data_source_id = os.environ.get("NOTION_DATA_SOURCE_ID", "").strip()
    database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if data_source_id:
        endpoints = [f"/data_sources/{data_source_id}/query"]
    elif database_id:
        database = notion_request(f"/databases/{database_id}")
        data_sources = database.get("data_sources", [])
        if data_sources:
            endpoints = [
                f"/data_sources/{item['id']}/query"
                for item in data_sources
                if item.get("id")
            ]
        else:
            endpoints = [f"/databases/{database_id}/query"]
    else:
        raise RuntimeError("NOTION_DATABASE_ID or NOTION_DATA_SOURCE_ID is required")

    payload = {"sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]}
    if filter_value:
        payload["filter"] = filter_value
    pages = []
    for endpoint in endpoints:
        pages.extend(paged_request(endpoint, payload))
    return pages


def query_child_databases(page_id: str) -> list[dict]:
    pages: list[dict] = []
    seen_data_sources: set[str] = set()

    for block in child_blocks(page_id):
        if block.get("type") != "child_database":
            continue

        database = notion_request(f"/databases/{block['id']}")
        data_sources = database.get("data_sources", [])
        if data_sources:
            for data_source in data_sources:
                data_source_id = data_source.get("id")
                if not data_source_id or data_source_id in seen_data_sources:
                    continue
                seen_data_sources.add(data_source_id)
                pages.extend(paged_request(f"/data_sources/{data_source_id}/query", {}))
        else:
            pages.extend(paged_request(f"/databases/{block['id']}/query", {}))

    return pages


def get_pages() -> list[dict]:
    if os.environ.get("NOTION_DATA_SOURCE_ID", "").strip() or os.environ.get("NOTION_DATABASE_ID", "").strip():
        return query_pages()

    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    if page_id:
        database_pages = query_child_databases(page_id)
        return database_pages or [notion_request(f"/pages/{page_id}")]
    return query_pages()


def sync_source_key() -> str:
    data_source_id = os.environ.get("NOTION_DATA_SOURCE_ID", "").strip()
    database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    if data_source_id:
        return f"data-source:{data_source_id}"
    if database_id:
        return f"database:{database_id}"
    if page_id:
        return f"page:{page_id}"
    return ""


def load_sync_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def save_sync_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    load_dotenv()
    if len(sys.argv) > 1 and sys.argv[1] == "--check-auth":
        notion_request("/users/me")
        print("Notion API authentication: ok")
        return

    force_full_sync = "--full" in sys.argv[1:]
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    state = load_sync_state()
    source_key = sync_source_key()
    can_incremental_sync = bool(os.environ.get("NOTION_DATA_SOURCE_ID", "").strip() or os.environ.get("NOTION_DATABASE_ID", "").strip())
    full_sync = (
        force_full_sync
        or not can_incremental_sync
        or state.get("version") != STATE_VERSION
        or state.get("source") != source_key
        or not state.get("last_scan_at")
    )

    # Always refresh the database index so deleted or unpublished pages can be
    # removed from the local cache. Only changed pages have their content read.
    current_pages = [page for page in get_pages() if is_published(page)]
    current_ids = {page["id"] for page in current_pages}
    if full_sync:
        pages = current_pages
    else:
        last_scan_at = state["last_scan_at"]
        pages = [
            page
            for page in current_pages
            if (page.get("last_edited_time") or page.get("created_time", ""))
            >= last_scan_at
        ]

    page_states = (
        {}
        if full_sync
        else {
            page_id: item
            for page_id, item in state.get("pages", {}).items()
            if page_id in current_ids
        }
    )
    active_ids = set(current_ids)
    active_files = {
        Path(item.get("filename")).name
        for item in page_states.values()
        if isinstance(item, dict) and item.get("filename")
    }
    synced_count = 0
    skipped_count = 0

    for page in pages:
        page_id = page["id"]
        edited_time = page.get("last_edited_time") or page.get("created_time", "")
        cached = page_states.get(page_id, {})
        if not isinstance(cached, dict):
            cached = {}
        cached_filename = cached.get("filename")
        if (
            not full_sync
            and cached.get("last_edited_time") == edited_time
            and isinstance(cached.get("number"), int)
            and cached_filename
            and Path(cached_filename).exists()
        ):
            active_ids.add(page_id)
            active_files.add(Path(cached_filename).name)
            skipped_count += 1
            continue

        body = page_content_markdown(page_id)
        title = page_title(page)
        active_ids.add(page_id)
        number = cached.get("number")
        if not isinstance(number, int):
            used_numbers = {
                item.get("number")
                for item in page_states.values()
                if isinstance(item, dict) and isinstance(item.get("number"), int)
            }
            number = 0
            while number in used_numbers:
                number += 1

        if title == "Untitled note" and not body:
            filename = None
        else:
            filename = POSTS_DIR / f"{number}.md"
            filename.write_text(page_markdown(page, body), encoding="utf-8")
            active_files.add(filename.name)

        page_states[page_id] = {
            "last_edited_time": edited_time,
            "number": number,
            "filename": filename.as_posix() if filename else None,
        }
        synced_count += 1

    state = {
        "version": STATE_VERSION,
        "source": source_key,
        "last_scan_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pages": page_states,
    }
    save_sync_state(state)

    for posts_dir in (POSTS_DIR, LEGACY_POSTS_DIR):
        for existing in posts_dir.glob("*.md"):
            content = existing.read_text(encoding="utf-8")
            if MARKER not in content:
                continue
            match = re.search(r"notion-page-id:\s*([^\s]+)", content)
            if match and (match.group(1) not in active_ids or existing.name not in active_files):
                existing.unlink()

    mode = "full" if full_sync else "incremental"
    print(f"Notion sync ({mode}): {synced_count} changed/new, {skipped_count} unchanged; {len(page_states)} cached page(s)")


if __name__ == "__main__":
    main()
