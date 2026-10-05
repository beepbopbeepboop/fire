# CODEGEN: a `zip`/`enumerate` loop target keeps the FIRST loop's declared type

Found 2026-10-02 while fixing
`bugs/CODEGEN_starred_rest_in_a_for_target_is_a_slot_named_star.md` (fixed
and deleted). It is a different defect in the same declaration machinery, and
it was found by writing the fix's own regression case.

## What I ran

```python
def main():
    for i, v in zip([1, 2], ["a", "b"]):
        print(i, v)
    for i, v in zip([1.5], [9]):
        print(i, v)
main()
```

    CPython:  1 a / 2 b / 1.5 9
    compiled: 1 a / 2 b / 1 [SIGBUS — exit -10, no third line]

No `*` in sight: this is the plain 2-slot zip target.

## Mechanism

`_declare_zip_slot` (`mojo/backend_gimple/emit_loops.py`) declares each slot
with its own sequence's element type and does NOT pass `force=True`, so
`_declare_var`'s first-decl-wins guard keeps the FIRST loop's declaration for
the whole function. The second loop then stores into it:

```c
i = (int64_t) mojo_list_get_double (...);   /* into an int64_t declared by loop 1 */
```

so `1.5` truncates to `1`, and the `print(i, v)` that follows formats an
`int64_t` with the string format the string-typed declaration implied — a
read of the wrong kind of slot, which is the SIGBUS.

