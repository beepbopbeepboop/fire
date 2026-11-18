# `f(*(<generator expression>))` dereferences the generator handle (C compile error)

Class: medium. One lowering path. Found by gimple-lint (`cast-illegal`).

## Symptom

    def cat(*parts):
        out = ""
        for p in parts:
            out += p
        return out

    def main():
        texts = {"x": "1", "y": "2"}
        print(cat(*(f"{p}={texts[p]};" for p in sorted(texts))))

    main()

CPython prints `x=1;y=2;`. Measured 2026-11-16: `python3 fire.py build`
fails in the C compiler:

    error: storage size of '_t10' isn't known
    error: invalid use of incomplete typedef 'MojoGenerator'

The emitted statements are

    _t6 = __mgco___genexp_0_start (...);     /* MojoGenerator * */
    _t10 = *_t6;                             /* a C DEREFERENCE of the handle */
    _t13 = (int64_t)_t10;

The compiler's own `gimple_codegen.py` has this shape near line 7120
(`cas._hash(*(f'{p}\0{texts[p]}' for p in sorted(texts)))`), so its
self-compiled output carries the same statement:

    python3 tools/gimple_lint.py -v --code cast-illegal gimple_codegen.ci
    gimple_codegen.ci: cast-illegal: MojoGenerator cast to int64_t
        in _dep_sources_digest

## Cause

The unary `*` in a call's argument list means "unpack this iterable into
positional arguments". For a list operand that is handled. For an operand
whose type is `MojoGenerator *` the `*` falls through to the lowering of a
unary operator on a pointer and is written out as a C dereference.

## Fix

In the star-argument path of the call lowering (search
`mojo/backend_gimple/emit_calls.py` and `emit_exprs.py` for where a
`UnaryOp` with `op == '*'` is handled as a call argument), when the
operand's type is `MojoGenerator *`, first materialize it as a list with
the helper the backend already uses for `list(<generator>)`
(`gen._materialize_as_list(ctype, value)`), then unpack that list. Never
emit `*<temp>` for a starred call argument.

## How to verify

1. Add the program above to `test_gimple_runner.py` (compare with CPython).
2. From an empty directory: `python3 /path/to/tree/fire.py --dump
   /path/to/tree/gimple_codegen.py`, then
   `python3 /path/to/tree/tools/gimple_lint.py --code cast-illegal gimple_codegen.ci`
   reports 0 findings.
3. `python3 test_gimple.py` keeps its pass count with 0 failed;
   `python3 tools/suite.py stdlib-syntax stdlib-dylib gimple-lint` passes.

## Status (2026-11-18)

**The lowering is fixed and verified; the doc stays open only because the
program in `## Symptom` still trips a SECOND, unrelated bug.**

Landed: `lower_call_args` (`mojo/backend_gimple/emit_calls.py`) no longer
routes a starred `MojoGenerator *` operand into `_lower_UnaryOp`'s pointer
dereference. It materializes the generator with `_materialize_as_list` and
unpacks that list, exactly as `## Fix` prescribes. The regression test is
`test_star_unpack_of_generator_expression_in_call` in
`test_gimple_runner.py` (its element is a plain f-string, so it isolates the
lowering).

Measured on this tree:

- The regression test FAILS on master's `emit_calls.py` with the documented
  gcc errors (`storage size of '_t10' isn't known`, `invalid use of
  incomplete typedef 'MojoGenerator'`) and PASSES with the fix.
- `fire.py --dump gimple_codegen.py` + `gimple_lint.py --code cast-illegal
  gimple_codegen.ci`: 1 finding on master
  (`_dep_sources_digest_1b532c`: `_t16 = (int64_t)_t13`) and **0 with the
  fix**. That is the self-host shape named in `## Symptom`, so the class the
  bug was filed for is closed.

The `## Done when` program does NOT pass yet, for the other bug:
`texts[p]` inside `(f"{p}={texts[p]};" for p in sorted(texts))` makes the
lifted generator's string value slot `int64_t`, so the string is boxed as an
integer; `cat` then receives pointer words as `char *` and the compiled
program dies with exit -10 (SIGBUS) and no output. Smaller repro and the
whole diagnosis are in `bugs/CODEGEN_generator_string_values_boxed_as_int_slot.md`:
even a hand-written `def g(): for p in sorted([...]): yield p` prints
addresses under `list(g())`, and `list(p for p in sorted(xs))` comes out
unsorted, with no star-unpack involved.

Next step: fix that doc's yield-slot/element-kind propagation, then add the
`## Symptom` program VERBATIM to the regression test, confirm it matches
CPython, and delete BOTH docs in that commit (with
`python3 tools/dangling_doc_refs.py --ratchet`).

## Done when

The test passes, the lint reports 0 `cast-illegal` for `gimple_codegen.ci`,
and this file is deleted in the same commit (then
`python3 tools/dangling_doc_refs.py --ratchet`).
