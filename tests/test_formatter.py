"""Tests for utils/formatter.py — markdown-like text to HTML rendering."""
from __future__ import annotations

import pytest

from utils.formatter import parse_and_render


class TestEmptyInput:
    def test_empty_string(self):
        result = parse_and_render("")
        assert "<body>" in result

    def test_whitespace_only(self):
        result = parse_and_render("   \n  \n  ")
        assert "<body>" in result


class TestParagraphs:
    def test_single_paragraph(self):
        result = parse_and_render("Hello world")
        assert "Hello world" in result
        assert "<p" in result

    def test_multiple_paragraphs(self):
        result = parse_and_render("First paragraph\n\nSecond paragraph")
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_paragraph_preserves_content(self):
        result = parse_and_render("Some important text here")
        assert "Some important text here" in result


class TestBoldAndItalic:
    def test_bold(self):
        result = parse_and_render("**bold text**")
        assert "<b>bold text</b>" in result

    def test_italic(self):
        result = parse_and_render("*italic text*")
        assert "<i>italic text</i>" in result

    def test_bold_italic_combined(self):
        result = parse_and_render("**bold** and *italic*")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result


class TestInlineCode:
    def test_inline_code(self):
        result = parse_and_render("Use `print()` to output")
        assert "print()" in result
        assert "Consolas" in result or "monospace" in result


class TestCodeBlocks:
    def test_fenced_code_block(self):
        md = "```python\ndef hello():\n    print('hi')\n```"
        result = parse_and_render(md)
        assert "def hello" in result
        assert "print" in result
        assert "<pre" in result

    def test_code_block_with_language_label(self):
        md = "```javascript\nconsole.log('test');\n```"
        result = parse_and_render(md)
        assert "javascript" in result

    def test_code_block_without_language(self):
        md = "```\nsome code\n```"
        result = parse_and_render(md)
        assert "some code" in result


class TestBulletLists:
    def test_dash_bullet(self):
        result = parse_and_render("- Item one\n- Item two")
        assert "Item one" in result
        assert "Item two" in result
        assert "\u2022" in result  # bullet character

    def test_star_bullet(self):
        result = parse_and_render("* Item one\n* Item two")
        assert "Item one" in result
        assert "Item two" in result

    def test_bullet_with_inline_formatting(self):
        result = parse_and_render("- **bold** item\n- *italic* item")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result


class TestNumberedLists:
    def test_numbered_list(self):
        result = parse_and_render("1. First step\n2. Second step\n3. Third step")
        assert "First step" in result
        assert "Second step" in result
        assert "1." in result
        assert "2." in result


class TestHTML:
    def test_html_output_structure(self):
        result = parse_and_render("Hello")
        assert result.startswith("<html>")
        assert "<head>" in result
        assert "<body" in result
        assert result.endswith("</body></html>")

    def test_charset_meta(self):
        result = parse_and_render("Hello")
        assert 'charset="utf-8"' in result or "charset=utf-8" in result


class TestComplex:
    def test_mixed_content(self):
        md = """# Title

Some text with **bold** and *italic*.

- Bullet 1
- Bullet 2

1. Step one
2. Step two

```python
code_here()
```
"""
        result = parse_and_render(md)
        assert "Title" in result
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "Bullet 1" in result
        assert "Step one" in result
        assert "code_here" in result

    def test_code_block_between_paragraphs(self):
        md = "Before code\n\n```python\nx = 1\n```\n\nAfter code"
        result = parse_and_render(md)
        assert "Before code" in result
        assert "x = 1" in result
        assert "After code" in result


class TestHeadings:
    def test_h1_heading(self):
        result = parse_and_render("# Main Title")
        assert "<h1" in result
        assert "Main Title" in result

    def test_h2_heading(self):
        result = parse_and_render("## Section Heading")
        assert "<h2" in result
        assert "Section Heading" in result

    def test_h3_heading(self):
        result = parse_and_render("### Subsection")
        assert "<h3" in result
        assert "Subsection" in result


class TestHorizontalRules:
    def test_dashes(self):
        result = parse_and_render("Above\n\n---\n\nBelow")
        assert "<hr" in result
        assert "Above" in result
        assert "Below" in result

    def test_stars(self):
        result = parse_and_render("***")
        assert "<hr" in result


class TestBlockquotesAndAnswers:
    def test_blockquote(self):
        result = parse_and_render("> Important note here")
        assert "border-left:3px solid #00FF88" in result
        assert "Important note here" in result

    def test_answer_badge(self):
        result = parse_and_render("**Answer:** [B] O(log n)")
        assert "border:1px solid #00FF88" in result
        assert "[B] O(log n)" in result

