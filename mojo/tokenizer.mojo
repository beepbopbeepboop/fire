"""Real tokenizer for Mojo - extracted from Python implementation.

This is the full Python tokenizer that handles:
- Indentation tracking (INDENT/DEDENT)
- String literals (single, double, triple-quoted)
- Comments
- All operators and keywords
- Proper paren/bracket/brace nesting
"""

from dataclasses import dataclass
import re

_KEYWORDS = {
    'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
    'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
    'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
    'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try',
    'while', 'with', 'yield',
    # Mojo-specific keywords
    'fn', 'struct', 'trait', 'owned', 'inout', 'borrowed', 'var',
}

_TOKEN_RE = re.compile(
    r'(?P<FLOAT>\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)|'
    r'(?:0x|0X)[0-9a-fA-F]+|(?:0o|0O)[0-7]+|(?:0b|0B)[01]+|'
    r'(?P<INT>(?:0|[1-9][0-9]*))|'
    r'(?P<AUGASSIGN>\*\*=|//=|<<=|>>=|\+=|\-=|\*=|/=|%=|@=|\&=|\|=|\^=)|'
    r'(?P<ARROW>->)|'
    r'(?P<OP>\*\*|//|<<|>>|==|!=|<=|>=|:=|\*|@|/|%|\+|\-|\&|\^|\||<|>)|'
    r'(?P<ASSIGN>=)|'
    r'(?P<XFER>\^)|'
    r'(?P<STRING>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`)|'
    r'(?P<DOT>\.)|'
    r'(?P<COLON>:)|'
    r'(?P<LPAREN>\()|(?P<RPAREN>\))|'
    r'(?P<LBRACKET>\[)|(?P<RBRACKET>\])|'
    r'(?P<LBRACE>\{)|(?P<RBRACE>\})|'
    r'(?P<COMMA>,)|'
    r'(?P<NAME>[A-Za-z_][A-Za-z0-9_]*)|'
    r'(?P<WS>[^\S\n]+)|'
    r'(?P<UNK>.)'
)

_INDENT_SIZE = 4
_SEP_CHAR = ';'
_CMT_CHAR = '#'

@dataclass
struct Token:
    """A lexical token."""
    kind: str
    value: str

def _strip_inline_comment(s: str) -> str:
    """Remove trailing # comment, respecting quoted strings."""
    in_str = None
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ('"', "'"):
            in_str = c
        elif c == _CMT_CHAR:
            return s[:i]
        i += 1
    return s

def _split_on_separators(s: str) -> list[str]:
    """Split on ';' statement separator, respecting quoted strings."""
    parts = []
    buf = []
    in_str = None
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            buf.append(c)
            if c == "\\" and i + 1 < len(s):
                i += 1
                buf.append(s[i])
            elif c == in_str:
                in_str = None
        elif c in ('"', "'"):
            in_str = c
            buf.append(c)
        elif c == _SEP_CHAR:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts

def tokenize(src: str) -> list[Token]:
    """Tokenize with layout rules:
    - Indentation (4 spaces) → INDENT/DEDENT
    - ';' → statement separator
    - '#' → end-of-line comment
    - Multi-line statements use indentation (no backslash continuation)
    """
    string_cache = {}
    string_idx = 0

    def replace_multiline_strings(src: str) -> str:
        nonlocal string_idx
        def repl(m):
            nonlocal string_idx
            placeholder = f"__MOJO_STR_{string_idx}__"
            string_cache[placeholder] = m.group(0)
            string_idx += 1
            return placeholder
        # Match triple-quoted strings
        src = re.sub(r'"""[\s\S]*?"""', repl, src)
        src = re.sub(r"'''[\s\S]*?'''", repl, src)
        return src

    src = replace_multiline_strings(src)
    joined = src.splitlines()

    out = []
    stack = [0]
    paren_depth = 0  # Track (), [], {} nesting to suppress INDENT/DEDENT inside

    for line in joined:
        expanded = line.expandtabs(_INDENT_SIZE)
        raw_content = expanded.lstrip()
        if not raw_content or raw_content.startswith(_CMT_CHAR):
            continue
        content = _strip_inline_comment(raw_content).rstrip()
        if not content:
            continue
        indent = len(expanded) - len(raw_content)
        sub_stmts = _split_on_separators(content)

        for stmt_idx, stmt in enumerate(sub_stmts):
            stmt = stmt.strip()
            if not stmt:
                continue
            # Only emit INDENT/DEDENT when at paren depth 0
            if stmt_idx == 0 and paren_depth == 0:
                if indent > stack[-1]:
                    stack.append(indent)
                    out.append(Token("INDENT", ""))
                else:
                    while indent < stack[-1]:
                        stack.pop()
                        out.append(Token("DEDENT", ""))

            for m in _TOKEN_RE.finditer(stmt):
                kind = m.lastgroup or "INT"
                val = m.group()
                if kind in ("WS", "UNK", "XFER"):
                    continue
                if kind == "NAME" and val in _KEYWORDS:
                    kind = "KW"
                # Restore multi-line strings from cache
                if kind == "NAME" and val in string_cache:
                    val = string_cache[val]
                    kind = "STRING"
                # Track paren/bracket/brace depth
                if kind in ("LPAREN", "LBRACKET", "LBRACE") or val in ("(", "[", "{"):
                    paren_depth += 1
                elif kind in ("RPAREN", "RBRACKET", "RBRACE") or val in (")", "]", "}"):
                    paren_depth = max(0, paren_depth - 1)

                out.append(Token(kind, val))

            # Only emit NEWLINE when paren depth is 0
            if paren_depth == 0:
                out.append(Token("NEWLINE", ""))

    while len(stack) > 1:
        stack.pop()
        out.append(Token("DEDENT", ""))

    out.append(Token("EOF", ""))
    return out
