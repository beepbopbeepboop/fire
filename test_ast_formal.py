#!/usr/bin/env python3
"""Build `formal/hostmods/ast.mojo` for the formal backend and RUN it against
CPython's own tokenizer and parser.

    python3 test_ast_formal.py [-v] [group ...]

**Why an oracle.** `ast.mojo` is a transcription of two pieces of CPython: the
`tokenize` state machine and the lexical half of the parser's statement rules.
A transcription is right on the inputs you tried and wrong on the one you did
not, so every case here is run TWICE — once through
`python3 fire.py build --formal --no-prove` and executed, once through this
process's `tokenize` and `compile` — and the two have to agree. Nothing in this
file states what `f"{x}"` tokenizes to; it asks.

**What is compared, per case.**

  * the token KINDS, one for one, with an f-string/t-string run collapsed to the
    run's first kind (the module's documented normalisation, applied to both
    sides);
  * the token POSITIONS, line and column, which is where a byte/character
    mistake shows up: CPython counts characters and this module works on bytes,
    so a line with a non-ASCII character on it is 259 of the 2017 files in the
    corpus;
  * the token COUNT, and that `token_bound` is at least it, so a caller can
    size a buffer with it;
  * `parse` against `compile`, unless the case is PINNED — see below.

**Pinned cases.** Some sources here are ones CPython's parser REFUSES and this
module accepts, because what it implements is the lexical and block-structure
half of the grammar and not the expression half. Those are listed in `PINNED`
with the verdict this module gives, and they are ASSERTED, not skipped: a
change in either direction is a change worth looking at. The list is the one
`bugs/FORMAL_ast_module_subset.md` prints, with the same reasons.

Groups: `stream`, `verdict`, `windows`, `names`. With no argument, all four.
"""
import argparse
import io
import os
import platform
import subprocess
import sys
import tempfile
import token
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 900

# The token window the generated program asks for. Three on purpose: it is the
# code path a caller with a small fixed buffer takes, and `tokenize_from` is
# resumable, so the whole corpus at window 3 is the resume path. `windows`
# runs it again at 1.
WIN = 3

# A formal program prints a NEGATIVE int as its unsigned 64-bit value
# (`print(0 - 1)` prints 18446744073709551615 — measured), so every value is
# folded back to signed before anything is compared.
def _fold(v):
    return v - (1 << 64) if v >= (1 << 63) else v


# ── the corpus ────────────────────────────────────────────────────────────
#
# source -> expected `parse` verdict, where None means "whatever CPython's
# `compile` says" and 0/1 is a PINNED verdict. The comments name the SHAPE, not
# the answer.
VERDICTS = {}


def _add(*sources):
    for s in sources:
        VERDICTS.setdefault(s, None)


def _pin(*pairs):
    for s, v in pairs:
        VERDICTS[s] = v


