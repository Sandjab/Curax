#!/usr/bin/env python3
"""
Pipeline d'import autonome pour Curax.

Analyse, classifie, score et importe les articles HTML dans articles/.

Usage:
  python3 scripts/import-articles.py [infiles/]        # Analyse + preview
  python3 scripts/import-articles.py --yes [infiles/]   # Analyse + import sans confirmation
"""

import os
import sys
import re
import json
import hashlib
import shutil
import subprocess
from collections import defaultdict

# ---------------------------------------------------------------------------
# Répertoires
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ARTICLES_DIR = os.path.join(PROJECT_ROOT, "articles")

# ---------------------------------------------------------------------------
# Fonctions réutilisées depuis extract-x-articles.py
# ---------------------------------------------------------------------------

def _clean_entities(text):
    return (text
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&#39;", "'")
            .replace("&quot;", '"')
            .replace("&nbsp;", " "))


def _escape_html(text):
    return (text
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def extract_author(content):
    m = re.search(r'UserAvatar-Container-([A-Za-z0-9_]+)', content)
    if m:
        return m.group(1)
    m = re.search(r'author-name-tooltip[^>]*><a[^>]*>([^<]+)', content)
    if m:
        return m.group(1).strip()
    m = re.search(r'Prof\.\s+[A-Za-z]+\s+[A-Za-z]+', content)
    if m:
        return m.group(0)
    return "unknown"


def extract_text_spans(content):
    spans = re.findall(r'data-text="true"[^>]*>(.*?)</span>', content)
    if spans:
        return ' '.join(_clean_entities(s) for s in spans)

    idx = content.rfind('</style>')
    if idx >= 0:
        after = content[idx:]
        texts = re.findall(r'>([^<]{30,})<', after)
        meaningful = [
            t.strip() for t in texts
            if not any(kw in t for kw in (
                'color:', 'background:', 'font-', 'padding:',
                'margin:', 'border:', 'display:', 'position:',
            ))
        ]
        return ' '.join(meaningful)
    return ""


def extract_text_preview(content, max_len=200):
    spans = re.findall(r'data-text="true"[^>]*>(.*?)</span>', content)
    if spans:
        collected = []
        total = 0
        for span in spans:
            text = _clean_entities(span)
            if total + len(text) > max_len and total > 30:
                break
            collected.append(text)
            total += len(text)
        return re.sub(r'\s+', ' ', ' '.join(collected)).strip()

    idx = content.rfind('</style>')
    if idx >= 0:
        after = content[idx:]
        texts = re.findall(r'>([^<]{30,})<', after)
        meaningful = [
            t.strip() for t in texts
            if not any(kw in t for kw in (
                'color:', 'background:', 'font-', 'padding:',
                'margin:', 'border:', 'display:', 'position:',
            ))
        ]
        if meaningful:
            return meaningful[0][:max_len]
    return ""


def extract_content_fingerprint(content):
    spans = re.findall(r'data-text="true"[^>]*>(.*?)</span>', content)
    if spans:
        text = ' '.join(_clean_entities(s) for s in spans)
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    idx = content.rfind('</style>')
    if idx >= 0:
        after = content[idx:]
        texts = re.findall(r'>([^<]{30,})<', after)
        meaningful = [
            t.strip() for t in texts
            if not any(kw in t for kw in (
                'color:', 'background:', 'font-', 'padding:',
                'margin:', 'border:', 'display:', 'position:',
            ))
        ]
        text = ' '.join(meaningful)
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    return None


def inject_metadata(html_content, title, description):
    html_content = re.sub(
        r'<title>[^<]*</title>',
        f'<title>{_escape_html(title)}</title>',
        html_content,
        count=1
    )
    if re.search(r'<meta\s+name=["\']description["\']', html_content):
        html_content = re.sub(
            r'<meta\s+name=["\']description["\']\s+content=["\'][^"\']*["\'][^>]*/?>',
            f'<meta name="description" content="{_escape_html(description)}">',
            html_content,
            count=1
        )
    else:
        html_content = re.sub(
            r'(<meta[^>]*>)(\s*<(?:title|style|link))',
            rf'\1<meta name="description" content="{_escape_html(description)}">\2',
            html_content,
            count=1
        )
        if 'meta name="description"' not in html_content:
            html_content = html_content.replace(
                '</head>',
                f'<meta name="description" content="{_escape_html(description)}">\n</head>',
                1
            )
    return html_content


# ---------------------------------------------------------------------------
# Auto-détection de domaine
# ---------------------------------------------------------------------------

DOMAIN_RULES = [
    (r'claude\s*code|cowork|skills?\s*hook|subagent|CLAUDE\.md', 'claude-code'),
    (r'openclaw|moltbot|clawdbot|peter\s*steinberger', 'openclaw'),
    (r'security|vulnerab|hardening|firewall|sandbox', 'securite-ia'),
    (r'agent|swarm|mcp|orchestrat|autonomous|ralph', 'agents-ia'),
    (r'prompt|prompting|structured\s*knowledge', 'prompt-engineering'),
    (r'pricing|business|b2c|startup|revenue|founder', 'business-ia'),
    (r'vibe\s*cod|rebuild|mainstream|tools\s*for', 'vibe-coding'),
]


def detect_domain(text):
    text_lower = text.lower()
    for pattern, domain in DOMAIN_RULES:
        if re.search(pattern, text_lower):
            return domain
    return 'agents-ia'


# ---------------------------------------------------------------------------
# Analyse d'un article
# ---------------------------------------------------------------------------

def analyze_article(filepath, content):
    text = extract_text_spans(content)
    words = text.split()
    word_count = len(words)
    has_code = bool(re.search(r'```|def |function |const |import |class ', text))
    link_count = len(re.findall(r'https?://', text))
    thread_length = len(re.findall(r'data-text="true"', content))

    # Content type heuristics
    if has_code and word_count > 500:
        content_type = 'tutorial'
    elif link_count > 5:
        content_type = 'compilation'
    elif any(kw in text.lower() for kw in ('step by step', 'how to', 'guide', 'tutorial')):
        content_type = 'tutorial'
    elif any(kw in text.lower() for kw in ('life-changing', 'guaranteed', 'you need to', 'let me tell you')):
        content_type = 'motivational'
    elif any(kw in text.lower() for kw in ('list', 'top ', 'best ', 'tips')):
        content_type = 'listicle'
    else:
        content_type = 'critique'

    # Substance score
    score = 2
    if word_count > 800:
        score += 1
    if has_code:
        score += 1
    if link_count > 2:
        score += 1
    if word_count > 2000 and has_code:
        score += 1
    if content_type == 'motivational' and word_count < 500:
        score -= 1
    score = max(1, min(5, score))

    # Quality note
    type_labels = {
        'tutorial': 'Tutoriel technique',
        'critique': 'Analyse critique',
        'compilation': 'Compilation de ressources',
        'listicle': 'Liste structuree',
        'motivational': 'Contenu motivationnel',
        'announcement': 'Annonce produit'
    }
    parts = [type_labels.get(content_type, content_type.title())]
    if word_count > 2000:
        parts.append('long format')
    elif word_count < 300:
        parts.append('format court')
    if has_code:
        parts.append('avec code')
    if link_count > 3:
        parts.append(f'{link_count} liens')
    quality_note = ' — '.join(parts)

    # Auto-detect domain
    domain = detect_domain(text)

    # Generate slug from preview text
    preview = extract_text_preview(content, max_len=300)
    author = extract_author(content)

    # Title: first meaningful sentence
    first_sentence = preview[:120].split('.')[0].split('!')[0].split('?')[0].strip()
    if len(first_sentence) < 15:
        first_sentence = preview[:80].strip()
    title = first_sentence[:100]

    # Slug from title
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60]
    if not slug:
        slug = os.path.splitext(os.path.basename(filepath))[0]

    return {
        'filepath': filepath,
        'filename': os.path.basename(filepath),
        'author': author,
        'domain': domain,
        'slug': slug,
        'title': title,
        'description': preview[:200] if preview else '',
        'quality_score': score,
        'quality_note': quality_note,
        'word_count': word_count,
        'content_type': content_type,
    }


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def dedup_files(file_contents):
    fingerprints = {}
    excluded = set()
    for filepath, content in file_contents.items():
        fp = extract_content_fingerprint(content)
        if fp is None:
            continue
        if fp in fingerprints:
            excluded.add(filepath)
            print(f"  Doublon exclu : {os.path.basename(filepath)} (identique a {os.path.basename(fingerprints[fp])})")
        else:
            fingerprints[fp] = filepath
    return excluded


