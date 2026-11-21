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
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Counted over gimple_codegen.py, mojo/middle/*.py and mojo/backend_gimple/*.py.
PATTERNS = {
    "endswith(' *')": r"""\.endswith\(\s*' \*'\s*\)""",
    "== 'int64_t'": r"""[=!]= *'int64_t'""",
    "in (.., 'int64_t', ..)": r"""\bin *\([^)]*'int64_t'[^)]*\)""",
    "== 'char *'": r"""[=!]= *'char \*'""",
    "== '_Bool'": r"""[=!]= *'_Bool'""",
    "== 'double'": r"""[=!]= *'double'""",
    "== 'MojoList *'": r"""[=!]= *'MojoList \*'""",
    # Stage 2b: a statement written with `gen._emit("...")` is text nobody
    # type-checks at the source; the builder calls (`_rt_call`, `_cast`,
    # `_copy`, `_goto`, `_binop`, ...) are checked by gimple_lint.
    "gen._emit( text": r"""\b(?:gen|self)\._emit\(""",
}

BASELINE = {
    "endswith(' *')": 344,
    "== 'int64_t'": 405,
    "in (.., 'int64_t', ..)": 312,
    # +1 on 2026-11-20: TypeLattice.is_cstr, the one definition call sites
    # should use instead of spelling the test.
    # also +1 each for is_word and is_double (same reason).
    "== 'char *'": 159,
    "== '_Bool'": 68,
    "== 'double'": 187,
    "== 'MojoList *'": 203,
    "gen._emit( text": 298,
}


def sources() -> list:
    return sorted(
        glob.glob(os.path.join(HERE, 'mojo', 'backend_gimple', '*.py'))
        + glob.glob(os.path.join(HERE, 'mojo', 'middle', '*.py'))
        + [os.path.join(HERE, 'gimple_codegen.py')])


def counts() -> dict:
    texts = [open(p).read() for p in sources()]
    return {k: sum(len(re.findall(v, t)) for t in texts) for k, v in PATTERNS.items()}


def main(argv: list) -> int:
    now = counts()
    if '--counts' in argv:
        for k in PATTERNS:
            print('%-26s %d' % (k, now[k]))
        return 0
    failures = 0
    for k in PATTERNS:
        if now[k] > BASELINE[k]:
            print('  FAIL  %s: %d, baseline %d -- ask a Type/TypeLattice method '
                  'instead of adding a string test' % (k, now[k], BASELINE[k]))
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
