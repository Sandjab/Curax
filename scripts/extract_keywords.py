#!/usr/bin/env python3
"""Backfill de mots-cles cherchables pour les articles et publications existants.

Usage:
    python3 scripts/extract_keywords.py                    # tout (articles + papers), reprend la ou on s'est arrete
    python3 scripts/extract_keywords.py --only articles    # articles uniquement
    python3 scripts/extract_keywords.py --only papers      # papers uniquement
    python3 scripts/extract_keywords.py --force            # reecrase les keywords existants
    python3 scripts/extract_keywords.py --workers 5        # 5 workers paralleles
    python3 scripts/extract_keywords.py --limit 5          # ne traite que 5 items (pour test)

Les mots-cles sont ecrits dans articles/catalog.json et papers/catalog.json sous la cle `keywords`.
Checkpoint tous les 10 items pour que le script soit resumable en cas d'interruption.
Le manifest.json est regenere a la fin.
"""

import argparse
import importlib.util
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Charger scripts/import.py comme module (le nom "import" est un mot-cle Python)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_IMPORT_PATH = os.path.join(SCRIPT_DIR, "import.py")
_spec = importlib.util.spec_from_file_location("curax_import", _IMPORT_PATH)
_curax = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_curax)

PROJECT_ROOT = _curax.PROJECT_ROOT
KEYWORDS_MODEL = _curax.KEYWORDS_MODEL
load_catalog = _curax.load_catalog
save_catalog = _curax.save_catalog
load_papers_catalog = _curax.load_papers_catalog
save_papers_catalog = _curax.save_papers_catalog
extract_text_spans = _curax.extract_text_spans
extract_pdf_abstract = _curax.extract_pdf_abstract
call_keywords_for_item = _curax.call_keywords_for_item
_regenerate_manifest = _curax._regenerate_manifest


CHECKPOINT_EVERY = 10


def _load_article_text(article_key):
    """Lit le HTML et renvoie le texte extrait, ou None si fichier introuvable."""
    path = os.path.join(PROJECT_ROOT, article_key)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    return extract_text_spans(content)


def _needs_keywords(meta, force):
    """True si l'entree doit etre (re)traitee."""
    if force:
        return True
    existing = meta.get("keywords", [])
    return not existing


def _pick_title(meta, key):
    """Titre a passer a Claude. Pour les articles, pas de title dans le catalog —
    fallback sur le basename."""
    if meta.get("title"):
        return meta["title"]
    return os.path.splitext(os.path.basename(key))[0].replace("-", " ")


def _process_articles(catalog, workers, force, limit):
    """Itere sur les articles du catalog et attribue des keywords en parallele."""
    articles = catalog.get("articles", {})
    candidates = [(k, m) for k, m in articles.items() if _needs_keywords(m, force)]
    skipped = len(articles) - len(candidates)

    if limit is not None:
        candidates = candidates[:limit]

    total = len(candidates)
    if total == 0:
        print(f"  Aucun article a traiter ({skipped} deja traites, skip).")
        return 0, 0, skipped

    print(f"  {total} articles a traiter ({skipped} deja avec keywords, skip).")

    def _work(key, meta):
        text = _load_article_text(key)
        if text is None:
            return (key, None, "fichier introuvable")
        title = _pick_title(meta, key)
        kw = call_keywords_for_item(title, text, meta.get("tags", []))
        return (key, kw, None)

    done = 0
    success = 0
    failed = 0
    since_checkpoint = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_work, k, m): k for k, m in candidates}
        for future in as_completed(futures):
            done += 1
            key, kw, err = future.result()
            if err or not kw:
                failed += 1
                reason = err or "aucun mot-cle retourne"
                print(f"  [{done}/{total}] ECHEC {key} ({reason})")
            else:
                success += 1
                articles[key]["keywords"] = kw
                preview = ", ".join(kw[:5]) + ("..." if len(kw) > 5 else "")
                print(f"  [{done}/{total}] {key} -> {len(kw)} mots-cles ({preview})")

            since_checkpoint += 1
            if since_checkpoint >= CHECKPOINT_EVERY:
                save_catalog(catalog)
                since_checkpoint = 0

    if since_checkpoint > 0:
        save_catalog(catalog)

    return success, failed, skipped


