#!/usr/bin/env python3
"""`tools/c_oracle.py` hashes the C++ coroutine lowering (GIR stage 7).

The oracle's job is "a behaviour-preserving backend change generates the same
text".  That is only true for the C++ printer if the text it emits is part of
what is hashed, and until 2026-11-21 it was not:

  * `tools/pydiff_corpus` holds NO coroutine program (285 programs, 0 with a
    non-empty `.cpp` companion), and
  * the default coroutine backend is the A3 stack-switch lowering
    (`mojo.middle.coro.enabled()` is False only for `MOJO_CORO=cpp`), so a
    compile of that corpus produces `cpp == ''` even for a program that does
    contain a `yield`.

So `c_oracle check` compared `c + '\\0' + ''` for every program, and a change to
`mojo/backend_gimple/cpp_core.py` or `cpp_async.py` reported "all 285 programs
generate identical C" while the `.cpp` it exists to protect changed.  Measured
before the fix: renaming the generator base symbol in `cpp_async.py` left
`c_oracle check` green.

This test pins the fix, which is a SECOND corpus (`tools/cpp_corpus`) compiled
with `MOJO_CORO=cpp`:

  * every program in it produces a non-empty companion (an empty one is an
    ERROR in the oracle, not a hashable no-op, so the corpus cannot silently
    stop exercising the lowering);
  * the corpus covers both promise shapes the lowering has -- `co_yield` (the
    generator unit) and `co_await` (the async unit);
  * the oracle's per-program hash folds BOTH texts in: it is neither
    `md5(c)` nor `md5(cpp)` alone;
  * the default backend really does emit no companion, which is WHY a second
    corpus is needed rather than more programs in the first one.  If this ever
    stops being true, re-derive the doc's claim instead of keeping two corpora.

    python3 test_regress_cpp_oracle_covers_lowering.py
"""
import hashlib
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ORACLE = os.path.join(ROOT, 'tools', 'c_oracle.py')

sys.path.insert(0, ROOT)
from exec_budget import COMPILE_TIMEOUT_S

# Both promise shapes: a generator unit is lowered by `_gen_cpp_generator_unit`
# (co_yield) and an async one by `_gen_cpp_async_unit` (co_await, which has no
# generator promise).  A corpus with only one of them leaves the other printer
# unhashed.
SHAPES = ['co_yield', 'co_await']

_COMPILE = r'''
import hashlib, json, sys
sys.path.insert(0, '.')
from gimple_codegen import compile_to_gimple_with_cpp
rel, path = sys.argv[1], sys.argv[2]
try:
    c, cpp = compile_to_gimple_with_cpp(open(path).read(), filename=rel)
    print(json.dumps([c, cpp]))
except BaseException as e:
    print(json.dumps(['ERR ' + type(e).__name__ + ': ' + str(e), '']))
'''


def compile_program(rel: str, path: str, cpp_backend: bool) -> tuple:
    """(C, companion C++) for one program, in a child with the backend pinned.

    A child, not an in-process compile: `MOJO_CORO` is read by
    `coro.enabled()` at each compile, so an in-process test would have to
    leave the process-wide variable in whatever state its last case wanted.
    """
    env = dict(os.environ, PYTHONPATH=ROOT)
    env.pop('MOJO_CORO', None)
    if cpp_backend:
        env['MOJO_CORO'] = 'cpp'
    p = subprocess.run([sys.executable, '-c', _COMPILE, rel, path],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=COMPILE_TIMEOUT_S)
    import json
    try:
        c, cpp = json.loads(p.stdout.strip().split('\n')[-1])
    except (ValueError, IndexError):
        raise AssertionError('%s: child produced no result (exit %d): %s'
                             % (rel, p.returncode, (p.stderr or '').strip()[-400:]))
    if c.startswith('ERR '):
        raise AssertionError('%s: refused: %s' % (rel, c[4:]))
    return c, cpp


def load_oracle():
    spec = importlib.util.spec_from_file_location('c_oracle_under_test', ORACLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    failures = []
    oracle = load_oracle()
    # The oracle's own API is half of what this test pins: a corpus no oracle
    # reads would be a directory of programs nothing compares.
    for attr in ('CPP_CORPUS',):
        if not hasattr(oracle, attr):
            print('FAIL: tools/c_oracle.py has no %s: the C++ coroutine lowering '
                  'is not hashed by `check`' % attr)
            return 1
    import inspect
    if 'cpp' not in inspect.signature(oracle.hash_tree).parameters:
        print('FAIL: tools/c_oracle.py hash_tree() has no `cpp` flag: there is no '
              'way to hash the companion .cpp text')
        return 1
    files = oracle.corpus(oracle.CPP_CORPUS)
    if len(files) < 10:
        failures.append('%s has %d program(s); the C++ lowering needs a corpus '
                        'that covers its shapes' % (oracle.CPP_CORPUS, len(files)))

    texts = {}
    for rel, path in files:
        try:
            c, cpp = compile_program(rel, path, cpp_backend=True)
        except AssertionError as e:
            failures.append(str(e))
            continue
        texts[rel] = cpp
        if not cpp.strip():
            failures.append('%s: MOJO_CORO=cpp produced an EMPTY companion — '
                            'this program no longer drives the C++ lowering' % rel)
            continue
        # The oracle must fold both texts in.  A hash equal to either one alone
        # means the other is invisible to `check`, which is the bug this test
        # exists for.
        hashed = oracle.hash_tree(ROOT, [(rel, path)], 1, cpp=True).get(rel, '')
        if hashed.startswith('ERR'):
            failures.append('%s: oracle refuses the program: %s' % (rel, hashed))
            continue
        if hashed != hashlib.md5((c + '\0' + cpp).encode()).hexdigest():
            failures.append('%s: oracle hash %r is not md5(C + companion)'
                            % (rel, hashed))
        elif hashed == hashlib.md5(c.encode()).hexdigest():
            failures.append('%s: oracle hash is md5(C) alone — the companion is '
                            'not hashed' % rel)
        elif hashed == hashlib.md5(cpp.encode()).hexdigest():
            failures.append('%s: oracle hash is md5(companion) alone — the C side '
                            'is not hashed' % rel)

    joined = '\n'.join(texts.values())
    for shape in SHAPES:
        if shape not in joined:
            failures.append('no corpus program emits `%s`: the corpus does not '
                            'reach that promise shape' % shape)

    # Why the second corpus: the first one cannot see the lowering at all.
    if files:
        rel, path = files[0]
        try:
            _, cpp_default = compile_program(rel, path, cpp_backend=False)
        except AssertionError as e:
            failures.append('default-backend compile of %s: %s' % (rel, e))
        else:
            if cpp_default.strip():
                failures.append(
                    'the DEFAULT coroutine backend now emits a companion for %s '
                    '(%d chars); re-derive doc/GIR.md stage 7 and whether the '
                    'second corpus is still needed before moving it into the '
                    'first one' % (rel, len(cpp_default)))

    for f in failures:
        print('FAIL: ' + f)
    print('%d program(s), %d shape(s), %d failure(s)'
          % (len(files), len(SHAPES), len(failures)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
