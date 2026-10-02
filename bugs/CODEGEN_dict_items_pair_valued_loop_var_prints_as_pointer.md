# A `for x in d.items()` loop variable holding a PAIR prints as a MojoList pointer

**Area:** CODEGEN (the compiled path's repr for a `d.items()` loop variable).
Found 2026-10-01 on `work/bugs3-codegen-2-r2` while fixing
`bugs/CODEGEN_for_loop_target_one_tuple_vs_paren_single_name.md` — a different
defect, found by the same test program, and **not fixed there** because it is
about what a pair-valued variable PRINTS, not about how a for-target is read.

## What I ran and what I saw

```
$ cat .tmp/forloop/c3.mojo
def main():
    d = {"a": (1,), "b": (2,)}
    for (v) in d.items():
        print(v)

$ python3 .tmp/forloop/c3.py        # CPython 3.14, main() appended
('a', (1,))
('b', (2,))

$ python3 fire.py run .tmp/forloop/c3.mojo      # the interpreter
('a', (1,))
('b', (2,))

$ python3 test_runtime_diff.py --case <this shape>
  FAIL  stdout line 3: interp="('a', (1,))"  jit='4304318048'
```

`4304318048` is the `MojoList *` of the pair, printed as a decimal — and
because it is a heap address, it is also **non-deterministic**, which makes
this worse than a stable wrong answer: `bootstrap`'s stage2-vs-stage3
byte-identity check is exactly the kind of thing a raw pointer in the output
breaks, and `emit_infra.py`'s own comments record having chased a whole class
of "raw ASLR pointer decimal baked into the generated code" regressions.

## Cause

`d.items()` is lowered by materializing a list of `[key, value]` pairs
(`mojo_dict_items`) and iterating that list. When the target is a 2-tuple
(`for k, v in d.items()`) each slot is read with the right accessor and both
print correctly. When the target is ONE name, the pair is bound to it whole and
nothing types the variable as a tuple:

* `mojo/backend_gimple/emit_loops.py:1938` (`_gen_for_list`'s `_is_pair_var`)
  registers the variable in `gen._dict_item_pair_vars` so that a body's
  `x.key` / `x.value` MEMBER access reads the right slot — that is the only
  thing the registration is for;
* the variable's own declared type stays whatever `_elem_of(it_val)` inferred
  for the pair list, so `print(x)` reaches the scalar `mojo_str_from_int` path
  with a `MojoList *` in hand.

The tuple LITERAL path does not have this problem, because
`_lower_tuple_literal` records the list's own per-slot kinds
(`mojo_list_set_kinds`) and the repr walkers read them — the machinery
`bugs/CODEGEN_ctor_temp_field_read_loses_element_type.md` describes from the
other end. `mojo_dict_items`' output carries no such record.

## Not a regression from the for-target fix

Before `bugs/CODEGEN_for_loop_target_one_tuple_vs_paren_single_name.md`, the
target `'(v)'` read as a TUPLE target (the paren test could not tell it from a
1-tuple), so this line unpacked the pair's slot 0 and printed `a` / `b` — also
wrong, also silently, just a different wrong answer. The fix made the question
answerable; the answer it now gives is "this is one binding, bind the pair",
which is right, and exposes the missing repr underneath. That is the fix
working, not the fix breaking something.

## Exact next step

The pair list is a `MojoList *` of 2-element tuples, so the honest fix is to
say so where it is built. In `_gen_for_list`'s `_is_pair_var` branch, seed the
pair list's slot kinds the way `_lower_tuple_literal` does — record
`'pp'`-style kinds for both slots, or record the per-slot element types the
repr walker consults — so `print(x)` reaches `mojo_repr_pair` /
`_mojo_generic_elem_repr` with the evidence it needs instead of falling
through to `mojo_str_from_int`.

That is the same missing-evidence family as
`bugs/CODEGEN_ctor_temp_field_read_loses_element_type.md` and
`bugs/CODEGEN_list_element_read_defaults_to_str_across_a_call.md`; whoever
fixes one should check the other two, because the fix is "a container knows
what its elements are", not three separate patches.

Verify with a `test_runtime_diff.py` case that CPython can also run, printing
the pair variable directly (`print(x)`), through `str(x)`, through an
f-string, and through `x.key` / `x.value` in the same loop — the last two are
the shapes that already work and must keep working.

## Evidence

- `python3 test_runtime_diff.py` on the 4-line program: the FAIL line quoted
  above.
- `mojo/backend_gimple/emit_loops.py:1938-1941` (`_is_pair_var` and
  `_dict_item_pair_vars`).
- The interpreter's output for the same source is correct, so this is the
  compiled path alone.
