#!/usr/bin/env python3
"""A per-STRUCT table must be asked once per STRUCT, not once per FUNCTION.

    python3 test_formal_per_struct_asks.py [-v]

`formal/model.py`'s per-struct predicates — `struct_is_framed`,
`struct_fits_one_word`, `struct_is_one_field`, `struct_field_names` — are not
cheap. Each derives the struct's whole field set by walking **every method body
of that struct, twice** (`_split_declaration` → `struct_receiver_stores` +
`struct_method_receiver_reads`). So the cost of one ask is proportional to the
struct's body, and an asker inside a per-FUNCTION loop pays it once per
function: `#functions × #methods × body size` instead of
`#structs × #methods × body size`.

That is the shape the 2026-10-02 per-struct census measured (its doc is
deleted with the fix; this file and
`bugs/PERF_struct_field_names_is_still_asked_once_per_function.md` are what
is left of the family) (43 508 redundant derivations on `myinterpreter.py`, 33 s of a 97 s
build) and its fix is the module-level tables `formal/build.py` derives once and
threads: `framed_struct_names`, `one_field_struct_names`, the `wide` table. Two
per-function askers survived that, both found by the measurement in
`bugs/FORMAL_build_cost_2026-10-03.md` §6 and fixed 2026-10-04:

  * `_seed_one_word_bindings` read `struct_is_framed(pst)` OR
    `not one_field_answer(pst, one_field)` — and the first operand is DEAD,
    because `struct_is_one_field` is `struct_fits_one_word and
    struct_field_count == 1` while `struct_is_framed` is `struct_field_count > 1
    and wide_receiver_by_reference()`: a struct the second claims, the first
    cannot. Reading it first was a whole-struct walk per declared parameter;
  * `_bound_receiver_structs`' owner fallback asked `struct_is_framed(owner)` for
    an owner `framed` does not cover, which is every ONE-field struct — and a
    one-field struct is absent from `framed` for the same reason it is not
    framed, so the table answers by ABSENCE.

**What this file pins is the property, not those two lines.** It doubles the
number of FUNCTIONS in a module whose struct has many methods and asserts the
ask counts do not move. A regression that puts a per-function asker back makes
the counts grow with the function count and this fails; a regression that
deletes a table makes them grow too, because the fallback path is the predicate.
The counts are the assertion rather than a wall clock on purpose — the cost of a
redundant ask is proportional to the struct's body, so whether it shows up in
seconds depends on the file, and an ask count is the same fact on every file.
(`bugs/FORMAL_build_cost_2026-10-03.md` §6.1 has the clock numbers, and they are
a wash outside the outlier.)

No Lean, no build, no sweep: a parse and `_prepare_functions`.
"""
import argparse
import collections
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import formal.build as B                                # noqa: E402
import formal.model as M                                # noqa: E402

# The four predicates of the partition, and the two per-struct tables they are
# read off. Named here so a table that loses a reader is visible in the diff.
# The three predicates of the partition. Each is read off a module-level table,
# so its ask count is a function of the module's STRUCTS and must not move when
# the FUNCTION count does.
PREDICATES = ('struct_is_framed', 'struct_fits_one_word', 'struct_is_one_field')
# …and the one that is NOT, with its per-function slope pinned. See
# `test_the_field_set_residue_is_pinned` for which asker it is and why it is
# still there. It is COUNTED rather than listed in `PREDICATES` because it is
# wrapped for the same reason the others are — a count nothing collects is a
# count nothing can assert on.
COUNTED = PREDICATES + ('struct_field_names',)
FIELD_SET = 'struct_field_names'
RESULTS = []


def check(ok, what, detail=''):
    RESULTS.append((bool(ok), what))
    print(f'{"PASS" if ok else "FAIL"}  {what}' + (f' — {detail}' if detail else ''))


def module_with(nfuncs: int, nmeths: int = 12) -> str:
    """One struct with `nmeths` methods, and `nfuncs` functions that take it.

    The struct's methods are the point: a per-function ask costs one walk of all
    of them, so a source with few methods and many functions understates the
    regression this file exists to catch.
    """
    out = ['struct Big:', '    var x: Int', '']
    for m in range(nmeths):
        out += [f'    fn m{m}(self, k: Int) -> Int:',
                '        var t: Int = k',
                f'        t = t + self.x + {m}']
        for j in range(6):
            out += [f'        t = t * 3 + {j}',
                    '        if t > 100:',
                    '            t = t - 7']
        out += ['        self.x = t', '        return t', '']
    out += ['fn use(o: Big, a: Int) -> Int:',
            '    return o.m0(a) + o.m1(a)', '']
    for i in range(nfuncs):
        out += [f'fn f{i}(o: Big, a: Int) -> Int:',
                f'    return o.m{i % nmeths}(a) + a + {i}', '']
    return '\n'.join(out)


