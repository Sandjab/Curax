#!/usr/bin/env python3
"""
Pipeline d'import autonome pour Curax.

Analyse, classifie via Claude CLI, score et importe les articles HTML dans articles/.

Usage:
  python3 scripts/import-articles.py [infiles/]            # Analyse + preview
  python3 scripts/import-articles.py --yes [infiles/]       # Analyse + import sans confirmation
  python3 scripts/import-articles.py --reclassify           # Reclassifier tous les articles existants
  python3 scripts/import-articles.py --workers 5            # Nombre de workers paralleles (defaut: 3)
"""

import os
import sys
import re
import json
import hashlib
import shutil
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import termios
import tty

# ---------------------------------------------------------------------------
# Repertoires
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ARTICLES_DIR = os.path.join(PROJECT_ROOT, "articles")
CATALOG_PATH = os.path.join(ARTICLES_DIR, "catalog.json")

# ---------------------------------------------------------------------------
# Claude CLI helper
# ---------------------------------------------------------------------------

def call_claude(prompt, json_schema=None):
    """Appelle Claude CLI en mode print, retourne le JSON parse."""
    cmd = [shutil.which("claude") or "claude", "-p",
           "--output-format", "json", "--model", "opus"]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]
    cmd.append(prompt)
    env = {**os.environ}
    env.pop("CLAUDECODE", None)  # eviter "nested session"
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr[:500]}")
    envelope = json.loads(result.stdout)
    if json_schema and "structured_output" in envelope:
        return envelope["structured_output"]
    raw = envelope.get("result", "")
    return json.loads(raw) if json_schema else raw


