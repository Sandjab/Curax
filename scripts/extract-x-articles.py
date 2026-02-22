#!/usr/bin/env python3
"""
Extracteur d'articles X/Twitter pour Curax.

Usage:
  python3 scripts/extract-x-articles.py [infiles/]           # Preview : affiche auteur + titre
  python3 scripts/extract-x-articles.py --apply [infiles/]    # Injecte métadonnées et copie dans articles/
  python3 scripts/extract-x-articles.py --dedup [infiles/]    # Détecte les doublons par contenu textuel

Requiert un fichier mapping.json dans le dossier source (sauf pour --dedup).
"""

import os
import sys
import re
import json
import hashlib
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Extraction de métadonnées depuis le HTML
# ---------------------------------------------------------------------------

def extract_author(content):
    """Extrait le @handle de l'auteur depuis le HTML X/Twitter."""
    # Méthode 1 : data-testid="UserAvatar-Container-{handle}"
    m = re.search(r'UserAvatar-Container-([A-Za-z0-9_]+)', content)
    if m:
        return "@" + m.group(1)

    # Méthode 2 : Cloudflare blog
    m = re.search(r'author-name-tooltip[^>]*><a[^>]*>([^<]+)', content)
    if m:
        return m.group(1).strip()

    # Méthode 3 : Substack
    m = re.search(r'Prof\.\s+[A-Za-z]+\s+[A-Za-z]+', content)
    if m:
        return m.group(0)

    return None


def extract_text_preview(content, max_len=200):
    """Extrait un aperçu du texte principal de l'article."""
    # Pour les articles X/Twitter standard
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

    # Fallback : texte après </style>
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

    return None


def _clean_entities(text):
    """Nettoie les entités HTML courantes."""
    return (text
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&#39;", "'")
            .replace("&quot;", '"')
            .replace("&nbsp;", " "))


def extract_content_fingerprint(content):
    """Génère un hash du contenu textuel pour détecter les doublons.

    Compare les spans data-text="true" (articles X/Twitter) ou le texte
    brut après </style> (autres formats). Ignore le CSS/boilerplate.
    """
    # Méthode 1 : spans data-text pour articles X/Twitter
    spans = re.findall(r'data-text="true"[^>]*>(.*?)</span>', content)
    if spans:
        text = ' '.join(_clean_entities(s) for s in spans)
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    # Méthode 2 : texte après </style> pour les autres formats
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
# Injection de métadonnées dans le HTML
# ---------------------------------------------------------------------------

def inject_metadata(html_content, title, description):
    """Injecte <title> et <meta description> dans le HTML."""
    # Remplacer le <title> existant
    html_content = re.sub(
        r'<title>[^<]*</title>',
        f'<title>{_escape_html(title)}</title>',
        html_content,
        count=1
    )

    # Ajouter ou remplacer <meta name="description">
    if re.search(r'<meta\s+name=["\']description["\']', html_content):
        html_content = re.sub(
            r'<meta\s+name=["\']description["\']\s+content=["\'][^"\']*["\'][^>]*/?>',
            f'<meta name="description" content="{_escape_html(description)}">',
            html_content,
            count=1
        )
    else:
        # Insérer après le dernier <meta> dans <head>
        html_content = re.sub(
            r'(<meta[^>]*>)(\s*<(?:title|style|link))',
            rf'\1<meta name="description" content="{_escape_html(description)}">\2',
            html_content,
            count=1
        )
        # Si ça n'a pas marché, insérer avant </head>
        if 'meta name="description"' not in html_content:
            html_content = html_content.replace(
                '</head>',
                f'<meta name="description" content="{_escape_html(description)}">\n</head>',
                1
            )

    return html_content


