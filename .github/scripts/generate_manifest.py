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
    catalog_path = ARTICLES_DIR / "catalog.json"
    return build_manifest_from_catalog(catalog_path)


def build_manifest_from_catalog(catalog_path: Path) -> dict:
    """Construit le manifest depuis catalog.json (source de verite)."""
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    # Grouper les articles par domaine
    by_domain = {}
    for article_path, meta in catalog.get("articles", {}).items():
        domain_slug = meta["domain"]
        if domain_slug not in by_domain:
            by_domain[domain_slug] = []
        by_domain[domain_slug].append((article_path, meta))

    domains = []
    for slug, articles_list in by_domain.items():
        domain_info = catalog.get("domains", {}).get(slug, {})
        articles = []
        for article_path, meta in articles_list:
            html_path = Path(article_path)
            if not html_path.is_file():
                continue
            html_meta = extract_metadata(html_path)
            article = {
                "file": article_path,
                "title": html_meta["title"] or html_path.stem.replace("-", " ").title(),
                "description": html_meta["description"],
                "date": get_last_commit_date(html_path),
                "quality_score": meta.get("quality_score", 0),
                "quality_note": meta.get("quality_note", ""),
                "tags": meta.get("tags", []),
            }
            articles.append(article)

        # Trier articles par score desc
        articles.sort(key=lambda a: a.get("quality_score", 0), reverse=True)

        domains.append({
            "slug": slug,
            "name": domain_info.get("name", slug.replace("-", " ").title()),
            "description": domain_info.get("description", ""),
            "icon": domain_info.get("icon", ""),
            "articles": articles,
        })

    # Trier domaines par score moyen desc
    def _avg_score(domain):
        scores = [a.get("quality_score", 0) for a in domain["articles"]]
        return sum(scores) / len(scores) if scores else 0

    domains.sort(key=_avg_score, reverse=True)

    result = {"generated": now(), "domains": domains, "uncategorized": []}
    observations = catalog.get("observations", "")
    if observations:
        result["observations"] = observations
    return result


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    manifest = build_manifest()
    OUTPUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total_articles = sum(len(d["articles"]) for d in manifest["domains"])
    print(f"Manifest generated: {len(manifest['domains'])} domain(s), {total_articles} article(s), {len(manifest['uncategorized'])} uncategorized")
