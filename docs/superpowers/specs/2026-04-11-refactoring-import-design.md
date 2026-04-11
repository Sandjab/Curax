# Refactoring import.py — Design Spec

> Date : 2026-04-11 | Statut : Valide | Fichier impacte : `scripts/import.py`

## Contexte

`scripts/import.py` (1988 lignes, 45 fonctions) est le pipeline d'import de Curax. Sa fonction `main()` fait 647 lignes avec 5 branches `if/elif` pour les differents modes CLI. Quatre fonctions de deduplication quasi-identiques existent en parallele. Le flag `--migrate` est du code mort (migration one-time deja executee).

Ce refactoring ameliore la maintenabilite sans changer le comportement observable.

## Decisions de design

| Decision | Choix | Justification |
|----------|-------|---------------|
| Structure fichier | Un seul fichier `import.py` | Projet mono-developpeur, pas besoin d'un package Python |
| Strategie | Extraction mecanique + unification dedup | Risque de regression minimal |
| `--migrate` | Supprime | Code mort, disponible dans l'historique git |
| Pattern parallele | Non abstrait | Les 5 instances ont des post-traitements differents, une abstraction a base de callbacks serait moins lisible |
| Nettoyage additionnel | Non | Pas de type hints, pas de correction d'exceptions — reserve pour la tache #3 (tests) |

## Transformation 1 : Refactoring de `main()`

### Avant

```python
def main():
    # argparse (28 lignes)
    if args.migrate:        # 4 lignes
    if args.reclassify:     # ~120 lignes
    if args.reclassify_papers:  # ~107 lignes
    if args.regenerate_companions:  # ~93 lignes
    # import standard         # ~264 lignes
```

### Apres

```python
def main():
    parser = argparse.ArgumentParser(
        description="Pipeline d'import autonome pour Curax.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            exemples:
              python3 scripts/import.py infiles/                Import HTML + PDF avec preview
              python3 scripts/import.py --yes infiles/          Import sans confirmation
              python3 scripts/import.py --reclassify            Reclassifier les articles
              python3 scripts/import.py --reclassify-papers     Reclassifier les publications
              python3 scripts/import.py --regenerate-companions Regenerer LCA + vulgarisation
              python3 scripts/import.py --workers 5             5 workers paralleles
        """)
    )
    parser.add_argument('source', nargs='?', default='infiles',
                        help="dossier source contenant les fichiers HTML et/ou PDF (defaut: infiles)")
    parser.add_argument('--yes', action='store_true',
                        help="importer sans demander de confirmation")
    parser.add_argument('--reclassify', action='store_true',
                        help="reclassifier tous les articles existants")
    parser.add_argument('--reclassify-papers', action='store_true',
                        help="reclassifier les publications existantes")
    parser.add_argument('--regenerate-companions', action='store_true',
                        help="regenerer les LCA et vulgarisations")
    parser.add_argument('--workers', type=int, default=3,
                        help="nombre de workers paralleles (defaut: 3)")
    args = parser.parse_args()

    if args.reclassify:
        cmd_reclassify(args)
    elif args.reclassify_papers:
        cmd_reclassify_papers(args)
    elif args.regenerate_companions:
        cmd_regenerate_companions(args)
    else:
        cmd_import(args)
```

### Fonctions extraites

**`cmd_reclassify(args)`** — Copie exacte des lignes 1382-1500 actuelles :
- Load catalog, appel taxonomie, scoring parallele, detection changements domaine/slug, preview, confirmation, execution moves/renames, save + regenerate manifest

**`cmd_reclassify_papers(args)`** — Copie exacte des lignes 1505-1612 actuelles :
- Meme pattern que `cmd_reclassify` mais pour papers. Score fige (pas de recalcul quality_score).

**`cmd_regenerate_companions(args)`** — Copie exacte des lignes 1617-1710 actuelles :
- Extract texte, parallel LCA + vulgarisation, ecriture fichiers companions, update scores, save + regenerate manifest

