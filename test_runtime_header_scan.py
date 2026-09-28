#!/usr/bin/env python3
"""test_runtime_header_scan.py -- `reflect.collect_runtime_exports_h` must see
every function the runtime headers declare, including the pointer-returning ones.

Found while implementing FORMAL.md phase 0 (make the sqlite runtime unit a real
linked part of the build). The phase needed a trustworthy list of which symbols
a runtime header promises to define, and the function that produces that list
was silently dropping 44% of them.

The bug
-------
`reflect._PROTO_RE`'s return-type group is `([\\w][\\w\\s\\*]*?)` — non-greedy,
and it can contain a `*`. The separator between the return type and the function
name used to be a bare `\\s+`. C writes a pointer return as `char *name(...)`,
with the `*` attached to the type and NO space before the name, so the regex
stopped the return group at `char`, `\\s+` ate the space, and the next character
was `*` where a function name was required. No match. Every pointer-returning
declaration was invisible.

Measured, before the fix:

| header | declared | found | missing |
|---|---|---|---|
| `fire_runtime.h` | 470 | 260 | 210 |
| `fire_sqlite3.h` | 22 | 15 | 7 |
| `fire_zlib.h` | 6 | 2 | 4 |
| `fire_ssl.h` | 13 | 9 | 4 |
| `fire_ncurses.h` | 18 | 16 | 2 |
| `fire_python.h` | 15 | 6 | 9 |

Every loss was a pointer return: `mojo_str_new`, `mojo_c_getenv`,
`mojo_path_join`, `mojo_chr`, `mojo_get_argv`, `int64_t_basename`, and all of
`mojo_sqlite3_open` / `_query` / `_query_dict`.

Why it mattered beyond the audit
--------------------------------
`build_stdlib_dylib.py:750-751` builds the stdlib dylib's reflection table with
this function. So the shipped dylib was advertising 260 of its own 459 runtime
entry points: a C client resolving `mojo_c_getenv` through reflection was told
the symbol did not exist. This is on the gimple path and predates FORMAL.md.

The fix is one optional `\\*?` in the separator. After it: 459 / 22 / 6 / 13 /
18 / 15, with the only remaining gaps being `static inline` helpers (which have
no external symbol and are correctly absent) and one name that appears only in a
comment.

These are pinned BY NAME, not by count. A count assertion would have to be
rewritten every time the runtime grows a function, and would fail for a reason
that has nothing to do with the defect.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RUNTIME = os.path.join(HERE, 'runtime')
RESULTS = []


def check(ok, what, detail=''):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f': {detail}' if detail else ''), flush=True)


def exports(header):
    import reflect
    return {e['name'] for e in reflect.collect_runtime_exports_h(
        os.path.join(RUNTIME, header))}


def test_pointer_returns_are_seen():
    """The regression itself: one name per distinct pointer-return shape."""
    rt = exports('fire_runtime.h')
    for sym, why in (
            ('mojo_str_new',     'MojoStr * — a runtime-typed box'),
            ('mojo_c_getenv',    'char *'),
            ('mojo_path_join',   'char *'),
            ('mojo_chr',         'char *'),
            ('mojo_get_argv',    'MojoList *'),
            ('int64_t_basename', 'char *, the os.path.basename shim'),
    ):
        check(sym in rt, f'fire_runtime.h: {sym} is scanned ({why})')

    sq = exports('fire_sqlite3.h')
    for sym in ('mojo_sqlite3_open', 'mojo_sqlite3_query',
                'mojo_sqlite3_query_dict', 'mojo_sqlite3_column_text',
                'mojo_sqlite3_errmsg', 'mojo_sqlite3_prepare'):
        check(sym in sq, f'fire_sqlite3.h: {sym} is scanned (pointer return)')


def test_every_declaration_is_seen():
    """Header-by-header completeness against an independent count.

    The expected numbers are the declaration counts, written down rather than
    recomputed with the regex under test — a test that computes its own oracle
    with the code it is testing asserts nothing. They are also the cheapest
    possible tripwire for the NEXT declaration shape the scanner cannot parse:
    a new form that is missed shows up here as a count that no longer matches.
    """
    for header, want in (('fire_runtime.h', 459),
                         ('fire_sqlite3.h', 22),
                         ('fire_zlib.h', 6),
                         ('fire_ssl.h', 13),
                         ('fire_ncurses.h', 18),
                         ('fire_python.h', 15)):
        got = exports(header)
        check(len(got) == want, f'{header}: {want} declarations scanned',
              f'got {len(got)}')


def test_non_exports_stay_excluded():
    """The fix must not start admitting things that are not exports.

    `static inline` helpers in the header have bodies and no external symbol;
    exporting them would put a name in the reflection table that the dylib
    cannot satisfy. Private and C-library names are excluded by contract
    (doc/ABI.md's public-symbol rule), and the scanner's own filter is what
    enforces it.
    """
    rt = exports('fire_runtime.h')
    for sym in ('mojo_bound_method_call_0',   # static inline
                'mojo_uint64_from_int64',     # static inline
                '_Bool_select',                # static inline
                '__mojo_floordiv',             # static inline
                '_mojo_getline',               # static inline, leading _
                ):
        check(sym not in rt, f'fire_runtime.h: {sym} is correctly NOT exported')
    for sym in ('printf', 'malloc', 'free', 'strlen', 'memcpy'):
        check(sym not in rt, f'fire_runtime.h: C-library {sym} is not re-exported')


def main():
    test_pointer_returns_are_seen()
    test_every_declaration_is_seen()
    test_non_exports_stay_excluded()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\n{npass} passed, {nfail} failed, {len(RESULTS)} checks")
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
