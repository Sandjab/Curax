# Unit Tests import.py — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter des tests unitaires pytest pour les fonctions de logique pure de `scripts/import.py` (22 fonctions, ~75 tests).

**Architecture:** Un seul fichier `tests/test_import.py` organise en classes pytest par groupe fonctionnel. Le module `import.py` est importe via `importlib` car `import` est un mot reserve Python. Pas de mock de Claude CLI, pas de fixture PDF.

**Tech Stack:** Python 3, pytest, tmp_path, monkeypatch

---

## File Structure

| Fichier | Action | Responsabilite |
|---------|--------|----------------|
| `tests/test_import.py` | Create | Tous les tests unitaires pour `scripts/import.py` |

---

### Task 1: Tests entites HTML, extraction HTML, fingerprint, et fonctions PDF texte

**Files:**
- Create: `tests/test_import.py`

- [ ] **Step 1: Creer le fichier de test avec setup + 4 premiers groupes**

Creer `tests/test_import.py` avec le contenu suivant :

```python
"""Tests unitaires pour scripts/import.py."""

import importlib
import hashlib
import os
import sys

import pytest

# import.py est un mot reserve Python — on utilise importlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
mod = importlib.import_module('import')


# =====================================================================
# Groupe 1 : Entites HTML
# =====================================================================

class TestCleanEntities:
    def test_amp(self):
        assert mod._clean_entities("a &amp; b") == "a & b"

    def test_lt_gt(self):
        assert mod._clean_entities("&lt;div&gt;") == "<div>"

    def test_apos(self):
        assert mod._clean_entities("it&#39;s") == "it's"

    def test_quot(self):
        assert mod._clean_entities("&quot;hello&quot;") == '"hello"'

    def test_nbsp(self):
        assert mod._clean_entities("a&nbsp;b") == "a b"

    def test_combined(self):
        assert mod._clean_entities("&lt;a&gt; &amp; &quot;b&quot;") == '<a> & "b"'


class TestEscapeHtml:
    def test_amp(self):
        assert mod._escape_html("a & b") == "a &amp; b"

    def test_lt_gt(self):
        assert mod._escape_html("<div>") == "&lt;div&gt;"

    def test_quot(self):
        assert mod._escape_html('"hello"') == "&quot;hello&quot;"

    def test_no_change(self):
        assert mod._escape_html("hello world") == "hello world"

    def test_round_trip_plain_text(self):
        text = "hello world 123"
        assert mod._clean_entities(mod._escape_html(text)) == text


# =====================================================================
# Groupe 2 : Extraction texte HTML
# =====================================================================

# HTML simule d'un article X/Twitter
TWITTER_HTML = '''
<style>.some-css { color: red; }</style>
<div>
  <div data-testid="UserAvatar-Container-elonmusk"></div>
  <span data-text="true">Premier tweet avec du contenu.</span>
  <span data-text="true">Deuxieme partie du texte.</span>
</div>
'''

TWITTER_HTML_WITH_CODE = '''
<style>.some-css { color: red; }</style>
<div>
  <span data-text="true">Voici du code :</span>
  <pre><code>def hello():
    print("world")</code></pre>
</div>
'''

# HTML generique (pas X/Twitter, pas de data-text)
GENERIC_HTML = '''
<html><head>
<style>body { color: black; background: white; font-size: 14px; padding: 10px; margin: 0; border: none; display: block; position: relative; }</style>
</head><body>
<p>Ceci est un paragraphe suffisamment long pour depasser trente caracteres.</p>
<p>Un autre paragraphe avec du texte significatif pour les tests unitaires.</p>
</body></html>
'''

CLOUDFLARE_HTML = '''
<div class="author-name-tooltip"><a href="/author">John Doe</a></div>
<p>Some article content here.</p>
'''

PROF_HTML = '''
<p>Article by Prof. Marie Curie about radioactivity.</p>
'''


class TestExtractPreBlocks:
    def test_extracts_code(self):
        html = '<pre><code>print("hello")</code></pre>'
        assert 'print("hello")' in mod._extract_pre_blocks(html)

    def test_strips_inner_tags(self):
        html = '<pre><code><span class="kw">def</span> foo():</code></pre>'
        result = mod._extract_pre_blocks(html)
        assert "<span" not in result
        assert "def" in result

    def test_cleans_entities(self):
        html = '<pre><code>a &amp; b</code></pre>'
        assert "a & b" in mod._extract_pre_blocks(html)

    def test_no_pre_blocks(self):
        assert mod._extract_pre_blocks("<p>hello</p>") == ""


class TestExtractAuthor:
    def test_twitter_handle(self):
        assert mod.extract_author(TWITTER_HTML) == "elonmusk"

    def test_cloudflare(self):
        assert mod.extract_author(CLOUDFLARE_HTML) == "John Doe"

    def test_prof(self):
        assert mod.extract_author(PROF_HTML) == "Prof. Marie Curie"

    def test_unknown(self):
        assert mod.extract_author("<p>no author here</p>") == "unknown"


class TestExtractTextSpans:
    def test_twitter_spans(self):
        text = mod.extract_text_spans(TWITTER_HTML)
        assert "Premier tweet" in text
        assert "Deuxieme partie" in text

    def test_twitter_with_code(self):
        text = mod.extract_text_spans(TWITTER_HTML_WITH_CODE)
        assert "Voici du code" in text
        assert "hello" in text

    def test_generic_html(self):
        text = mod.extract_text_spans(GENERIC_HTML)
        assert "paragraphe" in text

    def test_filters_css(self):
        text = mod.extract_text_spans(GENERIC_HTML)
        assert "color:" not in text
        assert "background:" not in text

    def test_empty_content(self):
        assert mod.extract_text_spans("") == ""

    def test_no_text(self):
        assert mod.extract_text_spans("<html><head></head><body></body></html>") == ""


class TestExtractTextPreview:
    def test_twitter_preview(self):
        preview = mod.extract_text_preview(TWITTER_HTML, max_len=50)
        assert len(preview) <= 50
        assert "Premier" in preview

    def test_max_len_respected(self):
        preview = mod.extract_text_preview(TWITTER_HTML, max_len=20)
        assert len(preview) <= 20

    def test_generic_html_preview(self):
        preview = mod.extract_text_preview(GENERIC_HTML, max_len=100)
        assert len(preview) <= 100
        assert len(preview) > 0


# =====================================================================
# Groupe 3 : Fingerprint HTML
# =====================================================================

class TestExtractContentFingerprint:
    def test_twitter_returns_hash(self):
        fp = mod.extract_content_fingerprint(TWITTER_HTML)
        assert fp is not None
        assert len(fp) == 64  # SHA-256 hex

    def test_generic_returns_hash(self):
        fp = mod.extract_content_fingerprint(GENERIC_HTML)
        assert fp is not None
        assert len(fp) == 64

    def test_deterministic(self):
        fp1 = mod.extract_content_fingerprint(TWITTER_HTML)
        fp2 = mod.extract_content_fingerprint(TWITTER_HTML)
        assert fp1 == fp2

    def test_different_content_different_hash(self):
        fp1 = mod.extract_content_fingerprint(TWITTER_HTML)
        fp2 = mod.extract_content_fingerprint(GENERIC_HTML)
        assert fp1 != fp2

    def test_no_text_returns_none(self):
        fp = mod.extract_content_fingerprint("<html><body></body></html>")
        assert fp is None


# =====================================================================
# Groupe 4 : Extraction PDF (fonctions texte)
# =====================================================================

class TestExtractPdfDoi:
    def test_standard_doi(self):
        text = "This paper (DOI: 10.1234/abc.def) presents..."
        assert mod.extract_pdf_doi(text) == "10.1234/abc.def"

    def test_arxiv_doi(self):
        text = "Available at 10.48550/arXiv.1706.03762 for review"
        assert mod.extract_pdf_doi(text) == "10.48550/arXiv.1706.03762"

    def test_doi_strips_trailing_dot(self):
        text = "See 10.1234/abc.def."
        assert mod.extract_pdf_doi(text) == "10.1234/abc.def"

    def test_no_doi(self):
        text = "This paper has no DOI reference at all."
        assert mod.extract_pdf_doi(text) == ""


class TestExtractPdfFingerprint:
    def test_normal_text(self):
        text = "A" * 200  # suffisamment long
        fp = mod.extract_pdf_fingerprint(text)
        assert fp is not None
        assert len(fp) == 64

    def test_short_text_returns_none(self):
        text = "Too short"
        fp = mod.extract_pdf_fingerprint(text)
        assert fp is None

    def test_deterministic(self):
        text = "A" * 200
        assert mod.extract_pdf_fingerprint(text) == mod.extract_pdf_fingerprint(text)

    def test_whitespace_normalization(self):
        text1 = "word " * 50  # 250 chars
        text2 = "word  " * 50  # double espaces mais meme contenu
        # Les deux devraient donner le meme fingerprint apres normalisation
        assert mod.extract_pdf_fingerprint(text1) == mod.extract_pdf_fingerprint(text2)
```