def _process_papers(papers_catalog, workers, force, limit):
    """Itere sur les papers et extrait les mots-cles depuis l'abstract PDF."""
    papers = papers_catalog.get("papers", {})
    candidates = [(k, m) for k, m in papers.items() if _needs_keywords(m, force)]
    skipped = len(papers) - len(candidates)

    if limit is not None:
        candidates = candidates[:limit]

    total = len(candidates)
    if total == 0:
        print(f"  Aucun paper a traiter ({skipped} deja traites, skip).")
        return 0, 0, skipped

    print(f"  {total} papers a traiter ({skipped} deja avec keywords, skip).")

    def _work(key, meta):
        pdf_path = os.path.join(PROJECT_ROOT, key)
        if not os.path.isfile(pdf_path):
            return (key, None, "PDF introuvable")
        try:
            abstract = extract_pdf_abstract(pdf_path)
        except Exception as e:
            return (key, None, f"erreur extraction PDF: {e}")
        if not abstract.strip():
            return (key, None, "abstract vide")
        title = meta.get("title") or os.path.splitext(os.path.basename(key))[0]
        kw = call_keywords_for_item(title, abstract, meta.get("tags", []))
        return (key, kw, None)

    done = 0
    success = 0
    failed = 0
    since_checkpoint = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_work, k, m): k for k, m in candidates}
        for future in as_completed(futures):
            done += 1
            key, kw, err = future.result()
            if err or not kw:
                failed += 1
                reason = err or "aucun mot-cle retourne"
                print(f"  [{done}/{total}] ECHEC {key} ({reason})")
            else:
                success += 1
                papers[key]["keywords"] = kw
                preview = ", ".join(kw[:5]) + ("..." if len(kw) > 5 else "")
                print(f"  [{done}/{total}] {key} -> {len(kw)} mots-cles ({preview})")

            since_checkpoint += 1
            if since_checkpoint >= CHECKPOINT_EVERY:
                save_papers_catalog(papers_catalog)
                since_checkpoint = 0

    if since_checkpoint > 0:
        save_papers_catalog(papers_catalog)

    return success, failed, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Backfill des mots-cles cherchables pour les articles et papers existants.",
    )
    parser.add_argument("--only", choices=["articles", "papers"], default=None,
                        help="traiter uniquement les articles ou les papers")
    parser.add_argument("--force", action="store_true",
                        help="retraiter les entrees qui ont deja des keywords")
    parser.add_argument("--workers", type=int, default=3,
                        help="workers paralleles (defaut: 3)")
    parser.add_argument("--limit", type=int, default=None,
                        help="ne traiter que N items (utile pour tester)")
    parser.add_argument("--skip-manifest", action="store_true",
                        help="ne pas regenerer manifest.json a la fin")
    args = parser.parse_args()

    do_articles = args.only != "papers"
    do_papers = args.only != "articles"

    a_success = a_failed = a_skipped = 0
    p_success = p_failed = p_skipped = 0

    if do_articles:
        print("=" * 60)
        print(f"  ARTICLES ({KEYWORDS_MODEL}, {args.workers} workers)")
        print("=" * 60)
        catalog = load_catalog()
        a_success, a_failed, a_skipped = _process_articles(
            catalog, args.workers, args.force, args.limit
        )
        print()

    if do_papers:
        print("=" * 60)
        print(f"  PAPERS ({KEYWORDS_MODEL}, {args.workers} workers)")
        print("=" * 60)
        papers_catalog = load_papers_catalog()
        p_success, p_failed, p_skipped = _process_papers(
            papers_catalog, args.workers, args.force, args.limit
        )
        print()

    print("=" * 60)
    print("  RESUME")
    print("=" * 60)
    if do_articles:
        print(f"  Articles : {a_success} traites, {a_failed} echecs, {a_skipped} skippes")
    if do_papers:
        print(f"  Papers   : {p_success} traites, {p_failed} echecs, {p_skipped} skippes")

    if not args.skip_manifest:
        print("\nRegeneration du manifeste...")
        _regenerate_manifest()

    print("\nTermine !")


if __name__ == "__main__":
    main()
