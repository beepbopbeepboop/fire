#!/usr/bin/env python3
"""Ratchets on the two remaining string-typed habits of the gimple backend
(doc/GIR.md, stages 4 and 2b): string type tests, and statements spelled as text.

The backend spells a type as a C string (`'int64_t'`, `'char *'`,
`'MojoList *'`) and decides things by comparing those strings. Stage 4
replaces them with `Type` objects, one method per question, so the answer to
"is this a pointer?" lives in one place. Until then this test only stops the
count growing: new code should ask a `Type`/`TypeLattice` method, not
re-spell the test.

    python3 test_type_string_ratchet.py            # check against BASELINE
    python3 test_type_string_ratchet.py --counts   # print the current counts

When a count FALLS the test fails until BASELINE is lowered to match (so the
gain is locked in), exactly as test_gimple_lint.py does.
"""
import ast
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TYPES_PY = os.path.join(HERE, 'mojo', 'middle', 'types.py')

# One regex for a C type spelling. Every type test the backend makes is some
# comparison against one of these, so the three type patterns below are one
# census of "a question asked of a type by its C name", not seven hand-picked
# spellings (which read as nearly done while about 930 tests remained).
TY = (r"(?:int|int(?:8|16|32|64)_t|uint(?:8|16|32|64)_t|_Bool|bool|char|double|float|long|void"
      r"|unsigned int|__fp16|size_t|[A-Za-z_][A-Za-z0-9_]* \*)")

# Counted over gimple_codegen.py, mojo/middle/*.py and mojo/backend_gimple/*.py.
PATTERNS = {
    # A comparison of a type variable against a C type spelling, `== 'MojoDict *'`.
    "== type string": r"[=!]= *'" + TY + r"'",
    # A membership test against a tuple that names a C type: `in ('int', 'int64_t')`.
    "in (type tuple)": r"\bin \([^()]*'" + TY + r"'[^()]*\)",
    # A pointer test by spelling: `.endswith(' *')` or `.endswith('*')`.
    "endswith('*')": r"\.endswith\(\s*' ?\*'\s*\)",
    # Stage 2b: a statement written with `gen._emit("...")` is text nobody
    # type-checks at the source; the builder calls (`_rt_call`, `_cast`,
    # `_copy`, `_goto`, `_binop`, ...) are checked by gimple_lint.
    "gen._emit( text": r"""\b(?:gen|self)\._emit\(""",
    # ...and `build.raw` is the builder's adapter for a statement no family
    # models yet, so it is the same debt and must not become the way around
    # the count above. Only `_emit_raw` itself should call it.
    "build.raw( text": r"""\bbuild\.raw\(""",
    # Stage 5b: the per-temp word facts are ONE `WordFacts` record map
    # (mojo/middle/valueinfo.py: `may_be_box`, `mark_tagged`, ...). A direct
    # `gen._boxed_vals` is the old spelling. The six sets themselves are gone
    # (stage 5b step 4, 2026-11-21), and no prose names them through `gen.`
    # either, so the baseline is 0 (it was 10 while the `bind` lines existed).
    "direct word-set use": r"""(?m)^(?![ \t]*#).*\b(?:gen|self)\._(?:boxed_vals|tagged_word_vals|dyn_word_vals|int_word_vals|maybe_kinds_vals|boxed_container_vals)\b""",
}

#   2026-11-23 (types.py counted, TypeLattice's is_* predicate bodies and comment
#   lines excluded). Before the exact rewrites and the single-type codemod, a
#   plain grep on master counted 619 `==` / 270 tuple / 38 `endswith` tests:
#   about 930 in all, not the 30 the old seven-spelling patterns showed. This
#   scanner measures 216 / 263 / 38 after them. `--counts` reprints the figures.
BASELINE = {
    # Stage 4 is landed (2026-11-27): the backlog this ratchet was created
    # against is drained. Every type test goes through a `TypeLattice`
    # predicate; the zeroes are the lock, not a temporary state.
    "== type string": 0,
    "in (type tuple)": 0,
    "endswith('*')": 0,
    # Stage 2b is landed: every statement the lowering writes is a builder
    # call, and `build.raw` is the only text channel left (its own baseline).
    "gen._emit( text": 0,
    "build.raw( text": 1,
    "direct word-set use": 0,
}

# A pattern whose SUBJECT is narrower than "every backend module".  The
# `gen._emit( text` ratchet counts a statement spelled as GIMPLE C text;
# `emit_metal.py` emits Metal Shading Language through its own `_emit` method
# and writes no gimple statement at all, so its 21 `self._emit(` calls can
# never move.  Leaving them in made the ratchet's floor 21 instead of 0,
# where a real regression could hide behind them (measured 2026-11-21).
#
# The three TYPE patterns are about C spellings; the Metal emitters spell Metal
# Shading Language (`uint`, `half`, `float`), which is a different vocabulary
# and not what stage 4 replaces. They are excluded whole, for the same reason.
_NOT_THIS_PATTERNS_SUBJECT = {
    "gen._emit( text": {"mojo/backend_gimple/emit_metal.py"},
    "== type string": {"mojo/backend_gimple/emit_metal.py", "mojo/middle/metal_ops.py"},
    "in (type tuple)": {"mojo/backend_gimple/emit_metal.py", "mojo/middle/metal_ops.py"},
    "endswith('*')": {"mojo/backend_gimple/emit_metal.py", "mojo/middle/metal_ops.py"},
}


