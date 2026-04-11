# Refactoring import.py — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactorer `scripts/import.py` pour extraire `main()` en sous-fonctions, unifier les 4 fonctions dedup, et supprimer le code mort `--migrate`.

**Architecture:** Extraction mecanique de code — chaque branche `if/elif` de `main()` devient une fonction `cmd_*`. Les 4 fonctions de deduplication sont remplacees par 2 fonctions parametrees. Aucun changement de comportement observable.

**Tech Stack:** Python 3 (stdlib uniquement)

---

## File Structure

| Fichier | Action | Responsabilite |
|---------|--------|----------------|
| `scripts/import.py` | Modify | Seul fichier modifie — refactoring interne |

---

### Task 1: Supprimer le code mort `--migrate`

**Files:**
- Modify: `scripts/import.py:641-687` (fonction `migrate_to_catalog`)
- Modify: `scripts/import.py:1341-1377` (argparse + branche migrate dans `main()`)

- [ ] **Step 1: Supprimer la fonction `migrate_to_catalog()`**

Supprimer les lignes 641-687 dans `scripts/import.py` — la fonction complete `migrate_to_catalog()` :

```python
# SUPPRIMER tout ce bloc (lignes 641-687) :
def migrate_to_catalog():
    """Migration one-time : lit les 8 manifests de domaine + observations.md
    et construit catalog.json. Les scores /5 sont convertis en /10 (x2, plafonne a 10)."""
    # ... tout le corps de la fonction
```

- [ ] **Step 2: Supprimer l'argument `--migrate` de argparse**

Dans `main()`, supprimer ces lignes de l'argument parser :

```python
# SUPPRIMER :
    parser.add_argument('--migrate', action='store_true',
                        help="migration one-time des manifests de domaine vers catalog.json")
```

- [ ] **Step 3: Supprimer la branche `if args.migrate:` dans `main()`**

Dans `main()`, supprimer ce bloc :

```python
# SUPPRIMER :
    # ------------------------------------------------------------------
    # --migrate : migration one-time
    # ------------------------------------------------------------------
    if args.migrate:
        print("Migration des manifests de domaine vers catalog.json...\n")
        migrate_to_catalog()
        return
```

- [ ] **Step 4: Supprimer la reference `--migrate` dans l'epilog argparse**

Dans le `epilog` de `main()`, supprimer cette ligne d'exemple :

```python
# SUPPRIMER cette ligne de l'epilog :
              python3 scripts/import.py --migrate               Migration vers catalog.json
```

Note : si cette ligne n'existe pas dans l'epilog (verifier), ignorer cette etape.

- [ ] **Step 5: Verifier que le fichier est syntaxiquement correct**

Run: `python3 -c "import ast; ast.parse(open('scripts/import.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Verifier que --migrate n'apparait plus**

Run: `grep -n "migrate" scripts/import.py`
Expected: aucune sortie (ou uniquement des commentaires non pertinents)

- [ ] **Step 7: Commit**

```bash
git add scripts/import.py
git commit -m "refactor: remove dead --migrate code from import.py"
```

---

### Task 2: Unifier les fonctions dedup

**Files:**
- Modify: `scripts/import.py:436-449` (remplacer `dedup_pdf_files`)
- Modify: `scripts/import.py:452-486` (remplacer `dedup_pdfs_against_catalog`)
- Modify: `scripts/import.py:561-573` (remplacer `dedup_files`)
- Modify: `scripts/import.py:576-600` (remplacer `dedup_against_catalog`)
- Modify: `scripts/import.py` dans `main()` (mettre a jour les appels)

Note : les numeros de lignes ci-dessus sont ceux du fichier ORIGINAL avant la Task 1. Apres Task 1, les lignes auront decale de ~50 lignes vers le haut. Utiliser les noms de fonctions pour se reperer.

- [ ] **Step 1: Remplacer `dedup_files` et `dedup_pdf_files` par `dedup_batch`**

Supprimer les deux fonctions `dedup_files` (dans la section "Dedup") et `dedup_pdf_files` (dans la section "Deduplication PDF"). Les remplacer par une seule fonction dans la section "Dedup" (a la place de `dedup_files`) :

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

- [ ] **Step 2: Ajouter les helpers lecteurs**

Juste apres `dedup_batch`, ajouter les deux helpers :

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

- [ ] **Step 3: Remplacer `dedup_against_catalog` et `dedup_pdfs_against_catalog` par une version unifiee**

Supprimer `dedup_against_catalog` (ancienne, dans la section "Dedup") et `dedup_pdfs_against_catalog` (dans la section "Deduplication PDF"). Les remplacer par une seule fonction (apres les helpers de l'etape 2) :

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

- [ ] **Step 4: Mettre a jour les appels dans `main()`**

Dans la section **pipeline articles HTML** de `main()`, remplacer :

```python
# AVANT :
excluded = dedup_files(file_contents)
catalog_dupes = dedup_against_catalog(file_contents, excluded, catalog)
```

Par :

```python
# APRES :
excluded = dedup_batch(file_contents, extract_content_fingerprint)
catalog_dupes = dedup_against_catalog(
    file_contents, excluded, catalog["articles"],
    extract_content_fingerprint, _read_article_content
)
```

Dans la section **pipeline publications PDF** de `main()`, remplacer :

```python
# AVANT :
excluded = dedup_pdf_files(pdf_texts)
catalog_dupes = dedup_pdfs_against_catalog(pdf_texts, excluded, papers_catalog)
```

Par :

```python
# APRES :
excluded = dedup_batch(pdf_texts, extract_pdf_fingerprint)
catalog_dupes = dedup_against_catalog(
    pdf_texts, excluded, papers_catalog["papers"],
    extract_pdf_fingerprint, _read_pdf_text, doi_fn=extract_pdf_doi
)
```

- [ ] **Step 5: Verifier que le fichier est syntaxiquement correct**

Run: `python3 -c "import ast; ast.parse(open('scripts/import.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Verifier que les anciennes fonctions n'existent plus**

