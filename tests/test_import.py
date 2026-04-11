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