`_gen_for_list` already fixed this exact hazard for its own targets, with a
long comment naming both halves (`_gen_for_list`: "a loop TARGET is not a read
of an existing name, so `_declare_var`'s first-decl-wins default is wrong
here — `for x in [1, 2]:` followed by `for x in ['p', 'q']:` REBINDS x"). The
zip/enumerate/zip_longest paths were never given the same treatment, so this
is the same bug in three lowerings that did not get the fix.

`_gen_for_enumerate` has it too, with the same program shape:
`for i, v in enumerate([1, 2]): ...` then `for i, v in enumerate([1.5]): ...`.

## Status 2026-10-04 — the rule is understood, written, and WITHDRAWN because it breaks the self-host closure

A fix was landed and then withdrawn in the same day, so read this before the
"Exact next step" below, which is still right about the SHAPE and wrong about
the cost.

**The rule is the obvious one** and it is already written down in three places
in the tree, each for its own family: a loop TARGET rebinds its name, so
`_declare_var`'s first-decl-wins default — right for a name a loop READS — must
be overridden with `force=True` when the requested ctype differs from what the
name is currently declared as. `_gen_for_list` and `_gen_for_set` do exactly
that (`_fl_retype` / `_retype`), and the doc's own next step is to give zip,
enumerate and zip_longest the same two lines. Applied to every family in
`mojo/backend_gimple/emit_loops.py` it fixes all three named families and three
more, and every rebind case measured here matches CPython afterwards:

    for i, v in zip([1, 2], ["a", "b"]): ...   then  zip([1.5], [9])
    enumerate([1, 2])          then  enumerate(["x", "y", "z"])
    enumerate("abc")           then  enumerate([7, 8])
    zip_longest([1, 2], ["p"]) then  zip_longest([1.5, 2.5], ["q"])
    zip([1, 2], ["a", "b"])    then  zip([1.5], [9])
    zip with a NESTED tuple slot, and with a starred slot

**And it breaks the self-host closure.** `python3 test_selfhost.py` with the
rule applied everywhere fails to COMPILE the compiler's own closure, five times
over and then twice over as families were excluded, all of them one shape:

    mojo/backend_gimple/module_gen.py:13106:20: error: assignment to 'int64_t'
        {aka 'long long long int'} from 'char *' makes integer from pointer
        without a cast [-Wint-conversion]

    # the generated C, in `gen_module_impl`:
    _z9_meths = sd.methods;            /* 13106 */
    m = _z9_meths[_z9k];               /* 13108 */

with the same error attributed to a comment line at `module_gen.py:6181` and to
`13226`/`13228` in the `_funcptr_builtins_needed` block. `sd` is the target of
TWO loops in that function — `for sd in track_best.values():` (12520) and
`for sd in struct_defs:` (13064) — which is exactly the rebind the rule is for,
so the breakage is not "the rule is wrong" but "the second loop's element type
is not what its first use needs". Isolated: with the rule applied to
zip/enumerate/zip_longest ONLY (leaving `_gen_for_list`, `_gen_for_set`,
`_gen_for_dict`, `_gfl_declare_target_name`, str, bytes, memoryview and cstr on
their existing rules) the closure still fails with the 6181/13106 pair; with the
rule applied NOWHERE (every family on its pre-existing rule) it compiles and
links (4.1 GB peak, 1560 functions) and the run then fails at its LAST step,
which is the known pre-existing red
(`bugs/CODEGEN_selfhost_binary_links_then_segfaults_on_a_two_line_program.md`:
the self-hosted binary exits -11 on a two-line program).

So the cost of this fix is not "zip/enumerate are hard", it is that the
declaration a rebind makes is load-bearing for a LATER read of the same name in
the same function, and `gen_module_impl` is where that shows. Three
measurements a next session should start from, in this order:

1. What is `struct_defs`' element type? It is built by
   `[s for s in stmts if isinstance(s, StructDef)]` (13061) and its `isinstance`
   filter does not obviously refine the element type, so `_elem_of` may be
   answering `int64_t` — and `sd.methods` (a `MojoList *` field) is then read
   off a slot that cannot carry a struct pointer at all. If that is the
   answer, the fix is in the COMPREHENSION's element type, not in the loop
   target's declaration, and every family can take the rule at once.
2. `track_best.values()` (12520) versus `struct_defs` (13064): two loops, one
   name, and the code between them reads `sd` (13065 `_moids =
   self._struct_method_overload_ids(sd)`, 13070 `_z8_meths = sd.methods`). If
   the first loop's type is the one those reads need, then a rebind has to
   re-type the READS too, which is a different fix from retyping the
   declaration — and is exactly what the shadow-variable mechanism in
   `_declare_var(force=True)` claims to do, so the claim is what needs
   checking.
3. The residual hazards are real and were measured while writing the fix, all
   still open: `for x in "cd"` then `for x in b"ab"` is a hard gcc error in
   either order ("assignment to 'int64_t' from 'char *'"), and `for k in [5]`
   then `for k in {"a": 1}` prints a POINTER DECIMAL, exit 0. Both are
   filed, with this self-host interaction, as
   `bugs/CODEGEN_loop_target_rebind_outside_the_zip_enumerate_families.md`.

The regression cases the withdrawn fix carried are worth keeping as prose: they
are the `for_target_zip_and_enumerate_rebind` program in
`test_runtime_diff.py` (reusing every target name across two differently-typed
loops in all six families, in `CPYTHON_COMPARABLE` because the interpreter was
wrong the same way) and `gimple_zip_longest_slot_rebinds_across_loops` in
`test_gimple_runner.py`.

## Exact next step

1. In `_declare_zip_slot` / `_gen_for_enumerate` / `_gen_for_zip_longest`,
   pass `force=True` (or the `shadow_name`-or-retyped rule `_gen_for_list`
   uses) when the requested ctype differs from what the name is currently
   declared as. `_gen_for_list`'s `_fl_retype` condition is the model:
   `gen.var_types.get(var) not in (None, _fl_ctype)`.
2. Regression: a CPython-comparable `test_runtime_diff.py` case with two zip
   loops over differently-typed sequences under the SAME target names. It is
   deliberately not added to `for_target_starred_rest`, which uses distinct
   names per loop and would keep this bug hidden.
3. Check `_gen_for_set` / `_gen_for_str` / `_gen_for_bytes` for the same
   missing force — `_gen_for_set` already passes it, the other two may not.
