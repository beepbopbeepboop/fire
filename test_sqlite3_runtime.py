#!/usr/bin/env python3
"""test_sqlite3_runtime.py -- the optional runtime units are a real build rule.

`runtime/` holds six C translation units. Exactly one of them, `fire_runtime.c`,
was in a build path. The headers of the other four were `#include`d
UNCONDITIONALLY into every generated translation unit, and all 59 of their
signatures sat in `gimple_codegen._KNOWN_SIGS` -- so a program calling
`mojo_sqlite3_open` saw a prototype, compiled clean, and died at link:

    Linking failed: Undefined symbols for architecture arm64:
      "_mojo_sqlite3_close", ... "_mojo_sqlite3_query"

Nothing noticed, because no suite entry built any `test_sqlite3*.mojo` and no
`.mojo` file in the tree calls any of these namespaces. See
bugs/CODEGEN_optional_runtime_units_not_linked.md.

What is pinned here
-------------------
Three things, in increasing order of how much they would hurt if they broke:

1. **The table is derived, not hand-kept.** Each unit's `mojo_<unit>_`
   namespace is the longest common prefix of what
   `reflect.collect_runtime_exports_h` reports for that unit's own header, and
   the link line follows from the generated C. A hand-copied symbol list is the
   rot this removes, so a test asserts the derivation still holds and still
   covers exactly its own symbols.

2. **Both link pipelines.** `fire.py build` goes through
   `driver.compile_program` and only falls back to `build_executable`, so
   patching one changes nothing observable. That is not a hypothetical: the
   first attempt at this fix did exactly that and appeared to do nothing.

3. **The programs build, LINK and RUN.** "It builds" is not "it works":
   `test_sqlite3_simple.mojo` used to call `mojo_print(n)` with an `int64` row
   count, and `mojo_print` is the raw runtime sink declared
   `void mojo_print(char *str)` -- so it dereferenced an integer as a pointer
   and segfaulted. That was found only because the link got fixed far enough to
   run the program. Everything below therefore RUNS the artifact and compares
   stdout.

And the negative half, which is the half that is easy to get wrong: a program
that never mentions sqlite must not link libsqlite3. A probe that matches too
eagerly is not a harmless conservatism -- see `test_probe_ignores_mentions`.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_config
import gimple_codegen

RESULTS = []
# Artifacts land under build/, named after this test, so two agents running
# different tests in a shared checkout cannot collide (FORMAL.md §11.3).
# The name deliberately contains no unit namespace: `otool -L` prints the
# binary's own path as its first line, so a directory called `sqlite3rt` makes
# the "does not link sqlite3" check match ITSELF. Measured, and it is the kind
# of thing that would have looked like a registry bug.
WORK = os.path.join(HERE, 'build', 'opt_runtime')

_SQLITE_SOURCES = ('test_sqlite3.mojo', 'test_sqlite3_simple.mojo',
                   'test_sqlite3_min.mojo', 'test_sqlite3_len.mojo',
                   'test_sqlite3_query.mojo')


def check(ok, what, detail=''):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f': {detail}' if detail else ''), flush=True)
    return bool(ok)


def step(msg):
    """Progress. The build checks below run ten real compiles, which is minutes
    of apparent silence; a test that looks hung gets killed and reported as
    flaky rather than as slow."""
    print(f"  ... {msg}", flush=True)


def skip(what, why):
    print(f"  skip  {what}: {why}", flush=True)


def _run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def _otool_deps(binary):
    """Dylibs the linked image actually records, or None if not inspectable."""
    if not os.path.exists(binary):
        return None
    if sys.platform != 'darwin':
        # `readelf -d` is the equivalent; nothing here is macOS-specific enough
        # to be worth a second code path in a test that exists to catch a
        # missing link line, and a Linux run is not the platform this was found
        # on. Reported as unknown rather than as "clean".
        return None
    r = _run(['otool', '-L', binary])
    if r.returncode != 0:
        return None
    return r.stdout


# ---------------------------------------------------------------------------
# 1. The table
# ---------------------------------------------------------------------------

def test_registry_is_derived_from_the_headers():
    """Each namespace covers exactly its own unit's symbols, and no other.

    Pinned by name per unit rather than by total count, for the reason
    test_runtime_header_scan.py gives: a count has to be rewritten every time
    the runtime gains or loses a function, and fails for a reason unrelated to
    the defect."""
    for unit, n_expected in (('sqlite3', 22), ('zlib', 6), ('ssl', 13),
                             ('ncurses', 18)):
        syms = build_config.optional_unit_symbols(unit)
        ns = build_config.optional_unit_namespace(unit)
        check(len(syms) == n_expected,
              f'{unit}: header declares {n_expected} symbols', f'got {len(syms)}')
        check(ns == f'mojo_{unit}_',
              f'{unit}: namespace is mojo_{unit}_', f'got {ns!r}')
        check(all(s.startswith(ns) for s in syms),
              f'{unit}: every declared symbol is inside its own namespace')
        check(build_config.optional_unit_source(unit).endswith(f'fire_{unit}.c')
              and os.path.exists(build_config.optional_unit_source(unit)),
              f'{unit}: its source exists and is named for it')
        check(build_config.optional_unit_libs(unit),
              f'{unit}: it has link flags', str(build_config.optional_unit_libs(unit)))


def test_fire_python_is_deliberately_excluded():
    """fire_python.c is NOT in the registry, and must stay out.

    Its whole surface is `#if USE_PYTHON 0` stubs, so linking it would trade a
    loud link error for a silent NULL from every `mojo_python_*` call -- a
    strictly worse failure. Its header is not `#include`d either, so a program
    that calls into it still gets the loud error. 'Add every runtime unit' is
    the wrong instinct here and this is what says so."""
    check('python' not in build_config.optional_unit_names(),
          'fire_python.c is not a registry unit',
          str(build_config.optional_unit_names()))
    header = os.path.join(build_config.runtime_dir(), 'fire_python.h')
    gen = gimple_codegen.compile_to_gimple_cached('fn main():\n    print(1)\n',
                                                  do_imports=True,
                                                  filename='x.mojo')
    check('fire_python.h' not in gen,
          'and its header is still not #include-d into generated C')


# ---------------------------------------------------------------------------
# 2. The probe
# ---------------------------------------------------------------------------

def test_probe_distinguishes_calls_from_mentions():
    """The probe must fire on a CALL and not on a mention.

    This is not a refinement. `gimple_codegen._KNOWN_SIGS` carries all 59
    optional-unit signatures as STRING KEYS, so any build that compiles the
    compiler itself -- every `make mojoc` -- has every unit's symbol names
    sitting in the generated C as string-literal data. A plain "does the
    namespace appear" test therefore matches all four units for a program that
    calls none of them, and the measured cost is that the project's own
    compiler cannot be built without four system development packages
    installed: on a machine with no OpenSSL, `fire.py build fire.py` tried to
    compile fire_ssl.c because `_KNOWN_SIGS['mojo_ssl_context_new']` is a
    string in the output.

    The imprecision is deliberately on the quiet side: a unit used in a shape
    the probe does not recognise is MISSED, and a missed unit is a loud
    `Undefined symbols` at link. A spurious unit is a needless dependency."""
    cases = (
        ('int x = mojo_sqlite3_open(0);',            ['sqlite3'], 'a real call'),
        ('void *c = mojo_ssl_context_new ();',       ['ssl'],
         'a call, with the whitespace this codegen emits before the args'),
        ('int64_t z = mojo_zlib_crc32(0, s, 4);',    ['zlib'], 'a real call'),
        ('void *w = mojo_ncurses_init();',           ['ncurses'], 'a real call'),
        ('mojo_dict_set_int(d, "mojo_ssl_context_new", v);', [],
         'the _KNOWN_SIGS shape: a quoted dict key, not a call'),
        ('const char *s = "mojo_sqlite3_open is handy";', [],
         'a string literal that merely contains the name'),
        ('static char *s = "we mention mojo_ncurses_getch in prose";', [],
         'a docstring, which reaches the generated C as a _slit initializer'),
        # A call-shaped fragment INSIDE a literal. The quote is at the start of
        # the literal, so "is the name preceded by a quote" says no, and the
        # name is followed by `(` -- which is exactly how the compiler's own
        # closure used to match `metal`: a code generator that emits C from
        # Python string templates has those templates in its own source, and
        # compiling the compiler inlines them as _slit initializers.
        ('static char *s = "  x = (int64_t) mojo_metal_init(src);";', [],
         'a call-shaped fragment inside a string literal'),
        ('/* real code: mojo_zlib_crc32(a, b, c) */',  [],
         'a call-shaped fragment inside a comment'),
        ('int main(void) { return 0; }',             [], 'nothing at all'),
    )
    for code, want, why in cases:
        got = build_config.referenced_optional_runtime_units(code)
        check(got == want, f'probe: {why}', f'want {want}, got {got}')


def test_probe_ignores_mentions():
    """The self-host case specifically: the compiler's own generated C.

    Cheapest way to state the whole regression: compiling the compiler must not
    pull in any optional unit, because nothing in it calls one. Asserted on a
    real codegen run rather than on a synthetic string, since the string that
    broke it was 59 real signatures."""
    gen = gimple_codegen.compile_to_gimple_cached(
        'from build_config import find_gcc\n'
        'def main():\n'
        '    print(find_gcc())\n', do_imports=True, filename='probe.mojo')
    hits = build_config.referenced_optional_runtime_units(gen)
    check(hits == [],
          'compiling a module that imports build_config pulls in NO optional '
          'unit (their symbols are in the generated C only as string data)',
          str(hits))


# ---------------------------------------------------------------------------
# 3. End to end: build, link, RUN
# ---------------------------------------------------------------------------

def _build_and_run(src_name, pipeline):
    """Build one .mojo through `pipeline` and return (rc, stdout)."""
    os.makedirs(WORK, exist_ok=True)
    src = os.path.join(HERE, src_name)
    out = os.path.join(WORK, f'{pipeline}_{os.path.splitext(src_name)[0]}')
    if pipeline == 'link':
        r = _run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                  '-o', out, src], cwd=HERE)
    else:
        # The fallback pipeline, driven directly. `fire.py build` only reaches
        # it when the link-mode path returns None, so calling it here is what
        # makes the SECOND pipeline covered rather than assumed.
        code = ('import fire, sys\n'
                'ok = fire.build_executable(sys.argv[1], open(sys.argv[1]).read(),'
                ' output=sys.argv[2], quiet=True)\n'
                'sys.exit(0 if ok else 1)\n')
        r = _run([sys.executable, '-c', code, src, out], cwd=HERE)
    if r.returncode != 0 or not os.path.exists(out):
        return None, r.stdout + r.stderr
    p = _run([out])
    return p.returncode, p.stdout


def test_programs_build_link_and_run():
    """Both pipelines, every test_sqlite3*.mojo, and the OUTPUT compared.

    The expected outputs are written out rather than recomputed, so this cannot
    agree with a broken build by construction."""
    expect = {
        'test_sqlite3.mojo':
            'rows:\n1\nhello\n2\nworld\n',
        'test_sqlite3_simple.mojo': '3\n',
        'test_sqlite3_len.mojo': '2\n',
        # These two print nothing at all -- not even a blank line. Written out
        # as empty strings rather than assumed, because a program that segfaults
        # before its first print also produces empty output.
        'test_sqlite3_min.mojo': '',
        'test_sqlite3_query.mojo': '',
    }
    for pipeline in ('link', 'fallback'):
        for name in _SQLITE_SOURCES:
            if name not in expect:
                continue
            step(f'{pipeline}: building {name}')
            rc, out = _build_and_run(name, pipeline)
            if rc is None:
                check(False, f'{pipeline}: {name} builds and links', out[-400:])
                continue
            check(rc == 0, f'{pipeline}: {name} RUNS (exit 0)', f'rc={rc}')
            check(out == expect[name],
                  f'{pipeline}: {name} prints the expected output',
                  f'want {expect[name]!r}, got {out!r}')


def test_a_program_without_sqlite_does_not_link_it():
    step('building a program that mentions no optional unit')
    """The negative half.

    Also asserted on the link line, not only on the absence of a build failure:
    a registry that always links every unit builds fine and is still wrong."""
    os.makedirs(WORK, exist_ok=True)
    src = os.path.join(WORK, 'plain.mojo')
    with open(src, 'w') as f:
        f.write('fn main():\n    print(1 + 1)\n')
    out = os.path.join(WORK, 'plain')
    r = _run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
              '-o', out, src], cwd=HERE)
    if not check(r.returncode == 0, 'a program that never mentions sqlite builds',
                 r.stdout[-400:] + r.stderr[-400:]):
        return
    p = _run([out])
    check(p.returncode == 0 and p.stdout.strip() == '2',
          'and runs', f'rc={p.returncode} out={p.stdout!r}')
    deps = _otool_deps(out)
    if deps is None:
        skip('link-line inspection', 'otool unavailable or not macOS')
        return
    for lib in ('sqlite3', 'libz', 'libssl', 'libcrypto', 'ncurses'):
        check(lib not in deps, f'and does NOT link {lib}')


def test_sqlite_program_does_link_sqlite():
    step('building the sqlite program to inspect its link line')
    """The positive half of the same assertion, so the check above cannot pass
    because the probe is dead rather than because it is precise."""
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, 'withsqlite')
    r = _run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', '-o', out,
              os.path.join(HERE, 'test_sqlite3.mojo')], cwd=HERE)
    if not check(r.returncode == 0, 'the sqlite program builds', r.stderr[-300:]):
        return
    deps = _otool_deps(out)
    if deps is None:
        skip('link-line inspection', 'otool unavailable or not macOS')
        return
    check('sqlite3' in deps, 'and it DOES link libsqlite3',
          '\n'.join(deps.splitlines()[:8]))


def test_a_failing_unit_names_itself():
    """The one diagnostic both pipelines print when a unit does not compile.

    `fire_ssl.c` does `#include <openssl/ssl.h>` and OpenSSL is not installed
    on every machine, so this path is reachable rather than hypothetical. A
    diagnostic that says which unit and which dev package is the difference
    between a five-second fix and an afternoon; `driver.py` used to raise a
    bare CalledProcessError here, on the path `fire.py build` normally takes,
    whose argv named a temp .o and no unit at all."""
    msg = build_config.optional_unit_compile_failed(
        'ssl', '/x/runtime/fire_ssl.c',
        'fire_ssl.c:2:10: fatal error: openssl/ssl.h: No such file or directory')
    check('ssl' in msg, 'the diagnostic names the unit')
    check('/x/runtime/fire_ssl.c' in msg, 'and the source file')
    check('openssl/ssl.h' in msg, "and the compiler's own error, verbatim")
    check('libssl-dev' in msg, 'and the development package to install')


def main():
    test_registry_is_derived_from_the_headers()
    test_fire_python_is_deliberately_excluded()
    test_probe_distinguishes_calls_from_mentions()
    test_probe_ignores_mentions()
    test_programs_build_link_and_run()
    test_a_program_without_sqlite_does_not_link_it()
    test_sqlite_program_does_link_sqlite()
    test_a_failing_unit_names_itself()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\n{npass} passed, {nfail} failed, {len(RESULTS)} checks")
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
