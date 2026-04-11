# Search and Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a search bar and collapsible filter panel (score, domain, tags) to Curax, enabling real-time filtering of articles and publications by metadata.

**Architecture:** All filtering is client-side against data already in `manifest.json`. A `window._manifest` stores the raw data (never mutated). An `applyFilters(tabId)` function re-renders the active tab's content by applying filter predicates. Filter state is per-tab, not persisted to localStorage.

**Tech Stack:** Vanilla HTML/CSS/JS (no new dependencies). CSS variables for theme compatibility.

**Spec:** `docs/superpowers/specs/2026-04-11-search-and-filtering-design.md`

---

### Task 1: Add search and filter HTML structure

**Files:**
- Modify: `index.html:49-51` (insert between tab-bar and main)

- [ ] **Step 1: Add search bar and filter panel HTML**

Insert after the closing `</nav>` of `.tab-bar` (line 49) and before `<main>` (line 51):

```html
<div class="search-bar">
  <div class="search-bar-content">
    <input type="text" id="search-input" placeholder="Rechercher dans les articles..." aria-label="Rechercher">
    <button type="button" id="filter-toggle" class="filter-toggle" aria-expanded="false" aria-controls="filter-panel">
      <span class="filter-toggle-icon">&#9881;</span> Filtres
      <span id="filter-count" class="filter-count" style="display:none"></span>
    </button>
    <span id="results-count" class="results-count" style="display:none"></span>
  </div>
  <div id="filter-panel" class="filter-panel" aria-hidden="true">
    <div class="filter-panel-content">
      <div class="filter-group">
        <label for="filter-score">Score min :</label>
        <input type="range" id="filter-score" min="0" max="10" value="0" step="1">
        <span id="filter-score-value">0</span>
      </div>
      <div class="filter-group">
        <label for="filter-domain">Domaine :</label>
        <select id="filter-domain" aria-label="Filtrer par domaine">
          <option value="">Tous</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Tags :</label>
        <div id="filter-tags" class="filter-tags"></div>
      </div>
      <button type="button" id="filter-reset" class="filter-reset" style="display:none">Réinitialiser</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Verify HTML renders**

Run: `cd /Users/jean-paulgavini/Documents/Dev/Curax && python3 -m http.server 8080`

Open `http://localhost:8080`. The search input and "Filtres" button should appear between the tabs and content. The filter panel should be hidden. No JS wired yet — just verify the HTML is visible.

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: add search bar and filter panel HTML structure"
```

---

### Task 2: Add CSS styles for search and filter components

**Files:**
- Modify: `style.css:403` (insert before the `@media` rule on line 404)

- [ ] **Step 1: Add search bar styles**

Insert before `@media (max-width: 600px)` (line 404) in `style.css`:

```css
/* Search and filter bar */
.search-bar {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 var(--space-md);
}

.search-bar-content {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) 0;
}

#search-input {
  flex: 1;
  min-width: 0;
  padding: 0.5rem 0.75rem;
  background-color: var(--card);
  color: var(--foreground);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: inherit;
  font-size: 0.9rem;
}

#search-input::placeholder {
  color: var(--muted-foreground);
}

#search-input:focus {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}

.filter-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.5rem 0.75rem;
  background-color: var(--secondary);
  color: var(--foreground);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: inherit;
  font-size: 0.85rem;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.15s ease;
}

.filter-toggle:hover {
  background-color: var(--muted);
}

.filter-toggle[aria-expanded="true"] {
  background-color: var(--primary);
  color: var(--primary-foreground);
  border-color: var(--primary);
}

.filter-toggle-icon {
  font-size: 0.9rem;
}

.filter-count {
  font-size: 0.7rem;
  font-weight: 700;
  background-color: var(--primary);
  color: var(--primary-foreground);
  padding: 0.1em 0.45em;
  border-radius: 9999px;
  margin-left: 0.2rem;
}

.filter-toggle[aria-expanded="true"] .filter-count {
  background-color: var(--primary-foreground);
  color: var(--primary);
}