# ---------------------------------------------------------------------------
# Observations transversales
# ---------------------------------------------------------------------------

def generate_observations(articles_dir):
    """Recalcule les stats transversales et ecrit observations.md."""
    all_articles = []
    for domain_name in sorted(os.listdir(articles_dir)):
        domain_dir = os.path.join(articles_dir, domain_name)
        manifest_path = os.path.join(domain_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        with open(manifest_path, encoding='utf-8') as f:
            manifest = json.load(f)
        for fname, meta in manifest.get("articles", {}).items():
            all_articles.append({
                'domain': domain_name,
                'filename': fname,
                'quality_score': meta.get('quality_score', 0),
                'quality_note': meta.get('quality_note', ''),
            })

    if not all_articles:
        return

    total = len(all_articles)
    with_code = sum(1 for a in all_articles if 'avec code' in a['quality_note'])
    code_pct = int(with_code / total * 100) if total else 0

    # Domain stats
    domain_scores = defaultdict(list)
    for a in all_articles:
        domain_scores[a['domain']].append(a['quality_score'])

    # Author stats from HTML files
    author_counts = defaultdict(int)
    for domain_name in sorted(os.listdir(articles_dir)):
        domain_dir = os.path.join(articles_dir, domain_name)
        if not os.path.isdir(domain_dir):
            continue
        for fname in os.listdir(domain_dir):
            if not fname.endswith('.html'):
                continue
            fpath = os.path.join(domain_dir, fname)
            with open(fpath, encoding='utf-8', errors='replace') as f:
                content = f.read()
            author = extract_author(content)
            if author and author != 'unknown':
                author_counts[author] += 1

    # Find most prolific author
    top_author = max(author_counts, key=author_counts.get) if author_counts else None

    parts = []
    if top_author:
        parts.append(f"@{top_author} ({author_counts[top_author]} articles) est le plus prolifique mais aussi le plus inegal — entre compilations de liens utiles et du pur hype motivationnel creux.")
    parts.append(f"{code_pct}% des articles contiennent du code, bon indicateur de contenu actionnable.")

    # Best domain
    for d, scores in sorted(domain_scores.items()):
        avg = sum(scores) / len(scores)
        if avg >= 4.5:
            parts.append(f"Les articles {d} sont tous solides (scores 4-5).")

    obs_path = os.path.join(articles_dir, "observations.md")
    with open(obs_path, 'w', encoding='utf-8') as f:
        f.write(' '.join(parts) + '\n')
    print(f"  Observations ecrites dans {obs_path}")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def do_import(analyses, file_contents):
    """Injecte les metadonnees et copie les fichiers."""
    counts = defaultdict(int)

    for info in analyses:
        filepath = info['filepath']
        content = file_contents[filepath]
        domain = info['domain']
        slug = info['slug']
        title = info['title']
        description = info['description']

        # Inject metadata
        content = inject_metadata(content, title, description)

        # Create domain dir if needed
        domain_dir = os.path.join(ARTICLES_DIR, domain)
        os.makedirs(domain_dir, exist_ok=True)

        # Create domain manifest if needed
        domain_manifest_path = os.path.join(domain_dir, "manifest.json")
        if os.path.isfile(domain_manifest_path):
            with open(domain_manifest_path, encoding='utf-8') as f:
                domain_manifest = json.load(f)
        else:
            domain_manifest = {
                "name": domain.replace("-", " ").title(),
                "description": "",
                "icon": "",
                "articles": {}
            }

        # Write HTML
        dest_name = f"{slug}.html"
        dest_path = os.path.join(domain_dir, dest_name)
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Update domain manifest
        if "articles" not in domain_manifest:
            domain_manifest["articles"] = {}
        domain_manifest["articles"][dest_name] = {
            "quality_score": info['quality_score'],
            "quality_note": info['quality_note'],
        }

        with open(domain_manifest_path, 'w', encoding='utf-8') as f:
            json.dump(domain_manifest, f, indent=2, ensure_ascii=False)
            f.write('\n')

        counts[domain] += 1
        print(f"  {info['filename']} -> articles/{domain}/{dest_name}")

    print(f"\nResume : {sum(counts.values())} articles importes dans {len(counts)} domaine(s)")
    for d, c in sorted(counts.items()):
        print(f"  {d}: {c}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    auto_yes = '--yes' in args
    args = [a for a in args if a != '--yes']

    source_dir = args[0] if args else 'infiles'

    if not os.path.isdir(source_dir):
        print(f"Erreur : dossier '{source_dir}' introuvable", file=sys.stderr)
        sys.exit(1)

    html_files = sorted(f for f in os.listdir(source_dir) if f.endswith('.html'))
    if not html_files:
        print(f"Aucun fichier HTML dans {source_dir}")
        sys.exit(0)

    print(f"Trouve {len(html_files)} fichiers HTML dans {source_dir}\n")

    # Read all files
    file_contents = {}
    for fname in html_files:
        filepath = os.path.join(source_dir, fname)
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            file_contents[filepath] = f.read()

    # Step 1: Dedup
    print("1. Detection des doublons...")
    excluded = dedup_files(file_contents)
    if excluded:
        print(f"   {len(excluded)} doublon(s) exclus\n")
    else:
        print("   Aucun doublon\n")

    # Step 2: Analyze
    print("2. Analyse des articles...")
    analyses = []
    for filepath, content in file_contents.items():
        if filepath in excluded:
            continue
        info = analyze_article(filepath, content)
        analyses.append(info)

    # Step 3: Display plan
    print(f"\n3. Plan d'import ({len(analyses)} articles) :\n")
    print(f"  {'Domaine':<20} {'Score':>5}  {'Titre'}")
    print(f"  {'-'*20} {'-'*5}  {'-'*50}")
    for info in sorted(analyses, key=lambda x: (x['domain'], -x['quality_score'])):
        title_short = info['title'][:50]
        print(f"  {info['domain']:<20} {info['quality_score']:>3}/5  {title_short}")
    print()

    # Step 4: Confirm
    if not auto_yes:
        resp = input("Confirmer l'import ? [y/N] ").strip().lower()
        if resp not in ('y', 'yes', 'o', 'oui'):
            print("Import annule.")
            sys.exit(0)

    # Step 5: Import
    print("\n4. Import en cours...")
    do_import(analyses, file_contents)

    # Step 6: Regenerate observations
    print("\n5. Regeneration des observations...")
    generate_observations(ARTICLES_DIR)

    # Step 7: Regenerate manifest
    print("\n6. Regeneration du manifeste...")
    manifest_script = os.path.join(PROJECT_ROOT, ".github", "scripts", "generate_manifest.py")
    subprocess.run([sys.executable, manifest_script], cwd=PROJECT_ROOT, check=True)

    print("\nTermine !")


if __name__ == '__main__':
    main()