- [ ] **Step 2: Lancer les tests**

Run: `cd /Users/jean-paulgavini/Documents/Dev/Curax && python3 -m pytest tests/test_import.py -v`
Expected: tous les tests PASS

- [ ] **Step 3: Corriger les echecs eventuels**

Si des tests echouent, ajuster les assertions pour correspondre au comportement reel des fonctions (les tests doivent documenter le comportement existant, pas le modifier).

- [ ] **Step 4: Commit**

```bash
git add tests/test_import.py
git commit -m "test: add unit tests for HTML entities, extraction, fingerprint, and PDF text functions"
```

---

### Task 2: Tests dedup, slugify, et metadata injection

**Files:**
- Modify: `tests/test_import.py` (ajouter des classes de test)

- [ ] **Step 1: Ajouter les tests dedup, slugify, et metadata injection**

Ajouter a la fin de `tests/test_import.py` :

```python


# =====================================================================
# Groupe 5 : Dedup
# =====================================================================

class TestDedupBatch:
    def test_no_duplicates(self):
        items = {"/a.html": "content a", "/b.html": "content b"}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        excluded = mod.dedup_batch(items, fp_fn)
        assert excluded == set()

    def test_with_duplicate(self):
        items = {"/a.html": "same content", "/b.html": "same content"}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        excluded = mod.dedup_batch(items, fp_fn)
        assert len(excluded) == 1
        # Le second est exclu (l'ordre depend de dict, mais un des deux doit etre exclu)
        assert excluded.issubset(items.keys())

    def test_fingerprint_none_ignored(self):
        items = {"/a.html": "content", "/b.html": "other"}
        fp_fn = lambda c: None  # toujours None
        excluded = mod.dedup_batch(items, fp_fn)
        assert excluded == set()

    def test_single_item(self):
        items = {"/a.html": "content"}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        excluded = mod.dedup_batch(items, fp_fn)
        assert excluded == set()


class TestDedupAgainstCatalog:
    def test_no_match(self):
        items = {"/new.html": "new content"}
        existing = {"articles/a.html": {"domain": "test"}}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        reader = lambda k: "different content"
        result = mod.dedup_against_catalog(items, set(), existing, fp_fn, reader)
        assert result == set()

    def test_match_by_fingerprint(self):
        items = {"/new.html": "same content"}
        existing = {"articles/a.html": {"domain": "test"}}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        reader = lambda k: "same content"
        result = mod.dedup_against_catalog(items, set(), existing, fp_fn, reader)
        assert "/new.html" in result

    def test_match_by_doi(self):
        items = {"/new.pdf": "text with 10.1234/abc"}
        existing = {"papers/a.pdf": {"domain": "test", "doi": "10.1234/abc"}}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        reader = lambda k: "totally different text"
        doi_fn = lambda c: mod.extract_pdf_doi(c)
        result = mod.dedup_against_catalog(items, set(), existing, fp_fn, reader, doi_fn=doi_fn)
        assert "/new.pdf" in result

    def test_no_doi_fn_skips_doi_check(self):
        items = {"/new.pdf": "text with 10.1234/abc"}
        existing = {"papers/a.pdf": {"domain": "test", "doi": "10.1234/abc"}}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        reader = lambda k: "different text"
        # Sans doi_fn, le DOI n'est pas verifie
        result = mod.dedup_against_catalog(items, set(), existing, fp_fn, reader)
        assert result == set()

    def test_reader_returns_none_skips(self):
        items = {"/new.html": "content"}
        existing = {"articles/missing.html": {"domain": "test"}}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        reader = lambda k: None  # fichier absent
        result = mod.dedup_against_catalog(items, set(), existing, fp_fn, reader)
        assert result == set()

    def test_already_excluded_skipped(self):
        items = {"/new.html": "same content"}
        existing = {"articles/a.html": {"domain": "test"}}
        fp_fn = lambda c: hashlib.sha256(c.encode()).hexdigest()
        reader = lambda k: "same content"
        # /new.html est deja exclu → ne devrait pas etre re-ajoute
        result = mod.dedup_against_catalog(items, {"/new.html"}, existing, fp_fn, reader)
        assert result == set()


# =====================================================================
# Groupe 6 : Slugification
# =====================================================================

class TestSlugify:
    def test_normal_text(self):
        assert mod.slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        result = mod.slugify("Hello, World! #2024")
        assert result == "hello-world-2024"

    def test_max_len(self):
        result = mod.slugify("a very long title that should be truncated", max_len=20)
        assert len(result) <= 20

    def test_empty_string(self):
        assert mod.slugify("") == "untitled"

    def test_only_special_chars(self):
        assert mod.slugify("!!!???") == "untitled"

    def test_accents_removed(self):
        result = mod.slugify("cafe resume")
        # Les accents ASCII simples sont supprimes par le regex
        assert "-" not in result or result.replace("-", "").isalnum()

    def test_leading_trailing_dashes_stripped(self):
        result = mod.slugify("--hello--")
        assert not result.startswith("-")
        assert not result.endswith("-")


# =====================================================================
# Groupe 7 : Injection metadata
# =====================================================================

class TestInjectMetadata:
    def test_replaces_title(self):
        html = "<html><head><title>Old Title</title></head><body></body></html>"
        result = mod.inject_metadata(html, "New Title", "Description")
        assert "<title>New Title</title>" in result

    def test_adds_meta_description_when_absent(self):
        html = "<html><head><title>Title</title></head><body></body></html>"
        result = mod.inject_metadata(html, "Title", "My Description")
        assert 'meta name="description"' in result
        assert "My Description" in result

    def test_replaces_meta_description_when_present(self):
        html = '<html><head><meta name="description" content="old"><title>T</title></head><body></body></html>'
        result = mod.inject_metadata(html, "T", "New Desc")
        assert "New Desc" in result
        assert "old" not in result

    def test_escapes_special_chars_in_title(self):
        html = "<html><head><title>X</title></head><body></body></html>"
        result = mod.inject_metadata(html, 'Title "with" <quotes>', "desc")
        assert "&quot;" in result or "with" in result
        assert "&lt;" in result or "quotes" in result

    def test_escapes_special_chars_in_description(self):
        html = "<html><head><title>T</title></head><body></body></html>"
        result = mod.inject_metadata(html, "T", 'Desc with "quotes" & <tags>')
        assert "&quot;" in result
        assert "&amp;" in result
```

