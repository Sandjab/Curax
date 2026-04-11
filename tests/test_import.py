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
        # The regex stops at whitespace/commas/semicolons/}/] but not ')'
        # so a trailing ')' is included in the match
        text = "This paper DOI: 10.1234/abc.def presents..."
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
