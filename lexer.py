"""Lexer for Formal English source code.

Produces a flat token stream including INDENT/DEDENT layout tokens.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator


class TT(Enum):
    # Layout
    INDENT = auto()
    DEDENT = auto()
    NEWLINE = auto()
    # Literals
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    # Names and keywords
    NAME = auto()
    # Punctuation / symbols
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    LBRACE = auto()
    RBRACE = auto()
    COMMA = auto()
    COLON = auto()
    DOT = auto()
    SEMICOLON = auto()
    EQUALS = auto()          # =
    ARROW = auto()           # ->
    WALRUS = auto()          # :=
    APOSTROPHE_S = auto()    # 's
    BACKSLASH = auto()
    EOF = auto()


@dataclass
class Token:
    type: TT
    value: str
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


# Regex patterns (order matters — longer/more specific first)
_TOKEN_RE = re.compile(r"""
    (?P<COMMENT>  \#[^\n]*          )  |
    (?P<FLOAT>    \d+\.\d*(?:[eE][+-]?\d+)?
               |  \.\d+(?:[eE][+-]?\d+)?
               |  \d+[eE][+-]?\d+    )  |
    (?P<INT>      0[xX][0-9a-fA-F]+
               |  0[oO][0-7]+
               |  0[bB][01]+
               |  \d+                )  |
    (?P<STRING>   (?:r|R|t|T|rt|tr|RT|TR)?
                  (?:\"\"\"[\s\S]*?\"\"\"|\'\'\'[\s\S]*?\'\'\'
                  |  \"(?:[^\"\\]|\\.)*\"
                  |  \'(?:[^\'\\]|\\.)*\' ) )  |
    (?P<APOSTROPHE_S>  \'s(?=\s|$|[,.:;()\[\]{}]) ) |
    (?P<ARROW>    ->                 )  |
    (?P<WALRUS>   :=                 )  |
    (?P<LPAREN>   \(                 )  |
    (?P<RPAREN>   \)                 )  |
    (?P<LBRACKET> \[                 )  |
    (?P<RBRACKET> \]                 )  |
    (?P<LBRACE>   \{                 )  |
    (?P<RBRACE>   \}                 )  |
    (?P<COMMA>    ,                  )  |
    (?P<COLON>    :                  )  |
    (?P<DOT>      \.                 )  |
    (?P<SEMICOLON> ;                 )  |
    (?P<EQUALS>   =                  )  |
    (?P<NAME>     [A-Za-z_][A-Za-z0-9_]* ) |
    (?P<NEWLINE>  \n                 )  |
    (?P<SPACE>    [ \t]+             )  |
    (?P<CONT>     \\[ \t]*\n         )  |
    (?P<UNKNOWN>  .                  )
""", re.VERBOSE | re.DOTALL)


def tokenize(source: str) -> list[Token]:
    """Tokenize source, emitting INDENT/DEDENT layout tokens."""
    tokens: list[Token] = []
    indent_stack = [0]
    lines = source.splitlines(keepends=True)
    if not source.endswith('\n'):
        lines.append('\n')  # ensure final newline

    logical_lines: list[tuple[int, str]] = []  # (indent_level, content)

    # Phase 1: join continuation lines, compute indent of each logical line
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        while raw.endswith('\\\n'):
            raw = raw[:-2] + ' '
            if i < len(lines):
                raw += lines[i].lstrip()
                i += 1
        stripped = raw.expandtabs(4)
        content = stripped.lstrip(' ')
        indent = len(stripped) - len(content)
        logical_lines.append((indent, raw))

    # Phase 2: tokenize each logical line, emitting INDENT/DEDENT
    lineno = 1
    for (indent, raw_line) in logical_lines:
        # Skip blank/comment-only lines
        stripped = raw_line.strip()
        if not stripped or stripped.startswith('#'):
            lineno += 1
            continue

        # Compute actual indent
        expanded = raw_line.expandtabs(4)
        content = expanded.lstrip(' ')
        cur_indent = len(expanded) - len(content)

        if cur_indent > indent_stack[-1]:
            indent_stack.append(cur_indent)
            tokens.append(Token(TT.INDENT, '', lineno, 0))
        else:
            while cur_indent < indent_stack[-1]:
                indent_stack.pop()
                tokens.append(Token(TT.DEDENT, '', lineno, 0))
            if cur_indent != indent_stack[-1]:
                raise SyntaxError(f"Inconsistent indentation at line {lineno}")

        # Tokenize the content of this line
        pos = len(expanded) - len(content)  # start after indent
        line_content = expanded[pos:]
        col_base = pos

        for m in _TOKEN_RE.finditer(line_content):
            kind = m.lastgroup
            val = m.group()
            col = col_base + m.start()

            if kind in ('SPACE', 'CONT'):
                continue
            if kind == 'COMMENT':
                break
            if kind == 'NEWLINE':
                tokens.append(Token(TT.NEWLINE, val, lineno, col))
                break
            if kind == 'UNKNOWN':
                raise SyntaxError(f"Unexpected character {val!r} at line {lineno}, col {col}")

            tt = TT[kind]
            tokens.append(Token(tt, val, lineno, col))

        lineno += 1

    # Emit remaining DEDENTs
    while len(indent_stack) > 1:
        indent_stack.pop()
        tokens.append(Token(TT.DEDENT, '', lineno, 0))

    tokens.append(Token(TT.EOF, '', lineno, 0))
    return tokens
