"""A small, bounded regex compiler: parses a real-but-limited subset of
Python regex syntax into a flat node array that a matching C runtime function
can execute at compile time and runtime, respectively.

Scope: this project's self-hosted tokenizer (fire_compiler.py's _TOKEN_RE) is
the only re.compile(...).finditer(...) call anywhere in the self-hosted
codebase (see BACKLOG-CODEGEN.md §4f) — it, and patterns like it, use:
literals, '.', character classes with ranges/negation, \\d \\s \\S \\w \\W
shorthand, alternation, capturing/non-capturing/named groups, and the
quantifiers * + ? {m,n} in both greedy and non-greedy form. That is exactly
what this module supports — it is not a general Python `re` implementation
(no lookaround, no backreferences, no \\b, no flags).

This module runs at COMPILE TIME only (inside gimple_codegen.py, executed by
whatever is running the compiler — CPython during normal use, or the
self-hosted binary if compile_to_gimple itself gets executed). It never runs
as part of a COMPILED program's own logic; it only produces the C data/code
that becomes part of that program.
"""
from __future__ import annotations
from dataclasses import dataclass, field


# ─── AST node types ──────────────────────────────────────────────────────
@dataclass
class Char:
    c: str

@dataclass
class Any:
    pass

@dataclass
class Class:
    ranges: list       # list[(lo_ord, hi_ord)]
    negate: bool

@dataclass
class Concat:
    parts: list        # list[Node]

@dataclass
class Alt:
    options: list       # list[Node]

@dataclass
class Group:
    node: object
    index: int          # 1-based capturing group index, or 0 for non-capturing
    name: str | None

@dataclass
class Repeat:
    node: object
    lo: int
    hi: int              # -1 = unbounded
    greedy: bool

Node = object  # Char | Any | Class | Concat | Alt | Group | Repeat


# ─── Parser ──────────────────────────────────────────────────────────────
_SHORTHAND = {
    'd': [(48, 57)],
    'D': None,  # negated d, handled specially
    's': [(9, 13), (32, 32)],
    'S': None,
    'w': [(48, 57), (65, 90), (97, 122), (95, 95)],
    'W': None,
}

# Standard single-letter escapes that mean a CONTROL CHARACTER, not the
# literal letter — \n is newline (10), not the letter 'n' (110). Missing
# this made `[^\S\n]` (the tokenizer's own WS pattern) parse '\n' as the
# literal letter 'n', so the class matched real newlines as whitespace
# instead of excluding them.
_CHAR_ESCAPES = {
    'n': '\n', 't': '\t', 'r': '\r', 'f': '\f', 'v': '\v', '0': '\0',
}


def _complement_ranges(ranges: list, lo_bound: int = 0, hi_bound: int = 255) -> list:
    """Concrete 0-255 ranges NOT covered by `ranges` (assumed sorted-mergeable
    but not necessarily sorted here — sort first)."""
    spans = sorted(ranges)
    out = []
    cur = lo_bound
    for lo, hi in spans:
        if lo > cur:
            out.append((cur, lo - 1))
        cur = max(cur, hi + 1)
    if cur <= hi_bound:
        out.append((cur, hi_bound))
    return out


