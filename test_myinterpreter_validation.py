#!/usr/bin/env python3
"""The interpreter's OWN output, validated against a directly-imported one.

Why this file exists
--------------------
Everything else in the tree compares the compiled path against the
interpreter, or the interpreter against CPython on whole programs
(`test_interp_oracle.py`). This file is different and it is the only check of
its kind: it takes ONE FUNCTION — `fire_compiler.py`'s `py_tokenize`, the
tokenizer every parse in this compiler starts with — and runs it twice, once
imported directly and once reached THROUGH `myinterpreter.py`'s `Interpreter`
executing `fire_compiler.py`'s own source. Both runs must produce the same
token stream.

That is a check this project cannot get any other way. An interpreter bug that
mis-evaluates an expression makes the interpreted `py_tokenize` compute
something different from the same code running on CPython, and the difference
is a wrong answer rather than an exception: the compiled path is then wrong in
the same direction, so every engine-vs-engine diff in the tree stays clean.
`bugs/UNTESTED.md` §3.2 records the two real instances — `@classmethod`'s `cls`
binding the first real ARGUMENT, and `@deco` being parsed and then never
applied at all — and both were invisible for exactly that reason.

What changed, and why this file was dead
----------------------------------------
It used to load three `.mojo` files:

    mojo/ast_nodes.mojo, mojo/tokenizer.mojo, mojo/parser.mojo

**None of them exists.** `mojo/` has no `.mojo` files at all; the tokenizer and
parser became `fire_compiler.py`, and `ast_nodes` was deleted outright
(CLAUDE.md: "`ast_nodes.py` is dead and should not exist"). So the file died at
its first `open()`, printed a `FileNotFoundError`, and nothing noticed for as
long as it existed — which is the `coro` story from CLAUDE.md, one file over:
a suite reporting green over a test that cannot run.

`bugs/UNTESTED.md` §3.2 called this file "the strongest cheap parity check in
the tree and nothing runs it", and said the choice was between moving it to
what the interpreter actually loads and deleting it. Moved. The corpus also
grew, because the point is the interpreter and the natural corpus for that is
the compiler's own source rather than eight hand-written snippets.

Exit status is the verdict: 0 iff every corpus text tokenizes identically
through both routes. (The three sibling files that could not make that claim —
`test_myinterpreter_simple.py`, `test_phase2_parser.py`,
`test_phase2_parser_simple.py` — were deleted rather than repaired, for the
reason in `bugs/UNTESTED.md` Tier 3: a test of a module that no longer exists
is not a slow test, it is a wrong claim, and `test_myinterpreter.py` already
runs the interpreter end to end and passes.)

    python3 test_myinterpreter_validation.py
    python3 test_myinterpreter_validation.py -v     # print every case
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fire_compiler import py_tokenize as python_tokenize     # noqa: E402
from myinterpreter import Interpreter                        # noqa: E402

# The file whose `py_tokenize` is under test, and the corpus it is run over.
#
# The corpus is deliberately WHOLE FILES, not snippets. A tokenizer's hard
# cases are the ones a snippet never reaches: a backslash line continuation
# inside a raw string, a triple-quoted docstring with quotes in it, an f-string
# with nested braces, a non-ASCII identifier, a `\` at the end of a line. And
# it is cheap: `fire_compiler.py` is ~3.4k lines and tokenizes in milliseconds.
SUBJECT = 'fire_compiler.py'

SNIPPETS = [
    "x = 1",
    "def foo(): pass",
    "if x > 0: y = 1",
    "for i in range(10): print(i)",
    "x = [1, 2, 3]",
    "# comment\nx = 1",
    's = "hello"',
    "x = 1 + 2 * 3",
    # The lexer hard cases, named because `test_string_literal_lexing.py`
    # documents that two of them changed what a program MEANS rather than what
    # it printed, and because a tokenizer that disagreed about one of them
    # would change the AST and therefore every answer downstream.
    's = "a\\nb"',
    "s = '''triple\nquoted'''",
    's = f"{x!r:>{width}}"',
    "s = 'unterminated",
    'r = r"a\\\nb"',
    "x: int = 1",
    "async def g():\n    await h()",
    "match x:\n    case 1:\n        pass",
    "x = 0xFF & 0o17 | 0b1011 ^ 3",
    "s = '\\u00e9\\N{GREEK SMALL LETTER ALPHA}'",
]


def corpus():
    """[(label, text)] — the snippets, then whole real files."""
    out = [(f'snippet {i + 1}', s) for i, s in enumerate(SNIPPETS)]
    files = [SUBJECT, 'myinterpreter.py', 'gimple_codegen.py', 'version.py']
    files += sorted(os.path.relpath(p, HERE) for p in
                    glob.glob(os.path.join(HERE, 'formal', 'examples', '*.mojo')))
    for rel in files:
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            out.append((rel, f.read()))
    return out


def interpreter_py_tokenize():
    """`fire_compiler.py`'s `py_tokenize`, reached THROUGH the interpreter.

    Built the way `fire.py run` builds every program it interprets — tokenize,
    parse, then `execute` each top-level statement into one `Interpreter`
    scope — so the function under test is the interpreter's own rendering of
    that code and not a re-import.
    """
    path = os.path.join(HERE, SUBJECT)
    with open(path, encoding='utf-8') as f:
        src = f.read()
    from fire_compiler import Parser
    stmts = Parser(python_tokenize(src)).with_filename(SUBJECT).parse_module()
    interp = Interpreter(filename=SUBJECT, argv=None)
    for stmt in stmts:
        interp.execute(stmt)
    fn = interp.scope.get('py_tokenize')
    if fn is None:
        raise AssertionError(
            f'the interpreter did not end up with a `py_tokenize` after '
            f'executing {SUBJECT} — the subject under test is not reachable, '
            f'so every comparison below would be vacuous')
    return fn


def compare(interp_tokens, ref_tokens):
    """`(ok, message)` for two token lists — kind and value, in order."""
    if len(interp_tokens) != len(ref_tokens):
        return False, (f'length {len(interp_tokens)} vs {len(ref_tokens)}; '
                       f'first divergence at '
                       f'{_first_divergence(interp_tokens, ref_tokens)}')
    for i, (it, pt) in enumerate(zip(interp_tokens, ref_tokens)):
        if it.kind != pt.kind or it.value != pt.value:
            return False, (f'token {i}: {it.kind} {it.value!r} vs '
                           f'{pt.kind} {pt.value!r}')
    return True, f'{len(interp_tokens)} tokens identical'


def _first_divergence(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x.kind != y.kind or x.value != y.value:
            return f'{i}: {x.kind} {x.value!r} vs {y.kind} {y.value!r}'
    return f'{min(len(a), len(b))} (the shorter one ended)'


def _one(interp_fn, text):
    """`(ok, message)` for one corpus text, comparing what each route DID.

    Comparing what each route did rather than only what it returned is the
    point, and it is not a formality: the lexer refuses an unterminated
    literal by RAISING, and the interpreter's copy of that raise is a
    different statement executed by a different engine. A compare that
    returned "both raised" would have reported 67/67 on the day the
    interpreter's scope had no `SyntaxError` in it and every one of those
    raises came out as `NameError` — which is the same
    "a test whose result is a string it prints is not a test" shape as a
    swallowed exception, one level down.

    So the exception TYPE and its MESSAGE are both part of the answer.
    """
    try:
        got = interp_fn(text)
    except BaseException as e:                              # noqa: BLE001
        got = ('!raise', type(e).__name__, str(e))
    else:
        got = ('!tokens',) + tuple(got)
    try:
        want = python_tokenize(text)
    except BaseException as e:                              # noqa: BLE001
        want = ('!raise', type(e).__name__, str(e))
    else:
        want = ('!tokens',) + tuple(want)
    if got[:1] != want[:1]:
        return False, f'{got[0]} vs {want[0]}'
    if got[0] == '!raise':
        if got[1] != want[1]:
            return False, f'raised {got[1]} where the imported one raised {want[1]}'
        if got[2] != want[2]:
            return False, f'raised {got[1]}({got[2]!r}) vs {want[1]}({want[2]!r})'
        return True, f'both raised {got[1]}({got[2]!r})'
    ok, msg = compare(got[1:], want[1:])
    return ok, msg


def main(argv):
    verbose = '-v' in argv
    print('=== the interpreter\'s py_tokenize vs the imported one ===\n')
    try:
        interp_fn = interpreter_py_tokenize()
    except AssertionError as e:
        print(f'✗ {e}')
        return 1
    print(f'✓ reached {SUBJECT}\'s py_tokenize through the interpreter\n')

    cases = corpus()
    print(f'{len(cases)} corpus texts ({len(SNIPPETS)} snippets, '
          f'{len(cases) - len(SNIPPETS)} whole files)\n')
    passed = failed = 0
    for label, text in cases:
        ok, msg = _one(interp_fn, text)
        if ok:
            passed += 1
            if verbose:
                print(f'  ✓ {label:44s} {msg}')
        else:
            failed += 1
            print(f'  ✗ {label:44s} {msg}')

    print(f'\n{"=" * 60}')
    print(f'Results: {passed} passed, {failed} failed')
    print(f'{"=" * 60}\n')
    if failed:
        print('✗ FAILED: the interpreter\'s tokenizer is not the imported one\n')
        return 1
    print('✓ PASSED: identical token streams through both routes\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))