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
# …and the one that is NOT one of the partition's three, COUNTED rather than
# listed in `PREDICATES` because it is wrapped for the same reason the others
# are — a count nothing collects is a count nothing can assert on — and
# asserted on by its own case rather than by the loop above. It grew by one per
# added FUNCTION until `model.sole_field_names` joined the other two tables; see
# `test_the_field_set_does_not_grow_with_the_function_count` for the asker and
# the numbers.
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


def test_the_field_set_does_not_grow_with_the_function_count():
    """`struct_field_names` is asked a FIXED number of times, and the number is
    a function of the module's STRUCTS.

    It used to grow by ONE per function, and this pinned that slope rather than
    pretending it was zero: the asker was
    `_one_word_sole_field_chain`'s `_sole_field_name(st)`, which asks
    `model.struct_sole_field_name` for the struct whose single field IS the word,
    once per function that holds or owns one — 64 asks at 20 functions, 84 at 40.

    The fix is the shape this file's docstring describes for the other two:
    `model.sole_field_names` publishes `{name: field}` per struct beside
    `one_field_struct_names`, derived with `struct_sole_field_name` so the two
    tables cannot disagree about which structs have one field, and
    `formal/build.py` threads it beside `one_field` through the eight helpers that
    ask. Measured after: **33 asks at 20 functions and 33 at 40** — and 33 rather
    than 1 because a struct's field set is still derived once per FUNCTION for
    the handful of predicates that were never in the table, which is the same
    bargain `framed` and `one_field` made.

    So the assertion is a STRICT EQUALITY now, and that is the point: a second
    per-function asker of the field set doubles the count and fails here, and
    the failure names which predicate moved rather than reporting a slope.
    """
    small = ask_counts(module_with(20))
    large = ask_counts(module_with(40))
    check(large[FIELD_SET] == small[FIELD_SET],
          f'{FIELD_SET}: 40 functions ask it as often as 20 do',
          f'{small[FIELD_SET]} then {large[FIELD_SET]}')


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
    test_the_field_set_does_not_grow_with_the_function_count()
    test_the_count_is_not_the_fallback_walking()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f'\n{npass} passed, {nfail} failed, {len(RESULTS)} checks')
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