def ask_counts(source: str):
    """{predicate: calls} for one `_prepare_functions` run over `source`."""
    counts = collections.Counter()
    saved = {}
    for name in COUNTED:
        fn = getattr(M, name)

        def timed(*a, _fn=fn, _n=name, **k):
            counts[_n] += 1
            return _fn(*a, **k)
        saved[name] = fn
        setattr(M, name, timed)
    try:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'asks.mojo')
            with open(path, 'w') as f:
                f.write(source)
            stmts = B.parse_module(source, path)
            B._prepare_functions(stmts, synthetic=True, source_path=path)
    finally:
        for name, fn in saved.items():
            setattr(M, name, fn)
    return counts


def test_the_asks_do_not_grow_with_the_function_count():
    """Doubling the FUNCTIONS doubles no per-struct ask.

    The tables are module-level, so the count is a function of the module's
    STRUCTS. Before the two fixes this read 22 asks at 20 functions and grew
    with every function after it; on a struct with 40 methods it was 83 asks
    for 40 functions against 2 after.
    """
    small = ask_counts(module_with(20))
    large = ask_counts(module_with(40))
    for name in PREDICATES:
        check(large[name] == small[name],
              f'{name}: 40 functions ask it as often as 20 do',
              f'{small[name]} then {large[name]}')
    # And the absolute floor: a per-struct predicate asked once per STRUCT is
    # asked about a handful of structs. A per-function asker shows up here too,
    # so this is the assertion that does not need a second measurement to read.
    for name in ('struct_is_framed', 'struct_is_one_field'):
        check(large[name] <= 8,
              f'{name}: asked {large[name]} times for ONE struct',
              'the per-struct tables answer this without a walk')


def test_the_field_set_residue_is_pinned():
    """`struct_field_names` still grows with the FUNCTION count — by ONE per
    function, and this pins that slope rather than pretending it is zero.

    The asker is `_one_word_sole_field_chain`'s `_sole_field_name(st)`, which
    asks `model.struct_sole_field_name` for the struct whose single field IS the
    word, once per function that holds or owns one. The fix is the shape this
    file's docstring describes for the other two — publish `{name: field}` per
    struct beside `one_field_struct_names` and thread it — and it is written up
    rather than done because it is six call sites in `formal/build.py`, which
    owes the gate.

    So the residue is a MEASURED number with a named asker and a slope, not a
    `known` note: adding a second per-function asker of the field set doubles the
    slope and fails here, and the failure says which predicate moved.
    """
    small = ask_counts(module_with(20))
    large = ask_counts(module_with(40))
    added = 20
    slope = (large[FIELD_SET] - small[FIELD_SET]) / added
    check(slope <= 1.0,
          f'{FIELD_SET}: grows by {slope:.2f} per added function, not more',
          f'{small[FIELD_SET]} at 20 functions, {large[FIELD_SET]} at 40; the '
          "known asker is _one_word_sole_field_chain's _sole_field_name")


def test_the_count_is_not_the_fallback_walking():
    """With the one-field table stubbed out the count jumps — so the table is on
    the path this file measures, and a check that only compared two runs would
    not notice a change that turned both into the slow shape.

    This is the control for the case above, in the direction that matters: the
    stub is what "the tables are gone" looks like from inside the model, and the
    assertion is that it is VISIBLE. A file that asserted only "the counts are
    equal at 20 and 40 functions" would pass just as happily with every reader
    on the predicate.
    """
    saved = M.one_field_struct_names
    M.one_field_struct_names = lambda *a, **k: None
    try:
        without = ask_counts(module_with(40))
    finally:
        M.one_field_struct_names = saved
    with_table = ask_counts(module_with(40))
    check(without['struct_is_one_field'] > with_table['struct_is_one_field'],
          'stubbing the one-field table makes the predicate be asked again',
          f"{with_table['struct_is_one_field']} with the table, "
          f"{without['struct_is_one_field']} without")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-v', '--verbose', action='store_true')
    ap.parse_args()
    test_the_asks_do_not_grow_with_the_function_count()
    test_the_field_set_residue_is_pinned()
    test_the_count_is_not_the_fallback_walking()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f'\n{npass} passed, {nfail} failed, {len(RESULTS)} checks')
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
