# Curax — Agrégateur d'articles IA sur GitHub Pages

## Structure du projet

```
Curax/
├── index.html              # Page d'accueil dynamique (vanilla JS)
├── style.css               # Design system (dark mode, responsive grid)
├── manifest.json           # Index auto-généré par GitHub Action
├── articles/               # Articles organisés par domaine
│   ├── observations.md     # Observations transversales sur le corpus
│   └── {domaine}/
│       ├── manifest.json   # Métadonnées du domaine (name, description, icon, articles+scores)
│       └── *.html          # Articles HTML
├── scripts/
│   ├── extract-x-articles.py  # Script d'extraction des articles X/Twitter (legacy)
│   └── import-articles.py     # Pipeline d'import autonome (recommandé)
├── infiles/                # Dossier d'import (dans .gitignore)
│   └── mapping.json        # Mapping fichier → domaine/titre/description (pour extract-x-articles.py)
└── .github/
    ├── workflows/build-manifest.yml
    └── scripts/generate_manifest.py
```

## Pipeline

1. `generate_manifest.py` scanne `articles/` et produit `manifest.json`
2. GitHub Action exécute ce script à chaque push sur `articles/**`
3. `index.html` fetch `manifest.json` et affiche les articles par domaine avec scores de qualité et observations transversales

## Format des manifestes de domaine

Chaque `articles/{domaine}/manifest.json` contient :
```json
{
  "name": "Claude Code",
  "description": "...",
  "icon": "🛠️",
  "articles": {
    "guide-avance-skills-hooks-subagents.html": {
      "quality_score": 5,
      "quality_note": "Tutoriel technique — long format — avec code — 7 liens"
    }
  }
}
```

`quality_score` (1-5) : score de substance basé sur word_count, has_code, link_count, content_type.
`quality_note` : synthèse du type de contenu et métriques clés.

## Observations transversales

`articles/observations.md` contient un paragraphe d'analyse transversale du corpus, affiché en préambule de l'index. Ce fichier est régénéré automatiquement par `import-articles.py`.

## Format des articles X/Twitter (infiles/)

Les fichiers HTML sauvegardés depuis X/Twitter ont ces caractéristiques :
- `<title>` générique : "X Article - DD/MM/YYYY"
- Pas de `<meta name="description">`
- ~5000+ lignes de CSS inline dans `<style>` avant le contenu réel
- Auteur dans `data-testid="UserAvatar-Container-{handle}"`
- Texte principal dans `<span data-text="true">`
- 2 exceptions : 1 article Cloudflare (auteur dans `.author-name-tooltip`), 1 Substack

## 7 domaines

| Slug | Nom | Icône |
|------|-----|-------|
| `claude-code` | Claude Code | 🛠️ |
| `agents-ia` | Agents IA | 🤖 |
| `openclaw` | OpenClaw / Moltbot | 🐙 |
| `securite-ia` | Sécurité IA | 🔒 |
| `prompt-engineering` | Prompt Engineering | ✍️ |
| `business-ia` | Business & IA | 💰 |
| `vibe-coding` | Vibe Coding | 💡 |

## Auto-détection de domaine

`import-articles.py` détecte le domaine par mots-clés dans le contenu :
- `claude code|cowork|skills|hooks|subagent|CLAUDE.md` → `claude-code`
- `openclaw|moltbot|clawdbot|peter steinberger` → `openclaw`
- `security|vulnerab|hardening|firewall|sandbox` → `securite-ia`
- `agent|swarm|mcp|orchestrat|autonomous|ralph` → `agents-ia`
- `prompt|prompting|structured knowledge` → `prompt-engineering`
- `pricing|business|b2c|startup|revenue|founder` → `business-ia`
- `vibe cod|rebuild|mainstream|tools for` → `vibe-coding`
- Fallback → `agents-ia`

## Workflow d'ajout d'articles

### Méthode recommandée : import-articles.py (automatique)

1. Placer les HTML dans `infiles/`
2. `python3 scripts/import-articles.py infiles/` → analyse, dedup, auto-détection domaine, preview
3. Confirmer → import, injection métadonnées, mise à jour manifestes + observations
4. Commit & push

Avec `--yes` pour sauter la confirmation.

### Méthode manuelle : extract-x-articles.py

1. Placer les HTML dans `infiles/`
2. `python3 scripts/extract-x-articles.py --dedup infiles/` → détecter doublons
3. Remplir `infiles/mapping.json` (domain, slug, title, description)
4. `python3 scripts/extract-x-articles.py infiles/` → preview
5. `python3 scripts/extract-x-articles.py --apply infiles/` → import
6. `python3 .github/scripts/generate_manifest.py` → regénérer manifeste
7. Commit & push

## Détection de doublons

Les sauvegardes X/Twitter produisent parfois des fichiers en double (même contenu, noms différents).
Les deux scripts détectent les doublons par empreinte SHA-256 du contenu textuel :
- Pour les articles X/Twitter : hash des spans `data-text="true"`
- Pour les autres formats : hash du texte significatif après `</style>`
