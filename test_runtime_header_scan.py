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

    The tripwire cuts both ways, and it has now fired in both directions.
    459 -> 447: seven prototypes that no object in the tree defines and no
    generated C calls were removed from `fire_runtime.h` (`mojo_type`,
    `mojo_obj_enter`, `mojo_obj_exit`, `int___enter__`, `int___exit__`,
    `MojoList__write_to`, `tuple` — see the note in that header), and the header
    scanner then stopped reporting five `mojo_fnptr_call_N` names it had been
    inventing out of a `return mojo_fnptr_call_0(f);` line inside a `static
    inline` body. The steps are separately attributable: 459->452 is the
    header, 452->447 is the scanner.

    447 -> 448: `mojo_type` went BACK IN, and it is the sixth name on that list
    whose removal was wrong. The zero-caller evidence for removing it was `nm`
    on the runtime OBJECT, and the caller is not in the runtime:
    `gimple_codegen._RUNTIME_FUNCS` maps the Mojo builtin `type` to this C
    function, so generated C emits a reference to it, and with the declaration
    gone the self-hosted compile of the compiler's own closure failed with
        myinterpreter.py: error: 'mojo_type' undeclared here (not in a
        function); did you mean '_mojo_type'?
    "not in a function" is the tell that the reference is in a DECLARATION —
    a prototype the imported-symbol extern block emits for a builtin it
    resolved to this name — and not a call. So the lesson generalises past this
    one symbol: a runtime symbol with no in-tree caller can still be reachable
    from GENERATED code, and `nm` on the runtime cannot see that. It is
    re-added as `int mojo_type(int obj)` rather than the old `int
    mojo_type(...)`, because a `(...)` with no named parameter before it is a
    hard error in clang, which is what the removal was for in the first place.
    """
    # 450 (before the 451 note below). Three different numbers have been asserted here and all three were
    # right on the tree that produced them, which is why this is measured
    # rather than adjusted:
    #
    #   459  the original regex-based scanner, original header.
    #   456  after [3] rewrote `reflect._PROTO_RE` into a real parser. It moved
    #        DOWN while the scanner got strictly more correct, in both
    #        directions at once:
    #          -5  `mojo_fnptr_call_0..4` are `static inline`
    #              (fire_runtime.h:116) with no external symbol, so they must
    #              NOT be exported. The regex counted them anyway, which made
    #              the old 459 inconsistent with the exclusion rule asserted
    #              elsewhere in this file.
    #          +2  `mojo_re_sub_fn` and `mojo_regex_sub_fn` take a
    #              FUNCTION-POINTER parameter, `char *(*callback)(void *, char
    #              *)`, and the regex's `([^)]*)` parameter group stopped at
    #              the first `)` -- which is inside the function-pointer type.
    #              It could not see them at all.
    #   448  [1]+[2]'s figure, on THEIR header. It is not comparable to 456:
    #        [1] and [2] edit fire_runtime.{h,c} themselves (they removed five
    #        dead declarations and restored `mojo_type`), and they measured
    #        with the OLD scanner, because [3]'s reflect.py was not in their
    #        tree -- [1]'s own message says so.
    #
    # So 450 is 456 with [1]+[2]'s header under [3]'s scanner, and the other
    # five headers are unchanged at 22/6/13/18/15 across every version. The
    # composition is verified, not just the total: `mojo_type` is present with
    # the non-variadic `int mojo_type(int obj)` prototype, the five `static
    # inline` helpers are still excluded, both function-pointer entry points
    # are still included, and all five removed declarations are still absent.
    # 450 -> 451 (2026-09-28): `mojo_cstr_or_int_release`, the free half of
    # `mojo_cstr_or_int_str`'s ownership contract (doc/MEMORY.html section 4).
    # 464 -> 465 (2026-09-29): mojo_dict_slot_key, the accessor that builds an integer
    # key's decimal string on demand (generated repr code read the field directly).
    # 462 -> 464 (2026-09-28): mojo_dict_iter_key_int and mojo_dict_items_int, the
    # integer-key readers for a loop over a Dict[Int, V].
    # 452 -> 462 (2026-09-28): the ten `mojo_dict_*_kw` entry points (integer dict
    # keys passed as a raw word; doc/MEMORY.html section 10.4).
    # 451 -> 452 (2026-09-28): `mojo_cleanup_push_ptr`, the cleanup-stack kind
    # for an owned struct instance (doc/MEMORY.html section 3.B).
    # 465 -> 474 (2026-09-29): the per-slot-kind side table on a MojoList
    # (`mojo_list_set_kinds` / `_get_kinds` / `_slot_kind` /
    # `_inherit_kinds`) and the box that carries an element kind out of a slot
    # whose index is not a compile-time constant (`mojo_list_get_boxed`,
    # `mojo_is_boxed`, `mojo_box_double`, `mojo_box_int`, `mojo_repr_boxed`) —
    # see bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md.
    # 474 -> 476 (2026-09-30): `mojo_list_free_owned_strs` and
    # `mojo_cleanup_push_list_strs`, the free and the matching cleanup thunk
    # for a list that owns its own string elements (a `split()` result) — see
    # bugs/CODEGEN_call_result_container_never_freed.md and
    # mojo/backend_gimple/emit_infra.py's `_OWNS_STR_ELEMS`.
    # 476 -> 479 (2026-09-30): `mojo_bound_method_free` and `mojo_closure_free`
    # (the two frees for the two things a bound method can be — a method value
    # whose `self` belongs to the receiver, and a capturing lambda whose `self`
    # is the environment its constructor allocated with it; the first is what
    # discards the `_reg_bound_method` entry, which is what makes freeing one
    # safe at all) and `mojo_cleanup_push_closure`, their unwind thunk — see
    # bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md.
    for header, want in (('fire_runtime.h', 479),
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