# Statements, expressions and the shapes around them.
_add(
    "x = 1\n", "x = 1", "x=1;", "x = 1;\n", "x = 1; y = 2\n", "x = 1 ;;\n",
    "x += 1\ny -= 2\nz *= 3\n", "global x, y\n", "del x[0], y\n",
    "assert x, 'm'\nassert x\n", "raise X from Y\nraise\n",
    "import a.b.c as d\nfrom . import e\nfrom ..x import (y, z)\n",
    "from a import *\nfrom . import *\n", "from a import (b, c)\n",
    "print(*a, **k)\nprint(*a, *b)\n", "x = ...\n",
    # compound statements, every header keyword
    "if x:\n    pass\nelse:\n    pass\n",
    "if x:\n    pass\nelif y:\n    pass\nelse:\n    pass\n",
    "while x:\n    break\nelse:\n    pass\n",
    "for i in y:\n    pass\nelse:\n    pass\n",
    "for i in j, k:\n    pass\n",
    "with open('f') as f:\n    pass\n",
    "with open('f') as f, open('g') as g:\n    pass\n",
    "with (open('f') as f, open('g') as g):\n    pass\n",
    "try:\n    pass\nexcept:\n    pass\n",
    "try:\n    pass\nexcept E:\n    pass\n",
    "try:\n    pass\nexcept (A, B) as e:\n    pass\n",
    "try:\n    pass\nexcept* E:\n    pass\n",
    "try:\n    pass\nexcept E:\n    pass\nelse:\n    pass\nfinally:\n    pass\n",
    "try:\n    pass\nfinally:\n    pass\n",
    "def f():\n    pass\n",
    "def f(a, b=1, *args, **kw) -> int:\n    return a\n",
    "def f(a: int = 1, *, b: str = 'x') -> None:\n    pass\n",
    "def f():\n    def g():\n        pass\n    return g\n",
    "class C:\n    pass\n", "class C(B):\n    x = 1\n",
    "class C(B, metaclass=M):\n    pass\n",
    "class C:\n    '''doc'''\n    def m(self):\n        return self\n",
    "@deco\n@deco2(1)\nclass C:\n    pass\n",
    "@deco\ndef f():\n    pass\n",
    "async def f():\n    await g()\n",
    "async def f():\n    async with a as b:\n        pass\n",
    "async def f():\n    async for i in x:\n        pass\n",
    "async def f():\n    return [i async for i in x]\n",
    "match x:\n    case 1:\n        pass\n    case _:\n        pass\n",
    "match = 1\ncase = 2\n", "match(x)\n", "case = match\n",
    "match x:\n    case [1, 2, *rest]:\n        pass\n    case {'a': 1, **rest}:\n        pass\n",
    "match x:\n    case C(y=1) if z:\n        pass\n",
    # expressions
    "x = a if b else c\n", "x = 1 if a else 2 if b else 3\n",
    "x = lambda a, b=1: a\n", "x = a[1:2, ::3]\nx = a[::-1]\n",
    "x = 0x_FF + 0o17 + 0b1_0 + 1_000 + 1e-5 + 1.5j + .5 + 5.\n",
    "x = 0XAB + 0O7 + 0B1 + 1E5 + 1J\n",
    "x = a.b.c(1).d[e]\nx = a[1][2][3]\nx = a.b[c].d(e).f\n",
    "x = -1 ** +2 // ~3\n", "x = not a\n", "x = a is not b\n",
    "x = a not in b\n", "x = a in b\n", "x = a and b or not c\n",
    "x = a < b <= c == d != e > f >= g\n", "x = a | b ^ c & d\n",
    "x = a << 1 >> 2\n", "x = a + b @ c * d / e // f % g ** h\n",
    "x = (a for b in c)\n", "x = [i for i in y if i]\n",
    "x = {k: v for k, v in y}\n", "x = {i for i in y}\n",
    "x = ()\nx = (1,)\nx = (1, 2)\nx = []\nx = {}\nx = {1: 2}\nx = {1, 2}\n",
    "x: int\n", "x: int = 1\n", "x, y = 1, 2\n",
    # strings, and the prefixes CPython accepts in any case
    "s = 'a' 'b' \"c\"\n", "s = '''a\nb'''\n", "s = \"\"\"a\nb\"\"\"\n",
    "s = 'a\\\nb'\n", "x = b'a' b'b'\n",
    "x = rb'q' + bR'q' + Rb'q' + BR'q'\n",
    "x = r'q' + R'q' + b'q' + B'q' + rb'q'\n",
    "x = u'q' + U'q'\n",
    "x = f'{a!r:>{w}} {b=}'\n", "x = t'{a}'\n", "print(f\"{'a'}\")\n",
    "x = f'{a}{b}' f'{c}'\n",
    # a nested f-string, a raw f-string with a backslash before a brace, and
    # the doubled braces — the three that decide where an f-string ENDS
    "x = f'({\",\".join([f\"{o}.{f}\" for f in fields])},)'\n",
    "x = rf'a\\{b}'\n", "x = rf'\\{b}'\n", "x = f'a\\{b}'\n",
    "x = f'a\\\\{b}'\n", "x = f'a\\\"{b}'\n", "x = f'\\{{b}}'\n",
    "x = f'{a}{{b}}'\n", "x = f'{x:{w}}'\n", "x = f\"{d['k']}\"\n",
    "x = f\"{ f'{x}' }\"\n", "x = f\"{x:'>10}\"\n", "x = f'{x}}}'\n",
    # line structure: continuations, brackets, indentation, DEDENT columns
    "x = 1 + \\\n    2\n", "x = 1 \\\n    + 2 \\\n    + 3\n",
    "x = (1,\n     2,\n     )\n", "x = [i\n     for i in y]\n",
    "x = {k: v\n     for k, v in y}\n", "x = (\n     1 +\n     2\n)\n",
    "f(\n    1,\n    2,\n)\n", "x = [\n]\nx = {\n}\n",
    "if (1,\n2):\n    pass\n", "if [\n1,\n]:\n    pass\n",
    "if a:\n    if b:\n        if c:\n            pass\n        else:\n"
    "            pass\n    else:\n        pass\nelse:\n    pass\n",
    "def f():\n    return\n\n\ndef g():\n    return 1\n",
    "class A:\n    def a(self):\n        pass\n    def b(self):\n"
    "        pass\n",
    "if x:\n        pass\nelse:\n    pass\n",
    "if x:\n\tpass\n", "if x:\n    pass\n", "if x:\n  pass\n  \n",
    # blank lines, comments, comment-only lines between blocks
    "\n", "\n\n\n", "   \n", "\t\n", " \n\n \n", "",
    "# just a comment\n", "# a\n# b\nx = 1\n", "x = 1  # trailing\n",
    "x = 1\n# after\n", "x = 1  # c\n\n# d\ny = 2\n",
    "if a:\n    pass\n# comment between\nelse:\n    pass\n",
    "try:\n    pass\n# a comment\nexcept E:\n    pass\n",
    "x = 1\n\n\n", "x = 1\n   \ny = 2\n",
    # a comment INSIDE brackets, and a comment after the code on a line
    "x = [\n    1,\n    # c\n    2,\n]\n", "x = (1,  # c\n     2)\n",
    "f(\n  # c\n  1)\n", "x = [\n  # only a comment\n]\n",
    "x = 1  # comment after code\ny = 2\n",
    # CRLF. A lone CR is a line break here and whitespace to CPython, which no
    # token stream can match, so it is not in this corpus at all; the bug doc
    # says so.
    "x = 1\r\ny = 2\r\n",
    # non-ASCII: the columns after a multi-byte character are the whole point
    "x = 'İ'\n", "# ─── box ───\n", "x = 1  # İ comment\n",
    "Ω = 1\nx = Ω + 1\n", "x = '日本語' + y\n",
    "def f():\n    return 'ünïcödé'\n",
)