def sources() -> list:
    """Every backend module, including mojo/middle/types.py. That file is no
    longer skipped whole: its TypeLattice `is_*` predicates are the one place a
    spelling may be tested (see `_code_lines`), and everything else in it counts."""
    return sorted(
        glob.glob(os.path.join(HERE, 'mojo', 'backend_gimple', '*.py'))
        + glob.glob(os.path.join(HERE, 'mojo', 'middle', '*.py'))
        + [os.path.join(HERE, 'gimple_codegen.py')])


def _predicate_lines(text: str) -> set:
    """1-based line numbers of the sanctioned spelling methods of TypeLattice.

    The `is_*` predicates and the two pointer-shape predicates (`ends_in_star`,
    `ends_with_star`) ARE the one place a spelling may be tested, so their
    bodies are not counted; every other method of the class is."""
    lines: set = set()
    for node in ast.parse(text).body:
        if not (isinstance(node, ast.ClassDef) and node.name == 'TypeLattice'):
            continue
        for item in node.body:
            if not (isinstance(item, ast.FunctionDef)
                    and (item.name.startswith('is_') or item.name.startswith('ends_'))):
                continue
            start = min([item.lineno] + [d.lineno for d in item.decorator_list])
            lines.update(range(start, item.end_lineno + 1))
    return lines


def _docstring_lines(text: str) -> set:
    """1-based line numbers of every docstring (module, class, function).

    A docstring is prose, not code: `emit_infra.py` explains a `join(...)`
    result by writing `== 'int'` inside one, and a text scan that counted it
    would report a type test that does not exist. Only the FIRST string
    statement of a scope is a docstring, so a string literal in an expression
    (`x == 'int'`) is still counted."""
    lines: set = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return lines
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = getattr(node, 'body', [])
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            lines.update(range(first.lineno, first.end_lineno + 1))
    return lines


def _code_lines(path: str, text: str) -> str:
    """`text` with the lines that are not code blanked out, so line numbers are kept.

    A comment line (first non-blank character `#`) is not code, a docstring is
    prose, and in types.py the TypeLattice predicate bodies are not counted.
    The blank lines keep the regexes' `^` and multi-line matches meaning what
    they meant."""
    skip: set = _docstring_lines(text)
    if os.path.normpath(path) == os.path.normpath(TYPES_PY):
        skip |= _predicate_lines(text)
    out: list = []
    for n, line in enumerate(text.split('\n'), 1):
        if n in skip or line.lstrip().startswith('#'):
            out.append('')
        else:
            out.append(line)
    return '\n'.join(out)


def _scan(p: str) -> dict:
    """Every pattern's match count within one source file, over its code lines."""
    code = _code_lines(p, open(p).read())
    return {k: len(re.findall(v, code)) for k, v in PATTERNS.items()}


def counts() -> dict:
    out: dict = {k: 0 for k in PATTERNS}
    for p in sources():
        rel = os.path.relpath(p, HERE).replace(os.sep, '/')
        per = _scan(p)
        for k in PATTERNS:
            if rel in _NOT_THIS_PATTERNS_SUBJECT.get(k, set()):
                continue
            out[k] += per[k]
    return out


def per_file(only_stage4: bool = True) -> None:
    """The census a work packet should be sized from: every file's counts.

    A packet doc's table is a snapshot and goes stale; this is measured."""
    stage4 = {"== type string", "in (type tuple)", "endswith('*')"}
    for p in sources():
        per = _scan(p)
        nz = [(k, per[k]) for k in PATTERNS
              if (k in stage4 or not only_stage4)]
        nz = [(k, n) for k, n in nz if n]
        if nz:
            print('%-46s %s' % (os.path.relpath(p, HERE),
                                ', '.join('%s: %d' % (k, n) for k, n in nz)))


def main(argv: list) -> int:
    now = counts()
    if '--counts' in argv:
        for k in PATTERNS:
            print('%-26s %d' % (k, now[k]))
        return 0
    if '--per-file' in argv:
        per_file('--all-patterns' not in argv)
        return 0
    failures = 0
    for k in PATTERNS:
        if now[k] > BASELINE[k]:
            print('  FAIL  %s: %d, baseline %d -- ask a Type/TypeLattice method '
                  'instead of adding a string test (python3 tools/type_string_codemod.py rewrites the simple ones)' % (k, now[k], BASELINE[k]))
            failures += 1
        elif now[k] < BASELINE[k]:
            print('  FAIL  %s: %d, baseline %d -- fixed! lower BASELINE[%r] to %d '
                  'in test_type_string_ratchet.py' % (k, now[k], BASELINE[k], k, now[k]))
            failures += 1
        else:
            print('  ok    %s: %d' % (k, now[k]))
    print('passed: %d failure(s)' % failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