.results-count {
  font-size: 0.8rem;
  color: var(--muted-foreground);
  white-space: nowrap;
}

/* Filter panel (collapsible) */
.filter-panel {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.2s ease;
}

.filter-panel.open {
  max-height: 200px;
}

.filter-panel-content {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm) var(--space-md);
  padding: var(--space-sm) var(--space-md);
  background-color: var(--secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: var(--space-sm);
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
}

.filter-group label {
  font-weight: 600;
  white-space: nowrap;
}

#filter-score {
  width: 100px;
  accent-color: var(--primary);
}

#filter-score-value {
  font-weight: 600;
  min-width: 1.5em;
  text-align: center;
}

#filter-domain {
  appearance: none;
  background-color: var(--card);
  color: var(--foreground);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.25rem 1.8rem 0.25rem 0.5rem;
  font-size: 0.85rem;
  font-family: inherit;
  cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23666' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.4rem center;
}

/* Tag chips in filter */
.filter-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

.filter-tag {
  font-size: 0.7rem;
  padding: 0.15em 0.55em;
  border-radius: 9999px;
  background-color: var(--muted);
  color: var(--muted-foreground);
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
  border: none;
  font-family: inherit;
}

.filter-tag:hover {
  background-color: var(--border);
}

.filter-tag.active {
  background-color: var(--primary);
  color: var(--primary-foreground);
}

.filter-reset {
  background: none;
  border: none;
  color: var(--muted-foreground);
  font-size: 0.8rem;
  font-family: inherit;
  cursor: pointer;
  text-decoration: underline;
  padding: 0.2rem 0;
  margin-left: auto;
}

.filter-reset:hover {
  color: var(--foreground);
}

/* No results message */
.no-results {
  text-align: center;
  padding: var(--space-xl) var(--space-md);
  color: var(--muted-foreground);
}

.no-results p {
  font-size: 1rem;
  margin-bottom: var(--space-sm);
}

.no-results button {
  background-color: var(--secondary);
  color: var(--foreground);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.4rem 1rem;
  font-family: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}

.no-results button:hover {
  background-color: var(--muted);
}
```

- [ ] **Step 2: Add responsive styles for search/filter**

Add inside the existing `@media (max-width: 600px)` block (after the last rule before the closing `}`):

```css
  .search-bar-content {
    flex-wrap: wrap;
  }

  #search-input {
    width: 100%;
    flex: none;
  }

  .filter-toggle {
    flex: 1;
  }

  .results-count {
    width: 100%;
    text-align: center;
  }

  .filter-panel.open {
    max-height: 320px;
  }

  .filter-panel-content {
    flex-direction: column;
    align-items: flex-start;
  }

  .filter-reset {
    margin-left: 0;
  }
```

- [ ] **Step 3: Verify styles in browser**

Reload `http://localhost:8080`. The search bar should be styled with theme colors. Toggle dark mode — colors should adapt. Resize to 600px — layout should stack vertically.

- [ ] **Step 4: Commit**

```bash
git add style.css
git commit -m "feat: add CSS styles for search bar and filter panel"
```

---

### Task 3: Refactor data layer — stop mutating manifest

**Files:**
- Modify: `index.html:397-521` (JS section)

This task stores the manifest in `window._manifest` and removes the in-place mutation that splices trash articles/papers. Instead, rendering functions receive the full data and filter trash at render time.

- [ ] **Step 1: Store manifest globally and refactor renderArticlesTab**

In `index.html`, replace the `renderArticlesTab` function (lines 397-447) with:

