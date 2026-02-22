# Curax

Index dynamique d'articles sur GitHub Pages. Ajoutez un fichier HTML dans `articles/`, poussez sur `main` — le site se met à jour automatiquement.

## Fonctionnement

1. Vous ajoutez un article `.html` dans `articles/`
2. Au push sur `main`, une GitHub Action génère un `manifest.json` listant tous les articles avec leurs métadonnées
3. La page `index.html` lit ce manifeste et affiche les articles groupés par domaine

Pas de framework, pas de dépendance externe — tout est en vanilla HTML/CSS/JS et Python stdlib.

## Structure du projet

```
├── index.html                          # Page d'accueil
├── style.css                           # Styles (dark mode, responsive)
├── manifest.json                       # Généré automatiquement par l'Action
├── articles/
│   ├── mon-domaine/
│   │   ├── manifest.json               # Métadonnées du domaine (optionnel)
│   │   ├── article-un.html
│   │   └── article-deux.html
│   └── article-orphelin.html           # Apparaît dans "Divers"
└── .github/
    ├── workflows/build-manifest.yml
    └── scripts/generate_manifest.py
```

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

### Article dans un domaine

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
  "icon": "🔬"
}
```

Les trois champs sont optionnels. Sans ce fichier, le nom du dossier est utilisé comme titre.

## Développement local

Pour prévisualiser le site localement :

```bash
# Générer le manifeste
python3 .github/scripts/generate_manifest.py

# Servir les fichiers (Python 3)
python3 -m http.server 8000
```

Puis ouvrez `http://localhost:8000`.