def _escape_html(text):
    """Échappe les caractères spéciaux pour les attributs HTML."""
    return (text
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# Commandes principales
# ---------------------------------------------------------------------------

def cmd_preview(source_dir):
    """Affiche un aperçu de chaque article avec auteur et contenu."""
    mapping_path = os.path.join(source_dir, 'mapping.json')
    has_mapping = os.path.exists(mapping_path)
    mapping = {}
    if has_mapping:
        with open(mapping_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)

    files = sorted(f for f in os.listdir(source_dir) if f.endswith('.html'))
    print(f"Trouvé {len(files)} fichiers HTML dans {source_dir}\n")

    for fname in files:
        filepath = os.path.join(source_dir, fname)
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        author = extract_author(content)
        preview = extract_text_preview(content)

        meta = mapping.get(fname, {})
        domain = meta.get('domain', '?')
        title = meta.get('title', '(pas de titre)')

        print(f"  {fname}")
        print(f"    Auteur   : {author or '(inconnu)'}")
        print(f"    Domaine  : {domain}")
        print(f"    Titre    : {title}")
        if preview:
            print(f"    Aperçu   : {preview[:120]}...")
        print()

    if not has_mapping:
        print("⚠  Pas de mapping.json trouvé — ajoutez-en un pour utiliser --apply")


def cmd_apply(source_dir):
    """Injecte les métadonnées et copie les fichiers dans articles/."""
    mapping_path = os.path.join(source_dir, 'mapping.json')
    if not os.path.exists(mapping_path):
        print(f"Erreur : {mapping_path} introuvable", file=sys.stderr)
        sys.exit(1)

    with open(mapping_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    # Répertoire racine du projet (parent de scripts/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    articles_dir = os.path.join(project_root, 'articles')

    counts = {}
    errors = []

    for fname, meta in sorted(mapping.items()):
        filepath = os.path.join(source_dir, fname)
        if not os.path.exists(filepath):
            errors.append(f"Fichier manquant : {fname}")
            continue

        domain = meta['domain']
        slug = meta['slug']
        title = meta['title']
        description = meta['description']

        # Lire le HTML
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()

        # Injecter les métadonnées
        html_content = inject_metadata(html_content, title, description)

        # Créer le dossier domaine si nécessaire
        domain_dir = os.path.join(articles_dir, domain)
        os.makedirs(domain_dir, exist_ok=True)

        # Écrire le fichier avec le nouveau nom
        dest_name = f"{slug}.html"
        dest_path = os.path.join(domain_dir, dest_name)
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        counts[domain] = counts.get(domain, 0) + 1
        print(f"  ✓ {fname} → articles/{domain}/{dest_name}")

    print(f"\n{'─' * 50}")
    print(f"Résumé :")
    for domain, count in sorted(counts.items()):
        print(f"  {domain}: {count} article(s)")
    print(f"  Total : {sum(counts.values())} articles copiés")

    if errors:
        print(f"\n⚠  Erreurs ({len(errors)}) :")
        for e in errors:
            print(f"  - {e}")


def cmd_dedup(source_dir):
    """Détecte les doublons par empreinte du contenu textuel."""
    files = sorted(f for f in os.listdir(source_dir) if f.endswith('.html'))
    print(f"Analyse de {len(files)} fichiers pour doublons...\n")

    fingerprints = {}  # hash → [filenames]

    for fname in files:
        filepath = os.path.join(source_dir, fname)
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        fp = extract_content_fingerprint(content)
        if fp:
            fingerprints.setdefault(fp, []).append(fname)

    duplicates = {h: fnames for h, fnames in fingerprints.items() if len(fnames) > 1}

    if not duplicates:
        print("Aucun doublon détecté.")
        return

    print(f"⚠  {len(duplicates)} groupe(s) de doublons détecté(s) :\n")
    for i, (h, fnames) in enumerate(duplicates.items(), 1):
        # Extraire l'auteur du premier fichier pour contexte
        filepath = os.path.join(source_dir, fnames[0])
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        author = extract_author(content) or '(inconnu)'
        preview = extract_text_preview(content, max_len=80) or ''

        print(f"  Groupe {i} (auteur: {author}):")
        for fname in fnames:
            print(f"    - {fname}")
        if preview:
            print(f"    Aperçu : {preview}...")
        print()

    print("Conseil : gardez le premier fichier de chaque groupe et retirez")
    print("les autres du mapping.json avant de lancer --apply.")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    apply_mode = '--apply' in args
    dedup_mode = '--dedup' in args
    args = [a for a in args if a not in ('--apply', '--dedup')]

    source_dir = args[0] if args else 'infiles'

    if not os.path.isdir(source_dir):
        print(f"Erreur : dossier '{source_dir}' introuvable", file=sys.stderr)
        sys.exit(1)

    if dedup_mode:
        cmd_dedup(source_dir)
    elif apply_mode:
        cmd_apply(source_dir)
    else:
        cmd_preview(source_dir)


if __name__ == '__main__':
    main()