**`cmd_import(args)`** — Copie exacte des lignes 1714-1978 actuelles :
- Scan source dir, pipeline articles HTML (dedup → taxonomy → scoring → preview → confirm → import), pipeline papers PDF (idem + LCA + vulgarisation), regenerate manifest

Les fonctions internes definies dans chaque branche (`_score_one`, `_reclassify_paper`, `_regenerate_one`, `_score_new`, `_process_paper`) restent definies localement dans leur `cmd_*` respective.

## Transformation 2 : Unification dedup

### Avant — 4 fonctions

```
dedup_files(file_contents)                              # intra-batch HTML
dedup_against_catalog(file_contents, excluded, catalog)  # HTML vs catalog
dedup_pdf_files(pdf_texts)                              # intra-batch PDF
dedup_pdfs_against_catalog(pdf_texts, excluded, catalog) # PDF vs catalog + DOI
```

### Apres — 2 fonctions + 2 helpers

**`dedup_batch(items, fingerprint_fn)`** — Remplace `dedup_files` + `dedup_pdf_files`

```python
def dedup_batch(items, fingerprint_fn):
    """Dedup intra-batch par fingerprint.
    items: {filepath: content_or_text}
    fingerprint_fn: content -> str|None
    Retourne set des chemins exclus."""
    fingerprints = {}
    excluded = set()
    for filepath, content in items.items():
        fp = fingerprint_fn(content)
        if fp is None:
            continue
        if fp in fingerprints:
            excluded.add(filepath)
            print(f"  Doublon exclu : {os.path.basename(filepath)} "
                  f"(identique a {os.path.basename(fingerprints[fp])})")
        else:
            fingerprints[fp] = filepath
    return excluded
```

**`dedup_against_catalog(items, excluded, existing_entries, fingerprint_fn, content_reader, doi_fn=None)`** — Remplace les deux fonctions catalog dedup

```python
def dedup_against_catalog(items, excluded, existing_entries,
                          fingerprint_fn, content_reader, doi_fn=None):
    """Compare les nouveaux items au catalogue existant.
    existing_entries: {key: meta} du catalogue
    content_reader(key) -> content|None
    doi_fn(content) -> str|None, optionnel (PDFs uniquement)"""
    existing_fps = set()
    existing_dois = set()
    for key, meta in existing_entries.items():
        content = content_reader(key)
        if content is not None:
            fp = fingerprint_fn(content)
            if fp:
                existing_fps.add(fp)
        if doi_fn:
            doi = meta.get("doi", "")
            if doi:
                existing_dois.add(doi.lower())

    catalog_dupes = set()
    for filepath, content in items.items():
        if filepath in excluded:
            continue
        fp = fingerprint_fn(content)
        if fp and fp in existing_fps:
            catalog_dupes.add(filepath)
            print(f"  Deja importe (fingerprint) : {os.path.basename(filepath)}")
            continue
        if doi_fn:
            doi = doi_fn(content)
            if doi and doi.lower() in existing_dois:
                catalog_dupes.add(filepath)
                print(f"  Deja importe (DOI) : {os.path.basename(filepath)}")
    return catalog_dupes
```

**Helpers lecteurs :**

```python
def _read_article_content(article_key):
    """Lit le contenu HTML d'un article depuis PROJECT_ROOT."""
    path = os.path.join(PROJECT_ROOT, article_key)
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()

def _read_pdf_text(paper_key):
    """Lit le texte extrait d'un PDF depuis PROJECT_ROOT."""
    path = os.path.join(PROJECT_ROOT, paper_key)
    if not os.path.isfile(path):
        return None
    try:
        return extract_pdf_text(path)
    except Exception:
        return None
```

### Appels dans le code

Articles (dans `cmd_import`) :
```python
excluded = dedup_batch(file_contents, extract_content_fingerprint)
catalog_dupes = dedup_against_catalog(
    file_contents, excluded, catalog["articles"],
    extract_content_fingerprint, _read_article_content
)
```

