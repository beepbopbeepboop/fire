import re
from .tokens import Token, TT
from .errors import LexError


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.lines = source.split("\n")
        self.indent_stack = [0]
        self.tokens = []

    def tokenize(self) -> list[Token]:
        for lineno, line in enumerate(self.lines, 1):
            self._tokenize_line(lineno, line)

        # Emit remaining DEDENTs
        while len(self.indent_stack) > 1:
            self.indent_stack.pop()
            self.tokens.append(Token(TT.DEDENT, "", lineno, 0))

        self.tokens.append(Token(TT.EOF, "", lineno + 1, 0))
        return self.tokens

    def _tokenize_line(self, lineno: int, line: str) -> None:
        # Skip blank lines and comment-only lines
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            return

        # Compute indentation
        indent = len(line) - len(stripped)
        if line[:indent] != " " * indent:
            raise LexError(f"tabs not allowed, use spaces", lineno, 0)

        # Handle indentation changes
        current_indent = self.indent_stack[-1]
        if indent > current_indent:
            self.indent_stack.append(indent)
            self.tokens.append(Token(TT.INDENT, "", lineno, 0))
        elif indent < current_indent:
            while len(self.indent_stack) > 1 and self.indent_stack[-1] > indent:
                self.indent_stack.pop()
                self.tokens.append(Token(TT.DEDENT, "", lineno, 0))
            if self.indent_stack[-1] != indent:
                raise LexError(f"inconsistent indentation", lineno, 0)

        # Tokenize the rest of the line
        line_tokens = self._tokenize_line_content(lineno, stripped)
        self.tokens.extend(line_tokens)
        if line_tokens:
            self.tokens.append(Token(TT.NEWLINE, "", lineno, 0))

    def _tokenize_line_content(self, lineno: int, line: str) -> list[Token]:
        tokens = []
        pos = 0

        while pos < len(line):
            # Skip spaces
            if line[pos].isspace():
                pos += 1
                continue

            # Skip comments
            if line[pos] == "#":
                break

            col = pos + 1

            # Try to match 's
            if pos < len(line) - 1 and line[pos:pos + 2] == "'s":
                if pos + 2 < len(line) and (line[pos + 2].isalnum() or line[pos + 2] == "_"):
                    # It's part of a string, not 's
                    pass
                else:
                    tokens.append(Token(TT.APOSTROPHE_S, "'s", lineno, col))
                    pos += 2
                    continue

            # Try multi-char operators (longest first)
            matched = False
            for op, tt in [
                ("->", TT.ARROW), (":=", TT.WALRUS), ("**", TT.DSTAR),
                ("//", TT.DSLASH), ("<<", TT.LSHIFT), (">>", TT.RSHIFT),
                ("==", TT.EQ), ("!=", TT.NEQ), ("<=", TT.LTE), (">=", TT.GTE),
                ("+=", TT.PLUSEQ), ("-=", TT.MINUSEQ), ("*=", TT.STAREQ),
                ("/=", TT.SLASHEQ), ("//=", TT.DSLASHEQ), ("%=", TT.PERCENTEQ),
                ("**=", TT.DSTAREQ), ("&=", TT.AMPEQ), ("|=", TT.PIPEEQ),
                ("^=", TT.CARETEQ), ("<<=", TT.LSHIFTEQ), (">>=", TT.RSHIFTEQ),
                ("...", TT.ELLIPSIS),
            ]:
                if line[pos:pos + len(op)] == op:
                    tokens.append(Token(tt, op, lineno, col))
                    pos += len(op)
                    matched = True
                    break

            if matched:
                continue

            # Single-char punctuation
            char = line[pos]
            single_ops = {
                "(": TT.LPAREN, ")": TT.RPAREN, "[": TT.LBRACKET, "]": TT.RBRACKET,
                "{": TT.LBRACE, "}": TT.RBRACE, ",": TT.COMMA, ":": TT.COLON,
                ".": TT.DOT, "+": TT.PLUS, "-": TT.MINUS, "*": TT.STAR,
                "/": TT.SLASH, "%": TT.PERCENT, "@": TT.AT,
                "&": TT.AMP, "|": TT.PIPE, "^": TT.CARET, "~": TT.TILDE,
                "<": TT.LT, ">": TT.GT, "=": TT.ASSIGN, ";": TT.SEMICOL,
            }
            if char in single_ops:
                tokens.append(Token(single_ops[char], char, lineno, col))
                pos += 1
                continue

            # String literals
            if char in ('"', "'"):
                token, new_pos = self._read_string(lineno, line, pos)
                tokens.append(token)
                pos = new_pos
                continue

            # Numeric literals
            if char.isdigit() or (char == "." and pos + 1 < len(line) and line[pos + 1].isdigit()):
                token, new_pos = self._read_number(lineno, line, pos)
                tokens.append(token)
                pos = new_pos
                continue

            # Identifier or keyword
            if char.isalpha() or char == "_":
                token, new_pos = self._read_identifier(lineno, line, pos)
                tokens.append(token)
                pos = new_pos
                continue

            raise LexError(f"unexpected character '{char}'", lineno, col)

        return tokens

    def _read_string(self, lineno: int, line: str, pos: int) -> tuple[Token, int]:
        # Check for prefix (r, t, rt, tr)
        prefix_start = pos
        while prefix_start > 0 and line[prefix_start - 1] in "rRtT":
            prefix_start -= 1
        prefix = line[prefix_start:pos]

        quote_char = line[pos]
        start_pos = pos

        # Check for triple-quoted string
        if pos + 2 < len(line) and line[pos:pos + 3] == quote_char * 3:
            # Triple-quoted string
            raw = line[prefix_start:pos + 3]
            pos += 3
            lineno_tracker = lineno

            while lineno_tracker <= len(self.lines):
                if pos < len(line) and line.find(quote_char * 3, pos) != -1:
                    idx = line.find(quote_char * 3, pos)
                    raw += line[pos:idx + 3]
                    return Token(TT.STRING, raw, lineno, prefix_start + 1), idx + 3

                raw += line[pos:] + "\n"
                lineno_tracker += 1
                if lineno_tracker <= len(self.lines):
                    line = self.lines[lineno_tracker - 1]
                    pos = 0
                else:
                    raise LexError(f"unclosed triple-quoted string", lineno, start_pos + 1)

        # Regular string
        raw = line[prefix_start:pos + 1]
        pos += 1

        while pos < len(line):
            if line[pos] == quote_char:
                raw += line[pos]
                return Token(TT.STRING, raw, lineno, prefix_start + 1), pos + 1
            elif line[pos] == "\\":
                raw += line[pos:pos + 2]
                pos += 2
            else:
                raw += line[pos]
                pos += 1

        raise LexError(f"unclosed string literal", lineno, start_pos + 1)

    def _read_number(self, lineno: int, line: str, pos: int) -> tuple[Token, int]:
        start = pos
        col = pos + 1

        # Hex, octal, binary
        if line[pos] == "0" and pos + 1 < len(line):
            if line[pos + 1] in "xX":
                pos += 2
                while pos < len(line) and (line[pos].isalnum() or line[pos] == "_"):
                    pos += 1
                return Token(TT.INTEGER, line[start:pos], lineno, col), pos
            elif line[pos + 1] in "oO":
                pos += 2
                while pos < len(line) and (line[pos].isdigit() or line[pos] == "_"):
                    pos += 1
                return Token(TT.INTEGER, line[start:pos], lineno, col), pos
            elif line[pos + 1] in "bB":
                pos += 2
                while pos < len(line) and (line[pos] in "01_"):
                    pos += 1
                return Token(TT.INTEGER, line[start:pos], lineno, col), pos

        # Decimal or float
        while pos < len(line) and line[pos].isdigit():
            pos += 1

        is_float = False
        if pos < len(line) and line[pos] == ".":
            is_float = True
            pos += 1
            while pos < len(line) and line[pos].isdigit():
                pos += 1

        if pos < len(line) and line[pos] in "eE":
            is_float = True
            pos += 1
            if pos < len(line) and line[pos] in "+-":
                pos += 1
            while pos < len(line) and line[pos].isdigit():
                pos += 1

        tt = TT.FLOAT if is_float else TT.INTEGER
        return Token(tt, line[start:pos], lineno, col), pos

    def _read_identifier(self, lineno: int, line: str, pos: int) -> tuple[Token, int]:
        start = pos
        col = pos + 1

        while pos < len(line) and (line[pos].isalnum() or line[pos] == "_"):
            pos += 1

        value = line[start:pos]

        # Check keywords
        if value == "True" or value == "False":
            return Token(TT.BOOL, value, lineno, col), pos
        elif value == "None":
            return Token(TT.NONE, value, lineno, col), pos
        elif value == "Self":
            return Token(TT.SELF, value, lineno, col), pos
        elif value == "_":
            return Token(TT.DISCARD, value, lineno, col), pos
        else:
            return Token(TT.NAME, value, lineno, col), pos
