"""Extract ```mojo fenced code blocks from docstrings.

Reusable API for diagnostics/checkers (e.g. docstring self-import detection).
Provides source locations so diagnostics can point into the docstring.
"""

from __future__ import annotations

import dataclasses
import re

import fire_compiler as F


@dataclasses.dataclass
class DocstringCodeBlock:
    """A fenced code block extracted from a docstring."""

    code: str
    language: str | None
    # 1-based source location of the first character of `code` in the file.
    line: int
    col: int
    # 1-based source location of the opening fence line.
    fence_line: int
    fence_col: int
    # 1-based source location of the closing fence line, or None if unterminated.
    end_fence_line: int | None


_FENCE_RE = re.compile(r"^([ \t]*)(```+|~~~+)([^\n`]*)$")


def _is_docstring_expr_stmt(stmt) -> bool:
    return (isinstance(stmt, F.ExprStmt)
            and isinstance(getattr(stmt, "value", None), F.StringLiteral))


def module_docstring_literal(stmts):
    """Return the module-level docstring StringLiteral, or None.

    A module docstring is the first statement when it is a bare string literal
    expression statement.
    """
    if not stmts:
        return None
    first = stmts[0]
    if _is_docstring_expr_stmt(first):
        return first.value
    return None


def _literal_content_start(source: str, lit) -> tuple[int, int]:
    """Return (line, col) 1-based of first content character of `lit` in source.

    Falls back to the literal token position when the opening delimiter cannot be
    located precisely in `source`.
    """
    line = int(getattr(lit, "line", 1) or 1)
    col = int(getattr(lit, "col", 1) or 1)
    lines = source.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        return (line, col)
    line_text = lines[line - 1]
    idx = col - 1
    if idx < 0 or idx > len(line_text):
        return (line, col)
    # Match optional string prefix (r, b, f, u, t, combinations) + quote delimiter.
    m = re.match(r'([rRbBuUfFtT]*)("""|\'\'\'|"|\')', line_text[idx:])
    if not m:
        return (line, col)
    delim = m.group(2)
    after = idx + m.end()
    # Triple-quoted: content may start on same line or next line depending on style,
    # but the literal value starts immediately after the opening delimiter.
    if after < len(line_text) and line_text[after] in "\r\n":
        # content begins on following line
        return (line + 1, 1)
    return (line, after + 1)


def _advance_pos(line: int, col: int, text: str) -> tuple[int, int]:
    for ch in text:
        if ch == "\n":
            line += 1
            col = 1
        elif ch == "\r":
            # treat as line break only if not followed by \n in a pair we already saw;
            # callers pass segments so this is fine as a simple advance.
            line += 1
            col = 1
        else:
            col += 1
    return (line, col)


