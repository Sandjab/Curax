# Recherche et filtrage — Design Spec

> Date : 2026-04-11 | Statut : Validé | Fichiers impactés : `index.html`, `style.css`

## Contexte

Curax affiche 261 articles (9 domaines) et 34 publications (6 domaines) sans aucun moyen de recherche ni filtrage. La navigation repose uniquement sur le parcours visuel des sections par domaine. Avec un corpus croissant, trouver un contenu précis devient fastidieux.

Cette spec ajoute une barre de recherche et des filtres à facettes pour permettre une exploration rapide du corpus.

## Décisions de design

| Décision | Choix | Justification |
|----------|-------|---------------|
| Périmètre de recherche | Métadonnées seules (titre, description, tags, domaine, auteurs) | Données déjà dans manifest.json, zéro infra supplémentaire |
| Filtres | Score minimum + domaine + tags | Couvre les cas d'usage principaux sans surcharger l'UI |
| Portée des filtres | Indépendant par onglet | Les taxonomies articles/papers sont différentes |
| Layout | Recherche visible + panneau filtres dépliable | Propre par défaut, puissant au besoin (option B) |
| Groupement résultats | Par domaine (domaines vides masqués) | Cohérent avec l'affichage actuel |
| Déclenchement recherche | Temps réel avec debounce 200ms | UX fluide, performant sur 300 items |
| Stratégie de rendu | Re-rendu filtré (pas show/hide CSS) | Propre, pas de DOM fantôme, prépare la pagination future |
| Persistance filtres | Non (reset au chargement) | Navigation ponctuelle, pas un état durable |

## HTML — Structure

Zone insérée entre `.tab-bar` et `.tab-content` dans `index.html` :

```
┌─────────────────────────────────────────────┐
│ .search-bar                                  │
│  ┌──────────────────────┐  ┌──────────────┐ │
│  │ 🔍 input text        │  │ ⚙ Filtres ▾  │ │
│  └──────────────────────┘  └──────────────┘ │
│                                              │
│ .filter-panel (collapsed par défaut)         │
│  ┌──────────────────────────────────────────┐│
│  │ Score min: [====○====] 5                 ││
│  │ Domaine:  [Tous ▾]                       ││
│  │ Tags:  [agents] [hooks] [mcp] [+]        ││
│  │                      [Réinitialiser]     ││
│  └──────────────────────────────────────────┘│
└─────────────────────────────────────────────┘
```

- Input placeholder dynamique par onglet ("Rechercher dans les articles..." / "...les publications")
- Panneau filtres animé en hauteur (`max-height` transition)
- Compteur de résultats affiché quand des filtres sont actifs ("12 résultats")
- Bouton "Réinitialiser" visible uniquement quand au moins un filtre est actif

## JavaScript — Logique

### Données

```js
window._manifest = manifest;  // stocké une fois, jamais muté
```

Correction au passage : le code actuel mute le manifest in-place (lignes 402-414, 462-474) pour séparer la corbeille. Remplacé par filtrage par prédicat.

### État des filtres

```js
window._filters = {
  articles:     { query: '', scoreMin: 0, domain: '', tags: [] },
  publications: { query: '', scoreMin: 0, domain: '', tags: [] }
}
```

### Fonction centrale `applyFilters(tabId)`

1. Lit `_filters[tabId]`
2. Parcourt les domaines du manifest pour cet onglet
3. Pour chaque item, applique les prédicats :
   - `query` : match insensible à la casse sur titre + description + tags + auteurs (papers)
   - `scoreMin` : `quality_score >= scoreMin`
   - `domain` : slug exact ('' = tous)
   - `tags` : l'item doit contenir AU MOINS un des tags sélectionnés (union)
4. Reconstruit le DOM : observations → sections domaines filtrées → corbeille
5. Masque les domaines sans résultat
6. Met à jour le compteur

### Debounce

Fonction utilitaire (~5 lignes), 200ms, sur `input` event.

### Event listeners

- `input` recherche → debounce → `applyFilters()`
- `input` slider score → `applyFilters()`
- `change` select domaine → `applyFilters()`
- `click` chip tag → toggle dans `_filters.tags[]` → `applyFilters()`
- `click` bouton filtres → toggle `.filter-panel.open`
- `click` réinitialiser → reset `_filters[tabId]` + reset UI → `applyFilters()`

### Interaction tabs

`switchTab()` appelle `applyFilters(newTabId)` pour restaurer les filtres de l'onglet cible. Peuple dynamiquement le select domaine et les chips tags depuis le manifest de l'onglet.

### Peuplement des filtres

- Select "Domaine" : peuplé depuis les domaines du manifest pour l'onglet actif
- Chips "Tags" : extraits de tous les items, dédoublonnés, triés par fréquence, top ~20 affichés

## CSS — Styles

Tous les styles s'appuient sur les variables CSS existantes (thème-compatible automatiquement) :

- **`.search-bar`** : flex, `max-width: 1400px`, centré, même padding que header/main
- **`#search-input`** : `var(--card)` bg, `var(--border)` border, `var(--radius)` radius, `var(--ring)` focus, `flex: 1`
- **`.filter-toggle`** : style secondaire (`var(--secondary)`), badge compteur en `var(--primary)` quand filtres actifs
- **`.filter-panel`** : `max-height: 0; overflow: hidden; transition: max-height 0.2s ease`. `.open` → `max-height: 200px`. Bg `var(--secondary)`, border, radius
- **Slider score** : `accent-color: var(--primary)`
- **Select domaine** : réutilise le pattern du select thème (`appearance: none` + SVG arrow)
- **Chips tags** : réutilise `.tag` existant. Sélectionné → `var(--primary)` bg + `var(--primary-foreground)` text. Non sélectionné → `var(--muted)` bg
- **Compteur résultats** : `0.8rem`, `var(--muted-foreground)`
- **Bouton réinitialiser** : `var(--muted-foreground)`, visible uniquement si filtre actif

### Responsive (max-width: 600px)

- `.search-bar` : `flex-wrap: wrap`, input 100% largeur, bouton filtres en dessous
- `.filter-panel` : éléments empilés verticalement

## Cas limites

- **Aucun résultat** : message "Aucun résultat pour « query »" + bouton "Réinitialiser les filtres"
- **Corbeille** : affichée en dernier, le filtre score s'y applique (scoreMin >= 5 la masque naturellement)
- **Onglet vide + filtres** : même pattern "aucun résultat"

## Fichiers modifiés

| Fichier | Modifications |
|---------|---------------|
| `index.html` | Ajout HTML recherche/filtres, refactoring JS (données en mémoire, applyFilters, debounce, event listeners, correction mutation manifest) |
| `style.css` | Ajout styles .search-bar, #search-input, .filter-toggle, .filter-panel, slider, chips, compteur, responsive |

Aucun nouveau fichier. Aucune modification de `themes.js`, `manifest.json`, catalogs, ou pipeline.

## Vérification

1. `python3 -m http.server` à la racine, ouvrir dans le navigateur
2. Frappe dans la barre → résultats filtrés en temps réel
3. Ouvrir filtres → slider score → domaines se masquent
4. Cliquer tag → combinaison recherche + tag + score
5. Switcher d'onglet → filtres indépendants conservés
6. Réinitialiser → retour à l'état initial
7. Changer de thème / dark mode → styles cohérents
8. Responsive 600px → layout correct
9. Vérifier que la corbeille disparaît avec scoreMin >= 5
10. Vérifier l'état "aucun résultat" avec une recherche impossible
