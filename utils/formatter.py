"""
Markdown-like text to HTML for QTextEdit / rich display.
"""
from __future__ import annotations

import html
import re
from typing import List


def _escape(s: str) -> str:
    return html.escape(s, quote=False)


def parse_and_render(text: str) -> str:
    """
    Convert plain / markdown-like text to HTML suitable for QTextEdit.setHtml().

    Supports:
    - ``` fenced code blocks (optional language line)
    - #, ##, ### Headings
    - --- / *** / ___ Horizontal rules
    - > Blockquotes / Answer callouts
    - **bold**, *italic*
    - `inline code`
    - bullet lines (- or *)
    - numbered lists (1. item)
    - paragraphs
    """
    if not text.strip():
        return "<body></body>"

    lines = text.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i = 0
    in_code = False
    code_lang = ""
    code_lines: List[str] = []

    def flush_code() -> None:
        nonlocal code_lines, code_lang
        if not code_lines:
            return
        body = _escape("\n".join(code_lines))
        lang = _escape(code_lang.strip()) if code_lang else ""
        label = f'<span style="color:#00FF88;font-size:10px;">{lang}</span><br/>' if lang else ""
        out.append(
            f'<pre style="background:#0A0A0A;border:1px solid #00FF88;border-radius:4px;'
            f'padding:8px;margin:6px 0;color:#00FF88;font-family:Consolas,monospace;">'
            f"{label}{body}</pre>"
        )
        code_lines = []
        code_lang = ""

    def render_inline(segment: str) -> str:
        segment = _escape(segment)
        segment = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", segment)
        segment = re.sub(r"\*(.+?)\*", r"<i>\1</i>", segment)
        segment = re.sub(
            r"`([^`]+?)`",
            r'<span style="background:#1A1A1A;color:#00FF88;padding:1px 4px;border-radius:3px;'
            r'font-family:Consolas,monospace;">\1</span>',
            segment,
        )
        return segment

    def flush_paragraph(buf: List[str]) -> None:
        if not buf:
            return
        inner = " ".join(render_inline(x) for x in buf if x.strip())
        if inner.strip():
            # Check for answer badge formatting
            if inner.startswith("<b>Answer:</b>") or inner.startswith("<b>ANSWER:</b>"):
                out.append(
                    f'<div style="background:#0F2A1C;border:1px solid #00FF88;border-radius:4px;'
                    f'padding:8px 12px;margin:8px 0;color:#E0FFE0;">{inner}</div>'
                )
            else:
                out.append(f'<p style="margin:6px 0;color:#E0E0E0;">{inner}</p>')
        buf.clear()

    para_buf: List[str] = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph(para_buf)
            if not in_code:
                in_code = True
                rest = stripped[3:].strip()
                code_lang = rest if rest else ""
                code_lines = []
            else:
                flush_code()
                in_code = False
                code_lang = ""
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if not stripped:
            flush_paragraph(para_buf)
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^(\-{3,}|\*{3,}|_{3,})$", stripped):
            flush_paragraph(para_buf)
            out.append('<hr style="border:none;border-top:1px solid #224433;margin:8px 0;"/>')
            i += 1
            continue

        # Headings (#, ##, ###)
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph(para_buf)
            level = len(heading_match.group(1))
            heading_text = render_inline(heading_match.group(2))
            if level == 1:
                out.append(
                    f'<h1 style="color:#00FF88;font-size:15px;margin:8px 0 4px 0;'
                    f'font-weight:bold;border-bottom:1px solid #1A3A2A;padding-bottom:2px;">{heading_text}</h1>'
                )
            elif level == 2:
                out.append(
                    f'<h2 style="color:#00FF88;font-size:14px;margin:6px 0 3px 0;font-weight:bold;">{heading_text}</h2>'
                )
            else:
                out.append(
                    f'<h3 style="color:#66FFAA;font-size:13px;margin:4px 0 2px 0;font-weight:bold;">{heading_text}</h3>'
                )
            i += 1
            continue

        # Blockquote (> text)
        blockquote_match = re.match(r"^>\s*(.+)$", stripped)
        if blockquote_match:
            flush_paragraph(para_buf)
            quote_text = render_inline(blockquote_match.group(1))
            out.append(
                f'<div style="border-left:3px solid #00FF88;padding:4px 10px;margin:6px 0;'
                f'background:#0D1A14;color:#B0E8D0;">{quote_text}</div>'
            )
            i += 1
            continue

        # Bullet lists (- or *)
        bullet = re.match(r"^[\-\*]\s+(.+)$", stripped)
        if bullet:
            flush_paragraph(para_buf)
            item = render_inline(bullet.group(1))
            out.append(
                f'<p style="margin:2px 0 2px 16px;color:#E0E0E0;text-indent:-12px;">'
                f'<span style="color:#00FF88;">•</span> {item}</p>'
            )
            i += 1
            continue

        # Numbered lists (1. item)
        numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if numbered:
            flush_paragraph(para_buf)
            n, rest = numbered.group(1), numbered.group(2)
            item = render_inline(rest)
            out.append(
                f'<p style="margin:2px 0 2px 8px;color:#E0E0E0;">'
                f'<span style="color:#00FF88;">{n}.</span> {item}</p>'
            )
            i += 1
            continue

        para_buf.append(stripped)
        i += 1

    flush_paragraph(para_buf)
    if in_code:
        flush_code()

    body = "\n".join(out)
    return (
        f'<html><head><meta charset="utf-8"/></head>'
        f'<body style="font-family:\'Segoe UI\',sans-serif;font-size:13px;">{body}</body></html>'
    )