```javascript
    // ── Render articles tab ──
    function renderArticlesTab(manifest, container, filterFn) {
      var domains = manifest.domains || [];
      var uncategorized = manifest.uncategorized || [];

      // Separate main vs trash via predicate (no mutation)
      var mainDomains = [];
      var trashArticles = [];
      for (var i = 0; i < domains.length; i++) {
        var kept = [];
        var articles = domains[i].articles || [];
        for (var j = 0; j < articles.length; j++) {
          var art = articles[j];
          if (art.quality_score && art.quality_score <= 4) {
            trashArticles.push(art);
          } else {
            kept.push(art);
          }
        }
        if (kept.length > 0) {
          mainDomains.push({ slug: domains[i].slug, name: domains[i].name, description: domains[i].description, icon: domains[i].icon, articles: kept });
        }
      }

      // Apply filter if provided
      if (filterFn) {
        var filteredDomains = [];
        for (var i = 0; i < mainDomains.length; i++) {
          var filtered = mainDomains[i].articles.filter(filterFn);
          if (filtered.length > 0) {
            filteredDomains.push({ slug: mainDomains[i].slug, name: mainDomains[i].name, description: mainDomains[i].description, icon: mainDomains[i].icon, articles: filtered });
          }
        }
        mainDomains = filteredDomains;
        uncategorized = uncategorized.filter(filterFn);
        trashArticles = trashArticles.filter(filterFn);
      }

      var totalArticles = mainDomains.reduce(function(sum, d) { return sum + d.articles.length; }, 0) + uncategorized.length + trashArticles.length;
      var totalDomains = mainDomains.length;
      window._articlesSubtitle = totalArticles + ' articles / ' + totalDomains + ' catégories';

      container.innerHTML = "";

      if (totalArticles === 0 && filterFn) {
        container.appendChild(buildNoResults());
        return;
      }

      if (totalArticles === 0) {
        container.innerHTML = '<div class="welcome-message"><p>Aucun article pour le moment.</p></div>';
        return;
      }

      if (manifest.observations && !filterFn) {
        container.appendChild(buildObservationsBox(manifest.observations));
      }

      for (var i = 0; i < mainDomains.length; i++) {
        container.appendChild(buildDomainSection(mainDomains[i], buildArticleCard));
      }

      if (uncategorized.length > 0) {
        container.appendChild(buildDomainSection({
          name: "Divers", description: "Articles non catégorisés", icon: "📂", articles: uncategorized
        }, buildArticleCard));
      }

      if (trashArticles.length > 0) {
        container.appendChild(buildDomainSection({
          name: "Poubelle", description: "Articles de faible qualité (score ≤ 4/10)", icon: "🗑️", articles: trashArticles
        }, buildArticleCard));
      }
    }
```

- [ ] **Step 2: Refactor renderPublicationsTab the same way**

Replace `renderPublicationsTab` (lines 450-494) with:

```javascript
    // ── Render publications tab ──
    function renderPublicationsTab(manifest, container, filterFn) {
      container.innerHTML = "";

      if (!manifest.papers || !manifest.papers.domains || manifest.papers.domains.length === 0) {
        window._publicationsSubtitle = '0 publications';
        container.innerHTML = '<div class="welcome-message"><p>Aucune publication pour le moment.</p><p>Placez des fichiers PDF dans <code>infiles/</code> et lancez <code>python scripts/import.py infiles/</code></p></div>';
        return;
      }

      var paperDomains = manifest.papers.domains;

      // Separate main vs trash (no mutation)
      var mainDomains = [];
      var trashPapers = [];
      for (var i = 0; i < paperDomains.length; i++) {
        var kept = [];
        var papers = paperDomains[i].papers || [];
        for (var j = 0; j < papers.length; j++) {
          if (papers[j].quality_score && papers[j].quality_score <= 4) {
            trashPapers.push(papers[j]);
          } else {
            kept.push(papers[j]);
          }
        }
        if (kept.length > 0) {
          mainDomains.push({ slug: paperDomains[i].slug, name: paperDomains[i].name, description: paperDomains[i].description, icon: paperDomains[i].icon, papers: kept });
        }
      }

      // Apply filter if provided
      if (filterFn) {
        var filteredDomains = [];
        for (var i = 0; i < mainDomains.length; i++) {
          var filtered = mainDomains[i].papers.filter(filterFn);
          if (filtered.length > 0) {
            filteredDomains.push({ slug: mainDomains[i].slug, name: mainDomains[i].name, description: mainDomains[i].description, icon: mainDomains[i].icon, papers: filtered });
          }
        }
        mainDomains = filteredDomains;
        trashPapers = trashPapers.filter(filterFn);
      }

      var totalPapers = mainDomains.reduce(function(sum, d) { return sum + d.papers.length; }, 0) + trashPapers.length;
      var totalDomains = mainDomains.length;
      window._publicationsSubtitle = totalPapers + ' publications / ' + totalDomains + ' axes';

      if (totalPapers === 0 && filterFn) {
        container.appendChild(buildNoResults());
        return;
      }

      if (manifest.papers.observations && !filterFn) {
        container.appendChild(buildObservationsBox(manifest.papers.observations));
      }

      for (var i = 0; i < mainDomains.length; i++) {
        container.appendChild(buildDomainSection(mainDomains[i], buildPaperCard));
      }

      if (trashPapers.length > 0) {
        container.appendChild(buildDomainSection({
          name: "Poubelle", description: "Publications de faible qualité (score ≤ 4/10)", icon: "🗑️", papers: trashPapers
        }, buildPaperCard));
      }
    }
```

