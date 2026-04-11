# Tests unitaires import.py — Design Spec

> Date : 2026-04-11 | Statut : Valide | Fichier cree : `tests/test_import.py`

## Contexte

`scripts/import.py` (1923 lignes, ~45 fonctions) n'a aucun test automatise. Le risque de regression est eleve, surtout apres le refactoring (tache #2). Cette spec ajoute des tests unitaires couvrant les fonctions de logique pure (sans Claude CLI).

## Decisions de design

| Decision | Choix | Justification |
|----------|-------|---------------|
| Framework | pytest | Standard de facto, assertions lisibles, fixtures puissantes |
| Structure | Un seul fichier `tests/test_import.py` | Un seul fichier source = un seul fichier de test |
| Fixture PDF | Non | `extract_pdf_text` est un wrapper mince autour de PyMuPDF. On teste les fonctions en aval avec des strings |
| Mock Claude CLI | Non | Les `cmd_*` et `call_claude` sont de l'orchestration, pas de la logique testable |
| Fichiers temporaires | `tmp_path` (fixture pytest) | Pour catalog I/O et dedup |
| Patching | `monkeypatch` (fixture pytest) | Pour `PROJECT_ROOT`, `CATALOG_PATH`, etc. |
| Organisation | Classes pytest par groupe | `TestCleanEntities`, `TestExtractTextSpans`, etc. |

## Fonctions couvertes

### Groupe 1 : Entites HTML

**Fonctions :** `_clean_entities`, `_escape_html`

**Tests :**
- `_clean_entities` : remplace `&amp;`, `&lt;`, `&gt;`, `&#39;`, `&quot;`, `&nbsp;`
- `_escape_html` : echappe `&`, `"`, `<`, `>`
- Round-trip : `_clean_entities(_escape_html(text))` ne perd pas d'information sur du texte sans caracteres speciaux

### Groupe 2 : Extraction texte HTML

**Fonctions :** `extract_text_spans`, `extract_text_preview`, `_extract_pre_blocks`, `extract_author`

**Tests `extract_text_spans` :**
- Contenu X/Twitter avec `data-text="true"` spans → extrait le texte
- Contenu X/Twitter avec blocs `<pre><code>` → texte + code
- Contenu generique (apres `</style>`) → extrait les blocs texte significatifs (>30 chars)
- Filtre les blocs CSS (contenant `color:`, `background:`, etc.)
- Contenu vide → retourne `""`

**Tests `extract_text_preview` :**
- Retourne un preview tronque a `max_len`
- Respecte `max_len` par defaut (200)
- Contenu X/Twitter → preview depuis les spans
- Contenu generique → preview depuis le premier bloc significatif

**Tests `_extract_pre_blocks` :**
- Extrait le texte de `<pre><code>...</code></pre>`
- Supprime les tags HTML internes
- Nettoie les entites HTML
- Pas de blocs `<pre>` → retourne `""`

**Tests `extract_author` :**
- Auteur X/Twitter : `UserAvatar-Container-{handle}` → retourne le handle
- Auteur Cloudflare : `.author-name-tooltip` → retourne le nom
- Auteur Prof : `Prof. Prenom Nom` → retourne le match
- Aucun auteur → retourne `"unknown"`

### Groupe 3 : Fingerprint HTML

**Fonction :** `extract_content_fingerprint`

**Tests :**
- Contenu X/Twitter → retourne un hash SHA-256 (64 chars hex)
- Contenu generique → retourne un hash SHA-256
- Meme contenu → meme hash (determinisme)
- Contenus differents → hashs differents
- Contenu sans texte significatif → retourne `None`

### Groupe 4 : Extraction PDF (texte en entree)

**Fonctions :** `extract_pdf_doi`, `extract_pdf_fingerprint`

**Tests `extract_pdf_doi` :**
- Texte avec DOI standard (`10.1234/abc.def`) → extrait le DOI
- DOI en fin de phrase avec point → strip le point final
- DOI avec caracteres complexes (`10.48550/arXiv.1706.03762`) → extrait correctement
- Texte sans DOI → retourne `""`

**Tests `extract_pdf_fingerprint` :**
- Texte normal (>100 chars) → retourne hash SHA-256
- Texte trop court (<100 chars apres nettoyage) → retourne `None`
- Meme texte → meme hash
- Texte avec whitespace variable → meme hash (normalisation)