PDFs (dans `cmd_import`) :
```python
excluded = dedup_batch(pdf_texts, extract_pdf_fingerprint)
catalog_dupes = dedup_against_catalog(
    pdf_texts, excluded, papers_catalog["papers"],
    extract_pdf_fingerprint, _read_pdf_text, doi_fn=extract_pdf_doi
)
```

## Transformation 3 : Suppression code mort

Suppression de :
- Flag `--migrate` dans argparse
- Branche `if args.migrate:` dans `main()`
- Fonction `migrate_to_catalog()` (lignes 641-687, 46 lignes)
- Reference a `--migrate` dans l'epilog argparse

## Ce qui ne change pas

- Tous les prompts (`build_*_prompt`) — intacts
- Tous les schemas JSON (`*_SCHEMA`) — intacts
- Extraction texte (`extract_text_spans`, `extract_pdf_text`, etc.) — intacts
- Template companion HTML (`build_companion_html`) — intact
- Import (`do_import`, `do_import_papers`) — intacts
- Move/rename (`move_or_rename_article`, `move_or_rename_paper`) — intacts
- Catalog I/O (`load_catalog`, `save_catalog`, `load_papers_catalog`, `save_papers_catalog`) — intacts
- Utilitaires (`slugify`, `_escape_html`, `_clean_entities`, `call_claude`, `call_claude_with_retry`, `prompt_confirm`) — intacts
- Directives d'humanisation (`_HUMANIZATION_*`) — intactes

## Organisation du fichier apres refactoring

```
import.py (~1900 lignes)
├── Imports + constantes (lignes 1-38)
├── Directives d'humanisation (lignes 40-108)
├── Claude CLI helper (lignes 110-145)
├── JSON schemas (lignes 148-267)
├── Extraction texte HTML (lignes 270-399)
├── Extraction PDF (lignes 402-429)
├── Dedup unifie (lignes 432-505)      ← MODIFIE (4 fonctions → 2 + 2 helpers)
├── Metadata injection (lignes ~508-516)
├── Slugification (ligne ~520)
├── Analyze article (lignes ~530-555)
├── Catalog I/O (lignes ~558-638)
├── Prompt builders (lignes ~640-965)   ← migrate_to_catalog() SUPPRIME
├── Companion HTML template (lignes ~968-1125)
├── Import functions (lignes ~1128-1300)
├── Move/rename (lignes ~1174-1247)
├── Confirmation interactive (lignes ~1305-1335)
├── cmd_reclassify(args) (~120 lignes)  ← NOUVEAU
├── cmd_reclassify_papers(args) (~107 lignes) ← NOUVEAU
├── cmd_regenerate_companions(args) (~93 lignes) ← NOUVEAU
├── cmd_import(args) (~264 lignes)      ← NOUVEAU
├── main() (~25 lignes)                 ← REDUIT
├── _regenerate_manifest()
└── if __name__ == '__main__': main()
```

## Verification

1. `python3 scripts/import.py --help` — verifier que `--migrate` n'apparait plus, les 4 autres flags sont presents
2. `python3 scripts/import.py infiles/` avec un dossier vide — doit afficher "Aucun fichier HTML ou PDF"
3. `python3 scripts/import.py --reclassify` — doit fonctionner identiquement (ne pas executer si pas de Claude CLI disponible, mais verifier que le flow demarre)
4. Verifier que `migrate_to_catalog` n'existe plus dans le fichier
5. Verifier que `dedup_files`, `dedup_pdf_files`, `dedup_against_catalog` (ancienne signature), `dedup_pdfs_against_catalog` n'existent plus
6. `grep -c "def " scripts/import.py` — compter les fonctions (devrait passer de ~45 a ~45 : -5 supprimees + 4 cmd_* + 2 helpers - 4 anciennes dedup + 2 nouvelles dedup)