# Sources CPython's PARSER refuses AND this module's rules refuse. The
# tokenizer part is compared for all of them; `parse` must be 0.
_add(
    "x = 'abc\n", "x = 'abc", 'x = """abc\n', "x = 'abc' 'd\n",
    "f(1]\n", "f(1}\n", "f(1\n", "[\n", "{1: 2\n", "f(\n",
    "= 5\n", "x =\n", "x +\n", "x ==\n", "x ->\n",
    ", x = 1\n", "f(,a)\n", "f(a,,b)\n", "x = [,]\n",
    "def :\n  pass\n", "def f(:\n", "class:\n    pass\n",
    "if:\n    pass\n", "while:\n    pass\n",
    "with :\n    pass\n",
    "x = 1 +\n", "x = 0x\n", "x = 1__0\n", "x = 0b2\n",
    "\\\n", "x = 1 \\\n", "x = \\\n",
)

# The PINNED cases: CPython refuses, this module accepts, because what it
# implements is the lexical half. The reason is the same one each time and the
# list is the one in `bugs/FORMAL_ast_module_subset.md`.
_pin(
    # the expression grammar, which `tokenize` does not check either
    ("x = 1..2\n", 1), ("x = 1j2\n", 1), ("x <> 1\n", 1), ("x = ,1\n", 1),
    ("x = 1 +* 2\n", 1), ("x = 1 ** * 2\n", 1), ("x = a | b ^ c & d ~ e\n", 1),
    ("x = 1 2\n", 1), ("x = a b c\n", 1), ("x = a.5\n", 1), ("x = *a\n", 1),
    ("x = 1e\n", 1), ("x = 1.2.3\n", 1),
    # a number that ends early (`1e__0` is the number 1 and the name `e__0`,
    # which is two expressions with no operator between them)
    ("x = 1e__0\n", 1), ("x = 1e_5\n", 1),
    # a statement keyword in the wrong place. NOT `x = def = 5`: the
    # `def`-needs-a-name rule already refuses that one, and so does CPython.
    ("for in x:\n    pass\n", 1), ("except:\n    pass\n", 1),
    ("else:\n    pass\n", 1), ("elif x:\n    pass\n", 1),
    ("finally:\n    pass\n", 1), ("if x\n    pass\n", 1),
    ("for i in\n    pass\n", 1), ("x = 1 if 2 else\n", 1),
    ("x = 1 else 2\n", 1), ("x = not not\n", 1), ("del\n", 1),
    ("x = 1 if 2 else 3 else 4\n", 1), ("lambda x: x\n", 1),
    # a compound statement's own rules
    ("return 1\n", 1), ("yield 1\n", 1), ("x = (yield)\n", 1),
    ("await x\n", 1), ("nonlocal x\n", 1), ("def f(x, x): pass\n", 1),
    # an annotation on a tuple target, and an unexpected INDENT
    ("x, y: int = 1, 2\n", 1), ("if x:\n  pass\n   pass\n", 1),
    ("def f():\n    x = 1\n      y = 2\n", 1),
    # a backslash before a closing brace INSIDE a replacement field
    ('x = f"a\\{b\\}c"\n', 1),
)

