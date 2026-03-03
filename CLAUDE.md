# Curax — AI Article & Paper Aggregator on GitHub Pages

## Project structure

```
Curax/
├── index.html              # Dynamic homepage (vanilla JS, theming engine, tab bar)
├── style.css               # Design system (6 tweakcn themes, light/dark, responsive grid)
├── themes.js               # Shared theme definitions (CURAX_THEMES object)
├── manifest.json           # Auto-generated index by GitHub Action
├── articles/               # Articles organized by domain
│   ├── catalog.json        # Source of truth: domains, articles metadata, observations
│   └── {domain}/
│       └── *.html          # HTML articles
├── papers/                 # Scientific publications organized by domain
│   ├── catalog.json        # Source of truth: domains, papers metadata, observations
│   └── {domain}/
│       └── {slug}/
│           ├── {slug}.pdf           # Original PDF
│           ├── {slug}-lca.html      # Companion: Lecture Critique d'Article
│           └── {slug}-vulgarisation.html  # Companion: vulgarisation article
├── scripts/
│   └── import.py           # Autonomous import pipeline (HTML articles + PDF papers)
├── infiles/                # Temporary import staging area (in .gitignore)
└── .github/
    ├── workflows/build-manifest.yml
    └── scripts/generate_manifest.py
```

## Pipeline

1. `import.py` classifies articles/papers via Claude CLI and maintains `articles/catalog.json` and `papers/catalog.json`
2. `generate_manifest.py` reads both catalogs and produces `manifest.json` (with `papers` key)
3. GitHub Action runs `generate_manifest.py` on every push to `articles/**` or `papers/**`
4. `index.html` fetches `manifest.json` and displays articles + publications in separate tabs

## Theming system