class _Parser:
    def __init__(self, pattern: str):
        self.p = pattern
        self.i = 0
        self.n = len(pattern)
        self.group_count = 0
        self.group_names: dict[str, int] = {}

    def peek(self) -> str:
        return self.p[self.i] if self.i < self.n else ''

    def advance(self) -> str:
        c = self.p[self.i]
        self.i += 1
        return c

    def parse(self) -> Node:
        node = self.parse_alt()
        if self.i != self.n:
            raise ValueError(f"regex parse error at {self.i} in {self.p!r}")
        return node

    def parse_alt(self) -> Node:
        options = [self.parse_concat()]
        while self.peek() == '|':
            self.advance()
            options.append(self.parse_concat())
        return options[0] if len(options) == 1 else Alt(options)

    def parse_concat(self) -> Node:
        parts = []
        while self.i < self.n and self.peek() not in ('|', ')'):
            parts.append(self.parse_repeat())
        if not parts:
            return Concat([])
        return parts[0] if len(parts) == 1 else Concat(parts)

    def parse_repeat(self) -> Node:
        atom = self.parse_atom()
        while self.peek() in ('*', '+', '?', '{'):
            c = self.peek()
            if c == '*':
                self.advance(); lo, hi = 0, -1
            elif c == '+':
                self.advance(); lo, hi = 1, -1
            elif c == '?':
                self.advance(); lo, hi = 0, 1
            else:  # '{'
                save = self.i
                self.advance()
                start = self.i
                while self.peek().isdigit():
                    self.advance()
                lo_s = self.p[start:self.i]
                hi_s = lo_s
                if self.peek() == ',':
                    self.advance()
                    start2 = self.i
                    while self.peek().isdigit():
                        self.advance()
                    hi_s = self.p[start2:self.i]
                if self.peek() != '}' or lo_s == '':
                    # Not a real {m,n} quantifier — treat '{' as literal (not
                    # needed by this codebase's patterns, but don't crash).
                    self.i = save
                    break
                self.advance()  # '}'
                lo = int(lo_s)
                hi = int(hi_s) if hi_s != '' else -1
            greedy = True
            if self.peek() == '?':
                self.advance()
                greedy = False
            atom = Repeat(atom, lo, hi, greedy)
        return atom

    def parse_atom(self) -> Node:
        c = self.advance()
        if c == '(':
            if self.peek() == '?':
                self.advance()
                if self.peek() == ':':
                    self.advance()
                    inner = self.parse_alt()
                    self._expect(')')
                    return Group(inner, 0, None)
                if self.peek() == 'P' and self.p[self.i:self.i+2] == 'P<':
                    self.advance()  # 'P'
                    self.advance()  # '<'
                    start = self.i
                    while self.peek() != '>':
                        self.advance()
                    name = self.p[start:self.i]
                    self.advance()  # '>'
                    self.group_count += 1
                    idx = self.group_count
                    self.group_names[name] = idx
                    inner = self.parse_alt()
                    self._expect(')')
                    return Group(inner, idx, name)
                raise ValueError(f"unsupported (?...) construct at {self.i} in {self.p!r}")
            self.group_count += 1
            idx = self.group_count
            inner = self.parse_alt()
            self._expect(')')
            return Group(inner, idx, None)
        if c == '[':
            return self._parse_class()
        if c == '.':
            return Any()
        if c == '\\':
            return self._parse_escape()
        return Char(c)

    def _expect(self, ch: str):
        if self.peek() != ch:
            raise ValueError(f"expected {ch!r} at {self.i} in {self.p!r}")
        self.advance()

    def _parse_escape(self) -> Node:
        e = self.advance()
        if e in _SHORTHAND:
            ranges = _SHORTHAND[e]
            if ranges is not None:
                return Class(ranges, False)
            base = _SHORTHAND[e.lower()]
            return Class(base, True)
        if e in _CHAR_ESCAPES:
            return Char(_CHAR_ESCAPES[e])
        # Literal escaped char (\., \\, \", \', \-, etc.)
        return Char(e)

    def _parse_class(self) -> Node:
        negate = False
        if self.peek() == '^':
            negate = True
            self.advance()
        ranges = []
        first = True
        while self.peek() != ']' or first:
            first = False
            if self.i >= self.n:
                raise ValueError(f"unterminated [ in {self.p!r}")
            c = self.advance()
            if c == '\\':
                e = self.advance()
                if e in _SHORTHAND:
                    if _SHORTHAND[e] is not None:
                        ranges.extend(_SHORTHAND[e])
                    else:
                        # Negated shorthand (\D, \S, \W) used INSIDE a class:
                        # Python semantics union its complement (over 0-255)
                        # into the class's own member set, e.g. `[^\S\n]` =
                        # complement of (non-space chars UNION '\n') = space
                        # chars excluding '\n'. Compute the concrete
                        # complement ranges over the shorthand's own ranges.
                        ranges.extend(_complement_ranges(_SHORTHAND[e.lower()]))
                    continue
                lo = ord(_CHAR_ESCAPES.get(e, e))
            else:
                lo = ord(c)
            if self.peek() == '-' and self.p[self.i+1:self.i+2] not in ('', ']'):
                self.advance()  # '-'
                c2 = self.advance()
                if c2 == '\\':
                    c2 = self.advance()
                    c2 = _CHAR_ESCAPES.get(c2, c2)
                hi = ord(c2)
                ranges.append((lo, hi))
            else:
                ranges.append((lo, lo))
        self.advance()  # ']'
        return Class(ranges, negate)


def parse_regex(pattern: str):
    parser = _Parser(pattern)
    node = parser.parse()
    return node, parser.group_count, parser.group_names


# ─── Serialize to a flat C node array ────────────────────────────────────
# Opcodes (must match runtime/fire_runtime.c's RE_OP_* / re_match_node):
OP_CHAR, OP_ANY, OP_CLASS, OP_CONCAT, OP_ALT, OP_GROUP, OP_REPEAT = range(7)


