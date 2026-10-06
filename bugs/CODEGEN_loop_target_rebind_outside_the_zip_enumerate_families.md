# CODEGEN: a loop target that rebinds keeps the first loop's slot — outside the zip/enumerate families, the fix is blocked by the self-host closure

**Area:** CODEGEN (`mojo/backend_gimple/emit_loops.py`). Found 2026-10-04 while
working `bugs/CODEGEN_zip_loop_target_keeps_the_first_loops_type.md`, whose fix
this is: that doc owns the zip/enumerate/zip_longest spelling and the
withdrawn fix; this one owns the OTHER families and the measurement that says
why the general fix cannot simply be applied to them.

## What I ran

Each program is two loops over the SAME target name, and CPython 3.14.7 is the
oracle. All three were measured on this tree with the rule applied and then
with it withdrawn, so both columns are real:

| program | CPython | rule applied | rule withdrawn (today) |
|---|---|---|---|
| `for x in "cd"` then `for x in b"ab"` | `c d 97 98` | correct | **gcc: assignment to 'int64_t' from 'char *'** |
| `for x in b"ab"` then `for x in "cd"` | `97 98 c d` | correct | **gcc: assignment to 'char *' from 'int64_t'** |
| `for k in [5]` then `for k in {"a": 1}` | `5 a` | correct | **`5` then `4376009104`** — a pointer decimal, exit 0 |
| `for x in ['p','q']` then `for x in {1,2}` | `p q 1 2` | correct | correct (set already retyped) |
| `for x in [1,2]` then `for x in ['p','q']` | `1 2 p q` | correct | correct (list already retyped) |

The first two are hard compile failures — a program that used to build no
longer does — and the third is the silent class: a wrong number, exit status 0,
no diagnostic.

## Mechanism

`_declare_var`'s default is first-decl-wins. That default is load-bearing for
every ORDINARY declaration (a name read later must keep coercing to the type it
was first given), and wrong for a loop TARGET, which rebinds its name:
`for x in <A>` then `for x in <B>` is `x = <B's element>` in Python. So the fix
is `force=True` when the requested ctype differs from what the name is currently
declared as — and two families already do it (`_gen_for_list`'s `_fl_retype`,
`_gen_for_set`'s `_retype`), which is why the list and set rows above are
already right. The families that do not: `_gen_for_str` (a `char` target),
`_gen_for_bytes` and `_gen_for_memoryview` (an `int64_t` target), `_gen_for_cstr`
(a `char *` target), `_gen_for_dict`'s non-key slot (whose key slot has its own
`_int_key_loop_vars` condition and its value slot has none at all), and
`_gfl_declare_target_name`'s nested-tuple leaves.

## Why it is not simply applied, which is the expensive half

Applying the rule to every family fixes all five rows above and every zip /
enumerate / zip_longest / nested-tuple / starred case the sibling doc lists —
and then the compiler cannot compile ITSELF. `python3 test_selfhost.py`:

    mojo/backend_gimple/module_gen.py:13106:20: error: assignment to 'int64_t'
        {aka 'long long int'} from 'char *' makes integer from pointer without
        a cast [-Wint-conversion]

in `gen_module_impl`, at `_z9_meths = sd.methods;` and `m = _z9_meths[_z9k];`,
with the same error attributed to `module_gen.py:6181` and to `13226`/`13228`.
`sd` is the target of TWO loops in that one function —
`for sd in track_best.values():` (12520) and `for sd in struct_defs:` (13064) —
so it is exactly the rebind the rule is for; the rule is faithfully applying a
declaration the following code cannot use.

Measured, narrowing as far as possible:

* rule on zip/enumerate/zip_longest only (every other family on its existing
  rule): the closure still fails, with the 6181/13106 pair;
* rule nowhere (every family on its pre-existing rule): the closure COMPILES
  AND LINKS — 4.1 GB peak, 1560 functions — and the run then fails at its last
  step, which is the known pre-existing red
  (`CODEGEN_selfhost_binary_links_then_segfaults_on_a_two_line_program.md`: the
  self-hosted binary exits -11 on a two-line program).

## Exact next step

The sibling doc's step 3 is where this starts, and it is an ELEMENT-TYPE
question rather than a declaration question:

1. What is `struct_defs`' element type? It comes from
   `[s for s in stmts if isinstance(s, StructDef)]` (13061) and the
   `isinstance` filter does not obviously refine it, so `_elem_of` may be
   answering `int64_t` while `sd.methods` needs a struct pointer. If that is
   the answer, the fix belongs in the comprehension's element type and every
   family can take the rule at once — this is the single measurement that
   unblocks the most.
2. Failing that: `track_best.values()` (12520) versus `struct_defs` (13064) —
   two loops, one name, and the code between them READS `sd` (13065, 13070). A
   rebind has to re-type the reads too, which is what `_declare_var(force=True)`
   claims to do by minting `_shadowN_<name>` and repointing `_c_names`. That
   claim is what needs checking: if a read between the two loops still resolves
   through the OLD name, the rule is not wrong, the rename is incomplete.
3. `_gen_for_dict`'s value slot is the cheapest of the three families and is
   independent of all of the above: it needs the same rule as its key slot,
   which means re-checking which accessor the pair store uses per slot
   (`_slot_ctypes`, and the `mojo_dict_iter_val_*` choice below it). Start here
   if 1 and 2 are not free: it fixes the SILENT wrong answer in the table above
   and touches no other family.

## Coverage to add with the fix

One case per row of the table, all in `test_gimple_runner.py`'s
`test_gimple_matches_cpython` (which runs CPython on the same text) rather than
in `test_runtime_diff.py`: two of them fail to COMPILE, so they are compile-time
assertions, and the third is the only one that is a wrong answer. The names
already used by the withdrawn sibling cases are `gimple_bytes_and_str_loop_
targets_rebind` and `for_target_zip_and_enumerate_rebind`, so a reader can find
the prose if not the program.