# Curax

Index dynamique d'articles sur GitHub Pages. Ajoutez un fichier HTML dans `articles/`, poussez sur `main` — le site se met à jour automatiquement.

## Fonctionnement

1. Vous ajoutez un article `.html` dans `articles/`
2. Au push sur `main`, une GitHub Action génère un `manifest.json` listant tous les articles avec leurs métadonnées
3. La page `index.html` lit ce manifeste et affiche les articles groupés par domaine

Pas de framework, pas de dépendance externe — tout est en vanilla HTML/CSS/JS et Python stdlib.

## Structure du projet

```
├── index.html                          # Page d'accueil (vanilla JS, theming)
├── style.css                           # Design system (6 thèmes tweakcn, light/dark)
├── manifest.json                       # Généré automatiquement par l'Action
├── articles/
│   ├── observations.md                 # Analyse transversale du corpus
│   ├── {domaine}/
│   │   ├── manifest.json               # Métadonnées du domaine (name, icon, scores)
│   │   └── *.html                      # Articles HTML
│   └── article-orphelin.html           # Apparaît dans "Divers"
├── scripts/
│   ├── import-articles.py              # Pipeline d'import autonome (recommandé)
│   └── extract-x-articles.py           # Script d'extraction X/Twitter (legacy)
├── infiles/                            # Staging d'import temporaire (.gitignore)
└── .github/
    ├── workflows/build-manifest.yml
    └── scripts/generate_manifest.py
```

## Thèmes

Le site propose 6 thèmes visuels issus de [tweakcn.com](https://tweakcn.com), chacun avec une variante light et dark :

| Thème | Style |
|-------|-------|
| **Portfolio** (défaut) | Tons dorés, coins arrondis |
| **MX-Brutalist** | Vert vif, bords carrés, bordures noires |
| **Sage Green** | Vert sauge, coins très arrondis |
| **2077** | Monochrome / rouge cyberpunk |
| **AstroVista** | Orange spatial, bleu secondaire |
| **Offworld** | Minimaliste, jaune pâle en dark |

Le thème et le mode (light/dark) sont persistés dans `localStorage` (`curax-theme`, `curax-mode`). Un script inline dans le `<head>` applique le thème avant le chargement du CSS pour éviter le flash de contenu non stylé (FOUC).

Les variables CSS suivent la convention shadcn/ui (`--background`, `--foreground`, `--primary`, `--card`, `--border`, etc.).

## Setup GitHub Pages

1. Allez dans **Settings > Pages** du repo
2. Source : **Deploy from a branch**
3. Branche : `main`, dossier : `/ (root)`
4. Sauvegardez — le site sera accessible à `https://<user>.github.io/Curax/`

## Setup GitHub Action

L'Action est déjà configurée dans `.github/workflows/build-manifest.yml`. Elle nécessite les **permissions d'écriture** pour commiter le manifeste généré.

Vérifiez que le repo autorise les Actions à écrire :

1. Allez dans **Settings > Actions > General**
2. Section **Workflow permissions** : cochez **Read and write permissions**
3. Sauvegardez

L'Action se déclenche automatiquement à chaque push modifiant `articles/**`. Vous pouvez aussi la lancer manuellement depuis l'onglet **Actions > Build Manifest > Run workflow**.

## Ajouter un article

### Méthode recommandée : import-articles.py

1. Placez les fichiers HTML dans `infiles/`
2. Lancez `python3 scripts/import-articles.py infiles/` — analyse, déduplication, auto-détection du domaine, preview
3. Confirmez l'import (ou utilisez `--yes` pour sauter la confirmation)
4. **Videz `infiles/`** après l'import — c'est un dossier de staging temporaire, les originaux restent dans vos sauvegardes navigateur
5. Commit & push

Le script détecte automatiquement le domaine par mots-clés, attribue un score de qualité (1-5), et met à jour les manifestes de domaine ainsi que le fichier `articles/observations.md`.

### Méthode manuelle

Créez un fichier HTML dans un sous-dossier de `articles/` :

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Description qui apparaîtra sur l'index.">
  <title>Titre de l'article</title>
</head>
<body>
  <!-- Votre contenu -->
</body>
</html>
```

L'Action extrait automatiquement le `<title>` et la `<meta name="description">` pour alimenter l'index.

### Article non catégorisé

Placez le fichier HTML directement dans `articles/` (sans sous-dossier). Il apparaîtra dans la section "Divers".

## Configurer un domaine

Pour personnaliser l'affichage d'un domaine, ajoutez un `manifest.json` dans son dossier :

```json
{
  "name": "Nom affiché",
  "description": "Description du domaine",
  "icon": "🔬",
  "articles": {
    "mon-article.html": {
      "quality_score": 4,
      "quality_note": "Tutoriel technique — long format"
    }
  }
}
```

Les champs `name`, `description` et `icon` sont optionnels. Sans ce fichier, le nom du dossier est utilisé comme titre. Les scores de qualité sont générés automatiquement par `import-articles.py`.

## Développement local

Pour prévisualiser le site localement :

```bash
# Générer le manifeste
python3 .github/scripts/generate_manifest.py

# Servir les fichiers (Python 3)
python3 -m http.server 8000
```

Puis ouvrez `http://localhost:8000`.
