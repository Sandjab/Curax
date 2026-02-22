#!/usr/bin/env python3
"""Scan articles/ and generate manifest.json at the repo root."""

import json
import os
import subprocess
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ARTICLES_DIR = Path("articles")
OUTPUT = Path("manifest.json")


class MetadataExtractor(HTMLParser):
    """Extract <title> and <meta name="description"> from an HTML file."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.description = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            attrs_dict = dict(attrs)
            if attrs_dict.get("name", "").lower() == "description":
                self.description = attrs_dict.get("content", "")

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False


def extract_metadata(html_path: Path) -> dict:
    parser = MetadataExtractor()
    parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    return {"title": parser.title.strip(), "description": parser.description.strip()}


def get_last_commit_date(file_path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI", "--", str(file_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        iso = result.stdout.strip()
        if iso:
            return iso[:10]
    except subprocess.CalledProcessError:
        pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build_manifest():
    domains = []
    uncategorized = []

    if not ARTICLES_DIR.is_dir():
        return {"generated": now(), "domains": [], "uncategorized": []}

    # Collect domain subdirectories and root-level HTML files
    for entry in sorted(ARTICLES_DIR.iterdir()):
        if entry.is_dir():
            domain = build_domain(entry)
            if domain["articles"]:
                domains.append(domain)
        elif entry.suffix == ".html":
            uncategorized.append(build_article(entry))

    return {"generated": now(), "domains": domains, "uncategorized": uncategorized}


def build_domain(domain_dir: Path) -> dict:
    # Read optional domain manifest
    manifest_path = domain_dir / "manifest.json"
    meta = {}
    if manifest_path.is_file():
        try:
            meta = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    articles = []
    for html_file in sorted(domain_dir.glob("*.html")):
        articles.append(build_article(html_file))

    return {
        "slug": domain_dir.name,
        "name": meta.get("name", domain_dir.name.replace("-", " ").title()),
        "description": meta.get("description", ""),
        "icon": meta.get("icon", ""),
        "articles": articles,
    }


def build_article(html_path: Path) -> dict:
    meta = extract_metadata(html_path)
    return {
        "file": str(html_path),
        "title": meta["title"] or html_path.stem.replace("-", " ").title(),
        "description": meta["description"],
        "date": get_last_commit_date(html_path),
    }


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    manifest = build_manifest()
    OUTPUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Manifest generated: {len(manifest['domains'])} domain(s), {len(manifest['uncategorized'])} uncategorized article(s)")
