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

The fix is one optional `\\*?` in the separator. After it, on the 2026-09-27 tree
it read 459 / 22 / 6 / 13 / 18 / 15 — a DATED reading, kept as the record of
that fix, and not the scanner's current output: `fire_runtime.h` has grown
since, and the ladder in `test_every_declaration_is_seen` is the current one.
The only remaining gaps were `static inline` helpers (which have no external
symbol and are correctly absent) and one name that appears only in a comment.

`test_the_quoted_census_is_the_live_census` at the bottom is the check that
keeps the OTHER copies of these numbers honest: five places in the tree quote
the census in prose, and every one of them had gone stale at the same time,
because nothing compared them with the headers they describe. That check now
runs in both directions — `python3 test_runtime_header_scan.py --fix` writes the
live census into every one of those quotes from the same table the check reads,
so the two ends of this file cannot drift apart, and a commit that adds a
runtime declaration does not have to remember which six sentences quoted the
number it changed. (`bugs/FORMAL_known_limits.md` quotes the census in more
sentences than the five above; every one of them is in the table, which is why
a change to that document's wording can now fail this file.)

These are pinned BY NAME, not by count. A count assertion would have to be
rewritten every time the runtime grows a function, and would fail for a reason
that has nothing to do with the defect.
"""
import os
import re
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

    # The count in test_every_declaration_is_seen moved 465 -> 476 for these;
    # the composition is verified here rather than trusted from the total, in
    # the same spirit as the `mojo_type` note above — a runtime symbol with no
    # in-tree caller can still be reachable from GENERATED code, and every one
    # of these is emitted by the compiler, not called from the runtime.
    for sym in ('mojo_vararg_fn_new',      # _lower_LambdaExpr / _lower_IdentExpr
                'mojo_is_vararg_fn',       # inside every mojo_fnptr_call_N
                'mojo_vararg_call_0',      # reached from the inline helpers
                'mojo_vararg_call_4',
                'mojo_vararg_call_8'):
        check(sym in rt, f'fire_runtime.h: {sym} is scanned (variadic callable)')


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
    # 465 -> 466: mojo_stream_write, the fd-keyed `sys.stdout.write` entry point
    # (a POSIX fd boxed as an opaque handle, so `.write()` on it has to resolve
    # against the fd rather than a FILE*; without it the call fell through to
    # `int_write(1, s)`, treating the integer 1 as a FILE*).
    # 464 -> 465 (2026-09-29): mojo_dict_slot_key, the accessor that builds an integer
    # key's decimal string on demand (generated repr code read the field directly).
    # 465 -> 476 (2026-09-29): the VARIADIC callable entry points —
    # `mojo_vararg_fn_new` and `mojo_is_vararg_fn`, plus
    # `mojo_vararg_call_0..8`. All eleven are real (non-`static`) declarations
    # in fire_runtime.c and all eleven are reachable from GENERATED code, which
    # is the lesson this file has already paid for twice over `mojo_type`:
    # `mojo_vararg_fn_new` is emitted by `_lower_LambdaExpr` (and, for a named
    # `*args`/`**kwargs` function, by `_lower_IdentExpr`), and
    # `mojo_vararg_call_N` is what the `mojo_fnptr_call_N` / `mojo_maybe_bound_
    # call_N` inline helpers call. The 20 new `mojo_fnptr_call_kw_N` /
    # `mojo_maybe_bound_call_kw_N` / arity-5..8 helpers are `static inline`
    # and are correctly NOT counted, exactly like the arity-0..4 family they
    # extend — `test_non_exports_stay_excluded` now pins that too.
    # 462 -> 464 (2026-09-28): mojo_dict_iter_key_int and mojo_dict_items_int, the
    # integer-key readers for a loop over a Dict[Int, V].
    # 452 -> 462 (2026-09-28): the ten `mojo_dict_*_kw` entry points (integer dict
    # keys passed as a raw word; doc/MEMORY.html section 10.4).
    # 451 -> 452 (2026-09-28): `mojo_cleanup_push_ptr`, the cleanup-stack kind
    # for an owned struct instance (doc/MEMORY.html section 3.B).
    # 465 -> 475. Two independent additions, so the counts ADD rather than
    # either side winning:
    #   465 -> 474 (integ, 2026-09-29): the per-slot-kind side table on a
    #   MojoList (`mojo_list_set_kinds` / `_get_kinds` / `_slot_kind` /
    #   `_inherit_kinds`) and the box that carries an element kind out of a
    #   slot whose index is not a compile-time constant (`mojo_list_get_boxed`,
    #   `mojo_is_boxed`, `mojo_box_double`, `mojo_box_int`, `mojo_repr_boxed`)
    #   -- the mechanism for a heterogeneous element read is documented at
    #   those definitions in runtime/fire_runtime.c.
    #   465 -> 466 (metal): one more entry point, from the self-host closure
    #   work in d446f5be.
    # Verified by COUNTING the merged header, not by adding the two deltas:
    # `reflect.collect_runtime_exports_h('runtime/fire_runtime.h')` returns 480
    # on the merged tree. Take this number from that call, not from the
    # arithmetic -- that is the whole point of the check.
    #
    # 479 -> 480 (2026-09-30): `mojo_str_from_double`, the float dict-key
    # formatter. It was defined in fire_runtime.c and CALLED by generated code
    # (emit_infra.py's dict-key path) with no declaration in the header, so the
    # emitted `.ci` prototype came from the compiler's own inference rather
    # than from the header this scan reads -- the exact gap the scan exists to
    # close, found by the scan rather than by a link error.
    #
    # 475 -> 479 (2026-09-30): the four container value-equality entry points
    # (`mojo_list_eq` / `mojo_dict_eq` / `mojo_set_eq` / `mojo_value_eq`). They
    # are declared here rather than in their container's own section because
    # unlike every other comparison primitive all three container types have to
    # be complete first -- see “CODEGEN: `==` / `!=` between two containers is POINTER identity”.
    #
    # 479 -> 521 (2026-10-01): three finished branches merged over this tree,
    # each of which added runtime entry points -- the bytes/memoryview surface
    # (`mojo_bytes_*`), the tuple-mutability guards and the vararg-lambda
    # dispatch behind `MojoVarargFn`. The delta is NOT derived from the three
    # branches' own arithmetic, which is the mistake this check exists to
    # catch: `reflect.collect_runtime_exports_h('runtime/fire_runtime.h')`
    # returns 521 on the merged header, and that call is where the number comes
    # from.
    # 521 -> 526 (2026-10-01, `compiled-silent`): the `double`-returning twins
    # of the function-pointer dispatch helpers (`mojo_fnptr_call_d0..d4`), plus
    # the sort primitive the `list.sort()` fix moved four orderings onto.
    # Again taken from the call, not from the arithmetic.
    # 526 -> 531 (2026-10-01, `memory-ownership`): the two frees for the two
    # things a bound method can be — `mojo_bound_method_free` and
    # `mojo_closure_free` — and their cleanup thunks. Taken from the call.
# 531 -> 532 (2026-10-01, merging batch 1 in): `mojo_str_from_double`, the
    # 479 -> 480 entry above, which no branch that landed on THIS side of the
    # merge had. One name, and it is the whole delta -- which is exactly why
    # the number is read off the call and never added up: 531 + 1 is right here and
    # would have been wrong on any other pair of sides.
    # 532 -> 537 (2026-10-01, `bugs-container-compare`): the container ORDERING
    # entry points, which are to `<` / `<=` / `>` / `>=` between containers what
    # `mojo_*_eq` / `mojo_value_eq` were to `==` / `!=` --
    # `mojo_list_cmp`, `mojo_set_cmp`, `mojo_value_cmp`, `mojo_cmp_fold`, and
    # `mojo_bytes_cmp` (the three-way sibling of `mojo_bytes_eq`, needed for a
    # bytes ELEMENT of an ordered container). Five, taken from the call.
    # 537 -> 539 (2026-10-01, `bugs-container-compare` again, the tuple dict-key
    # work): `mojo_dict_key_for` and `mojo_dict_key_free` — the CONTENT key a
    # tuple used as a dict key is stored and looked up under, replacing the
    # object's address. Two, taken from the call.
    # 539 -> 541 (2026-10-01, the rest of the bug batch, merged over the two
    # container-compare entries above): two names in and one net change out, so
    # the total is NOT theirs plus these:
    #   +1  `mojo_int_str_transient` (`bugs-segfaults`) — the decimal spelling
    #       of an integer dict key above 2 GiB, which cannot be a borrowed
    #       8-byte buffer and needs its own allocator's lifetime.
    #   +1  `mojo_repr_list_slotkinds` (`bugs-silent-values-b`) — the repr of a
    #       list whose per-slot kinds now travel with the value.
    #   +2/-2, net zero (`bugs-silent-values-a`): `mojo_dict_set_bool` and
    #       `mojo_dict_set_bytes_bool` REPLACE `mojo_is_bool_dict` and
    #       `mojo_mark_dict_bool_values`. The pair that went away marked a dict
    #       as bool-valued and read the flag off it; the pair that arrived sets
    #       the value's kind at the store, which is what stops one bool value
    #       from poisoning its neighbours' repr.

    # 541 -> 543 (2026-10-02, `bugs3-codegen-5-r2`), for the container ELEMENT
    # repr: `mojo_list_set_elem_repr` (what the codegen emits on every
    # list/tuple literal whose element type is a registered struct) and
    # `mojo_list_repr_elem` (what both repr walkers ask per slot). Two,
    # taken from the call.
    # 543 -> 545 (2026-10-02, `bugs4-6-c`), for a dict slot that holds a
    # Python `None`: `mojo_dict_set_none` and its bytes-key twin
    # `mojo_dict_set_bytes_none`. Two, not one, for the same reason
    # `mojo_dict_set_bytes_bool` exists beside `mojo_dict_set_bool` — a bytes
    # key is its own key domain (`_DictSlot.keykind`), so it needs its own
    # setter. The value kind they tag (`kind == 4`) is what lets `{'z': 0}`
    # print `0` while `{'n': None}` prints `None` from one generic value
    # repr, whose `val == 0` arm has to answer "None" for a NULL pointer
    # slot; before this, every plain zero in every dict printed as `None`.
    #
    # NOT 544 in between: neither of these two needs a `-bytes_` DOUBLE twin
    # for its own sake, because the float setter that already existed is
    # dispatched by the shared `emit_dict_int_value_store` on `key_ctype`
    # (`mojo_dict_set_bytes_double` was in the header already). A new value
    # KIND needs a new setter; a value shape that already had one does not
    # get a second spelling of it.
    # 545 -> 551 (2026-10-02, `bugs4-6-c`), for a STRUCT stored as a dict
    # value: `mojo_dict_set_struct` / `mojo_dict_set_val_repr` /
    # `mojo_dict_repr_val` and the pair `mojo_dict_set_bytes_struct` /
    # `mojo_dict_set_bytes_other_struct` — six, taken from the call. The
    # `other_struct` pair exists because the dict records ONE repr function
    # (a property of the dict) while the tag is per SLOT, so a second struct
    # type needs its own tag (`kind == 6`) rather than being handed the first
    # type's repr; without it `{'a': p, 'b': q}` printed q's repr twice, which
    # is a wild read and not merely a wrong string. Four of the six are
    # `_bytes_` twins of the same shape as `mojo_dict_set_bytes_bool`, so the
    # key DOMAIN keeps exactly one spelling per value shape.
    #
    # NOT 542 in between: `bugs3-codegen-1-r2` added
    # `mojo_require_str_arg`, the runtime half of a str-annotated parameter
    # given an int RAISING a catchable TypeError, and that is a different
    # answer to the same question `codegen-3-r2`'s `_stringify_value`
    # lowering already answers correctly -- CPython prints `5` for
    # `Dialog(5)` because a parameter annotation there is documentation, not
    # a cast, so refusing is a divergence from the oracle and stringifying is
    # not. One fix, one spelling: the runtime function went with the lowering
    # it was written for, and its ledger line with it.
    #
    # 543 -> 544 (merging master into the bugs3 tree): `mojo_char_at_str`, from
    # 5ba5a8aa ("a character is an immortal table entry, not a malloc per
    # character") -- the commit that fixed the char-scan leak. It added one
    # declaration line to fire_runtime.h and did not bump this ladder, so
    # `rthdrscan` went red in the same commit. Which is the whole argument for
    # reading this number off the call rather than trusting the commit that
    # changed the header: the commit that adds a declaration is exactly the
    # commit that has to remember to. It arrived on the OTHER side of this
    # merge and was never on this one, so 544 is this side's 543 plus that one
    # name -- read off `reflect.collect_runtime_exports_h` on the merged header
    # (544), not added up from the two sides.
    #
    # A sibling branch's header grew by SEVEN instead, for the SAME ordering fix
    # in its own spelling: `MOJO_ORD_INCOMPARABLE`, `mojo_value_order`,
    # `mojo_list_order`, `mojo_set_order`, `mojo_dict_order`,
    # `mojo_value_order_op`, and an operator-less `mojo_list_cmp` /
    # `mojo_set_cmp`. None of those names is in this header -- the ordering
    # entry points here are the three-way `mojo_*_cmp` plus `mojo_cmp_fold`,
    # with `op` threaded down -- so it is not counted twice. One implementation
    # of a fix is one set of names, and the runtime file records which spelling
    # won and why.
    #
    # `py_tokenize_named` is deliberately NOT an entry, and two separate merges
    # have now settled that rather than adding one. It is not in
    # `_NO_OVERLOAD_MANGLE` (only `py_tokenize` is), so a generated call would
    # reach it under a mangled name and a bare-name declaration here could never
    # be that call's prototype -- and nothing calls it from generated code at
    # all, its callers being Python (formal/build.py, the lexing tests), which
    # take the prototype from the definition. Declaring it would put a fact in
    # this header that nothing checks and nothing could use. See the header's own
    # comment.
    #
    # 544 -> 546: `mojo_open` and `mojo_close`, declared under the same
    # `#ifndef __MOJO_STDLIB_MODE__` guard `mojo_write` uses
    # (`runtime/fire_runtime.h`, and `bugs/FORMAL_runtime_library_on_the_link_line.md`
    # §0.2 for why they were left out and what decided it). Both are DEFINED by
    # `fire_runtime.c` in both arms of its `#if USE_PYTHON`, with the signature
    # declared here, so both cross the export-trie intersection and both are
    # callable from a formal image -- `mojo_close`; `mojo_open`'s `void *`
    # return is the ceiling-3 shape and is still refused. Read off the CALL
    # (546), the same way every other number in this ledger was.
    #
    # 546 -> 550 (2026-10-02, `bugs4-2`): the `d.pop(k, default)` value
    # domains on the str-key side — `mojo_dict_pop_str` / `mojo_dict_pop_double`
    # and their `_kw` twins. `mojo_dict_pop_int` gained the `dflt` parameter
    # Python's two-argument `pop` needs and did so by CHANGING that one
    # signature rather than adding a parallel `..._dflt` name; the four new
    # names are the str and double readers the same family needed, so that a
    # str-valued dict pops its value as a `char *` instead of a pointer
    # decimal (“A dict's value accessor is guessed from the DEFAULT argument”,
    # “CODEGEN: `d.pop(k, default)` returns 0 on a MISS”). Read off the CALL
    # on the MERGED header (550 = this side's 546 plus those four), which is
    # the point the ledger exists to record: bugs4-2 counted from its own
    # base's 543, so its `547` was right for its tree and wrong for this one.
    #
    # 550 -> 552 (2026-10-02, `bugs4-3`): iterating a value whose container
    # KIND is a runtime fact, decided by the runtime instead of by the
    # codegen's guess. `mojo_iter_boxed_list` is the call the shared
    # chokepoint's not-a-container arm makes (a boxed string becomes its
    # characters, anything else raises `TypeError` rather than answering an
    # empty list), and `mojo_str_chars` is `list(<a str>)`, split out
    # because it is answerable without knowing anything about the value. Two,
    # read off the call on the MERGED header -- bugs4-3 counted from its own
    # base's 543 and wrote `545`, which was right for its tree and wrong here.
    #
    # Every entry here is read off the CALL, never added up, and the count is
    # read off the merged header rather than being any one branch's total plus
    # its own new names: two branches that each added names did not each add
    # them to THIS header. That is the whole reason this list is a ledger and
    # not a formula -- a name in the header that no line accounts for is the
    # only way this count can go wrong silently.
    # 552 -> 560 (2026-10-02, `bugs4-6`): the dict's own VALUE kinds. The
    # store moved from one integer setter to one per kind, so the runtime grew
    # `mojo_dict_set_none` (a bare `None`, which is int64_t 0 — the same word a
    # plain `0` stores, so only a tag tells them apart), `mojo_dict_set_struct` /
    # `mojo_dict_set_other_struct` (a struct VALUE, tagged per slot, with the
    # second form for "a struct this dict's repr does not describe"),
    # `mojo_dict_set_val_repr` (the recorded repr function) and
    # `mojo_dict_repr_val` (what the dict's own walker asks), plus the
    # `bytes_`-keyed twin of the None one. Eight, read off the call on the
    # MERGED header; bugs4-6 counted from its own base's 543 and wrote `551`,
    # which was right for its tree and wrong here.
    #
    # 560 -> 561 (2026-10-02, `bugs4-8`): `mojo_sprintf_ptr` — the
    # `<function f at 0x...>` spelling `print(f)` needs, because a function
    # value is a `void *` and `TypeLattice.printf_fmt` has no format for a
    # pointer, so `print(f)` used to `sprintf` one with `%d` (undefined
    # behaviour; a decimal address on this target). One name: the codegen half
    # is a `print` dispatch arm, which adds no runtime entry point. bugs4-8
    # counted from its own base's 543 and wrote `544`.
    for header, want in (('fire_runtime.h', 571),
    # 570 -> 571: `mojo_len_of_word`, the LENGTH discriminator the `len()`
    # lowering asks when the operand's slot is type-erased and no single kind
    # was recorded for it -- `bugs/CODEGEN_len_of_a_param_called_with_both_a_
    # list_and_a_str.md`. It is the `mojo_cstr_or_int_str` family member
    # `len` was missing: a parameter called with both a list and a string had
    # its length measured as `mojo_list_len` over a `char *`, which reads a
    # header out of string bytes and so answers differently run to run.
    #
    # 565 -> 570 (2026-10-04), FIVE names over two commits, neither of which
    # touched this ledger — which is the point of `--fix`, added with this
    # entry:
    #   +4  `mojo_str_startswith_from`, `mojo_str_endswith_from`,
    #       `mojo_str_rfind_from` and `mojo_str_count_from` (a35765a0, "str's
    #       [start[, end]] window was dropped"). The window family went from one
    #       three-argument `mojo_str_find_from` to a plain form plus an `_from`
    #       twin per method, mirroring the bytes-side search helpers: the
    #       windows were silently DROPPED, so `s.startswith(p, i)` compared
    #       from byte 0 — which is how the self-hosted tokenizer's
    #       `src.startswith(delim, j)` ended up testing the whole source
    #       against a one-character prefix. `mojo_str_find_from` is not a NEW
    #       name (it existed with three parameters), which is why the delta is
    #       four and not five.
    #   +1  `mojo_regex_split` (d8cdca63), `re.Pattern.split(text)`: the pieces
    #       between matches, with each participating capturing group emitted in
    #       place.
    # This rung is the one `bugs/CODEGEN_the_runtime_export_ladder_is_five_
    # behind.md` filed for, together with the five PROSE copies of the census
    # in `formal/model.py`, `build_stdlib_dylib.py` and
    # `bugs/FORMAL_known_limits.md`. Both are closed by the same thing: this
    # entry, its ladder rung, and `--fix`, which writes the live scan into
    # every quote from the table above rather than leaving five hand-typed
    # copies of a computed number to agree with each other. The doc went with
    # the fix.
    # Read off the call as always — `python3 test_runtime_header_scan.py
    # --fix` writes this number from the same scan — and NOT added up from the
    # two commits' own arithmetic, which is the mistake the 2026-10-02 merge
    # entries below record twice.
    # 561 -> 565 (2026-10-02, `bugs4-9`), FOUR names on the merged header
    # (its own ledger said five, from its base's 543 -> 548):
    #   +1  `mojo_str_cat_free`, the left-operand-releasing cat every repr
    #       walker is a chain of. It was a file-local `_cat_free` in
    #       fire_runtime.c and is now PUBLIC because the repr walkers the
    #       CODEGEN emits into every generated program are the same chain and
    #       were leaking the same N-1 buffers per printed container; a second
    #       copy emitted into the preamble would have been two
    #       implementations of one rule in two languages.
    #   +1  `mojo_dict_slot_double`, the double twin of `mojo_dict_slot_key`,
    #       for the same caller: the emitted dict repr walks slots by INDEX and
    #       `mojo_dict_get_double` takes a KEY, so a `kind == 1` slot had no
    #       reader and went to the generic element repr, which dereferences a
    #       word above 65536 — a double's IEEE-754 bits. `print({"c": 3.5})`
    #       was a SIGSEGV.
    #   +2  `mojo_raise_not_implemented` (the sixth typed raiser, beside the
    #       five above) and `mojo_module_not_compiled`, the codegen's half of
    #       it: a method call on a bare-imported module this compile never
    #       compiled used to return the module marker (an int64_t 0) unchanged,
    #       so `argparse.ArgumentParser(...)` "constructed" a parser that is not
    #       one and every later method echoed it back, silently, until an
    #       unrelated attribute read died naming an attribute of a class the
    #       program never built. Raising at the CALL is where it becomes true,
    #       and it is catchable.
    # The fifth, `mojo_char_at`, is NOT in this count: it is the same helper
    # master already had under the name `mojo_char_at_str` (5ba5a8aa, one day
    # after bugs4-9's base), and this merge keeps ONE of the two — master's
    # name, with bugs4-9's body, whose bounds are `mojo_cstr_slice`'s. Two
    # names for one immortal-table character accessor would have been two
    # implementations of one rule, which is what this file exists to catch.
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
                'mojo_bound_method_call_8',   # static inline (variadic arity)
                'mojo_fnptr_call_kw_4',       # static inline (keyword twin)
                'mojo_fnptr_call_8',          # static inline (variadic arity)
                'mojo_maybe_bound_call_kw_0', # static inline (keyword twin)
                'mojo_uint64_from_int64',     # static inline
                '_Bool_select',                # static inline
                '__mojo_floordiv',             # static inline
                '_mojo_getline',               # static inline, leading _
                ):
        check(sym not in rt, f'fire_runtime.h: {sym} is correctly NOT exported')
    for sym in ('printf', 'malloc', 'free', 'strlen', 'memcpy'):
        check(sym not in rt, f'fire_runtime.h: C-library {sym} is not re-exported')


# Every place in the tree that QUOTES the census in prose, and which figure of
# it each one quotes. This table exists because five such places had all gone
# stale at the same time, in the same way, for the same reason: the census is
# computed (`formal.model.runtime_abi`, off the headers) and a COMMENT is a
# second copy of a computed number, so the copy drifts and nothing fails. The
# check below reads each figure out of the file it lives in and compares it with
# the live table, which is the difference between a comment and a derived
# figure — a comment cannot be derived, so the next best thing is to refuse to
# let it disagree.
#
# (path, a regex whose groups are the figures to compare, what those groups are)
# The regexes are deliberately specific — each names the SENTENCE, not just a
# number — because "some comment in this file contains 668" is not a check, and
# a loose one would pass on a stale figure sitting next to a correct one.
CENSUS_QUOTES = (
    ('formal/model.py',
     r'the shape answers the same question for all (\d+) entry\s*\n'
     r'# points the headers declare',
     ('total',)),
    ('formal/model.py',
     r'a rule that refuses all (\d+) entry points for that reason',
     ('total',)),
    ('bugs/FORMAL_known_limits.md',
     r'\| entry points declared \| (\d+) \|',
     ('total',)),
    ('bugs/FORMAL_known_limits.md',
     r'\| every type crossing the boundary is one word \| \*\*(\d+)\*\* \|',
     ('word',)),
    ('bugs/FORMAL_known_limits.md',
     r'\| a box in an argument or the return \| (\d+) \|',
     ('box',)),
    ('bugs/FORMAL_known_limits.md',
     r'\*\*(\d+) of (\d+) is what a link line converts',
     ('word', 'total')),
    ('bugs/FORMAL_known_limits.md',
     r'For `mojo_sqlite3_\*` it is \*\*(\d+) of (\d+)\*\*',
     ('sqlite_word', 'sqlite_total')),
    ('bugs/FORMAL_known_limits.md',
     r'\| of the (\d+), refused only for want of a linked library \| (\d+) \|',
     ('word', 'word')),
    ('bugs/FORMAL_known_limits.md',
     r'the shape answers the same question for all (\d+)\n'
     r'entry points instead of',
     ('total',)),
    ('bugs/FORMAL_known_limits.md',
     r'repeating this table: (\d+)\s*\nentry points, (\d+) word-shaped, '
     r'(\d+) with a box',
     ('total', 'word', 'box')),
    # the round-1 correction: the split by RETURN TYPE alone, which is a
    # different question from the table's (every type crossing the boundary)
    # and so a different pair of figures -- quoted here because the doc quotes
    # it, and derived with `model`'s own word rule rather than by arithmetic.
    ('bugs/FORMAL_known_limits.md',
     r'I measure (\d+) / (\d+) / (\d+) by return type alone, and (\d+)\s*\n',
     ('total', 'return_word', 'return_box', 'word')),
    ('bugs/FORMAL_known_limits.md',
     r'So today the (\d+) are refused',
     ('word',)),
    ('bugs/FORMAL_known_limits.md',
     r'it is the only thing between the (\d+) and working code',
     ('word',)),
    ('build_stdlib_dylib.py',
     r"of `fire_runtime\.h`'s (\d+)\n\s*entry points",
     ('fire_runtime_h',)),
)

# The same table plus the count this file asserts on `fire_runtime.h` itself.
# It is a LITERAL IN CODE rather than prose, so it is not checked a second time
# (`test_every_declaration_is_seen` already compares that number against the
# live scan, by a better route) — but it IS rewritten by `--fix`, because a
# figure a tool has to leave to a human is a figure that gets edited in some of
# its five places.
LADDER_QUOTE = (
    'test_runtime_header_scan.py',
    r"\('fire_runtime\.h', (\d+)\)",
    ('fire_runtime_h',),
)
FIXABLE_QUOTES = CENSUS_QUOTES + (LADDER_QUOTE,)


def live_census():
    """Every figure the prose quotes, read off the headers exactly once.

    `return_word`/`return_box` are the split the round-1 correction in
    `bugs/FORMAL_known_limits.md` quotes: the RETURN type alone, with the
    argument list not counted. That is a different question from the table's
    ("every type crossing the boundary"), so it is a different pair of numbers
    from the same table -- asked with `model`'s own word rule rather than by
    arithmetic on the table's figures, because the two questions are answered
    by two different predicates and subtracting one from the other would
    answer neither.
    """
    sys.path.insert(0, HERE)
    from formal import model as M
    abi = M.runtime_abi()
    total = len(abi)
    word = sum(1 for e in abi.values() if e['word'])
    box = total - word
    sqlite = {k: e for k, e in abi.items() if 'sqlite' in k}
    return_word = 0
    for e in abi.values():
        base, depth = M._parse_ctype(e['ret'])
        if M._ctype_is_word(base, depth, in_return=True):
            return_word += 1
    import reflect
    hdr_dir = M._runtime_header_dir()
    return {
        'total': total,
        'word': word,
        'box': box,
        'return_word': return_word,
        'return_box': total - return_word,
        'sqlite_word': sum(1 for e in sqlite.values() if e['word']),
        'sqlite_total': len(sqlite),
        'fire_runtime_h': len(reflect.collect_runtime_exports_h(
            os.path.join(hdr_dir, 'fire_runtime.h'))),
    }


def rewrite_quoted_figures():
    """Write the live census into every place that quotes it. Returns the
    number of files whose text changed.

    This is the OTHER half of `test_the_quoted_census_is_the_live_census`, and
    it exists because a check that can only say "no" sends the person who
    broke it to the header, reads the number off it by hand, and edits five
    files — which is exactly the manual step that let all five go stale at
    same moment in the first place. `--fix` performs the substitution the check
    would have performed, from the same regexes, so the two cannot disagree
    about which sentence is the quote.

    It is NOT called by the check. The check compares; this rewrites. Keeping
    them one function would make the gate's verdict depend on whether the tree
    was writable, and would make a stale figure self-healing — which is how a
    figure stops being checked at all.
    """
    live = live_census()
    touched = []
    for path, pattern, keys in FIXABLE_QUOTES:
        full = os.path.join(HERE, path)
        try:
            with open(full, encoding='utf-8') as f:
                # re-read every time: two entries can name the same file (and
                # several name FORMAL_known_limits.md), and an earlier write in
                # this loop has to be visible to the later ones
                text = f.read()
        except OSError as e:
            print(f'skip  {path}: {e}')
            continue
        m = re.search(pattern, text)
        if m is None:
            print(f'skip  {path}: no text matches {pattern!r} — the quote is '
                  f'gone, and a tool cannot put prose back')
            continue
        new = splice_quoted_figures(text, m, keys, live)
        if new == text:
            continue
        with open(full, 'w', encoding='utf-8') as f:
            f.write(new)
        if path not in touched:
            touched.append(path)
        moved = ', '.join(
            f'{key} {m.group(i)} -> {live[key]}'
            for i, key in enumerate(keys, start=1)
            if m.group(i) != str(live[key]))
        print(f'fixed {path}: {moved}')
    return len(touched)


def splice_quoted_figures(text, m, keys, live):
    """`text` with each captured figure replaced by its live value, and every
    other character — including the prose around and between the figures —
    left exactly as it was.

    The figures are of different WIDTHS (668 -> 673, 414 -> 500), so this
    cannot be done by string replacement of the captured digits: the second
    group's offset moves as soon as the first is rewritten. Splicing each
    group over its own span, carrying `last` forward, is what makes a
    four-figure sentence correct rather than nearly correct.
    """
    pieces = []
    last = 0
    for i, key in enumerate(keys, start=1):
        s, e = m.span(i)
        pieces.append(text[last:s])
        pieces.append(str(live[key]))
        last = e
    pieces.append(text[last:])
    return ''.join(pieces)


def test_the_fixer_touches_only_the_figures():
    """`--fix` rewrites the numbers and nothing else.

    The splicer is the one piece of this file that WRITES, so it is the piece
    whose bug would be expensive: an off-by-one in `last` does not fail a
    check, it corrupts a docstring in `formal/model.py`. Both properties are
    asserted here on a synthetic sentence rather than on a real file — the
    real figures are `673`/`266`/`407` today and would be wrong in the test
    the moment a declaration is added, which is the rot this file exists to
    stop.
    """
    text = 'It is **262 of 668** that converts, and 262 by return alone.'
    m = re.search(r'\*\*(\d+) of (\d+)\*\* that converts, and (\d+) by',
                   text)
    live = {'word': 266, 'total': 673, 'box': 407}
    got = splice_quoted_figures(text, m, ('word', 'total', 'word'), live)
    check(got == 'It is **266 of 673** that converts, and 266 by return alone.',
          'the splicer rewrites three figures of different widths in place',
          f'got {got!r}')
    check(splice_quoted_figures(text, m, ('word', 'total', 'word'),
                                {'word': 262, 'total': 668}) == text,
          'the splicer is a no-op when every figure is already live')
    long, short = 1000, 7
    txt2 = f'from {long} to {short}'
    m2 = re.search(r'from (\d+) to (\d+)', txt2)
    check(splice_quoted_figures(txt2, m2, ('total', 'box'),
                                {'total': 9, 'box': 123456}) == 'from 9 to 123456',
          'a figure that GROWS moves the group after it correctly',
          'the narrower figure was spliced at a stale offset')


def test_the_quoted_census_is_the_live_census():
    """Every prose copy of the ABI census agrees with `runtime_abi()`.

    The figures come from ONE place — `formal.model.runtime_abi()`, which reads
    every header in `runtime/` through `reflect.collect_runtime_exports_h` — and
    this check is what stops the tree from carrying a second, drifting answer.
    It is the check the five stale quotes were missing, and it is here rather
    than in a formal suite because the thing being checked is a COMMENT's
    agreement with a header scan, which is a question about this file's own
    scanner.

    A quote that cannot be found is a FAILURE and not a skip. A missing quote is
    how this table rots: someone edits the sentence, the regex stops matching,
    and a check that quietly stops checking is worse than no check at all.
    """
    live = live_census()
    for path, pattern, keys in CENSUS_QUOTES:
        full = os.path.join(HERE, path)
        try:
            with open(full, encoding='utf-8') as f:
                text = f.read()
        except OSError as e:
            check(False, f'{path}: the census quote is readable', str(e))
            continue
        m = re.search(pattern, text)
        if m is None:
            check(False, f'{path}: the census quote is still there',
                  f'no text matches {pattern!r} — a quote that cannot be found '
                  f'is a stale TABLE, not a passing check')
            continue
        for i, key in enumerate(keys, start=1):
            got = int(m.group(i))
            check(got == live[key],
                  f'{path}: the quoted {key} count is {live[key]}',
                  f'the text says {got}; `runtime_abi()` says {live[key]}')


def main():
    if '--fix' in sys.argv:
        n = rewrite_quoted_figures()
        print(f"\n{n} file(s) rewritten from the live census; re-run without "
              f"--fix to check")
        return 0
    test_pointer_returns_are_seen()
    test_every_declaration_is_seen()
    test_non_exports_stay_excluded()
    test_the_fixer_touches_only_the_figures()
    test_the_quoted_census_is_the_live_census()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\n{npass} passed, {nfail} failed, {len(RESULTS)} checks")
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