CASES = list(VERDICTS.items())


# ── the Mojo side ─────────────────────────────────────────────────────────
#
# A string literal on this path is interned VERBATIM and its delimiters are
# syntax: the value of a triple-quoted literal is its content, and a backslash
# is stored as written but is still an escape to the compiler's lexer, so a
# literal holding a backslash can swallow the rest of the file. All three are
# measured, and they are why a source goes in as a chain of joins with the
# quote runs and the awkward bytes built at RUN time instead of as one literal.
DQ1, SQ1, BSL = '"', "'", "\\"
DQ3, SQ3 = DQ1 * 3, SQ1 * 3


def _seg_exprs(seg):
    """Mojo expressions for `seg`, which holds no backslash."""
    if seg == "":
        return ['""']
    for q in (DQ3, SQ3):
        if q not in seg and not seg.endswith(q[0]):
            return [q + seg + q]
    k = 0
    while k < len(seg) and seg[len(seg) - 1 - k] in (DQ1, SQ1):
        k += 1
    return _seg_exprs(seg[:len(seg) - k]) + \
        ["CH(%d, 1)" % ord(c) for c in seg[len(seg) - k:]]


def _piece_exprs(part):
    """Mojo expressions whose values, concatenated, are exactly `part`."""
    out = []
    for i, seg in enumerate(part.split(BSL)):
        if i:
            out.append("CH(92, 1)")
        out.extend(_seg_exprs(seg))
    return out


def lit_exprs(s):
    """`s` as a list of Mojo expressions, in order."""
    if s == "":
        return ['""']
    exprs = []
    if DQ3 in s:
        for i, part in enumerate(s.split(DQ3)):
            if i:
                exprs.append("DQ3BYTES()")
            exprs.extend(_piece_exprs(part))
    else:
        exprs.extend(_piece_exprs(s))
    return exprs


def lit_groups(s, cap):
    """`lit_exprs(s)` in groups of at most `cap`.

    The cap is the HOST's, not the target's: `formal/arm64_codegen.py`'s
    `_always_returns` recurses once per statement in a function and the host
    recursion limit is 1000, so one function cannot hold a whole corpus. A
    group per `cap` expressions costs nothing at RUN time.
    """
    exprs = lit_exprs(s)
    return [exprs[i:i + cap] for i in range(0, len(exprs), cap)] or [[]]


PREAMBLE = '''\
from ast import parse, parse_reason, token_bound, tokenize_from, token_name

def CH(byte: int, n: int) -> str:
    var p: Pointer[UInt8] = malloc(n + 1)
    memset(p, byte, n)
    memset(p + n, 0, 1)
    return p

def DQ3BYTES() -> str:
    return CH(34, 3)

def join2(a: str, b: str) -> str:
    var la = strlen(a)
    var lb = strlen(b)
    var p: Pointer[UInt8] = malloc(la + lb + 1)
    memcpy(p, a, la)
    memcpy(p + la, b, lb)
    memset(p + la + lb, 0, 1)
    return p

# One record per case: the case index, `token_bound`, then a WINDOW's count
# and three words per token, repeated until the stream ends, then END, the
# total token count, `parse` and `parse_reason`. A count of -1 is the
# tokenizer's own refusal (TOKEN_ERROR) and -3 is the END marker; both are
# printed as `0 - n`, which comes back as the unsigned 64-bit value and is
# folded to signed by this file.
def show(s: str, tag: int, work):
    print(tag)
    print(token_bound(s))
    first = 0
    total = 0
    while 1:
        n = tokenize_from(s, first, work, WIN)
        if n == 0 - 1:
            # The same three-value tail a finished record has, so a refusal is
            # a count of -1 where a window's count would be: the total is -1.
            print(0 - 1)
            print(0 - 1)
            print(parse(s))
            print(parse_reason(s))
            fflush(0)
            return
        if n >= 0:
            total = n
        cnt = WIN
        if n >= 0 and n - first < WIN:
            cnt = n - first
        print(cnt)
        i = 0
        while i < cnt * 3:
            v = work[i]
            print(v)
            i = i + 1
        if n >= 0:
            break
        first = first + WIN
    print(0 - 3)
    print(total)
    print(parse(s))
    print(parse_reason(s))
    fflush(0)
'''