### Groupe 5 : Dedup

**Fonctions :** `dedup_batch`, `dedup_against_catalog`

**Tests `dedup_batch` :**
- Items sans doublons → set vide
- Items avec doublons (meme fingerprint) → le second est exclu
- Items avec fingerprint None → ignores (pas exclus, pas erreur)
- Un seul item → set vide

**Tests `dedup_against_catalog` :**
- Aucun match → set vide
- Match par fingerprint → item exclu
- Match par DOI (avec `doi_fn`) → item exclu
- `doi_fn=None` → DOI non verifie
- Fichier absent dans le catalogue (content_reader retourne None) → skip sans erreur
- Item deja dans `excluded` → skip

### Groupe 6 : Slugification

**Fonction :** `slugify`

**Tests :**
- Texte normal → kebab-case (`"Hello World"` → `"hello-world"`)
- Caracteres speciaux → remplaces par tirets
- `max_len` respecte → tronque
- Texte vide → `"untitled"`
- Accents et unicode → supprimes

### Groupe 7 : Injection metadata

**Fonction :** `inject_metadata`

**Tests :**
- Remplace le `<title>` existant
- Ajoute `<meta description>` quand absente
- Remplace `<meta description>` quand existante
- Echappe les caracteres speciaux dans title et description
- Fonctionne avec du HTML minimal

### Groupe 8 : Catalog I/O

**Fonctions :** `load_catalog`, `save_catalog`, `load_papers_catalog`, `save_papers_catalog`

**Tests :**
- `load_catalog` fichier absent → retourne `{"domains": {}, "articles": {}, "observations": ""}`
- `load_catalog` fichier existant → retourne le contenu parse
- `save_catalog` → ecrit du JSON valide avec `indent=2` et `ensure_ascii=False`
- Round-trip : save puis load → memes donnees
- Memes tests pour `load_papers_catalog` / `save_papers_catalog`

**Strategie :** utiliser `tmp_path` + `monkeypatch` pour rediriger `CATALOG_PATH` et `PAPERS_CATALOG_PATH` vers des fichiers temporaires.

### Groupe 9 : Analyze article

**Fonction :** `analyze_article`

**Tests :**
- Retourne un dict avec les cles `filepath`, `filename`, `author`, `slug`, `text`
- Slug derive du premier texte extrait (pas vide, pas "untitled" si texte suffisant)
- Auteur extrait correctement

### Groupe 10 : Companion HTML

**Fonction :** `build_companion_html`

**Tests :**
- Type `'lca'` → titre contient "Lecture Critique d'Article"
- Type `'vulgarisation'` → titre contient "Vulgarisation"
- Titre echappe dans le HTML
- Contient le lien retour (`../../../index.html`)
- Contient le script `themes.js` (`../../../themes.js`)
- Contient le script anti-FOUC (`localStorage`)
- Contient le body_html injecte

## Fonctions NON couvertes

| Fonction | Raison |
|----------|--------|
| `call_claude`, `call_claude_with_retry` | Dependance externe (Claude CLI) |
| `cmd_reclassify`, `cmd_reclassify_papers`, `cmd_regenerate_companions`, `cmd_import` | Orchestration dependant de Claude CLI |
| `extract_pdf_text` | Wrapper mince autour de PyMuPDF, teste via PyMuPDF |
| `prompt_confirm` | Interactif (terminal) |
| `build_*_prompt` | Construisent des strings de prompt, trop dependants du format exact — un changement de wording ne devrait pas casser un test |
| `do_import`, `do_import_papers` | Effets de bord (fichiers), orchestration |
| `move_or_rename_article`, `move_or_rename_paper` | Effets de bord (fichiers), orchestration |
| `_regenerate_manifest` | Appelle un subprocess externe |

## Fichier cree

| Fichier | Modifications |
|---------|---------------|
| `tests/test_import.py` | Nouveau fichier — ~400-500 lignes de tests |

Aucun fichier existant modifie. Aucune dependance ajoutee au runtime (pytest est dev-only).

## Execution

```bash
pip install pytest  # si pas deja installe
pytest tests/test_import.py -v
```