- [ ] **Step 3: Add buildNoResults helper**

Insert right after `buildObservationsBox` (after line 175):

```javascript
    function buildNoResults() {
      var div = document.createElement("div");
      div.className = "no-results";
      var p = document.createElement("p");
      var query = window._filters ? window._filters[currentTab].query : '';
      p.textContent = query ? 'Aucun résultat pour « ' + query + ' »' : 'Aucun résultat avec ces filtres';
      div.appendChild(p);
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Réinitialiser les filtres";
      btn.addEventListener("click", function() { resetFilters(); });
      div.appendChild(btn);
      return div;
    }
```

- [ ] **Step 4: Update main app to store manifest globally**

Replace the main app IIFE (lines 497-521) with:

```javascript
    // ── Main app ──
    (async function () {
      try {
        var response = await fetch("manifest.json");
        if (!response.ok) throw new Error("Manifeste introuvable");

        window._manifest = await response.json();
        var articlesContainer = document.getElementById("tab-articles");
        var publicationsContainer = document.getElementById("tab-publications");

        renderArticlesTab(window._manifest, articlesContainer, null);
        renderPublicationsTab(window._manifest, publicationsContainer, null);

        // Init filters UI
        initFilters();

        // Apply initial tab
        switchTab(currentTab);
      } catch (e) {
        document.getElementById("tab-articles").innerHTML =
          '<div class="welcome-message">' +
          "<p>Bienvenue sur Curax.</p>" +
          "<p>Ajoutez des articles dans le dossier <code>articles/</code> et poussez sur <code>main</code> pour les voir apparaître ici.</p>" +
          "</div>";
        window._articlesSubtitle = '';
        window._publicationsSubtitle = '';
        switchTab('articles');
      }
    })();
```

- [ ] **Step 5: Verify no regression**

Reload `http://localhost:8080`. Articles and publications should render exactly as before — same grouping, same trash section, same counts in subtitle. The manifest is no longer mutated.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "refactor: store manifest globally, stop mutating data in render functions"
```

---

### Task 4: Implement filter state, debounce, and applyFilters

**Files:**
- Modify: `index.html` (JS section, insert after tab switching code ~line 154)

- [ ] **Step 1: Add filter state and utility functions**

Insert after the `switchTab` event listeners block (after line 154, before `// ── Shared helpers ──`):