class _Emitter:
    def __init__(self):
        self.nodes: list[tuple] = []   # (op, a, b, c, d, e) six-int rows
        self.classes: list[list] = []  # list of ranges lists

    def emit(self, node: Node) -> int:
        if isinstance(node, Char):
            self.nodes.append((OP_CHAR, ord(node.c), 0, 0, 0, 0, 0))
            return len(self.nodes) - 1
        if isinstance(node, Any):
            self.nodes.append((OP_ANY, 0, 0, 0, 0, 0, 0))
            return len(self.nodes) - 1
        if isinstance(node, Class):
            cid = len(self.classes)
            self.classes.append(node.ranges)
            self.nodes.append((OP_CLASS, cid, int(node.negate), 0, 0, 0, 0))
            return len(self.nodes) - 1
        if isinstance(node, Concat):
            if not node.parts:
                # Empty concat: zero-width match. Represent as a CLASS-less
                # ANY-of-nothing via a CHAR node that always matches: use a
                # dedicated marker (child=-1 CONCAT with no parts).
                self.nodes.append((OP_CONCAT, -1, -1, 0, 0, 0, 0))
                return len(self.nodes) - 1
            idx = self.emit(node.parts[0])
            for part in node.parts[1:]:
                nxt = self.emit(part)
                idx = self._push((OP_CONCAT, idx, nxt, 0, 0, 0, 0))
            return idx
        if isinstance(node, Alt):
            idx = self.emit(node.options[0])
            for opt in node.options[1:]:
                nxt = self.emit(opt)
                idx = self._push((OP_ALT, idx, nxt, 0, 0, 0, 0))
            return idx
        if isinstance(node, Group):
            inner = self.emit(node.node)
            return self._push((OP_GROUP, inner, 0, node.index, 0, 0, 0))
        if isinstance(node, Repeat):
            inner = self.emit(node.node)
            return self._push((OP_REPEAT, inner, 0, 0, node.lo, node.hi, int(node.greedy)))
        raise TypeError(f"unknown regex node {node!r}")

    def _push(self, row) -> int:
        self.nodes.append(row)
        return len(self.nodes) - 1


def compile_pattern(pattern: str, c_prefix: str) -> dict:
    """Compile a Python regex source string into C data.

    Returns a dict with:
      'decls': C source text (static node/class-bitmap arrays + counts)
      'root': index of the root node in the emitted array
      'ngroups': total capturing group count
      'group_names': {name: 1-based group index}
      'prog_var', 'ranges_var', 'classinfo_var', 'names_var': the emitted
        array names (for the caller to reference in the
        mojo_regex_search(...)/mojo_regex_lastgroup(...) calls).
    """
    ast, ngroups, group_names = parse_regex(pattern)
    em = _Emitter()
    root = em.emit(ast)

    prog_var = f"_{c_prefix}_prog"
    classes_var = f"_{c_prefix}_classes"
    ranges_var = f"_{c_prefix}_ranges"

    # Flatten all class ranges into one array; each class stores
    # (offset, count) into it via two extra node-less side tables.
    range_flat = []
    class_offsets = []
    for ranges in em.classes:
        class_offsets.append((len(range_flat), len(ranges)))
        range_flat.extend(ranges)

    lines = []
    if range_flat:
        items = ", ".join(f"{{{lo}, {hi}}}" for lo, hi in range_flat)
        lines.append(f"static const ReRange {ranges_var}[] = {{{items}}};")
    else:
        lines.append(f"static const ReRange {ranges_var}[1] = {{{{0, 0}}}};")

    if class_offsets:
        items = ", ".join(f"{{{off}, {cnt}}}" for off, cnt in class_offsets)
        lines.append(f"static const ReClassInfo _{c_prefix}_classinfo[] = {{{items}}};")
    else:
        lines.append(f"static const ReClassInfo _{c_prefix}_classinfo[1] = {{{{0, 0}}}};")

    node_items = []
    for (op, a, b, c, d, e, f_) in em.nodes:
        node_items.append(f"{{{op}, {a}, {b}, {c}, {d}, {e}, {f_}}}")
    lines.append(f"static const ReNode {prog_var}[] = {{{', '.join(node_items)}}};")

    # Group-index -> name table (index 0 unused; NULL for unnamed/non-capturing
    # groups), for m.lastgroup — see mojo_regex_lastgroup in runtime/fire_runtime.c.
    idx_to_name = {v: k for k, v in group_names.items()}
    names_var = f"_{c_prefix}_names"
    _null = "(const char *)0"
    name_items = [_null] + [
        (f'"{idx_to_name[i]}"' if i in idx_to_name else _null)
        for i in range(1, ngroups + 1)
    ]
    lines.append(f"static const char * {names_var}[] = {{{', '.join(name_items)}}};")

    return {
        'decls': "\n".join(lines),
        'root': root,
        'ngroups': ngroups,
        'group_names': group_names,
        'prog_var': prog_var,
        'classinfo_var': f"_{c_prefix}_classinfo",
        'ranges_var': ranges_var,
        'names_var': names_var,
    }