def build_program(tmpdir, sources, win, label="ast"):
    """Write the program, build it, and return its path (or the error)."""
    lines = [PREAMBLE.replace("WIN", str(win))]
    groups = []
    for i, s in enumerate(sources):
        g = lit_groups(s, 80)
        groups.append(g)
        for gi, exprs in enumerate(g):
            lines.append("def case%d_%d(v: str) -> str:" % (i, gi))
            for e in exprs:
                lines.append("    v = join2(v, %s)" % e)
            lines.append("    return v")
            lines.append("")
    lines.append("def main():")
    lines.append("    work = [%s]" % ", ".join(["0"] * (3 * win + 8)))
    for i in range(len(sources)):
        lines.append('    var src%d = ""' % i)
        for gi in range(len(groups[i])):
            lines.append("    src%d = case%d_%d(src%d)" % (i, i, gi, i))
        lines.append("    show(src%d, %d, work)" % (i, i + 1))
    path = os.path.join(tmpdir, "%s_prog.py" % label)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    out = os.path.join(tmpdir, "%s.bin" % label)
    if os.path.exists(out):
        os.remove(out)          # a stale binary is worse than no binary
    r = subprocess.run([sys.executable, FIRE, "build", "--formal", "--no-prove",
                        "-o", out, path], capture_output=True, text=True,
                       cwd=HERE, timeout=BUILD_TIMEOUT)
    if r.returncode != 0 or not os.path.exists(out):
        return None, (r.stderr or r.stdout)[-2000:]
    return out, None


def read_records(vals, nsources):
    """The program's integers as one record per case."""
    recs, i = [], 0
    while i + 1 < len(vals) and len(recs) < nsources:
        tag, bound = vals[i], vals[i + 1]
        i += 2
        toks, refused, total = [], 0, 0
        while i < len(vals):
            cnt = vals[i]
            i += 1
            if cnt == -3 or cnt == -1:
                # -3 is the END marker and -1 is the tokenizer's refusal, and
                # the total follows either of them (and is -1 for a refusal).
                if cnt == -1:
                    refused = 1
                total = vals[i]
                i += 1
                break
            toks.extend([tuple(vals[i + 3 * j:i + 3 * j + 3])
                         for j in range(cnt)])
            i += 3 * cnt
        else:
            return recs, "the program stopped mid-record"
        if i + 1 >= len(vals):
            return recs, "the program stopped before parse/parse_reason"
        parse_v, reason = vals[i], vals[i + 1]
        i += 2
        recs.append({"tag": tag, "bound": bound, "total": total,
                     "tokens": toks, "refused": refused,
                     "parse": parse_v, "reason": reason})
    return recs, None


# ── CPython's side ────────────────────────────────────────────────────────

def collapse(src, attr):
    """`attr` (`type` or `start`) of every token, f/t-string runs collapsed.

    The module emits ONE token for a run, and so does this, which is the
    normalisation both sides are compared under. A run NESTED inside another
    run's replacement field belongs to the outer one — that is the case
    `Lib/dataclasses.py` has, and it is three runs in CPython's stream.
    """
    out, depth = [], []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if depth:
            if t.type in (token.FSTRING_START, token.TSTRING_START):
                depth.append(0)
            elif t.type == token.OP and t.string == "{":
                depth[-1] += 1
            elif t.type == token.OP and t.string == "}":
                if depth[-1] == 0:
                    depth.pop()
                else:
                    depth[-1] -= 1
            elif t.type in (token.FSTRING_END, token.TSTRING_END):
                depth.pop()
            continue
        if t.type in (token.FSTRING_START, token.TSTRING_START):
            depth.append(0)
            out.append(getattr(t, attr))
            continue
        out.append(getattr(t, attr))
    return out