```javascript
    // ── Search & filter state ──
    window._filters = {
      articles:     { query: '', scoreMin: 0, domain: '', tags: [] },
      publications: { query: '', scoreMin: 0, domain: '', tags: [] }
    };

    function debounce(fn, delay) {
      var timer;
      return function() {
        clearTimeout(timer);
        timer = setTimeout(fn, delay);
      };
    }

    function collectAllTags(tabId) {
      var tags = {};
      var items = [];
      if (tabId === 'articles') {
        var domains = (window._manifest && window._manifest.domains) || [];
        for (var i = 0; i < domains.length; i++) {
          items = items.concat(domains[i].articles || []);
        }
        items = items.concat((window._manifest && window._manifest.uncategorized) || []);
      } else {
        var pDomains = (window._manifest && window._manifest.papers && window._manifest.papers.domains) || [];
        for (var i = 0; i < pDomains.length; i++) {
          items = items.concat(pDomains[i].papers || []);
        }
      }
      for (var i = 0; i < items.length; i++) {
        var t = items[i].tags || [];
        for (var j = 0; j < t.length; j++) {
          tags[t[j]] = (tags[t[j]] || 0) + 1;
        }
      }
      // Sort by frequency desc, return top 20
      return Object.keys(tags).sort(function(a, b) { return tags[b] - tags[a]; }).slice(0, 20);
    }

    function collectDomains(tabId) {
      if (tabId === 'articles') {
        return (window._manifest && window._manifest.domains) || [];
      }
      return (window._manifest && window._manifest.papers && window._manifest.papers.domains) || [];
    }

    function buildFilterPredicate(f) {
      return function(item) {
        // Score filter
        if (f.scoreMin > 0 && (!item.quality_score || item.quality_score < f.scoreMin)) return false;
        // Domain filter
        if (f.domain && item._domainSlug !== f.domain) return false;
        // Tag filter (union — item must have at least one selected tag)
        if (f.tags.length > 0) {
          var itemTags = item.tags || [];
          var match = false;
          for (var i = 0; i < f.tags.length; i++) {
            if (itemTags.indexOf(f.tags[i]) !== -1) { match = true; break; }
          }
          if (!match) return false;
        }
        // Text query
        if (f.query) {
          var q = f.query.toLowerCase();
          var haystack = (item.title || '') + ' ' + (item.description || '') + ' ' + (item.tags || []).join(' ') + ' ' + ((item.authors || []).join(' '));
          if (haystack.toLowerCase().indexOf(q) === -1) return false;
        }
        return true;
      };
    }

    function hasActiveFilters(f) {
      return f.query !== '' || f.scoreMin > 0 || f.domain !== '' || f.tags.length > 0;
    }

    function populateFilterUI(tabId) {
      // Populate domain select
      var domainSelect = document.getElementById('filter-domain');
      var domains = collectDomains(tabId);
      domainSelect.innerHTML = '<option value="">Tous</option>';
      for (var i = 0; i < domains.length; i++) {
        var opt = document.createElement('option');
        opt.value = domains[i].slug;
        opt.textContent = (domains[i].icon || '') + ' ' + (domains[i].name || domains[i].slug);
        domainSelect.appendChild(opt);
      }

      // Populate tag chips
      var tagsContainer = document.getElementById('filter-tags');
      var allTags = collectAllTags(tabId);
      tagsContainer.innerHTML = '';
      for (var i = 0; i < allTags.length; i++) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'filter-tag';
        chip.textContent = allTags[i];
        chip.setAttribute('data-tag', allTags[i]);
        chip.addEventListener('click', (function(tag) {
          return function() { toggleTag(tag); };
        })(allTags[i]));
        tagsContainer.appendChild(chip);
      }

      // Update placeholder
      var searchInput = document.getElementById('search-input');
      searchInput.placeholder = tabId === 'articles' ? 'Rechercher dans les articles...' : 'Rechercher dans les publications...';

      // Restore filter state to UI
      var f = window._filters[tabId];
      searchInput.value = f.query;
      document.getElementById('filter-score').value = f.scoreMin;
      document.getElementById('filter-score-value').textContent = f.scoreMin;
      domainSelect.value = f.domain;
      var tagChips = tagsContainer.querySelectorAll('.filter-tag');
      tagChips.forEach(function(c) {
        c.classList.toggle('active', f.tags.indexOf(c.getAttribute('data-tag')) !== -1);
      });

      updateFilterBadges(tabId);
    }

    function updateFilterBadges(tabId) {
      var f = window._filters[tabId];
      var active = hasActiveFilters(f);
      var countBadge = document.getElementById('filter-count');
      var resetBtn = document.getElementById('filter-reset');
      if (active) {
        var n = (f.query ? 1 : 0) + (f.scoreMin > 0 ? 1 : 0) + (f.domain ? 1 : 0) + f.tags.length;
        countBadge.textContent = n;
        countBadge.style.display = '';
        resetBtn.style.display = '';
      } else {
        countBadge.style.display = 'none';
        resetBtn.style.display = 'none';
      }
    }

    function applyFilters() {
      var tabId = currentTab;
      var f = window._filters[tabId];
      var filterFn = hasActiveFilters(f) ? buildFilterPredicate(f) : null;

      // Tag items with their domain slug for domain filtering
      if (window._manifest) {
        var domains = tabId === 'articles' ? (window._manifest.domains || []) : ((window._manifest.papers && window._manifest.papers.domains) || []);
        for (var i = 0; i < domains.length; i++) {
          var items = domains[i].articles || domains[i].papers || [];
          for (var j = 0; j < items.length; j++) {
            items[j]._domainSlug = domains[i].slug;
          }
        }
      }

      var container = document.getElementById('tab-' + tabId);
      if (tabId === 'articles') {
        renderArticlesTab(window._manifest, container, filterFn);
      } else {
        renderPublicationsTab(window._manifest, container, filterFn);
      }

      // Update results count
      var resultsEl = document.getElementById('results-count');
      if (filterFn) {
        var sub = tabId === 'articles' ? window._articlesSubtitle : window._publicationsSubtitle;
        resultsEl.textContent = sub;
        resultsEl.style.display = '';
      } else {
        resultsEl.style.display = 'none';
      }

      updateSubtitle(tabId);
      updateFilterBadges(tabId);
    }

    function toggleTag(tag) {
      var f = window._filters[currentTab];
      var idx = f.tags.indexOf(tag);
      if (idx === -1) f.tags.push(tag);
      else f.tags.splice(idx, 1);
      // Update chip UI
      var chips = document.getElementById('filter-tags').querySelectorAll('.filter-tag');
      chips.forEach(function(c) {
        c.classList.toggle('active', f.tags.indexOf(c.getAttribute('data-tag')) !== -1);
      });
      applyFilters();
    }

    function resetFilters() {
      var f = window._filters[currentTab];
      f.query = '';
      f.scoreMin = 0;
      f.domain = '';
      f.tags = [];
      populateFilterUI(currentTab);
      applyFilters();
    }
```

