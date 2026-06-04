---
name: curax-import
description: Importe les fichiers HTML (articles X/Twitter/Medium/LinkedIn) et PDF (publications scientifiques) déposés dans `infiles/` vers le repo Curax. Classifie, score, génère LCA + vulgarisation des PDF, met à jour les catalogues et le manifest. Utilise un workflow dynamique parallèle avec routing modèle (Opus/Sonnet/Haiku) au lieu de la CLI `claude -p` standalone. Déclencher quand l'utilisateur dit "importe les fichiers", "lance curax-import", "intègre les nouveaux articles/PDF", etc.
---

# curax-import — Workflow d'import Curax

Ce skill orchestre l'import autonome des fichiers placés dans `infiles/` en suivant le pipeline décrit dans `CLAUDE.md` du repo. **Aucun appel `claude -p`** — toute la classification/rédaction est faite par des subagents Claude Code en parallèle, avec un modèle adapté par tâche.

## Quand l'utiliser

Quand l'utilisateur veut importer ce qu'il a déposé dans `infiles/` :
- "importe les fichiers de `infiles/`", "lance l'import"
- "lance curax-import", "déclenche le workflow d'import"
- "intègre les nouveaux articles", "ajoute les PDF que j'ai mis"

Pour **reclassifier** l'existant ou **régénérer les compagnons**, ce skill ne s'applique pas — utiliser `python3 scripts/import.py --reclassify` (ou `--reclassify-papers` / `--regenerate-companions`) qui reste en mode standalone CLI.

## Procédure

### 1. Vérifications préalables

Exécuter en parallèle :
```bash
ls infiles/ 2>/dev/null
python3 -c "import fitz" 2>&1 | head -1
```

- Si `infiles/` n'existe pas ou est vide → dire à l'utilisateur "Rien à importer dans `infiles/`" et s'arrêter.
- Si des PDF sont présents et PyMuPDF (`fitz`) est manquant → demander `pip install pymupdf` avant de continuer.

### 2. Scan + dédup (déterministe)

```bash
python3 scripts/import.py --scan infiles/ > /tmp/curax-scan.json
```

Le JSON contient :
- `existing_articles_catalog` (domains + liste des paths existants)
- `existing_papers_catalog` (domains + liste des paths existants)
- `new_articles[]` : items HTML après dédup (filepath, filename, source, author, text, preview, provisional_slug)
- `new_papers[]` : items PDF après dédup (filepath, filename, text, preview, abstract)

Si les deux listes `new_*` sont vides → tout est déjà importé, s'arrêter en le disant à l'utilisateur.

### 3. Lancer le workflow

Vérifier d'abord si le workflow `curax-import` est déjà sauvegardé :
```bash
ls .claude/workflows/curax-import.js 2>/dev/null
```

**Si oui** → invoquer `/curax-import` en passant le chemin du scan :
```
/curax-import scan=/tmp/curax-scan.json
```

**Si non** (première exécution) → générer le workflow via `ultracode` en collant la spec ci-dessous, puis le sauvegarder avec `s` dans la vue `/workflows` à l'emplacement `.claude/workflows/curax-import.js`. Ensuite l'invoquer.

### 4. Après le workflow

Le workflow appelle `python3 scripts/import.py --finalize <json>` en dernière phase, qui :
- écrit les fichiers HTML/PDF + compagnons LCA/vulgarisation
- met à jour `articles/catalog.json` et `papers/catalog.json`
- régénère `manifest.json`
- nettoie `infiles/`

Afficher à l'utilisateur le résumé renvoyé par finalize : nombre d'articles + papers importés, domaines touchés, scores moyens.

Proposer ensuite : `git add` + `git commit` + `git push` (sans push automatique sauf demande explicite).

---

## Spec à coller dans `ultracode` à la première exécution

> **Important** : cette section est destinée à être lue par Claude lors de la première exécution du skill pour générer `workflow.js`. Coller le bloc qui suit dans un prompt commençant par `ultracode:`.