6 themes from [tweakcn.com](https://tweakcn.com): **portfolio** (default), **mx-brutalist**, **sage-green**, **2077**, **astrovista**, **offworld**.

Each theme has light + dark variants defined in the `CURAX_THEMES` object in `themes.js`. `index.html` aliases it as `THEMES = CURAX_THEMES`. Companion documents load `themes.js` via relative path for theme inheritance.

### CSS variables

Follow shadcn/ui convention: `--background`, `--foreground`, `--card`, `--card-foreground`, `--primary`, `--primary-foreground`, `--primary-hover`, `--secondary`, `--muted`, `--muted-foreground`, `--accent`, `--border`, `--input`, `--ring`, `--radius`.

`:root` defaults in `style.css` correspond to Portfolio light theme.

### Link contrast variables

`--link` / `--link-hover`: dedicated variables for article title links, used only in themes where `--primary` has insufficient contrast against the background (Portfolio, Sage Green). CSS uses `var(--link, var(--primary))` fallback pattern — themes without `--link` fall back to `--primary` automatically.

### Anti-FOUC

Inline `<script>` in `<head>` (before CSS `<link>`) reads `localStorage` and sets `data-mode` / `data-theme` attributes on `<html>` immediately. This prevents a flash of unstyled content on page load.

### Theme switching

`applyTheme(themeId, mode)` must call `root.style.cssText = ''` before setting new properties. This resets inline styles from the previous theme and prevents stale variables from leaking across theme changes.

Theme and mode persisted in `localStorage` keys: `curax-theme`, `curax-mode`.

### Dark mode

Dark mode is JS-driven via `data-mode="dark"` attribute. No `@media (prefers-color-scheme)` queries are used.

Dark mode quality badges use `[data-mode="dark"]` selector, not media query.

## CSS architecture

- Shadows use `color-mix(in srgb, var(--foreground) N%, transparent)` for theme-adaptive opacity
- Spacing tokens: `--space-xs` through `--space-xl`
- Responsive breakpoint at 600px (single-column layout on mobile)

## UI — Tab navigation

Two tabs: "Articles" and "Publications", controlled by pill buttons in `.tab-bar`. Active tab stored in `localStorage` key `curax-tab`. Subtitle updates dynamically per tab.

## Catalog format — Articles (source of truth)

`articles/catalog.json` is the single source of truth for all article metadata:
```json
{
  "domains": {
    "claude-code": {"name": "Claude Code", "description": "...", "icon": "🛠️"}
  },
  "articles": {
    "articles/claude-code/guide.html": {
      "domain": "claude-code",
      "tags": ["skills", "hooks", "subagents"],
      "quality_score": 9,
      "quality_note": "Tutoriel technique approfondi..."
    }
  },
  "observations": "Analyse du corpus..."
}
```

`quality_score` (1-10): semantic quality score assigned by Claude CLI.
- 1-2: Empty/promotional content
- 3-4: Superficial, few actionable insights
- 5-6: Decent, some insights but lacks depth
- 7-8: Good content, actionable, code examples or useful links
- 9-10: Excellent, deep tutorial, concrete code, rich resources

`quality_note`: synthetic content description (1 sentence, assigned by Claude).

`tags`: 1-3 free-form tags in kebab-case per article, assigned by Claude.

`observations`: cross-cutting corpus analysis paragraph, generated by Claude.

## Catalog format — Papers (source of truth)

`papers/catalog.json` is the source of truth for all publication metadata:
```json
{
  "domains": {
    "recherche-ia": {"name": "Recherche IA", "description": "...", "icon": "🔬"}
  },
  "papers": {
    "papers/recherche-ia/attention-is-all-you-need/attention-is-all-you-need.pdf": {
      "domain": "recherche-ia",
      "title": "Attention Is All You Need",
      "description": "Article fondateur des Transformers...",
      "tags": ["transformers", "attention"],
      "quality_score": 10,
      "quality_note": "Article fondateur...",
      "authors": ["Vaswani, A.", "Shazeer, N."],
      "year": 2017,
      "journal": "NeurIPS",
      "doi": "10.48550/arXiv.1706.03762",
      "robustness_score": 5.0,
      "vulgarisation_file": "papers/recherche-ia/attention-is-all-you-need/attention-is-all-you-need-vulgarisation.html",
      "lca_file": "papers/recherche-ia/attention-is-all-you-need/attention-is-all-you-need-lca.html"
    }
  },
  "observations": "..."
}
```

`quality_score` for papers: derived from LCA robustness global note /5, mapped to /10 via `min(round(robustness_global * 2), 10)`.

`robustness_score`: Claude's independent global assessment of the publication (0-5), based on 8 criteria (question_recherche, design_experimental, taille_echantillon, qualite_metriques, controle_biais, reproductibilite, transparence_limitations, impact_nouveaute).

## Manifest structure

`manifest.json` contains both articles and papers:
```json
{
  "generated": "...",
  "domains": [...],           // article domains (existing)
  "uncategorized": [...],
  "observations": "...",      // article observations
  "papers": {                 // added by generate_manifest.py if papers/catalog.json exists
    "domains": [
      {
        "slug": "recherche-ia", "name": "...", "icon": "...",
        "papers": [
          { "file": "...", "title": "...", "description": "...", "date": "...",
            "quality_score": 10, "quality_note": "...", "tags": [...],
            "authors": [...], "year": 2017, "journal": "...", "doi": "...",
            "robustness_score": 5.0, "vulgarisation_file": "...", "lca_file": "..." }
        ]
      }
    ],
    "observations": "..."
  }
}
```

## X/Twitter article format (infiles/)

HTML files saved from X/Twitter have these characteristics:
- Generic `<title>`: "X Article - DD/MM/YYYY"
- No `<meta name="description">`
- ~5000+ lines of inline CSS in `<style>` before actual content
- Author in `data-testid="UserAvatar-Container-{handle}"`
- Main text in `<span data-text="true">`
- 2 exceptions: 1 Cloudflare article (author in `.author-name-tooltip`), 1 Substack

## Domains

Domains are managed dynamically in `catalog.json` (articles) and `papers/catalog.json` (publications). They have separate taxonomies — article domains are editorial categories, paper domains are research axes.

## Classification IA via Claude CLI

`import.py` uses `claude -p` (CLI) for semantic classification:

### Articles
1. **Taxonomy call** (1 per import): receives corpus summary + new article previews, produces optimal domain taxonomy and cross-cutting observations
2. **Per-article call** (1 per article, parallelized with 3 workers by default): receives extracted text + taxonomy, produces domain, tags (1-3), quality_score (1-10), quality_note, title, description

### Papers (PDF)
1. **Taxonomy call** (1 per import): oriented towards research axes
2. **Per-paper LCA call** (1 per paper): produces domain, tags, title, description, quality_note, authors, year, journal, DOI, 8 robustness scores, global robustness note, and full LCA HTML document
3. **Per-paper vulgarisation call** (1 per paper, after LCA): produces ~2000 word vulgarisation article in French

LCA and vulgarisation calls are sequential per paper (vulgarisation needs LCA metadata), but parallel cross-papers.

No hardcoded domain rules — Claude Opus decides classification based on content semantics. The `--json-schema` flag enforces structured output. Retry with exponential backoff on failure (max 2 retries).

File slugs are derived from the Claude-generated title (not raw text). During `--reclassify` / `--reclassify-papers`, files are renamed if the new title-based slug differs from the current filename.

Environment variable `CLAUDECODE` is unset in subprocess to avoid nested session detection.

## Import workflow

### Article import (HTML)

1. Place HTML files in `infiles/`
2. `python3 scripts/import.py infiles/` → dedup, Claude Opus taxonomy + scoring, preview
3. Confirm → import, metadata injection, catalog.json + manifest.json update
4. **Clean up `infiles/` after import**
5. Commit & push

### Paper import (PDF)

1. Place PDF files in `infiles/` (requires `pip install pdfplumber`)
2. `python3 scripts/import.py infiles/` → text extraction, dedup (fingerprint + DOI), taxonomy, LCA + vulgarisation
3. Confirm → import to `papers/{domain}/{slug}/` (PDF + 2 companion HTML), papers/catalog.json + manifest.json update
4. **Clean up `infiles/` after import**
5. Commit & push

### Mixed import

If `infiles/` contains both HTML and PDF, both pipelines run sequentially (articles first, then papers).

### Flags

- `--yes` : skip confirmation
- `--reclassify` : reclassify ALL existing articles (new taxonomy, new scores, new tags, file renames)
- `--reclassify-papers` : reclassify publications (domain, tags, quality_note updated; quality_score frozen, companions not regenerated)
- `--workers N` : number of parallel scoring workers (default: 3)

## Companion documents (LCA + Vulgarisation)

Standalone HTML files in each paper's subfolder. They:
- Load `themes.js` via `<script src="../../../themes.js">` for theme inheritance (3 levels up: slug → domain → papers → root)
- Have inline CSS with fallback to Portfolio light theme variables
- Include anti-FOUC script reading localStorage
- Apply active theme via JS after load
- Feature a "Retour a Curax" link to `../../../index.html`
- Are responsive at 600px breakpoint

## Duplicate detection

### Articles
`import.py` detects duplicates via SHA-256 hash of textual content:
- For X/Twitter articles: hash of `data-text="true"` spans
- For other formats: hash of significant text after `</style>`

### Papers
Duplicate detection via:
- SHA-256 hash of extracted PDF text (cleaned, minimum 100 chars)
- DOI matching against existing catalog

## infiles/ workflow

- Temporary import staging area, listed in `.gitignore`
- Clean up all files after import (they are copies, originals stay in browser saves)

## GitHub Pages deploy

- CDN cache TTL ~5 minutes — new deploys may not be visible immediately
- Hard reload (Cmd+Shift+R) bypasses browser cache but not CDN
- `gh run list --limit 3` to check deploy status