- [ ] **Step 2: Verify no JS errors**

Reload `http://localhost:8080`. Open browser console. There should be no errors. The `initFilters` function is called in main but not yet defined — add a stub at the end of step 3 (next task).

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: add filter state, debounce, applyFilters and helper functions"
```

---

### Task 5: Wire up event listeners and initFilters

**Files:**
- Modify: `index.html` (JS section)

- [ ] **Step 1: Add initFilters function and event bindings**

Insert right after the `resetFilters` function (before `// ── Shared helpers ──`):

```javascript
    function initFilters() {
      var searchInput = document.getElementById('search-input');
      var filterToggle = document.getElementById('filter-toggle');
      var filterPanel = document.getElementById('filter-panel');
      var scoreSlider = document.getElementById('filter-score');
      var scoreValue = document.getElementById('filter-score-value');
      var domainSelect = document.getElementById('filter-domain');
      var resetBtn = document.getElementById('filter-reset');

      // Search input with debounce
      var debouncedApply = debounce(applyFilters, 200);
      searchInput.addEventListener('input', function() {
        window._filters[currentTab].query = this.value;
        debouncedApply();
      });

      // Filter toggle
      filterToggle.addEventListener('click', function() {
        var isOpen = filterPanel.classList.toggle('open');
        filterToggle.setAttribute('aria-expanded', isOpen);
        filterPanel.setAttribute('aria-hidden', !isOpen);
      });

      // Score slider
      scoreSlider.addEventListener('input', function() {
        scoreValue.textContent = this.value;
        window._filters[currentTab].scoreMin = parseInt(this.value, 10);
        applyFilters();
      });

      // Domain select
      domainSelect.addEventListener('change', function() {
        window._filters[currentTab].domain = this.value;
        applyFilters();
      });

      // Reset
      resetBtn.addEventListener('click', function() {
        resetFilters();
      });

      // Populate for initial tab
      populateFilterUI(currentTab);
    }
```

