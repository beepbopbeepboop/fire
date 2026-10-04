# Iterating a `set` loses the element type, so `sorted()` on one answers by ADDRESS

## Status

OPEN, found 2026-10-03 while integrating the parallel stdlib-xfail tree. Not
fixed here: it is a separate codegen project (set element-type tracking), it is
outside the area the integrating session was working in, and it is the cause of
an INTERMITTENT red in `test_silent_noop_iter.py`, which is worth recording
precisely rather than acting on under time pressure.

## What I ran

`python3 tools/suite.py … silentnoop …` on a worktree whose only other change
was the iterator-cursor work (see "Not this change" below). It failed:

```
FAIL  parameter_rebound_to_one_container_kind_is_not_multi_kind
      compiled "['a']\n['x']\n['r', 'q']\nfirst\n" != reference "['a']\n['x']\n['q', 'r']\nfirst\n"
```

A second run of `python3 test_silent_noop_iter.py` passed. So it is
intermittent, and the failing line is the third `print` of the case's program —
`sorted()` over a set that a set COMPREHENSION built.

The case is `test_silent_noop_iter.py`'s
`parameter_rebound_to_one_container_kind_is_not_multi_kind`, whose program is:

```python
def pick(box):
    if box is None:      box = {"a"}
    elif box == "x":     box = {box}
    else:                box = {v for v in box}
    return sorted(box)
```

## What is actually wrong

Minimised to a program that fails EVERY time, not intermittently:

```python
def pick(box):
    box = {v for v in box}
    return sorted(box)

def via_for(box):
    out = []
    for v in box:
        out.append(v)
    return sorted(out)

print(pick({"r", "q"}))
print(via_for({"r", "q"}))
```

    compiled:  ['r', 'q']                     CPython: ['q', 'r']
    compiled:  [4313143584, 4313143600]        CPython: ['q', 'r']

The second line is the clearer half: the `for` loop over a set of strings
yields two raw heap-address decimals.

The generated C says why. Both shapes read the set's element through the INT
accessor:

```c
  v = mojo_set_iter_val_int (_t2);
  ...
  mojo_set_add_int (_t1, _t5);
```

while the set literal itself was built correctly:

```c
  mojo_set_add_str (_t1, _t2);
  mojo_set_add_str (_t1, _t3);
```

So a `MojoSet *`'s element type is never tracked, and every reader of a set's
elements (`emit_infra`'s set loop, the set comprehension arm, `sorted()`) uses
`mojo_set_iter_val_int`. Three consequences, all silent, all exit 0:

1. **A set of strings iterates as boxed `int64_t` pointers.** `via_for` above is
   a pointer decimal per element, and the decimals are ASLR-dependent.
2. **`sorted(<set of strings>)` sorts the POINTERS.** `mojo_set_sorted`
   (runtime/fire_runtime.c:10326) decides whether to sort as strings from the
   SLOT TAGS — `is_str` — and a set built by a comprehension has every slot
   tagged `0`, so it takes the `mojo_sorted` branch and orders the boxed
   addresses numerically.
3. **The answer therefore depends on where the string literals were placed,
   which depends on how many other programs the same compiler PROCESS compiled
   first** (string literals are interned per compile, and the interning order
   decides the `_slit_10000`, `_slit_10001`, … numbering, which decides the
   static arrays' relative addresses). That is the intermittency: the case's own
   program is stable, and its answer flips when its literals land the other way
   round. Isolated, the same program printed `['q', 'r']` on eight consecutive
   runs and `['r', 'q']` inside the whole-file harness.

## Not this change

The merged tree's own generated C for the failing case is BYTE-IDENTICAL with
and without the iterator-cursor work that was in flight
(`diff` of `gimple_codegen._run_pipeline("…pick.py…", link_mode=True)`'s output
against the same call on `HEAD`, 1474 lines each, no diff), and the
cursor/span paths are not reachable from that program. Verified before filing.

## Next step

Track a set's element type the way `MojoList *` already is — `gen._elem_types`
is the side-table, `_lower_struct_constructor`'s `Span` branch and the list
literals already populate it — and have the three readers consult it:

* the set loop in `emit_infra`/`emit_loops` (`mojo_set_iter_val_int` →
  `_str`/`_double` by `TypeLattice.list_suffix(elem)`);
* the set comprehension arm `_compr_set_loop` (which then emits
  `mojo_set_add_str`);
* `mojo_set_sorted`'s `is_str` decision, which is a RUNTIME fact here and
  should become a compile-time one — a set built with `add_str` everywhere can
  be sorted with `mojo_list_sorted_str` unconditionally.

Acceptance bar, in the spirit of `compile_stdlib.py`'s own (the check is
`gcc -fsyntax-only` and cannot see any of this): the two-line program above
must print CPython's two lines in both pipeline modes, AND
`test_silent_noop_iter.py` must pass on five consecutive whole-file runs — one
green run proves nothing here, which is how this reached a gate at all.
