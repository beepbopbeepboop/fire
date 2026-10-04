# Iterating a `set` loses the element type, so `sorted()` on one answers by ADDRESS

## Status

FIXED 2026-10-04 — the doc's acceptance bar is met — and KEPT, because the
`for`-over-a-set-parameter half is a DIFFERENT and larger defect that this fix
does not reach. Both are recorded below with what was measured.

What landed, and what it was:

**A set LITERAL passed as a call argument recorded no element type at all.**
The cross-call element-type contract in `mojo/backend_gimple/module_gen.py` has
two argument paths — `_static_arg_elems` for positional, `_literal_arg_elems`
for keyword — and BOTH recognised `ListExpr` only. So `f({'r','q'})` observed
nothing, an unannotated set parameter stayed at the `int64_t` default, and every
reader of its elements used the int accessor. The damage was the three
consequences this doc listed, all of them gone:

* the set comprehension arm read each element as a boxed pointer DECIMAL and
  then STORED those decimals (`mojo_set_add_int`), so `sorted()` of the result
  ordered by address — the answer depended on where the string literals landed,
  which is the intermittency this was filed for;
* `sorted(<set of strings>)` no longer answers by address;
* a set of strings iterated as boxed pointers.

```python
def pick(box):
    box = {v for v in box}
    return sorted(box)

def via_for(box):
    out = []
    for v in box:
        out.append(v)
    return sorted(out)

print(pick({'r', 'q'}))       # CPython ['q', 'r']   was ['r', 'q']
print(via_for({'r', 'q'}))    # CPython ['q', 'r']   was [4313143584, 4313143600]
```

Both lines now print CPython's answer on BOTH pipeline modes. Regression:
`gimple_set_literal_param_keeps_its_element_type` in `test_gimple_runner.py`,
against CPython so the ORDER is pinned and not just the set. The generated C is
the evidence that the element type really crossed: `mojo_set_iter_val_str` and
`mojo_set_add_str` in the comprehension, `mojo_list_get_str` for the loop
target, and `mojo_list_sorted_str` for the `sorted()`.

`test_silent_noop_iter.py` — the intermittent red this was filed for — is
27 passed / 0 failed, on consecutive whole-file runs (see "Verified" in the
commit message for the count actually measured).

## What is NOT fixed, and is larger: a set PARAMETER's container KIND

`via_for`'s parameter is still declared `MojoList *` for a set argument:

```c
MojoList * via_for_815e8f (MojoList * box)     /* the call site passed a MojoSet * */
```

It produces the right answer only because `MojoSet`'s first two fields are
`len` and `data` exactly as `MojoList`'s are, so `mojo_list_len` /
`mojo_list_get_str` read the right words. Nothing in this tree types a
PARAMETER's container kind from its call sites: `_scalar_obs`'s
container-literal arm records `'void *'` and is explicitly whitelisted away by
the application loop, on the grounds that "the pointer is real information" and
the element type is recorded elsewhere — which was true until this fix made the
element type real for sets too, and is now the only thing standing between a set
parameter and a list parameter.

It is visible without a set argument, and badly:

```python
def via_for(box):
    out = []
    for v in box:
        out.append(v)
    return out

s = {"b", "a", "c"}
print(via_for(s))
```

    CPython   ['b', 'a', 'c']
    compiled  [4294967295, 0, 0]   and then the process SEGFAULTS (rc -11)

A `for` over a set must go through `mojo_set_iter_new` / `_next` /
`_val_str` / `_free` — `emit_loops.py`'s `_gen_for_set`, which exists and is
selected by `it_type == 'MojoSet *'` — so that the values come out in the
runtime's INSERTION order (`mojo_set_order_indices`, which is the runtime's
determinism requirement, see `mojo_set_to_list`'s comment). Reading `slots[]`
through the list accessors instead yields the hash-table order, which for a
three-element set is three words of pointer bits read as integers.

Verified pre-existing: the same program compiled on `git archive ccb157ed`
(this branch's base, before any of this branch's work) produces
**byte-identical** output, `[4294967295, 0, 0]` then `rc=-11`, in both pipeline
modes. So this is not caused by the element-type fix above.

### The exact next step for that half

1. One new observation table beside `_scalar_obs`:
   `{callee: {pname: set_of_container_ctypes}}`, filled from the call site's
   argument with the same unanimity rule `_record_param_elem` uses — and
   applying `_struct_obs`'s rule rather than `_record_param_elem`'s, because the
   question is "is every call site a `MojoSet *`?" and a `None` must mean
   "disagree" rather than "unknown". A `SetExpr` argument is provably
   `MojoSet *` and a `ListExpr` provably `MojoList *`, so this table has real
   evidence to work with from the first call site, unlike the element type.
2. Apply it in `emit_funcs.py`'s `gen_func`, beside the existing
   `_param_elem_types` seeding: a slot this table resolves becomes
   `gen.var_types[name]`, which is what `emit_loops.py`'s dispatch reads. The
   declaration follows from `var_types`, so the prototype and the body cannot
   disagree — which is the failure the dict-value twin's comment warns about.
3. Then assert the program above against CPython, plus one where the set
   survives a call (`g(s)`) so the seed and the dispatch are pinned separately.
   Until step 1 lands, `for v in <set>` reads a set as a list everywhere, and
   that is a SIGSEGV on a four-line program.

## Original report (2026-10-03)

Found while integrating the parallel stdlib-xfail tree. It was filed rather than
fixed there: it is a separate codegen project (set element-type tracking), it is
outside the area that session was working in, and it is the cause of an
INTERMITTENT red in `test_silent_noop_iter.py`, which is worth recording
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

## What this doc asked for, and where each item landed

* "the set comprehension arm `_compr_set_loop` (which then emits
  `mojo_set_add_str`)" — **already consulted the side table and needed no
  change** (`mojo/backend_gimple/emit_infra.py`'s `_sv_is_str` check on
  `_elem_of(_iv)`). What it needed was for the side table to have an entry,
  which is the fix above; the arm then emitted `mojo_set_iter_val_str` and
  `mojo_set_add_str` with no edit at all.
* "the set loop in `emit_infra`/`emit_loops`" — same: `emit_loops.py` reads
  `_elem_types` through the same table, and produced `mojo_list_get_str` for the
  target once it did. The loop's ACCESSOR is right; its CONTAINER is the
  separate defect above.
* "`mojo_set_sorted`'s `is_str` decision, which is a RUNTIME fact here and
  should become a compile-time one" — not needed for this fix, and deliberately
  not done: the set the comprehension builds really does tag every slot with
  `mojo_set_add_str`, so the runtime's `is_str` is correct and the decision is
  only a fact in the wrong place. Making it compile-time would mean the codegen
  tracking a set's element type through `mojo_set_update`/`mojo_set_add`
  call-by-call, which is a bigger table than the one the fix above needed.

The acceptance bar is met for the element-type half: the two-line program prints
CPython's two lines in both pipeline modes, and `test_silent_noop_iter.py`
passes on consecutive whole-file runs — one green run proves nothing here, which
is how this reached a gate at all.