- [ ] **Step 2: Update switchTab to repopulate filters**

In the existing `switchTab` function, add a call to `populateFilterUI` after `updateSubtitle`. Replace the function body (lines 124-139):

```javascript
    function switchTab(tabId) {
      currentTab = tabId;
      localStorage.setItem('curax-tab', tabId);

      document.querySelectorAll('.tab-content').forEach(function(el) {
        el.style.display = 'none';
      });
      var target = document.getElementById('tab-' + tabId);
      if (target) target.style.display = '';

      document.querySelectorAll('.tab-button').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
      });

      updateSubtitle(tabId);

      // Update filter UI for this tab (if filters initialized)
      if (window._manifest) {
        populateFilterUI(tabId);
        // Re-apply filters if any are active
        if (hasActiveFilters(window._filters[tabId])) {
          applyFilters();
        }
      }
    }
```

- [ ] **Step 3: Full end-to-end test**

Reload `http://localhost:8080`. Test each interaction:

1. Type in search bar → articles filter in real time after 200ms
2. Click "Filtres" → panel slides open
3. Drag score slider → low-score articles disappear
4. Select a domain → only that domain shows
5. Click a tag chip → it highlights, filters apply
6. Combine: query + score + tag → intersection works
7. Click "Réinitialiser" → all filters clear, full view returns
8. Switch to Publications tab → filters are independent
9. Switch back to Articles → previous filters restored
10. Type impossible query → "Aucun résultat" message with reset button
11. Change theme → search/filter styles follow theme
12. Toggle dark mode → all elements adapt
13. Resize to mobile → layout stacks properly

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat: wire up search and filter event listeners, complete filtering feature"
```

---

### Task 6: Final polish and edge cases

**Files:**
- Modify: `index.html`, `style.css` (minor adjustments)

- [ ] **Step 1: Hide observations box when filters are active**

Already handled: `renderArticlesTab` and `renderPublicationsTab` skip observations when `filterFn` is truthy. Verify in browser by typing a search query — the "Analyse du corpus" box should disappear.

- [ ] **Step 2: Verify corbeille behavior with score filter**

Set score slider to 5. The "Poubelle" section (score ≤ 4) should disappear completely. Set slider back to 0 — Poubelle reappears.

- [ ] **Step 3: Test with all 6 themes × 2 modes**

Cycle through each theme (Portfolio, MX-Brutalist, Sage Green, 2077, AstroVista, Offworld) in both light and dark modes. Verify:
- Search input border/background follows theme
- Filter toggle colors are correct
- Filter panel background matches secondary
- Tag chips use correct primary/muted colors
- Slider accent follows primary
- Domain select styling is consistent

- [ ] **Step 4: Final commit**

```bash
git add index.html style.css
git commit -m "feat: complete search and filtering feature with all edge cases"
```

---

## File Summary

| File | Changes |
|------|---------|
| `index.html` | +~150 lines: HTML structure (search bar, filter panel), JS functions (filter state, debounce, applyFilters, populateFilterUI, initFilters, resetFilters, buildNoResults, collectAllTags, collectDomains, buildFilterPredicate, hasActiveFilters, toggleTag, updateFilterBadges), refactored renderArticlesTab/renderPublicationsTab (filterFn param, no mutation), updated switchTab, updated main IIFE |
| `style.css` | +~120 lines: .search-bar, #search-input, .filter-toggle, .filter-panel, .filter-group, .filter-tags, .filter-tag, .filter-reset, .no-results, responsive rules |

No new files. No changes to `themes.js`, `manifest.json`, catalogs, or import pipeline.