def call_claude_with_retry(prompt, json_schema=None, max_retries=2):
    """Appelle Claude CLI avec retry et backoff exponentiel."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return call_claude(prompt, json_schema)
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


# ---------------------------------------------------------------------------
# Confirmation interactive
# ---------------------------------------------------------------------------

def prompt_confirm(message):
    """Demande confirmation avec un seul caractere (y/o = oui). Pas besoin d'Entree."""
    sys.stdout.write(f"{message} ")
    sys.stdout.flush()
    try:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.cbreak(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print(ch)
        return ch.lower() in ('y', 'o')
    except (termios.error, ValueError):
        # Fallback si pas de terminal (pipe, etc.)
        resp = sys.stdin.readline().replace('\r', '').strip().lower()
        return resp in ('y', 'yes', 'o', 'oui')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    auto_yes = '--yes' in args
    do_migrate = '--migrate' in args
    do_reclassify = '--reclassify' in args

    # Extraire --workers N
    max_workers = 3
    if '--workers' in args:
        idx = args.index('--workers')
        if idx + 1 < len(args):
            max_workers = int(args[idx + 1])
            args = args[:idx] + args[idx + 2:]

    args = [a for a in args if not a.startswith('--')]

    # ------------------------------------------------------------------
    # --migrate : migration one-time
    # ------------------------------------------------------------------
    if do_migrate:
        print("Migration des manifests de domaine vers catalog.json...\n")
        migrate_to_catalog()
        return

    # ------------------------------------------------------------------
    # --reclassify : reclassifier tous les articles existants
    # ------------------------------------------------------------------
    if do_reclassify:
        print("Reclassification de tous les articles existants...\n")
        catalog = load_catalog()
        if not catalog["articles"]:
            print("Aucun article dans catalog.json. Lancez --migrate d'abord.")
            sys.exit(1)

        total = len(catalog["articles"])
        print(f"1. Appel Claude pour la taxonomie ({total} articles)...")
        taxonomy_prompt = build_reclassify_taxonomy_prompt(catalog)
        taxonomy = call_claude_with_retry(taxonomy_prompt, TAXONOMY_SCHEMA)
        catalog["domains"] = taxonomy["domains"]
        catalog["observations"] = taxonomy["observations"]
        print(f"   {len(taxonomy['domains'])} domaines, observations mises a jour\n")

        # Scorer chaque article (en parallele)
        print(f"2. Scoring des {total} articles ({max_workers} workers)...")
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
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
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

            if not auto_yes:
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
    # Import standard de nouveaux articles
    # ------------------------------------------------------------------
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

    # Step 2: Analyze (extraction basique)
    print("2. Extraction du texte...")
    analyses = []
    for filepath, content in file_contents.items():
        if filepath in excluded:
            continue
        info = analyze_article(filepath, content)
        analyses.append(info)

    # Step 3: Load catalog
    catalog = load_catalog()

    # Step 4: Appel Claude taxonomie
    print(f"\n3. Appel Claude pour la taxonomie ({len(analyses)} nouveaux articles)...")
    taxonomy_prompt = build_taxonomy_prompt(catalog, analyses)
    taxonomy = call_claude_with_retry(taxonomy_prompt, TAXONOMY_SCHEMA)
    catalog["domains"] = taxonomy["domains"]
    catalog["observations"] = taxonomy["observations"]
    print(f"   {len(taxonomy['domains'])} domaines, observations mises a jour\n")

    # Step 5: Appel Claude scoring par article (en parallele)
    print(f"4. Scoring des {len(analyses)} articles ({max_workers} workers)...")
    total_import = len(analyses)

    def _score_new(info):
        """Score un nouvel article via Claude."""
        result = call_claude_with_retry(
            build_article_prompt(info['text'], taxonomy["domains"]),
            ARTICLE_SCHEMA
        )
        return (info, result)

    done_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_score_new, info): info for info in analyses}
        for future in as_completed(futures):
            done_count += 1
            info, result = future.result()

            # Verifier que le domaine existe
            domain = result["domain"]
            if domain not in taxonomy["domains"]:
                domain = next(iter(taxonomy["domains"]))

            info['domain'] = domain
            info['tags'] = result['tags']
            info['quality_score'] = result['quality_score']
            info['quality_note'] = result['quality_note']
            info['title'] = result['title']
            info['description'] = result['description']
            # Slug base sur le titre Claude (remplace le slug provisoire)
            title_slug = slugify(result['title'])
            if title_slug != "untitled":
                info['slug'] = title_slug
            print(f"  [{done_count}/{total_import}] {info['filename']} -> {domain} ({result['quality_score']}/10) [{', '.join(result['tags'])}]")

    # Step 6: Display plan
    print(f"\n5. Plan d'import ({len(analyses)} articles) :\n")
    print(f"  {'Domaine':<20} {'Score':>6}  {'Tags':<30} {'Titre'}")
    print(f"  {'-'*20} {'-'*6}  {'-'*30} {'-'*40}")
    for info in sorted(analyses, key=lambda x: (x['domain'], -x['quality_score'])):
        title_short = info['title'][:40]
        tags_str = ', '.join(info.get('tags', []))[:30]
        print(f"  {info['domain']:<20} {info['quality_score']:>3}/10  {tags_str:<30} {title_short}")
    print()

    # Step 7: Confirm
    if not auto_yes:
        if not prompt_confirm("Confirmer l'import ? [y/N]"):
            print("Import annule.")
            sys.exit(0)

    # Step 8: Import
    print("\n6. Import en cours...")
    do_import(analyses, file_contents, catalog)

    # Step 9: Save catalog
    print("\n7. Sauvegarde du catalogue...")
    save_catalog(catalog)

    # Step 10: Regenerate manifest
    print("\n8. Regeneration du manifeste...")
    _regenerate_manifest()

    print("\nTermine !")


def _regenerate_manifest():
    """Lance generate_manifest.py."""
    manifest_script = os.path.join(PROJECT_ROOT, ".github", "scripts", "generate_manifest.py")
    subprocess.run([sys.executable, manifest_script], cwd=PROJECT_ROOT, check=True)


if __name__ == '__main__':
    main()