def extract_mojo_code_blocks_from_text(text: str, start_line: int = 1,
                                       start_col: int = 1):
    """Extract ```mojo/untagged fenced blocks from `text`.

    `start_line/start_col` give the 1-based source position of the first
    character of `text`. Block `line/col` point to the first character of the
    block's code content in the original source.
    """
    blocks: list[DocstringCodeBlock] = []
    # Normalize line endings for scanning while tracking original positions by
    # walking the original text.
    line = start_line
    col = start_col
    i = 0
    n = len(text)
    while i < n:
        # find end of current line
        j = i
        while j < n and text[j] not in "\r\n":
            j += 1
        line_text = text[i:j]
        # line ending
        k = j
        if k < n and text[k] == "\r":
            k += 1
            if k < n and text[k] == "\n":
                k += 1
        elif k < n and text[k] == "\n":
            k += 1
        eol = text[j:k]

        m = _FENCE_RE.match(line_text)
        if m:
            fence = m.group(2)
            info = (m.group(3) or "").strip()
            lang = info.split()[0] if info else None
            is_mojo = (lang or "").lower() == "mojo"
            # Accept mojo-tagged blocks and untagged blocks. Other tagged blocks
            # (e.g. ```python) must still be consumed so their closing fence is not
            # misinterpreted as a new block.
            if is_mojo or lang is None:
                fence_line, fence_col = line, col + len(m.group(1))
                content_start_line, content_start_col = _advance_pos(line, col, line_text + eol)
                code_parts: list[str] = []
                ci = k
                cline, ccol = content_start_line, content_start_col
                end_fence_line = None
                found_close = False
                while ci < n:
                    cj = ci
                    while cj < n and text[cj] not in "\r\n":
                        cj += 1
                    cline_text = text[ci:cj]
                    ck = cj
                    if ck < n and text[ck] == "\r":
                        ck += 1
                        if ck < n and text[ck] == "\n":
                            ck += 1
                    elif ck < n and text[ck] == "\n":
                        ck += 1
                    ceol = text[cj:ck]
                    cm = _FENCE_RE.match(cline_text)
                    if cm and cm.group(2)[0] == fence[0] and len(cm.group(2)) >= len(fence) and not cm.group(3).strip():
                        end_fence_line = cline
                        i = ck
                        line, col = _advance_pos(cline, ccol, cline_text + ceol)
                        found_close = True
                        break
                    code_parts.append(cline_text)
                    code_parts.append(ceol)
                    cline, ccol = _advance_pos(cline, ccol, cline_text + ceol)
                    ci = ck
                if not found_close:
                    i = n
                    line, col = cline, ccol
                blocks.append(DocstringCodeBlock(
                    code="".join(code_parts),
                    language=lang,
                    line=content_start_line,
                    col=content_start_col,
                    fence_line=fence_line,
                    fence_col=fence_col,
                    end_fence_line=end_fence_line,
                ))
                continue
            else:
                # Skip a non-mojo fenced block entirely.
                ci = k
                cline, ccol = _advance_pos(line, col, line_text + eol)
                found_close = False
                while ci < n:
                    cj = ci
                    while cj < n and text[cj] not in "\r\n":
                        cj += 1
                    cline_text = text[ci:cj]
                    ck = cj
                    if ck < n and text[ck] == "\r":
                        ck += 1
                        if ck < n and text[ck] == "\n":
                            ck += 1
                    elif ck < n and text[ck] == "\n":
                        ck += 1
                    ceol = text[cj:ck]
                    cm = _FENCE_RE.match(cline_text)
                    if cm and cm.group(2)[0] == fence[0] and len(cm.group(2)) >= len(fence) and not cm.group(3).strip():
                        i = ck
                        line, col = _advance_pos(cline, ccol, cline_text + ceol)
                        found_close = True
                        break
                    cline, ccol = _advance_pos(cline, ccol, cline_text + ceol)
                    ci = ck
                if not found_close:
                    i = n
                    line, col = cline, ccol
                continue
        # advance
        line, col = _advance_pos(line, col, line_text + eol)
        i = k
    return blocks


def extract_mojo_code_blocks_from_string_literal(lit, source: str | None = None):
    """Extract mojo code blocks from a docstring StringLiteral node.

    If `source` is provided, positions are computed relative to the source file
    (accounting for the literal's location and opening delimiter). Otherwise they
    are relative to the literal's decoded text content starting at (lit.line, lit.col).
    """
    if not isinstance(lit, F.StringLiteral):
        return []
    text = lit.value
    if source is not None:
        start_line, start_col = _literal_content_start(source, lit)
    else:
        start_line = int(getattr(lit, "line", 1) or 1)
        start_col = int(getattr(lit, "col", 1) or 1)
    return extract_mojo_code_blocks_from_text(text, start_line, start_col)


def extract_module_docstring_mojo_blocks(stmts, source: str | None = None):
    """Extract mojo code blocks from a module's top-level docstring, if any."""
    lit = module_docstring_literal(stmts)
    if lit is None:
        return []
    return extract_mojo_code_blocks_from_string_literal(lit, source=source)