Run: `grep -n "def dedup_files\|def dedup_pdf_files\|def dedup_pdfs_against_catalog" scripts/import.py`
Expected: aucune sortie

Run: `grep -n "def dedup_batch\|def dedup_against_catalog\|def _read_article_content\|def _read_pdf_text" scripts/import.py`
Expected: 4 lignes (les 4 nouvelles fonctions)

- [ ] **Step 7: Commit**

```bash
git add scripts/import.py
git commit -m "refactor: unify 4 dedup functions into 2 parameterized ones"
```

---

### Task 3: Extraire `cmd_reclassify(args)` de `main()`

**Files:**
- Modify: `scripts/import.py` — `main()` function

- [ ] **Step 1: Creer la fonction `cmd_reclassify(args)`**

Juste avant `main()`, inserer une nouvelle fonction `cmd_reclassify(args)`. Son contenu est le bloc `if args.reclassify:` extrait de `main()`, tel quel — les lignes actuelles entre le commentaire `# --reclassify` et le `return` inclus.

Copie exacte du bloc. Voici la fonction complete a inserer :

```python
def cmd_reclassify(args):
    """Reclassifier tous les articles existants."""
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
```

- [ ] **Step 2: Remplacer le bloc dans `main()` par un appel**

Dans `main()`, remplacer tout le bloc `if args.reclassify:` (du commentaire `# --reclassify` jusqu'au `return` inclus) par :

```python
    if args.reclassify:
        cmd_reclassify(args)
        return
```

- [ ] **Step 3: Verifier la syntaxe**

Run: `python3 -c "import ast; ast.parse(open('scripts/import.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add scripts/import.py
git commit -m "refactor: extract cmd_reclassify() from main()"
```

---

### Task 4: Extraire `cmd_reclassify_papers(args)` de `main()`

**Files:**
- Modify: `scripts/import.py` — `main()` function

- [ ] **Step 1: Creer la fonction `cmd_reclassify_papers(args)`**

Juste apres `cmd_reclassify`, inserer `cmd_reclassify_papers(args)`. Contenu = le bloc `if args.reclassify_papers:` extrait de `main()` :

```python
def cmd_reclassify_papers(args):
    """Reclassifier les publications existantes."""
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
```

- [ ] **Step 2: Remplacer le bloc dans `main()`**

Dans `main()`, remplacer le bloc `if args.reclassify_papers:` par :

```python
    if args.reclassify_papers:
        cmd_reclassify_papers(args)
        return
```

- [ ] **Step 3: Verifier la syntaxe**

Run: `python3 -c "import ast; ast.parse(open('scripts/import.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add scripts/import.py
git commit -m "refactor: extract cmd_reclassify_papers() from main()"
```

---

### Task 5: Extraire `cmd_regenerate_companions(args)` de `main()`

**Files:**
- Modify: `scripts/import.py` — `main()` function

- [ ] **Step 1: Creer la fonction `cmd_regenerate_companions(args)`**

Juste apres `cmd_reclassify_papers`, inserer :

```python
def cmd_regenerate_companions(args):
    """Regenerer les LCA et vulgarisations de toutes les publications."""
    print("Regeneration des LCA et vulgarisations...\n")
    papers_catalog = load_papers_catalog()
    if not papers_catalog["papers"]:
        print("Aucune publication dans papers/catalog.json.")
        sys.exit(1)

    total = len(papers_catalog["papers"])
    print(f"1. Extraction du texte de {total} publications...")

    paper_infos = []
    for paper_key, meta in papers_catalog["papers"].items():
        pdf_path = os.path.join(PROJECT_ROOT, paper_key)
        if not os.path.isfile(pdf_path):
            print(f"  SKIP {paper_key} (fichier introuvable)")
            continue
        text = extract_pdf_text(pdf_path)
        if not text or len(text.strip()) < 100:
            print(f"  SKIP {paper_key} (texte trop court)")
            continue
        paper_infos.append({
            'key': paper_key,
            'meta': meta,
            'text': text,
        })

    if not paper_infos:
        print("Aucune publication a traiter.")
        sys.exit(0)

    print(f"   {len(paper_infos)} publications pretes\n")

    print(f"2. Appel Claude pour LCA + vulgarisation ({args.workers} workers)...")

    def _regenerate_one(info):
        """LCA puis vulgarisation pour une publication."""
        lca_result = call_claude_with_retry(
            build_paper_lca_prompt(info['text'], papers_catalog["domains"]),
            PAPER_LCA_SCHEMA,
            timeout=600
        )
        vulg_result = call_claude_with_retry(
            build_paper_vulgarisation_prompt(
                info['text'],
                lca_result['title'],
                lca_result['authors']
            ),
            PAPER_VULGARISATION_SCHEMA,
            timeout=600
        )
        return (info, lca_result, vulg_result)

    done_count = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_regenerate_one, info): info for info in paper_infos}
        for future in as_completed(futures):
            done_count += 1
            info, lca_result, vulg_result = future.result()
            paper_key = info['key']
            meta = info['meta']

            # Mettre a jour les scores
            new_robustness = lca_result['robustness_global']
            new_quality = min(round(new_robustness * 2), 10)

            # Ecrire les fichiers companions
            parts = paper_key.split('/')
            domain = parts[1]
            slug = parts[2]
            paper_dir = os.path.join(PAPERS_DIR, domain, slug)

            lca_html = build_companion_html(meta['title'], lca_result['lca_html'], 'lca')
            lca_path = os.path.join(paper_dir, f"{slug}-lca.html")
            with open(lca_path, 'w', encoding='utf-8') as f:
                f.write(lca_html)

            vulg_html = build_companion_html(meta['title'], vulg_result['vulgarisation_html'], 'vulgarisation')
            vulg_path = os.path.join(paper_dir, f"{slug}-vulgarisation.html")
            with open(vulg_path, 'w', encoding='utf-8') as f:
                f.write(vulg_html)

            # Mettre a jour le catalogue
            papers_catalog["papers"][paper_key]["quality_score"] = new_quality
            papers_catalog["papers"][paper_key]["robustness_score"] = new_robustness

            authors_short = meta['authors'][0] if meta.get('authors') else 'Unknown'
            if len(meta.get('authors', [])) > 1:
                authors_short += ' et al.'
            print(f"  [{done_count}/{len(paper_infos)}] {slug} ({new_quality}/10, robustesse {new_robustness}/5) {authors_short}")

    save_papers_catalog(papers_catalog)
    _regenerate_manifest()
    print(f"\nTermine ! {done_count} publications regenerees.")
```

- [ ] **Step 2: Remplacer le bloc dans `main()`**

Dans `main()`, remplacer le bloc `if args.regenerate_companions:` par :

```python
    if args.regenerate_companions:
        cmd_regenerate_companions(args)
        return
```

- [ ] **Step 3: Verifier la syntaxe**

Run: `python3 -c "import ast; ast.parse(open('scripts/import.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add scripts/import.py
git commit -m "refactor: extract cmd_regenerate_companions() from main()"
```

---

### Task 6: Extraire `cmd_import(args)` et finaliser `main()`

**Files:**
- Modify: `scripts/import.py` — `main()` function

- [ ] **Step 1: Creer la fonction `cmd_import(args)`**

Juste apres `cmd_regenerate_companions`, inserer `cmd_import(args)`. Son contenu est tout le code restant dans `main()` apres les branches `if/elif` — c'est-a-dire la section "Import standard de nouveaux fichiers" (pipeline articles HTML + pipeline papers PDF + regenerate manifest). Copie exacte :

```python
def cmd_import(args):
    """Import standard de nouveaux fichiers (HTML articles + PDF papers)."""
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
        excluded = dedup_batch(file_contents, extract_content_fingerprint)
        catalog_dupes = dedup_against_catalog(
            file_contents, excluded, catalog["articles"],
            extract_content_fingerprint, _read_article_content
        )
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
        if not _HAS_PYMUPDF:
            print("\nERREUR : PyMuPDF est requis pour importer des PDFs.", file=sys.stderr)
            print("  pip install pymupdf", file=sys.stderr)
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
            excluded = dedup_batch(pdf_texts, extract_pdf_fingerprint)
            catalog_dupes = dedup_against_catalog(
                pdf_texts, excluded, papers_catalog["papers"],
                extract_pdf_fingerprint, _read_pdf_text, doi_fn=extract_pdf_doi
            )
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
                        timeout=600
                    )

                    # Appel vulgarisation (utilise title/authors du LCA)
                    vulg_result = call_claude_with_retry(
                        build_paper_vulgarisation_prompt(
                            info['text'],
                            lca_result['title'],
                            lca_result['authors']
                        ),
                        PAPER_VULGARISATION_SCHEMA,
                        timeout=600
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
```

- [ ] **Step 2: Reduire `main()` au dispatch**

Remplacer tout le contenu de `main()` (apres argparse) par le dispatch :

```python
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
              python3 scripts/import.py --regenerate-companions Regenerer LCA + vulgarisation
              python3 scripts/import.py --workers 5             5 workers paralleles
        """)
    )
    parser.add_argument('source', nargs='?', default='infiles',
                        help="dossier source contenant les fichiers HTML et/ou PDF (defaut: infiles)")
    parser.add_argument('--yes', action='store_true',
                        help="importer sans demander de confirmation")
    parser.add_argument('--reclassify', action='store_true',
                        help="reclassifier tous les articles existants (nouveau scoring, tags, domaines)")
    parser.add_argument('--reclassify-papers', action='store_true',
                        help="reclassifier les publications (domain, tags, quality_note ; score fige, compagnons non regeneres)")
    parser.add_argument('--regenerate-companions', action='store_true',
                        help="regenerer les LCA et vulgarisations de toutes les publications existantes")
    parser.add_argument('--workers', type=int, default=3,
                        help="nombre de workers paralleles pour le scoring (defaut: 3)")
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

- [ ] **Step 3: Verifier la syntaxe**

Run: `python3 -c "import ast; ast.parse(open('scripts/import.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Verifications finales**

Run: `python3 scripts/import.py --help`
Expected: affiche l'aide avec les 4 flags (sans `--migrate`), les exemples, et la description

Run: `python3 scripts/import.py nonexistent_dir/`
Expected: `Erreur : dossier 'nonexistent_dir/' introuvable`

Run: `grep -c "^def " scripts/import.py`
Expected: un nombre (verifier qu'il est coherent — environ 42-44 fonctions)

- [ ] **Step 5: Commit**

```bash
git add scripts/import.py
git commit -m "refactor: extract cmd_import() and finalize main() as dispatcher"
```

---

### Task 7: Verification finale et nettoyage

**Files:**
- Modify: `scripts/import.py` (si nettoyage necessaire)

- [ ] **Step 1: Verifier que les anciennes fonctions sont supprimees**

Run: `grep -n "def migrate_to_catalog\|def dedup_files\|def dedup_pdf_files\|def dedup_pdfs_against_catalog" scripts/import.py`
Expected: aucune sortie

- [ ] **Step 2: Verifier que les nouvelles fonctions existent**

Run: `grep -n "def cmd_reclassify\|def cmd_reclassify_papers\|def cmd_regenerate_companions\|def cmd_import\|def dedup_batch\|def dedup_against_catalog\|def _read_article_content\|def _read_pdf_text" scripts/import.py`
Expected: 8 lignes

- [ ] **Step 3: Verifier que `main()` est court**

Run: `awk '/^def main\(\):/,/^def [a-z]/' scripts/import.py | wc -l`
Expected: environ 25-30 lignes (le dispatch)

- [ ] **Step 4: Verifier le nombre total de lignes**

Run: `wc -l scripts/import.py`
Expected: environ 1890-1920 lignes (reduction d'environ 70-100 lignes)

- [ ] **Step 5: Syntaxe finale**

Run: `python3 -c "import ast; ast.parse(open('scripts/import.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Test fonctionnel basique**

Run: `mkdir -p /tmp/curax-test-empty && python3 scripts/import.py /tmp/curax-test-empty/`
Expected: `Aucun fichier HTML ou PDF dans /tmp/curax-test-empty/`

Run: `python3 scripts/import.py --help`
Expected: affiche l'aide complete sans `--migrate`

- [ ] **Step 7: Commit final si nettoyage necessaire**

Si des ajustements ont ete faits aux etapes precedentes :

```bash
git add scripts/import.py
git commit -m "refactor: final cleanup after import.py refactoring"
```