```
ultracode: Génère un workflow dynamique `curax-import` qui orchestre en parallèle l'import des fichiers Curax.

# Input
- args (passé au workflow) : `{ scanPath: "/tmp/curax-scan.json" }`
- Le fichier scan contient : existing_articles_catalog, existing_papers_catalog, new_articles[], new_papers[]

# Phases

## Phase 1 — Taxonomies (parallèle, 2 agents max)
Si `new_articles.length > 0` : spawn 1 agent `curax-taxonomy-architect` avec :
  - prompt : "Type=articles. Corpus existant: <existing_articles_catalog>. Nouveaux items: <new_articles avec previews tronqués à 500 chars>. Produis la taxonomie de domaines articles + observations."
Si `new_papers.length > 0` : spawn 1 agent `curax-taxonomy-architect` avec :
  - prompt : "Type=papers. Corpus existant: <existing_papers_catalog>. Nouvelles publications: <new_papers avec previews 500 chars>. Produis la taxonomie d'axes de recherche + observations."
Attendre les 2 résultats. Stocker `articlesTaxonomy` et `papersTaxonomy`.

## Phase 2a — Articles (parallèle, jusqu'à 16 agents)
Pour chaque `article` dans `new_articles`, en parallèle, spawn 2 agents simultanés :
  1. `curax-article-classifier` (modèle sonnet) :
     - prompt : "Taxonomie: <articlesTaxonomy.domains>. Texte article: <article.text>. Classifie et score."
     - récupère : `{ domain, tags, quality_score, quality_note, title, description }`
  2. `curax-keyword-extractor` (modèle haiku) :
     - prompt : "Titre: <article.text first line ou provisional_slug>. Auteur: <article.author si != 'unknown'>. Tags déjà assignés: à remplir après que classifier ait fini. Extrait: <article.text[:4000]>. Extrait 10-20 mots-clés."
     - Note: pour éviter la dépendance, lancer keyword-extractor avec `existing_tags=[]` puis dédupliquer côté workflow contre les tags issus du classifier.
     - récupère : `{ keywords: [...] }`

Collecter pour chaque article :
  - filepath, source, author (du scan)
  - domain, tags, quality_score, quality_note, title, description (du classifier)
  - keywords filtrés (dédup contre tags) (du keyword-extractor)
  - slug = slugify(title) (côté workflow JS : lowercase, [^a-z0-9]+ → "-", trim "-", max 60 chars; fallback provisional_slug)

## Phase 2b — Papers (parallèle, 3 agents par paper)
Pour chaque `paper` dans `new_papers`, en parallèle (3 agents simultanés par paper) :
  1. `curax-paper-lca-analyst` (modèle opus) :
     - prompt : "Taxonomie: <papersTaxonomy.domains>. Texte publication: <paper.text>. Produis LCA complète."
     - récupère : `{ domain, tags, title, description, quality_note, authors, year, journal, doi, robustness_scores, robustness_global, lca_html }`
  2. `curax-paper-vulgarizer` (modèle sonnet) :
     - prompt : "Texte publication: <paper.text>. Le titre et les auteurs seront raffinés par l'analyste LCA mais tu peux les extraire toi-même de l'abstract. Rédige la vulgarisation."
     - récupère : `{ vulgarisation_html }`
  3. `curax-keyword-extractor` (modèle haiku) :
     - prompt : "Extrait: <paper.abstract>. Tags: à remplir après LCA. Extrait 10-20 mots-clés."
     - récupère : `{ keywords: [...] }`

Collecter pour chaque paper : filepath + tous les champs ci-dessus + slug = slugify(LCA.title).

## Phase 3 — Finalize (déterministe, 1 appel Bash)
Construire le payload JSON final :
{
  "articles_taxonomy": <articlesTaxonomy ou null>,
  "papers_taxonomy": <papersTaxonomy ou null>,
  "articles": [...],
  "papers": [...],
  "cleanup_infiles": true,
  "infiles_dir": "infiles"
}

L'écrire dans /tmp/curax-finalize.json puis exécuter :
  python3 scripts/import.py --finalize /tmp/curax-finalize.json

Renvoyer le stdout (résumé compté) comme résultat du workflow.

# Contraintes runtime
- Limite à 16 agents concurrents (limite runtime).
- En cas d'échec d'un agent : retry 1 fois, puis exclure l'item et continuer.
- Chaque subagent référencé par son `name` (curax-taxonomy-architect, curax-article-classifier, curax-paper-lca-analyst, curax-paper-vulgarizer, curax-keyword-extractor) — leurs définitions vivent dans .claude/agents/.
- Aucun appel `claude -p`. Aucune écriture filesystem depuis le workflow (le finalize Python s'en charge).
```

---

## Subagents associés (déjà définis dans `.claude/agents/`)

| Nom | Modèle | Rôle |
|-----|--------|------|
| `curax-taxonomy-architect` | Opus | Taxonomie + observations (articles ET papers) |
| `curax-article-classifier` | Sonnet | Classify + score + tags + title/desc d'1 article HTML |
| `curax-paper-lca-analyst` | Opus | LCA complète + métadonnées + robustness d'1 PDF |
| `curax-paper-vulgarizer` | Sonnet | Vulgarisation ~2000 mots d'1 PDF |
| `curax-keyword-extractor` | Haiku | 10-20 keywords d'1 article OU paper |

## Fallback standalone

Si pour une raison quelconque le workflow ne tourne pas (offline, runtime indispo, version Claude Code < 2.1.154), `scripts/import.py infiles/` continue de fonctionner en mode standalone via `claude -p` — c'est le fallback historique. Le skill prend la main quand on est dans Claude Code v2.1.154+.
