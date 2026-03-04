#!/usr/bin/env python3

import argparse
import os
import sys
import re
import json
import hashlib
import shutil
import subprocess
import textwrap
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    import termios
    import tty
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

# ---------------------------------------------------------------------------
# Repertoires
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ARTICLES_DIR = os.path.join(PROJECT_ROOT, "articles")
CATALOG_PATH = os.path.join(ARTICLES_DIR, "catalog.json")
PAPERS_DIR = os.path.join(PROJECT_ROOT, "papers")
PAPERS_CATALOG_PATH = os.path.join(PAPERS_DIR, "catalog.json")

# ---------------------------------------------------------------------------
# Claude CLI helper
# ---------------------------------------------------------------------------

def call_claude(prompt, json_schema=None, timeout=120):
    """Appelle Claude CLI en mode print, retourne le JSON parse."""
    cmd = [shutil.which("claude") or "claude", "-p",
           "--output-format", "json", "--model", "opus"]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]
    # Pass prompt via stdin to avoid Windows command-line length limit (32k chars)
    env = {**os.environ}
    env.pop("CLAUDECODE", None)  # eviter "nested session"
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, encoding='utf-8', input=prompt)
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr[:500]}")
    envelope = json.loads(result.stdout)
    if json_schema and "structured_output" in envelope:
        return envelope["structured_output"]
    raw = envelope.get("result", "")
    return json.loads(raw) if json_schema else raw


def call_claude_with_retry(prompt, json_schema=None, max_retries=2, timeout=120):
    """Appelle Claude CLI avec retry et backoff exponentiel."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return call_claude(prompt, json_schema, timeout=timeout)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"  Retry {attempt + 1}/{max_retries} dans {wait}s... ({e})")
                time.sleep(wait)
    raise last_error


# ---------------------------------------------------------------------------
# JSON schemas pour Claude
# ---------------------------------------------------------------------------

TAXONOMY_SCHEMA = {
    "type": "object",
    "properties": {
        "domains": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "icon": {"type": "string"}
                },
                "required": ["name", "description", "icon"]
            }
        },
        "observations": {"type": "string"}
    },
    "required": ["domains", "observations"]
}

ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3
        },
        "quality_score": {"type": "integer", "minimum": 1, "maximum": 10},
        "quality_note": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"}
    },
    "required": ["domain", "tags", "quality_score", "quality_note", "title", "description"]
}

# ---------------------------------------------------------------------------
# JSON schemas pour Claude — Publications PDF
# ---------------------------------------------------------------------------

PAPER_TAXONOMY_SCHEMA = {
    "type": "object",
    "properties": {
        "domains": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "icon": {"type": "string"}
                },
                "required": ["name", "description", "icon"]
            }
        },
        "observations": {"type": "string"}
    },
    "required": ["domains", "observations"]
}

PAPER_LCA_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "quality_note": {"type": "string"},
        "authors": {"type": "array", "items": {"type": "string"}},
        "year": {"type": "integer"},
        "journal": {"type": "string"},
        "doi": {"type": "string"},
        "robustness_scores": {
            "type": "object",
            "properties": {
                "question_recherche": {"type": "integer", "minimum": 0, "maximum": 5},
                "design_experimental": {"type": "integer", "minimum": 0, "maximum": 5},
                "taille_echantillon": {"type": "integer", "minimum": 0, "maximum": 5},
                "qualite_metriques": {"type": "integer", "minimum": 0, "maximum": 5},
                "controle_biais": {"type": "integer", "minimum": 0, "maximum": 5},
                "reproductibilite": {"type": "integer", "minimum": 0, "maximum": 5},
                "transparence_limitations": {"type": "integer", "minimum": 0, "maximum": 5},
                "impact_nouveaute": {"type": "integer", "minimum": 0, "maximum": 5}
            },
            "required": ["question_recherche", "design_experimental", "taille_echantillon",
                         "qualite_metriques", "controle_biais", "reproductibilite",
                         "transparence_limitations", "impact_nouveaute"]
        },
        "robustness_global": {"type": "number", "minimum": 0, "maximum": 5},
        "lca_html": {"type": "string"}
    },
    "required": ["domain", "tags", "title", "description", "quality_note",
                  "authors", "year", "journal", "doi",
                  "robustness_scores", "robustness_global", "lca_html"]
}

PAPER_VULGARISATION_SCHEMA = {
    "type": "object",
    "properties": {
        "vulgarisation_html": {"type": "string"}
    },
    "required": ["vulgarisation_html"]
}

PAPER_RECLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
        "quality_note": {"type": "string"},
        "title": {"type": "string"}
    },
    "required": ["domain", "tags", "quality_note", "title"]
}


# ---------------------------------------------------------------------------
# Fonctions reutilisees depuis extract-x-articles.py
# ---------------------------------------------------------------------------

def _clean_entities(text):
    return (text
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&#39;", "'")
            .replace("&quot;", '"')
            .replace("&nbsp;", " "))


def _extract_pre_blocks(content):
    """Extract text from <pre><code>...</code></pre> blocks, stripping inner HTML tags."""
    blocks = re.findall(r'<pre[^>]*>(.*?)</pre>', content, re.DOTALL)
    if not blocks:
        return ""
    cleaned = []
    for block in blocks:
        text = re.sub(r'<[^>]+>', '', block)
        text = _clean_entities(text).strip()
        if text:
            cleaned.append(text)
    return '\n\n'.join(cleaned)


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
        text = ' '.join(_clean_entities(s) for s in spans)
        pre_text = _extract_pre_blocks(content)
        if pre_text:
            text = text + '\n\n' + pre_text
        return text

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
        if total < max_len:
            pre_text = _extract_pre_blocks(content)
            if pre_text:
                remaining = max_len - total
                collected.append(pre_text[:remaining])
        return re.sub(r'\s+', ' ', ' '.join(collected)).strip()[:max_len]

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
        pre_text = _extract_pre_blocks(content)
        if pre_text:
            text = text + '\n\n' + pre_text
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


# ---------------------------------------------------------------------------
# Extraction PDF
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path):
    """Extrait le texte complet d'un PDF via pdfplumber."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return '\n\n'.join(text_parts)


def extract_pdf_doi(text):
    """Extrait le premier DOI trouve dans le texte."""
    m = re.search(r'10\.\d{4,9}/[^\s,;}\]]+', text)
    return m.group(0).rstrip('.') if m else ""