def cpython_tokens(src):
    r"""CPython's token kinds and positions, or None if it refuses the source.

    None is a real answer and not a failure: `tokenize` itself raises a
    TokenError on a backslash before a closing brace inside a replacement
    field (`f"a\{b\}c"`), and a case the ORACLE cannot tokenize has no token
    stream to compare — only the `parse` verdict, which is pinned.
    """
    try:
        return collapse(src, "type"), collapse(src, "start")
    except Exception:
        return None


def cpython_verdict(src):
    """1 if CPython's parser accepts `src`, else 0."""
    try:
        compile(src, "<case>", "exec")
        return 1
    except SyntaxError:
        return 0


# ── the runs, cached so the groups share one build ────────────────────────
_RUNS = {}


def run_corpus(win, label):
    if win in _RUNS:
        return _RUNS[win]
    sources = [s for s, _ in CASES]
    with tempfile.TemporaryDirectory() as tmp:
        out, err = build_program(tmp, sources, win, label=label)
        if out is None:
            _RUNS[win] = (None, "build failed: " + err)
            return _RUNS[win]
        r = subprocess.run([out], capture_output=True, text=True,
                           timeout=RUN_TIMEOUT)
        if r.returncode != 0:
            _RUNS[win] = (None, f"the image exited {r.returncode}: "
                                f"{r.stderr[-400:]}")
            return _RUNS[win]
        vals = [_fold(int(x)) for x in r.stdout.split()]
        recs, err = read_records(vals, len(sources))
        if err:
            _RUNS[win] = (None, err)
            return _RUNS[win]
    _RUNS[win] = (recs, None)
    return _RUNS[win]


def _want(src):
    pinned = VERDICTS[src]
    return cpython_verdict(src) if pinned is None else pinned


def _tok_name(k):
    return token.tok_name.get(k, k)


def group_stream(verbose):
    recs, err = run_corpus(WIN, "ast")
    if err:
        return False, err
    bad = []
    for rec in recs:
        src = [s for s, _ in CASES][rec["tag"] - 1]
        if rec["refused"]:
            try:
                list(tokenize.generate_tokens(io.StringIO(src).readline))
            except Exception:
                continue        # both refuse: there is nothing to compare
            bad.append((src, "CPython tokenizes it and this module refused"))
            continue
        if rec["total"] != len(rec["tokens"]):
            bad.append((src, f"emitted {len(rec['tokens'])} triples for "
                            f"{rec['total']} tokens"))
            continue
        if rec["total"] > rec["bound"]:
            bad.append((src, f"token_bound {rec['bound']} < {rec['total']}"))
        oracle = cpython_tokens(src)
        if oracle is not None:
            got = [t[0] for t in rec["tokens"]]
            exp, exppos = oracle
            if got != exp:
                j = _first_diff(got, exp)
                bad.append((src, f"token {j}: "
                                f"{_tok_name(got[j] if j < len(got) else None)}"
                                f" != {_tok_name(exp[j] if j < len(exp) else None)}"))
                continue
            gotpos = [(t[1], t[2]) for t in rec["tokens"]]
            if gotpos != exppos:
                j = _first_diff(gotpos, exppos)
                bad.append((src, f"position of token {j}: "
                                f"{gotpos[j] if j < len(gotpos) else None}"
                                f" != {exppos[j] if j < len(exppos) else None}"))
                continue
        want = _want(src)
        if rec["parse"] != want:
            bad.append((src, f"parse={rec['parse']} want={want}"))
            continue
        if verbose:
            print(f"  ok {rec['total']:4d} tokens  parse={rec['parse']}"
                  f"  {src[:60]!r}")
    return _report(bad, f"kinds, positions, counts, token_bound, parse"
                         f" over {len(CASES)} cases at window {WIN}")


def group_verdict(verbose):
    """`parse_reason`'s two failure classes, and the invariant between them.

    `reason` is 0 exactly when `parse` is 1, 1 for a lexical refusal and 2 for
    a structural one, and both refusals have to be one of the two classes — a
    reason of 0 next to a parse of 0, or a reason outside {1, 2}, would mean
    the two entry points disagree about the same scan.
    """
    recs, err = run_corpus(WIN, "ast")
    if err:
        return False, err
    bad = []
    for rec in recs:
        src = [s for s, _ in CASES][rec["tag"] - 1]
        if rec["parse"] == 1 and rec["reason"] != 0:
            bad.append((src, f"parse=1 but parse_reason={rec['reason']}"))
        if rec["parse"] == 0 and rec["reason"] == 0:
            bad.append((src, "parse=0 but parse_reason=0"))
        if rec["parse"] == 0 and rec["reason"] not in (1, 2):
            bad.append((src, f"parse_reason={rec['reason']} is neither "
                             f"lexical nor structural"))
    return _report(bad, "parse_reason's classes")