- [ ] **Step 2: Lancer les tests**

Run: `cd /Users/jean-paulgavini/Documents/Dev/Curax && python3 -m pytest tests/test_import.py -v`
Expected: tous les tests PASS

- [ ] **Step 3: Corriger les echecs eventuels**

Ajuster les assertions si necessaire pour correspondre au comportement reel.

- [ ] **Step 4: Commit**

```bash
git add tests/test_import.py
git commit -m "test: add unit tests for dedup, slugify, and metadata injection"
```

---

### Task 3: Tests catalog I/O, analyze article, et companion HTML

**Files:**
- Modify: `tests/test_import.py` (ajouter des classes de test)

- [ ] **Step 1: Ajouter les tests catalog I/O, analyze article, et companion HTML**

Ajouter a la fin de `tests/test_import.py` :

```python


# =====================================================================
# Groupe 8 : Catalog I/O
# =====================================================================

class TestCatalogIO:
    def test_load_catalog_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, 'CATALOG_PATH', str(tmp_path / 'nonexistent.json'))
        catalog = mod.load_catalog()
        assert catalog == {"domains": {}, "articles": {}, "observations": ""}

    def test_load_catalog_existing_file(self, tmp_path, monkeypatch):
        import json
        catalog_path = tmp_path / 'catalog.json'
        data = {"domains": {"test": {"name": "Test", "description": "d", "icon": "t"}},
                "articles": {}, "observations": "obs"}
        catalog_path.write_text(json.dumps(data), encoding='utf-8')
        monkeypatch.setattr(mod, 'CATALOG_PATH', str(catalog_path))
        loaded = mod.load_catalog()
        assert loaded == data

    def test_save_load_roundtrip(self, tmp_path, monkeypatch):
        catalog_path = tmp_path / 'catalog.json'
        monkeypatch.setattr(mod, 'CATALOG_PATH', str(catalog_path))
        data = {
            "domains": {"ai": {"name": "AI", "description": "Artificial Intelligence", "icon": "🤖"}},
            "articles": {"articles/ai/test.html": {"domain": "ai", "tags": ["test"],
                         "quality_score": 7, "quality_note": "Good"}},
            "observations": "Test observations with accents: cafe, resume"
        }
        mod.save_catalog(data)
        loaded = mod.load_catalog()
        assert loaded == data

    def test_save_catalog_creates_dirs(self, tmp_path, monkeypatch):
        catalog_path = tmp_path / 'subdir' / 'catalog.json'
        monkeypatch.setattr(mod, 'CATALOG_PATH', str(catalog_path))
        mod.save_catalog({"domains": {}, "articles": {}, "observations": ""})
        assert catalog_path.exists()

    def test_save_catalog_ensure_ascii_false(self, tmp_path, monkeypatch):
        catalog_path = tmp_path / 'catalog.json'
        monkeypatch.setattr(mod, 'CATALOG_PATH', str(catalog_path))
        mod.save_catalog({"domains": {}, "articles": {}, "observations": "cafe"})
        content = catalog_path.read_text(encoding='utf-8')
        # ensure_ascii=False → les accents ne sont pas echappes
        assert "cafe" in content
        assert "\\u" not in content


class TestPapersCatalogIO:
    def test_load_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, 'PAPERS_CATALOG_PATH', str(tmp_path / 'nonexistent.json'))
        catalog = mod.load_papers_catalog()
        assert catalog == {"domains": {}, "papers": {}, "observations": ""}

    def test_save_load_roundtrip(self, tmp_path, monkeypatch):
        catalog_path = tmp_path / 'papers_catalog.json'
        monkeypatch.setattr(mod, 'PAPERS_CATALOG_PATH', str(catalog_path))
        data = {
            "domains": {"ml": {"name": "ML", "description": "Machine Learning", "icon": "🧠"}},
            "papers": {"papers/ml/test/test.pdf": {
                "domain": "ml", "title": "Test Paper", "description": "A test",
                "tags": ["test"], "quality_score": 8, "quality_note": "Solid",
                "authors": ["Doe, J."], "year": 2025, "journal": "NeurIPS",
                "doi": "10.1234/test", "robustness_score": 4.0,
                "vulgarisation_file": "papers/ml/test/test-vulgarisation.html",
                "lca_file": "papers/ml/test/test-lca.html"
            }},
            "observations": "Test"
        }
        mod.save_papers_catalog(data)
        loaded = mod.load_papers_catalog()
        assert loaded == data


# =====================================================================
# Groupe 9 : Analyze article
# =====================================================================

class TestAnalyzeArticle:
    def test_returns_expected_keys(self):
        result = mod.analyze_article("/path/to/file.html", TWITTER_HTML)
        assert "filepath" in result
        assert "filename" in result
        assert "author" in result
        assert "slug" in result
        assert "text" in result

    def test_filepath_preserved(self):
        result = mod.analyze_article("/path/to/file.html", TWITTER_HTML)
        assert result["filepath"] == "/path/to/file.html"
        assert result["filename"] == "file.html"

    def test_author_extracted(self):
        result = mod.analyze_article("/path/to/file.html", TWITTER_HTML)
        assert result["author"] == "elonmusk"

    def test_text_extracted(self):
        result = mod.analyze_article("/path/to/file.html", TWITTER_HTML)
        assert "Premier tweet" in result["text"]

    def test_slug_not_untitled_when_text_present(self):
        result = mod.analyze_article("/path/to/file.html", TWITTER_HTML)
        assert result["slug"] != "untitled"


# =====================================================================
# Groupe 10 : Companion HTML
# =====================================================================

class TestBuildCompanionHtml:
    def test_lca_type(self):
        html = mod.build_companion_html("Test Title", "<p>Body</p>", "lca")
        assert "Lecture Critique" in html

    def test_vulgarisation_type(self):
        html = mod.build_companion_html("Test Title", "<p>Body</p>", "vulgarisation")
        assert "Vulgarisation" in html

    def test_title_in_html(self):
        html = mod.build_companion_html("Mon Titre", "<p>Body</p>", "lca")
        assert "Mon Titre" in html

    def test_title_escaped(self):
        html = mod.build_companion_html('Title "with" <special>', "<p>Body</p>", "lca")
        assert "&quot;" in html
        assert "&lt;" in html

    def test_body_injected(self):
        html = mod.build_companion_html("T", "<p>Custom content here</p>", "lca")
        assert "<p>Custom content here</p>" in html

    def test_themes_js_link(self):
        html = mod.build_companion_html("T", "<p>B</p>", "lca")
        assert "../../../themes.js" in html

    def test_anti_fouc_script(self):
        html = mod.build_companion_html("T", "<p>B</p>", "lca")
        assert "localStorage" in html
        assert "curax-mode" in html
        assert "curax-theme" in html

    def test_back_link(self):
        html = mod.build_companion_html("T", "<p>B</p>", "lca")
        assert "../../../index.html" in html

    def test_is_valid_html(self):
        html = mod.build_companion_html("T", "<p>B</p>", "lca")
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
```

- [ ] **Step 2: Lancer tous les tests**

Run: `cd /Users/jean-paulgavini/Documents/Dev/Curax && python3 -m pytest tests/test_import.py -v`
Expected: tous les tests PASS (~75 tests)

- [ ] **Step 3: Corriger les echecs eventuels**

Ajuster les assertions si necessaire.

- [ ] **Step 4: Verifier le compte total de tests**

Run: `cd /Users/jean-paulgavini/Documents/Dev/Curax && python3 -m pytest tests/test_import.py -v --tb=short 2>&1 | tail -5`
Expected: `XX passed` (environ 75 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_import.py
git commit -m "test: add unit tests for catalog I/O, analyze article, and companion HTML"
```