def extract_pdf_fingerprint(text):
    """SHA-256 du texte nettoyé. Retourne None si texte trop court."""
    cleaned = re.sub(r'\s+', ' ', text).strip()
    if len(cleaned) < 100:
        return None
    return hashlib.sha256(cleaned.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# Deduplication PDF
# ---------------------------------------------------------------------------

def dedup_pdf_files(pdf_texts):
    """Dedup intra-batch par fingerprint. Retourne l'ensemble des chemins exclus."""
    fingerprints = {}
    excluded = set()
    for filepath, text in pdf_texts.items():
        fp = extract_pdf_fingerprint(text)
        if fp is None:
            continue
        if fp in fingerprints:
            excluded.add(filepath)
            print(f"  Doublon PDF exclu : {os.path.basename(filepath)} (identique a {os.path.basename(fingerprints[fp])})")
        else:
            fingerprints[fp] = filepath
    return excluded


def dedup_pdfs_against_catalog(pdf_texts, excluded, papers_catalog):
    """Compare les nouveaux PDFs au catalogue existant par fingerprint + DOI."""
    # Fingerprints existants
    existing_fps = set()
    existing_dois = set()
    for paper_key, meta in papers_catalog.get("papers", {}).items():
        pdf_path = os.path.join(PROJECT_ROOT, paper_key)
        if os.path.isfile(pdf_path):
            try:
                text = extract_pdf_text(pdf_path)
                fp = extract_pdf_fingerprint(text)
                if fp:
                    existing_fps.add(fp)
            except Exception:
                pass
        doi = meta.get("doi", "")
        if doi:
            existing_dois.add(doi.lower())

    catalog_dupes = set()
    for filepath, text in pdf_texts.items():
        if filepath in excluded:
            continue
        # Check fingerprint
        fp = extract_pdf_fingerprint(text)
        if fp and fp in existing_fps:
            catalog_dupes.add(filepath)
            print(f"  Deja importe (fingerprint) : {os.path.basename(filepath)}")
            continue
        # Check DOI
        doi = extract_pdf_doi(text)
        if doi and doi.lower() in existing_dois:
            catalog_dupes.add(filepath)
            print(f"  Deja importe (DOI) : {os.path.basename(filepath)}")
    return catalog_dupes


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
# Slugification
# ---------------------------------------------------------------------------

def slugify(text, max_len=60):
    """Convertit un texte en slug kebab-case."""
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:max_len]
    return slug or "untitled"


# ---------------------------------------------------------------------------
# Analyse d'un article (simplifiee — plus de scoring/domain heuristiques)
# ---------------------------------------------------------------------------