def group_windows(verbose):
    """`tokenize_from` is resumable, and window 1 is that path exercised hard.

    Also `token_bound` again: an upper bound a caller can size a buffer with is
    only an upper bound if it is at least the real count on every case, and the
    window-1 run is the one with the most resumes.
    """
    recs, err = run_corpus(1, "astwin")
    if err:
        return False, err
    bad = []
    for rec in recs:
        if rec["refused"]:
            continue
        src = [s for s, _ in CASES][rec["tag"] - 1]
        if rec["bound"] < rec["total"]:
            bad.append((src, f"token_bound {rec['bound']} < {rec['total']}"))
        oracle = cpython_tokens(src)
        if oracle is not None and \
                [t[0] for t in rec["tokens"]] != oracle[0]:
            bad.append((src, "the one-token window does not reproduce the "
                             "stream"))
    return _report(bad, f"the same corpus at window 1, and token_bound")


# Every kind code the module can be asked about, and what it answers.
# FSTRING_MIDDLE, FSTRING_END, TSTRING_MIDDLE and TSTRING_END are in the list
# because they are codes a CALLER may hold — from a stream it read elsewhere —
# and the answer has to be "" for all four: this module collapses a run to its
# START and never emits the rest. `tok_name` in CPython would say
# "FSTRING_MIDDLE" for 60, and saying so would be a lie about this module.
NAME_CASES = [
    (0, "ENDMARKER"), (1, "NAME"), (2, "NUMBER"), (3, "STRING"), (4, "NEWLINE"),
    (5, "INDENT"), (6, "DEDENT"), (55, "OP"), (59, "FSTRING_START"),
    (60, ""), (61, ""), (62, "TSTRING_START"), (63, ""), (64, ""),
    (65, "COMMENT"), (66, "NL"), (67, "ERRORTOKEN"),
    (7, ""), (68, ""), (-1, ""), (-2, ""),
]


def group_names(verbose):
    lines = ["from ast import token_name", "", "def main():"]
    for kind, _ in NAME_CASES:
        lines.append("    n = token_name(%d)" % kind)
        lines.append('    printf("[%s]", n)')
        lines.append('    printf("@@")')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "astnames.py")
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        out = os.path.join(tmp, "astnames.bin")
        r = subprocess.run([sys.executable, FIRE, "build", "--formal",
                            "--no-prove", "-o", out, path],
                           capture_output=True, text=True, cwd=HERE,
                           timeout=BUILD_TIMEOUT)
        if r.returncode != 0 or not os.path.exists(out):
            return False, (r.stderr or r.stdout)[-1500:]
        got = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT).stdout.split("@@")
    bad = []
    for (kind, want), g in zip(NAME_CASES, got):
        g = g.strip()
        if g.startswith("[") and g.endswith("]"):
            g = g[1:-1]           # the brackets are printf's, not the answer
        if g != want:
            bad.append((str(kind), f"token_name({kind}) = {g!r} want {want!r}"))
    return _report(bad, f"{len(NAME_CASES)} kind codes")


def _first_diff(a, b):
    for j in range(max(len(a), len(b))):
        x = a[j] if j < len(a) else None
        y = b[j] if j < len(b) else None
        if x != y:
            return j
    return 0


def _report(bad, what):
    for src, why in bad:
        print(f"FAIL {src!r}\n      {why}")
    if bad:
        return False, f"{len(bad)} failures: {what}"
    return True, what


GROUPS = {
    "stream": group_stream,
    "verdict": group_verdict,
    "windows": group_windows,
    "names": group_names,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    for name in names:
        try:
            ok, detail = GROUPS[name](args.verbose)
        except Exception as e:      # report, do not mask
            import traceback
            if args.verbose:
                traceback.print_exc()
            ok, detail = False, f"{type(e).__name__}: {e}"
        print(("PASS " if ok else "FAIL ") + name +
              (("  " + detail) if detail else ""))
        if not ok:
            failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