def analyze_article(filepath, content):
    """Extrait les donnees brutes d'un article. Le scoring et le domaine
    sont delegues a Claude."""
    text = extract_text_spans(content)
    author = extract_author(content)
    preview = extract_text_preview(content, max_len=300)

    # Slug provisoire depuis le texte (sera remplace par le titre Claude apres scoring)
    first_sentence = preview[:120].split('.')[0].split('!')[0].split('?')[0].strip()
    if len(first_sentence) < 15:
        first_sentence = preview[:80].strip()
    slug = slugify(first_sentence[:100])
    if slug == "untitled":
        slug = os.path.splitext(os.path.basename(filepath))[0]

    return {
        'filepath': filepath,
        'filename': os.path.basename(filepath),
        'author': author,
        'slug': slug,
        'text': text,
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


def dedup_against_catalog(file_contents, excluded, catalog):
    """Compare les nouveaux fichiers aux articles deja importes dans catalog.json.
    Retourne l'ensemble des fichiers source qui sont des doublons d'articles existants."""
    # Construire les fingerprints des articles existants
    existing_fps = {}
    for article_key in catalog.get("articles", {}):
        html_path = os.path.join(PROJECT_ROOT, article_key)
        if not os.path.isfile(html_path):
            continue
        with open(html_path, encoding='utf-8', errors='replace') as f:
            content = f.read()
        fp = extract_content_fingerprint(content)
        if fp is not None:
            existing_fps[fp] = article_key

    # Comparer les nouveaux fichiers
    catalog_dupes = set()
    for filepath, content in file_contents.items():
        if filepath in excluded:
            continue
        fp = extract_content_fingerprint(content)
        if fp is not None and fp in existing_fps:
            catalog_dupes.add(filepath)
            print(f"  Deja importe : {os.path.basename(filepath)} (identique a {existing_fps[fp]})")
    return catalog_dupes


# ---------------------------------------------------------------------------
# Catalog management (articles/catalog.json)
# ---------------------------------------------------------------------------

def load_catalog():
    """Charge catalog.json ou retourne un catalogue vide."""
    if os.path.isfile(CATALOG_PATH):
        with open(CATALOG_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {"domains": {}, "articles": {}, "observations": ""}


def save_catalog(catalog):
    """Ecrit catalog.json."""
    os.makedirs(os.path.dirname(CATALOG_PATH), exist_ok=True)
    with open(CATALOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f"  Catalog ecrit dans {CATALOG_PATH}")


def load_papers_catalog():
    """Charge papers/catalog.json ou retourne un catalogue vide."""
    if os.path.isfile(PAPERS_CATALOG_PATH):
        with open(PAPERS_CATALOG_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {"domains": {}, "papers": {}, "observations": ""}


def save_papers_catalog(catalog):
    """Ecrit papers/catalog.json."""
    os.makedirs(os.path.dirname(PAPERS_CATALOG_PATH), exist_ok=True)
    with open(PAPERS_CATALOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f"  Catalog papers ecrit dans {PAPERS_CATALOG_PATH}")


def migrate_to_catalog():
    """Migration one-time : lit les 8 manifests de domaine + observations.md
    et construit catalog.json. Les scores /5 sont convertis en /10 (x2, plafonne a 10)."""
    catalog = {"domains": {}, "articles": {}, "observations": ""}

    # Lire observations.md
    obs_path = os.path.join(ARTICLES_DIR, "observations.md")
    if os.path.isfile(obs_path):
        with open(obs_path, encoding='utf-8') as f:
            catalog["observations"] = f.read().strip()

    # Lire les manifests de domaine
    for domain_name in sorted(os.listdir(ARTICLES_DIR)):
        domain_dir = os.path.join(ARTICLES_DIR, domain_name)
        manifest_path = os.path.join(domain_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue

        with open(manifest_path, encoding='utf-8') as f:
            manifest = json.load(f)

        # Ajouter le domaine
        catalog["domains"][domain_name] = {
            "name": manifest.get("name", domain_name.replace("-", " ").title()),
            "description": manifest.get("description", ""),
            "icon": manifest.get("icon", ""),
        }

        # Ajouter les articles
        for fname, meta in manifest.get("articles", {}).items():
            article_path = f"articles/{domain_name}/{fname}"
            old_score = meta.get("quality_score", 3)
            new_score = min(old_score * 2, 10)
            catalog["articles"][article_path] = {
                "domain": domain_name,
                "tags": [],
                "quality_score": new_score,
                "quality_note": meta.get("quality_note", ""),
            }

    total = len(catalog["articles"])
    domains = len(catalog["domains"])
    print(f"Migration terminee : {total} articles dans {domains} domaines")
    print(f"Scores convertis de /5 a /10 (x2, plafonne a 10)")

    save_catalog(catalog)
    return catalog


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_taxonomy_prompt(catalog, new_articles):
    """Construit le prompt pour l'appel taxonomie Claude.
    Recoit le catalogue existant + les previews des nouveaux articles."""
    existing_summary = []
    for path, meta in catalog.get("articles", {}).items():
        existing_summary.append(f"- {path} (domaine: {meta['domain']})")
    existing_text = '\n'.join(existing_summary) if existing_summary else "(aucun article existant)"

    new_previews = []
    for info in new_articles:
        preview = info['text'][:500]
        new_previews.append(f"- {info['filename']}: {preview}")
    new_text = '\n'.join(new_previews)

    return f"""Tu es un classificateur d'articles sur l'IA et la tech.

ARTICLES EXISTANTS dans le corpus :
{existing_text}

NOUVEAUX ARTICLES a classifier :
{new_text}

DOMAINES EXISTANTS :
{json.dumps(catalog.get('domains', {}), indent=2, ensure_ascii=False)}

Ta tache :
1. Produis la taxonomie optimale des domaines pour le corpus complet (existants + nouveaux).
   - Conserve les domaines existants sauf si un domaine n'a vraiment plus de sens.
   - Tu peux creer de nouveaux domaines si un nouveau article ne rentre dans aucun existant.
   - Chaque domaine a un slug (kebab-case), un nom, une description courte, et un emoji icon.

2. Genere un paragraphe "observations" : une analyse transversale du corpus entier (tendances, points forts, lacunes, auteurs notables). 2-4 phrases maximum, style editorialise et critique.

Reponds en JSON."""


def build_article_prompt(text, taxonomy_domains):
    """Construit le prompt pour scorer un article individuel."""
    truncated = text[:40000]
    domains_desc = json.dumps(taxonomy_domains, indent=2, ensure_ascii=False)

    return f"""Tu es un evaluateur d'articles techniques sur l'IA.

TAXONOMIE DES DOMAINES DISPONIBLES :
{domains_desc}

TEXTE DE L'ARTICLE :
{truncated}

REGLE IMPORTANTE : classe selon le SUJET PRINCIPAL de l'article, pas selon les outils ou technologies mentionnes en exemple.
Un article qui explique des patterns d'agents IA avec des exemples Claude Code reste un article sur les agents IA.
Un article sur la securite des LLM qui mentionne des outils de code reste un article sur la securite.

Ta tache : analyse cet article et produis :
- domain : le slug du domaine le plus pertinent parmi ceux listes ci-dessus
- tags : 1-3 tags en kebab-case (ex: "mcp", "orchestration", "prompting", "few-shot", "rag")
- quality_score : note de 1 a 10 selon ces criteres :
  * 1-2 : Contenu creux, promotionnel ou motivationnel sans substance
  * 3-4 : Superficiel, peu d'informations actionnables
  * 5-6 : Correct, quelques insights mais manque de profondeur ou d'exemples
  * 7-8 : Bon contenu, informations actionnables, exemples de code ou liens utiles
  * 9-10 : Excellent, tutoriel approfondi, code concret, ressources riches, reference sur le sujet
- quality_note : description synthetique du contenu (1 phrase, pas de label generique)
- title : titre clair et descriptif pour l'article
- description : description en 1-2 phrases du contenu

Reponds en JSON."""


def build_reclassify_taxonomy_prompt(catalog):
    """Construit le prompt taxonomie pour la reclassification complete."""
    article_summaries = []
    for path, meta in catalog.get("articles", {}).items():
        article_summaries.append(f"- {path} (domaine actuel: {meta['domain']}, score: {meta['quality_score']})")
    articles_text = '\n'.join(article_summaries)

    return f"""Tu es un classificateur d'articles sur l'IA et la tech.

CORPUS COMPLET ({len(catalog.get('articles', {}))} articles) :
{articles_text}

DOMAINES ACTUELS :
{json.dumps(catalog.get('domains', {}), indent=2, ensure_ascii=False)}

Ta tache :
1. Reevalue la taxonomie des domaines pour ce corpus.
   - Conserve les domaines pertinents, supprime ceux qui sont vides ou redondants.
   - Tu peux creer de nouveaux domaines si necessaire.
   - Chaque domaine a un slug (kebab-case), un nom, une description courte, et un emoji icon.

2. Genere un paragraphe "observations" : une analyse transversale du corpus (tendances, points forts, lacunes, auteurs notables). 2-4 phrases maximum, style editorialise et critique.

Reponds en JSON."""


# ---------------------------------------------------------------------------
# Prompt builders — Publications PDF
# ---------------------------------------------------------------------------

def build_paper_taxonomy_prompt(papers_catalog, new_papers):
    """Construit le prompt taxonomie pour les publications scientifiques."""
    existing_summary = []
    for path, meta in papers_catalog.get("papers", {}).items():
        existing_summary.append(f"- {path} (domaine: {meta['domain']})")
    existing_text = '\n'.join(existing_summary) if existing_summary else "(aucune publication existante)"

    new_previews = []
    for info in new_papers:
        preview = info['text'][:500]
        new_previews.append(f"- {info['filename']}: {preview}")
    new_text = '\n'.join(new_previews)

    return f"""Tu es un classificateur de publications scientifiques en IA et tech.

PUBLICATIONS EXISTANTES dans le corpus :
{existing_text}

NOUVELLES PUBLICATIONS a classifier :
{new_text}

DOMAINES EXISTANTS :
{json.dumps(papers_catalog.get('domains', {}), indent=2, ensure_ascii=False)}

Ta tache :
1. Produis la taxonomie optimale des axes de recherche pour le corpus complet (existants + nouveaux).
   - Conserve les domaines existants sauf si un domaine n'a vraiment plus de sens.
   - Tu peux creer de nouveaux domaines si une publication ne rentre dans aucun existant.
   - Chaque domaine a un slug (kebab-case), un nom, une description courte, et un emoji icon.
   - Oriente les domaines vers des axes de recherche scientifique (pas des categories editoriales).

2. Genere un paragraphe "observations" : une analyse transversale du corpus de publications (tendances methodologiques, axes porteurs, lacunes, auteurs notables). 2-4 phrases maximum, style editorialise et critique.

Reponds en JSON."""


def build_paper_lca_prompt(text, taxonomy_domains):
    """Construit le prompt pour l'analyse LCA d'une publication."""
    truncated = text[:60000]
    domains_desc = json.dumps(taxonomy_domains, indent=2, ensure_ascii=False)

    return f"""Tu es un évaluateur de publications scientifiques. Tu produis une Lecture Critique d'Article (LCA) rigoureuse, rédigée en français correct avec accents.

TAXONOMIE DES DOMAINES DISPONIBLES :
{domains_desc}

TEXTE DE LA PUBLICATION :
{truncated}

Ta tâche : analyse cette publication et produis :

1. MÉTADONNÉES :
- domain : le slug du domaine le plus pertinent
- tags : 1-3 tags en kebab-case
- title : titre de la publication
- description : description en 1-2 phrases
- quality_note : appréciation synthétique du contenu (1 phrase)
- authors : liste des auteurs (format "Nom, Initiale.")
- year : année de publication (entier)
- journal : nom du journal/conférence
- doi : identifiant DOI si présent dans le texte (sinon chaîne vide)

2. SCORES DE ROBUSTESSE (0-5 chacun) :
- question_recherche : clarté, originalité, pertinence
- design_experimental : adéquation du protocole
- taille_echantillon : puissance statistique
- qualite_metriques : validité des mesures
- controle_biais : gestion des confondants
- reproductibilite : données/code disponibles
- transparence_limitations : honnêteté sur les limites
- impact_nouveaute : contribution au domaine

3. NOTE GLOBALE (robustness_global) : note de 0 à 5 (nombre décimal), appréciation indépendante de la qualité globale de la publication. Ce n'est PAS la moyenne des scores ci-dessus mais ton évaluation synthétique.

4. LCA EN HTML (lca_html) : document HTML complet d'analyse critique en français, structuré en 7 sections :
   - Objectif et contexte
   - Méthodologie
   - Résultats principaux
   - Discussion et limites
   - Reproductibilité
   - Impact et applications
   - Positionnement dans la littérature

   Inclus un tableau récapitulatif des 8 critères de robustesse avec les scores.
   Le HTML doit contenir UNIQUEMENT le contenu du <body> (pas de <html>, <head>, <body> tags).
   Utilise des balises sémantiques : <h2>, <h3>, <p>, <table>, <ul>, <strong>.

Rédige l'intégralité du HTML en français correctement accentué.
Réponds en JSON."""


def build_paper_vulgarisation_prompt(text, title, authors):
    """Construit le prompt pour la vulgarisation d'une publication."""
    truncated = text[:40000]
    authors_str = ', '.join(authors[:5])

    return f"""Tu es un vulgarisateur scientifique expert. Tu rediges des articles de vulgarisation en francais.

PUBLICATION : "{title}" par {authors_str}

TEXTE DE LA PUBLICATION :
{truncated}

Ta tache : redige un article de vulgarisation en francais (~2000 mots).

STRUCTURE en 6 sections :
1. Introduction : accroche et contexte general
2. Le probleme : quel defi scientifique est adresse
3. La methode vulgarisee : comment les chercheurs s'y sont pris (sans formules, analogies bienvenues)
4. Resultats cles : les decouvertes principales, chiffres marquants
5. Implications pratiques : pourquoi ca compte pour l'industrie/la societe
6. Pour aller plus loin : ouvertures, questions non resolues, pistes futures

PUBLIC : professionnel tech non specialiste du domaine.
TON : pedagogique, engage, pas condescendant. Pas de formules mathematiques.

Le HTML doit contenir UNIQUEMENT le contenu du <body> (pas de <html>, <head>, <body> tags).
Utilise des balises semantiques : <h2>, <h3>, <p>, <blockquote>, <ul>, <strong>, <em>.

Reponds en JSON avec la cle "vulgarisation_html"."""


def build_paper_reclassify_taxonomy_prompt(papers_catalog):
    """Construit le prompt taxonomie pour la reclassification des publications."""
    paper_summaries = []
    for path, meta in papers_catalog.get("papers", {}).items():
        paper_summaries.append(f"- {path} (domaine actuel: {meta['domain']}, score: {meta['quality_score']})")
    papers_text = '\n'.join(paper_summaries)

    return f"""Tu es un classificateur de publications scientifiques en IA et tech.

CORPUS COMPLET ({len(papers_catalog.get('papers', {}))} publications) :
{papers_text}

DOMAINES ACTUELS :
{json.dumps(papers_catalog.get('domains', {}), indent=2, ensure_ascii=False)}

Ta tache :
1. Reevalue la taxonomie des axes de recherche pour ce corpus.
   - Conserve les domaines pertinents, supprime ceux qui sont vides ou redondants.
   - Tu peux creer de nouveaux domaines si necessaire.
   - Chaque domaine a un slug (kebab-case), un nom, une description courte, et un emoji icon.

2. Genere un paragraphe "observations" : une analyse transversale du corpus (tendances methodologiques, axes porteurs, lacunes). 2-4 phrases maximum, style editorialise et critique.

Reponds en JSON."""


def build_paper_reclassify_prompt(text, taxonomy_domains):
    """Construit le prompt pour reclassifier une publication (leger, sans LCA)."""
    truncated = text[:40000]
    domains_desc = json.dumps(taxonomy_domains, indent=2, ensure_ascii=False)

    return f"""Tu es un evaluateur de publications scientifiques.

TAXONOMIE DES DOMAINES DISPONIBLES :
{domains_desc}

TEXTE DE LA PUBLICATION :
{truncated}

Ta tache : reclassifie cette publication et produis :
- domain : le slug du domaine le plus pertinent
- tags : 1-3 tags en kebab-case
- quality_note : appreciation synthetique du contenu (1 phrase)
- title : titre de la publication

Reponds en JSON."""


# ---------------------------------------------------------------------------
# Template HTML compagnon (LCA / vulgarisation)
# ---------------------------------------------------------------------------

def build_companion_html(title, body_html, doc_type):
    """Wrap le contenu genere dans un HTML standalone avec theme Curax.

    doc_type: 'lca' ou 'vulgarisation'
    """
    doc_label = "Lecture Critique d'Article" if doc_type == 'lca' else "Vulgarisation"

    return f'''<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_escape_html(title)} — {doc_label}</title>
  <script>
  (function(){{
    var m = localStorage.getItem('curax-mode') || 'light';
    var t = localStorage.getItem('curax-theme') || 'portfolio';
    document.documentElement.setAttribute('data-mode', m);
    document.documentElement.setAttribute('data-theme', t);
  }})();
  </script>
  <script src="../../../themes.js"></script>
  <style>
    :root {{
      --background: #f8f7f2; --foreground: #1a1a1a; --card: #ffffff;
      --card-foreground: #1a1a1a; --primary: #c1a875; --primary-foreground: #ffffff;
      --primary-hover: #b09560; --secondary: #f0ece0; --muted: #f0ece0;
      --muted-foreground: #6b6352; --border: #e2decb; --input: #e2decb;
      --ring: #c1a875; --radius: 0.75rem;
      --font-stack: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: var(--font-stack);
      background-color: var(--background);
      color: var(--foreground);
      line-height: 1.8;
      min-height: 100vh;
    }}
    .companion-header {{
      padding: 1.5rem 2rem 1rem;
      border-bottom: 1px solid var(--border);
      max-width: 800px;
      margin: 0 auto;
    }}
    .companion-header a {{
      color: var(--muted-foreground);
      text-decoration: none;
      font-size: 0.9rem;
    }}
    .companion-header a:hover {{ text-decoration: underline; }}
    .companion-header h1 {{
      font-size: 1.6rem;
      font-weight: 700;
      margin-top: 0.5rem;
      line-height: 1.3;
    }}
    .companion-header .doc-type {{
      font-size: 0.85rem;
      color: var(--muted-foreground);
      margin-top: 0.25rem;
    }}
    .companion-content {{
      max-width: 800px;
      margin: 0 auto;
      padding: 2rem;
    }}
    .companion-content h2 {{
      font-size: 1.3rem;
      font-weight: 600;
      margin: 2rem 0 0.75rem;
      padding-bottom: 0.3rem;
      border-bottom: 1px solid var(--border);
    }}
    .companion-content h3 {{
      font-size: 1.1rem;
      font-weight: 600;
      margin: 1.5rem 0 0.5rem;
    }}
    .companion-content p {{
      margin-bottom: 1rem;
    }}
    .companion-content ul, .companion-content ol {{
      margin: 0.5rem 0 1rem 1.5rem;
    }}
    .companion-content li {{
      margin-bottom: 0.3rem;
    }}
    .companion-content blockquote {{
      border-left: 3px solid var(--primary);
      padding: 0.75rem 1rem;
      margin: 1rem 0;
      background-color: var(--muted);
      border-radius: var(--radius);
      font-style: italic;
    }}
    .companion-content table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0;
      font-size: 0.9rem;
    }}
    .companion-content th, .companion-content td {{
      padding: 0.6rem 0.8rem;
      border: 1px solid var(--border);
      text-align: left;
    }}
    .companion-content th {{
      background-color: var(--muted);
      font-weight: 600;
    }}
    .companion-content tr:nth-child(even) {{
      background-color: color-mix(in srgb, var(--muted) 50%, transparent);
    }}
    /* Score coloring in LCA tables */
    .score-5 {{ color: hsl(142, 71%, 35%); font-weight: 700; }}
    .score-4 {{ color: hsl(120, 40%, 40%); font-weight: 600; }}
    .score-3 {{ color: hsl(45, 93%, 37%); font-weight: 600; }}
    .score-2 {{ color: hsl(25, 95%, 43%); font-weight: 600; }}
    .score-1 {{ color: hsl(0, 72%, 45%); font-weight: 600; }}
    .score-0 {{ color: hsl(0, 0%, 50%); font-weight: 600; }}
    @media (max-width: 600px) {{
      .companion-header, .companion-content {{ padding: 1rem; }}
      .companion-header h1 {{ font-size: 1.3rem; }}
      .companion-content table {{ font-size: 0.8rem; }}
      .companion-content th, .companion-content td {{ padding: 0.4rem; }}
    }}
  </style>
</head>
<body>
  <div class="companion-header">
    <a href="../../../index.html">&larr; Retour a Curax</a>
    <h1>{_escape_html(title)}</h1>
    <p class="doc-type">{doc_label}</p>
  </div>
  <div class="companion-content">
    {body_html}
  </div>
  <script>
  (function(){{
    if (typeof CURAX_THEMES !== 'undefined') {{
      var t = localStorage.getItem('curax-theme') || 'portfolio';
      var m = localStorage.getItem('curax-mode') || 'light';
      var theme = CURAX_THEMES[t];
      if (theme) {{
        var styles = theme[m];
        var root = document.documentElement;
        for (var key in styles) {{
          root.style.setProperty('--' + key, styles[key]);
        }}
      }}
    }}
  }})();
  </script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def do_import(analyses, file_contents, catalog):
    """Injecte les metadonnees et copie les fichiers. Met a jour catalog."""
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

        # Write HTML
        dest_name = f"{slug}.html"
        dest_path = os.path.join(domain_dir, dest_name)
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Update catalog
        article_key = f"articles/{domain}/{dest_name}"
        catalog["articles"][article_key] = {
            "domain": domain,
            "tags": info.get('tags', []),
            "quality_score": info['quality_score'],
            "quality_note": info['quality_note'],
        }

        counts[domain] += 1
        print(f"  {info['filename']} -> articles/{domain}/{dest_name}")

    print(f"\nResume : {sum(counts.values())} articles importes dans {len(counts)} domaine(s)")
    for d, c in sorted(counts.items()):
        print(f"  {d}: {c}")


def move_or_rename_article(catalog, article_key, new_domain=None, new_slug=None):
    """Deplace et/ou renomme un fichier HTML. Met a jour catalog."""
    old_path = os.path.join(PROJECT_ROOT, article_key)
    if not os.path.isfile(old_path):
        print(f"  ATTENTION : {article_key} introuvable, skip")
        return None

    old_filename = os.path.basename(article_key)
    old_domain = article_key.split('/')[1]  # articles/{domain}/{file}

    domain = new_domain or old_domain
    filename = f"{new_slug}.html" if new_slug else old_filename

    new_dir = os.path.join(ARTICLES_DIR, domain)
    os.makedirs(new_dir, exist_ok=True)
    new_path = os.path.join(new_dir, filename)
    new_key = f"articles/{domain}/{filename}"

    if new_key == article_key:
        return None  # Rien a faire

    shutil.move(old_path, new_path)

    # Mettre a jour catalog
    meta = catalog["articles"].pop(article_key)
    meta["domain"] = domain
    catalog["articles"][new_key] = meta

    return new_key


def move_or_rename_paper(papers_catalog, paper_key, new_domain=None, new_slug=None):
    """Deplace et/ou renomme un sous-dossier de publication. Met a jour le catalogue."""
    old_path = os.path.join(PROJECT_ROOT, paper_key)
    if not os.path.isfile(old_path):
        print(f"  ATTENTION : {paper_key} introuvable, skip")
        return None

    # papers/{domain}/{slug}/{slug}.pdf
    parts = paper_key.split('/')
    old_domain = parts[1]
    old_slug = parts[2]
    old_folder = os.path.join(PAPERS_DIR, old_domain, old_slug)

    domain = new_domain or old_domain
    slug = new_slug or old_slug

    new_folder = os.path.join(PAPERS_DIR, domain, slug)
    new_key = f"papers/{domain}/{slug}/{slug}.pdf"

    if new_key == paper_key:
        return None

    os.makedirs(os.path.dirname(new_folder), exist_ok=True)
    shutil.move(old_folder, new_folder)

    # Renommer les fichiers si le slug a change
    if new_slug and new_slug != old_slug:
        for fname in os.listdir(new_folder):
            if fname.startswith(old_slug):
                suffix = fname[len(old_slug):]
                new_fname = slug + suffix
                os.rename(os.path.join(new_folder, fname), os.path.join(new_folder, new_fname))

    # Mettre a jour catalog
    meta = papers_catalog["papers"].pop(paper_key)
    meta["domain"] = domain
    # Mettre a jour les chemins des compagnons
    meta["vulgarisation_file"] = f"papers/{domain}/{slug}/{slug}-vulgarisation.html"
    meta["lca_file"] = f"papers/{domain}/{slug}/{slug}-lca.html"
    papers_catalog["papers"][new_key] = meta

    return new_key


def do_import_papers(paper_analyses, papers_catalog):
    """Copie les PDFs, ecrit les compagnons, met a jour papers/catalog.json."""
    counts = defaultdict(int)

    for info in paper_analyses:
        domain = info['domain']
        slug = info['slug']
        filepath = info['filepath']

        # Creer le sous-dossier papers/{domain}/{slug}/
        paper_dir = os.path.join(PAPERS_DIR, domain, slug)
        os.makedirs(paper_dir, exist_ok=True)

        # Copier le PDF
        dest_pdf = os.path.join(paper_dir, f"{slug}.pdf")
        shutil.copy2(filepath, dest_pdf)

        # Ecrire les compagnons
        lca_html = build_companion_html(info['title'], info['lca_html'], 'lca')
        lca_path = os.path.join(paper_dir, f"{slug}-lca.html")
        with open(lca_path, 'w', encoding='utf-8') as f:
            f.write(lca_html)

        vulg_html = build_companion_html(info['title'], info['vulgarisation_html'], 'vulgarisation')
        vulg_path = os.path.join(paper_dir, f"{slug}-vulgarisation.html")
        with open(vulg_path, 'w', encoding='utf-8') as f:
            f.write(vulg_html)

        # Mettre a jour le catalogue
        paper_key = f"papers/{domain}/{slug}/{slug}.pdf"
        papers_catalog["papers"][paper_key] = {
            "domain": domain,
            "title": info['title'],
            "description": info.get('description', ''),
            "tags": info.get('tags', []),
            "quality_score": info['quality_score'],
            "quality_note": info['quality_note'],
            "authors": info.get('authors', []),
            "year": info.get('year', 0),
            "journal": info.get('journal', ''),
            "doi": info.get('doi', ''),
            "robustness_score": info.get('robustness_global', 0),
            "vulgarisation_file": f"papers/{domain}/{slug}/{slug}-vulgarisation.html",
            "lca_file": f"papers/{domain}/{slug}/{slug}-lca.html",
        }

        counts[domain] += 1
        print(f"  {info['filename']} -> papers/{domain}/{slug}/")

    print(f"\nResume : {sum(counts.values())} publications importees dans {len(counts)} domaine(s)")
    for d, c in sorted(counts.items()):
        print(f"  {d}: {c}")


# ---------------------------------------------------------------------------
# Confirmation interactive
# ---------------------------------------------------------------------------

def prompt_confirm(message):
    """Demande confirmation avec un seul caractere (y/o = oui). Pas besoin d'Entree."""
    sys.stdout.write(f"{message} ")
    sys.stdout.flush()
    if _HAS_TERMIOS:
        try:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print(ch)
            return ch.lower() in ('y', 'o')
        except (termios.error, ValueError):
            pass
    else:
        try:
            import msvcrt
            ch = msvcrt.getwch()
            print(ch)
            return ch.lower() in ('y', 'o')
        except ImportError:
            pass
    # Fallback si pas de terminal (pipe, etc.)
    resp = sys.stdin.readline().replace('\r', '').strip().lower()
    return resp in ('y', 'yes', 'o', 'oui')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline d'import autonome pour Curax. Analyse, classifie via Claude CLI, score et importe les articles HTML et publications PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            exemples:
              python3 scripts/import.py infiles/                Import HTML + PDF avec preview
              python3 scripts/import.py --yes infiles/          Import sans confirmation
              python3 scripts/import.py --reclassify            Reclassifier les articles
              python3 scripts/import.py --reclassify-papers     Reclassifier les publications
              python3 scripts/import.py --workers 5             5 workers parallèles
        """)
    )
    parser.add_argument('source', nargs='?', default='infiles',
                        help="dossier source contenant les fichiers HTML et/ou PDF (défaut: infiles)")
    parser.add_argument('--yes', action='store_true',
                        help="importer sans demander de confirmation")
    parser.add_argument('--reclassify', action='store_true',
                        help="reclassifier tous les articles existants (nouveau scoring, tags, domaines)")
    parser.add_argument('--reclassify-papers', action='store_true',
                        help="reclassifier les publications (domain, tags, quality_note ; score figé, compagnons non régénérés)")
    parser.add_argument('--migrate', action='store_true',
                        help="migration one-time des manifests de domaine vers catalog.json")
    parser.add_argument('--workers', type=int, default=3,
                        help="nombre de workers parallèles pour le scoring (défaut: 3)")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # --migrate : migration one-time
    # ------------------------------------------------------------------
    if args.migrate:
        print("Migration des manifests de domaine vers catalog.json...\n")
        migrate_to_catalog()
        return

    # ------------------------------------------------------------------
    # --reclassify : reclassifier tous les articles existants
    # ------------------------------------------------------------------
    if args.reclassify:
        print("Reclassification de tous les articles existants...\n")
        catalog = load_catalog()
        if not catalog["articles"]:
            print("Aucun article dans catalog.json. Lancez --migrate d'abord.")
            sys.exit(1)

        total = len(catalog["articles"])
        print(f"1. Appel Claude pour la taxonomie ({total} articles)...")
        taxonomy_prompt = build_reclassify_taxonomy_prompt(catalog)
        taxonomy = call_claude_with_retry(taxonomy_prompt, TAXONOMY_SCHEMA, timeout=300)
        catalog["domains"] = taxonomy["domains"]
        catalog["observations"] = taxonomy["observations"]
        print(f"   {len(taxonomy['domains'])} domaines, observations mises a jour\n")

        # Scorer chaque article (en parallele)
        print(f"2. Scoring des {total} articles ({args.workers} workers)...")
        changes = []

        def _score_one(article_key, meta):
            """Score un article via Claude. Retourne (article_key, meta, result) ou None."""
            html_path = os.path.join(PROJECT_ROOT, article_key)
            if not os.path.isfile(html_path):
                return None
            with open(html_path, encoding='utf-8', errors='replace') as f:
                content = f.read()
            text = extract_text_spans(content)
            result = call_claude_with_retry(
                build_article_prompt(text, taxonomy["domains"]),
                ARTICLE_SCHEMA
            )
            return (article_key, meta, result)

        articles_list = list(catalog["articles"].items())
        done_count = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(_score_one, key, meta): key
                for key, meta in articles_list
            }
            for future in as_completed(futures):
                done_count += 1
                res = future.result()
                if res is None:
                    article_key = futures[future]
                    print(f"  [{done_count}/{total}] SKIP {article_key} (fichier introuvable)")
                    continue

                article_key, meta, result = res
                new_domain = result["domain"]
                old_domain = meta["domain"]

                # Verifier que le domaine existe dans la taxonomie
                if new_domain not in taxonomy["domains"]:
                    print(f"  [{done_count}/{total}] {article_key} -> ATTENTION domaine '{new_domain}' inconnu, garde '{old_domain}'")
                    new_domain = old_domain
                else:
                    print(f"  [{done_count}/{total}] {article_key} -> {new_domain} ({result['quality_score']}/10) [{', '.join(result['tags'])}]")

                catalog["articles"][article_key] = {
                    "domain": new_domain,
                    "tags": result["tags"],
                    "quality_score": result["quality_score"],
                    "quality_note": result["quality_note"],
                }

                # Detecter changements de domaine et/ou de slug
                old_filename = os.path.basename(article_key)
                old_slug = os.path.splitext(old_filename)[0]
                new_slug = slugify(result.get("title", ""))
                domain_changed = old_domain != new_domain
                slug_changed = new_slug != old_slug and new_slug != "untitled"

                if domain_changed or slug_changed:
                    changes.append((article_key, old_domain, new_domain,
                                    old_slug, new_slug if slug_changed else None))

        # Sauvegarder les scores/tags AVANT la confirmation des deplacements
        save_catalog(catalog)
        print(f"   Scores et tags sauvegardes dans catalog.json")

        # Preview des deplacements/renommages
        if changes:
            print(f"\n3. Deplacements/renommages prevus ({len(changes)}) :")
            for key, old_dom, new_dom, old_slug, new_slug_val in changes:
                old_filename = os.path.basename(key)
                new_filename = f"{new_slug_val}.html" if new_slug_val else old_filename
                new_key = f"articles/{new_dom}/{new_filename}"
                if old_dom != new_dom and new_slug_val:
                    label = "deplace + renomme"
                elif old_dom != new_dom:
                    label = "deplace"
                else:
                    label = "renomme"
                print(f"  {key} -> {new_key} ({label})")

            if not args.yes:
                if not prompt_confirm("\nConfirmer les deplacements/renommages ? [y/N]"):
                    print("Deplacements annules (scores et tags deja sauvegardes).")
                    _regenerate_manifest()
                    print("\nTermine !")
                    return

            # Executer les deplacements/renommages
            for key, old_dom, new_dom, old_slug, new_slug_val in changes:
                new_key = move_or_rename_article(
                    catalog, key,
                    new_domain=new_dom if old_dom != new_dom else None,
                    new_slug=new_slug_val,
                )
                if new_key:
                    print(f"  {key} -> {new_key}")
        else:
            print("\n3. Aucun deplacement/renommage necessaire.")

        save_catalog(catalog)
        _regenerate_manifest()
        print("\nTermine !")
        return

    # ------------------------------------------------------------------
    # --reclassify-papers : reclassifier les publications existantes
    # ------------------------------------------------------------------
    if args.reclassify_papers:
        print("Reclassification des publications existantes...\n")
        papers_catalog = load_papers_catalog()
        if not papers_catalog["papers"]:
            print("Aucune publication dans papers/catalog.json.")
            sys.exit(1)

        total = len(papers_catalog["papers"])
        print(f"1. Appel Claude pour la taxonomie ({total} publications)...")
        taxonomy_prompt = build_paper_reclassify_taxonomy_prompt(papers_catalog)
        taxonomy = call_claude_with_retry(taxonomy_prompt, PAPER_TAXONOMY_SCHEMA, timeout=300)
        papers_catalog["domains"] = taxonomy["domains"]
        papers_catalog["observations"] = taxonomy["observations"]
        print(f"   {len(taxonomy['domains'])} domaines, observations mises a jour\n")

        print(f"2. Reclassification des {total} publications ({args.workers} workers)...")
        changes = []

        def _reclassify_paper(paper_key, meta):
            pdf_path = os.path.join(PROJECT_ROOT, paper_key)
            if not os.path.isfile(pdf_path):
                return None
            text = extract_pdf_text(pdf_path)
            result = call_claude_with_retry(
                build_paper_reclassify_prompt(text, taxonomy["domains"]),
                PAPER_RECLASSIFY_SCHEMA
            )
            return (paper_key, meta, result)

        papers_list = list(papers_catalog["papers"].items())
        done_count = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(_reclassify_paper, key, meta): key
                for key, meta in papers_list
            }
            for future in as_completed(futures):
                done_count += 1
                res = future.result()
                if res is None:
                    paper_key = futures[future]
                    print(f"  [{done_count}/{total}] SKIP {paper_key} (fichier introuvable)")
                    continue

                paper_key, meta, result = res
                new_domain = result["domain"]
                old_domain = meta["domain"]

                if new_domain not in taxonomy["domains"]:
                    print(f"  [{done_count}/{total}] {paper_key} -> ATTENTION domaine '{new_domain}' inconnu, garde '{old_domain}'")
                    new_domain = old_domain
                else:
                    print(f"  [{done_count}/{total}] {paper_key} -> {new_domain} [{', '.join(result['tags'])}]")

                # Score fige : on ne recalcule pas quality_score
                papers_catalog["papers"][paper_key]["domain"] = new_domain
                papers_catalog["papers"][paper_key]["tags"] = result["tags"]
                papers_catalog["papers"][paper_key]["quality_note"] = result["quality_note"]

                # Detecter changements
                parts = paper_key.split('/')
                old_slug = parts[2]
                new_slug = slugify(result.get("title", ""))
                domain_changed = old_domain != new_domain
                slug_changed = new_slug != old_slug and new_slug != "untitled"

                if domain_changed or slug_changed:
                    changes.append((paper_key, old_domain, new_domain,
                                    old_slug, new_slug if slug_changed else None))

        save_papers_catalog(papers_catalog)
        print(f"   Tags et domaines sauvegardes dans papers/catalog.json")

        if changes:
            print(f"\n3. Deplacements/renommages prevus ({len(changes)}) :")
            for key, old_dom, new_dom, old_slug, new_slug_val in changes:
                slug = new_slug_val or old_slug
                new_key = f"papers/{new_dom}/{slug}/{slug}.pdf"
                if old_dom != new_dom and new_slug_val:
                    label = "deplace + renomme"
                elif old_dom != new_dom:
                    label = "deplace"
                else:
                    label = "renomme"
                print(f"  {key} -> {new_key} ({label})")

            if not args.yes:
                if not prompt_confirm("\nConfirmer les deplacements/renommages ? [y/N]"):
                    print("Deplacements annules (tags et domaines deja sauvegardes).")
                    _regenerate_manifest()
                    print("\nTermine !")
                    return

            for key, old_dom, new_dom, old_slug, new_slug_val in changes:
                new_key = move_or_rename_paper(
                    papers_catalog, key,
                    new_domain=new_dom if old_dom != new_dom else None,
                    new_slug=new_slug_val,
                )
                if new_key:
                    print(f"  {key} -> {new_key}")
        else:
            print("\n3. Aucun deplacement/renommage necessaire.")

        save_papers_catalog(papers_catalog)
        _regenerate_manifest()
        print("\nTermine !")
        return

    # ------------------------------------------------------------------
    # Import standard de nouveaux fichiers (HTML articles + PDF papers)
    # ------------------------------------------------------------------
    source_dir = args.source

    if not os.path.isdir(source_dir):
        print(f"Erreur : dossier '{source_dir}' introuvable", file=sys.stderr)
        sys.exit(1)

    html_files = sorted(f for f in os.listdir(source_dir) if f.lower().endswith('.html'))
    pdf_files = sorted(f for f in os.listdir(source_dir) if f.lower().endswith('.pdf'))

    if not html_files and not pdf_files:
        print(f"Aucun fichier HTML ou PDF dans {source_dir}")
        sys.exit(0)

    if html_files:
        print(f"Trouve {len(html_files)} fichier(s) HTML dans {source_dir}")
    if pdf_files:
        print(f"Trouve {len(pdf_files)} fichier(s) PDF dans {source_dir}")
    print()

    # ===== Pipeline articles HTML =====
    if html_files:
        print("=" * 60)
        print("  PIPELINE ARTICLES HTML")
        print("=" * 60 + "\n")

        file_contents = {}
        for fname in html_files:
            filepath = os.path.join(source_dir, fname)
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                file_contents[filepath] = f.read()

        catalog = load_catalog()
        print("1. Detection des doublons...")
        excluded = dedup_files(file_contents)
        catalog_dupes = dedup_against_catalog(file_contents, excluded, catalog)
        excluded |= catalog_dupes
        total_dupes = len(excluded)
        if total_dupes:
            print(f"   {total_dupes} doublon(s) exclus\n")
        else:
            print("   Aucun doublon\n")

        print("2. Extraction du texte...")
        analyses = []
        for filepath, content in file_contents.items():
            if filepath in excluded:
                continue
            info = analyze_article(filepath, content)
            analyses.append(info)

        if analyses:
            print(f"\n3. Appel Claude pour la taxonomie ({len(analyses)} nouveaux articles)...")
            taxonomy_prompt = build_taxonomy_prompt(catalog, analyses)
            taxonomy = call_claude_with_retry(taxonomy_prompt, TAXONOMY_SCHEMA, timeout=300)
            catalog["domains"] = taxonomy["domains"]
            catalog["observations"] = taxonomy["observations"]
            print(f"   {len(taxonomy['domains'])} domaines, observations mises a jour\n")

            print(f"4. Scoring des {len(analyses)} articles ({args.workers} workers)...")
            total_import = len(analyses)

            def _score_new(info):
                result = call_claude_with_retry(
                    build_article_prompt(info['text'], taxonomy["domains"]),
                    ARTICLE_SCHEMA
                )
                return (info, result)

            done_count = 0
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {executor.submit(_score_new, info): info for info in analyses}
                for future in as_completed(futures):
                    done_count += 1
                    info, result = future.result()

                    domain = result["domain"]
                    if domain not in taxonomy["domains"]:
                        domain = next(iter(taxonomy["domains"]))

                    info['domain'] = domain
                    info['tags'] = result['tags']
                    info['quality_score'] = result['quality_score']
                    info['quality_note'] = result['quality_note']
                    info['title'] = result['title']
                    info['description'] = result['description']
                    title_slug = slugify(result['title'])
                    if title_slug != "untitled":
                        info['slug'] = title_slug
                    print(f"  [{done_count}/{total_import}] {info['filename']} -> {domain} ({result['quality_score']}/10) [{', '.join(result['tags'])}]")

            print(f"\n5. Plan d'import ({len(analyses)} articles) :\n")
            print(f"  {'Domaine':<20} {'Score':>6}  {'Tags':<30} {'Titre'}")
            print(f"  {'-'*20} {'-'*6}  {'-'*30} {'-'*40}")
            for info in sorted(analyses, key=lambda x: (x['domain'], -x['quality_score'])):
                title_short = info['title'][:40]
                tags_str = ', '.join(info.get('tags', []))[:30]
                print(f"  {info['domain']:<20} {info['quality_score']:>3}/10  {tags_str:<30} {title_short}")
            print()

            if not args.yes:
                if not prompt_confirm("Confirmer l'import des articles ? [y/N]"):
                    print("Import articles annule.")
                    analyses = []

            if analyses:
                print("\n6. Import articles en cours...")
                do_import(analyses, file_contents, catalog)
                save_catalog(catalog)
                print("   Catalogue articles sauvegarde.")
        else:
            print("   Aucun nouvel article a importer (tous des doublons).\n")

    # ===== Pipeline publications PDF =====
    if pdf_files:
        if not _HAS_PDFPLUMBER:
            print("\nERREUR : pdfplumber est requis pour importer des PDFs.", file=sys.stderr)
            print("  pip install pdfplumber", file=sys.stderr)
            sys.exit(1)

        print("\n" + "=" * 60)
        print("  PIPELINE PUBLICATIONS PDF")
        print("=" * 60 + "\n")

        # Extraire le texte de chaque PDF
        print("1. Extraction du texte PDF...")
        pdf_texts = {}
        for fname in pdf_files:
            filepath = os.path.join(source_dir, fname)
            try:
                text = extract_pdf_text(filepath)
                pdf_texts[filepath] = text
                print(f"  {fname}: {len(text)} caracteres")
            except Exception as e:
                print(f"  ERREUR {fname}: {e}")

        if not pdf_texts:
            print("   Aucun PDF lisible.")
        else:
            # Deduplication
            papers_catalog = load_papers_catalog()
            print("\n2. Detection des doublons PDF...")
            excluded = dedup_pdf_files(pdf_texts)
            catalog_dupes = dedup_pdfs_against_catalog(pdf_texts, excluded, papers_catalog)
            excluded |= catalog_dupes
            total_dupes = len(excluded)
            if total_dupes:
                print(f"   {total_dupes} doublon(s) exclus\n")
            else:
                print("   Aucun doublon\n")

            new_papers = []
            for filepath, text in pdf_texts.items():
                if filepath in excluded:
                    continue
                new_papers.append({
                    'filepath': filepath,
                    'filename': os.path.basename(filepath),
                    'text': text,
                })

            if new_papers:
                # Taxonomy
                print(f"3. Appel Claude pour la taxonomie ({len(new_papers)} nouvelles publications)...")
                tax_prompt = build_paper_taxonomy_prompt(papers_catalog, new_papers)
                paper_taxonomy = call_claude_with_retry(tax_prompt, PAPER_TAXONOMY_SCHEMA, timeout=300)
                papers_catalog["domains"] = paper_taxonomy["domains"]
                papers_catalog["observations"] = paper_taxonomy["observations"]
                print(f"   {len(paper_taxonomy['domains'])} domaines, observations mises a jour\n")

                # LCA + vulgarisation (parallele cross-papers, sequentiel par paper)
                print(f"4. Analyse LCA + vulgarisation ({len(new_papers)} publications, {args.workers} workers)...")
                total_papers = len(new_papers)

                def _process_paper(info):
                    """LCA puis vulgarisation pour une publication."""
                    # Appel LCA
                    lca_result = call_claude_with_retry(
                        build_paper_lca_prompt(info['text'], paper_taxonomy["domains"]),
                        PAPER_LCA_SCHEMA,
                        timeout=300
                    )

                    # Appel vulgarisation (utilise title/authors du LCA)
                    vulg_result = call_claude_with_retry(
                        build_paper_vulgarisation_prompt(
                            info['text'],
                            lca_result['title'],
                            lca_result['authors']
                        ),
                        PAPER_VULGARISATION_SCHEMA,
                        timeout=300
                    )

                    return (info, lca_result, vulg_result)

                paper_analyses = []
                done_count = 0
                with ThreadPoolExecutor(max_workers=args.workers) as executor:
                    futures = {executor.submit(_process_paper, info): info for info in new_papers}
                    for future in as_completed(futures):
                        done_count += 1
                        info, lca_result, vulg_result = future.result()

                        domain = lca_result["domain"]
                        if domain not in paper_taxonomy["domains"]:
                            domain = next(iter(paper_taxonomy["domains"]))

                        quality_score = min(round(lca_result["robustness_global"] * 2), 10)

                        title_slug = slugify(lca_result['title'])
                        if title_slug == "untitled":
                            title_slug = os.path.splitext(info['filename'])[0].lower().replace(' ', '-')

                        info['domain'] = domain
                        info['tags'] = lca_result['tags']
                        info['quality_score'] = quality_score
                        info['quality_note'] = lca_result['quality_note']
                        info['title'] = lca_result['title']
                        info['description'] = lca_result['description']
                        info['authors'] = lca_result['authors']
                        info['year'] = lca_result['year']
                        info['journal'] = lca_result['journal']
                        info['doi'] = lca_result['doi']
                        info['robustness_global'] = lca_result['robustness_global']
                        info['lca_html'] = lca_result['lca_html']
                        info['vulgarisation_html'] = vulg_result['vulgarisation_html']
                        info['slug'] = title_slug

                        authors_short = lca_result['authors'][0] if lca_result['authors'] else 'Unknown'
                        if len(lca_result['authors']) > 1:
                            authors_short += ' et al.'
                        print(f"  [{done_count}/{total_papers}] {info['filename']} -> {domain} ({quality_score}/10) {authors_short} ({lca_result['year']})")

                        paper_analyses.append(info)

                # Preview
                print(f"\n5. Plan d'import ({len(paper_analyses)} publications) :\n")
                print(f"  {'Domaine':<20} {'Score':>6}  {'Auteurs':<25} {'Titre'}")
                print(f"  {'-'*20} {'-'*6}  {'-'*25} {'-'*40}")
                for info in sorted(paper_analyses, key=lambda x: (x['domain'], -x['quality_score'])):
                    title_short = info['title'][:40]
                    authors_short = info['authors'][0][:20] if info['authors'] else 'Unknown'
                    if len(info['authors']) > 1:
                        authors_short += ' et al.'
                    print(f"  {info['domain']:<20} {info['quality_score']:>3}/10  {authors_short:<25} {title_short}")
                print()

                if not args.yes:
                    if not prompt_confirm("Confirmer l'import des publications ? [y/N]"):
                        print("Import publications annule.")
                        paper_analyses = []

                if paper_analyses:
                    print("\n6. Import publications en cours...")
                    do_import_papers(paper_analyses, papers_catalog)
                    save_papers_catalog(papers_catalog)
                    print("   Catalogue publications sauvegarde.")
            else:
                print("   Aucune nouvelle publication a importer (tous des doublons).\n")

    # Regenerer le manifeste global
    print("\nRegeneration du manifeste...")
    _regenerate_manifest()
    print("\nTermine !")


def _regenerate_manifest():
    """Lance generate_manifest.py."""
    manifest_script = os.path.join(PROJECT_ROOT, ".github", "scripts", "generate_manifest.py")
    subprocess.run([sys.executable, manifest_script], cwd=PROJECT_ROOT, check=True)


if __name__ == '__main__':
    main()
