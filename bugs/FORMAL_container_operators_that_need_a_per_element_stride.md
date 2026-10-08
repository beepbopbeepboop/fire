# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED 2026-10-08 (`work/formal197-docs`). ITEM 3 — set
algebra `&`, `^`, `-` — IS LOWERED ON arm64, with its augmented forms; the five
rows that were refusals are answers now. The x86-64 half of item 3 and items 1,
2 and 4 are still open, and this document is the record of exactly what
landed and what did not.** `test_formal_container_methods.py` measures the
whole surface against CPython on both architectures and is green; this doc is
about the rows in it that are green *as refusals*, which is a different thing
from green as answers.

## What landed 2026-10-08: item 3 on arm64

`arm64_codegen.py::_emit_set_algebra`, with `_emit_set_select`/`_emit_set_append`
beside it, lowers `a & b`, `a - b` and `a ^ b` over two set blobs to CPython's
answers element-wise over the 8-byte element stride: `&` keeps every element of
`a` also in `b`, `-` keeps every element of `a` not in `b`, and `^` is both
directions of `-` (the two appended sequences are disjoint because both operands
hold unique elements, so — unlike `_emit_set_union` — no dedup pass is needed).
It shares `_emit_set_union`'s reservation, `_emit_blob_growth_guard` and
`_emit_list_base`, so a site's frame cost does not depend on which of the four
operators it is. The augmented spellings `s &= {2}`, `s -= {2}`, `s ^= {2}` reach
the same emitter through the existing container desugaring.

**The gate became per-backend, because the answer is.** `&`, `^` and `-` stay in
`model.CONTAINER_GATED_OPS` — x86-64 still has no emitter and still refuses them
— and arm64 passes `lowered_container_ops=model.SET_ALGEBRA_OPS` to
`string_binary_refusal` at its two call sites (`_emit_binop` and the augmented
`_emit_aug`), which makes `container_operator_refusal` stand aside for exactly
those three. Arm64 then asks the new `model.container_setop_refusal`, which
lowers only `set OP set` and refuses a LIST/dict/other operand by name — CPython
raises `TypeError` for every one of those, so refusing is the correct answer,
not a missing feature. `o_sub` (two LISTS) is still a refusal on both backends
and pins that.

**Measured, `test_formal_container_methods.py set operator`, both backends,
green:**

| | before | after |
|---|---|---|
| `set` group, arm64 answers | 8 | **13** |
| `set` group, x86-64 answers | 4 | 4 (unchanged) |
| the five `s_*_r` rows | refusals on both | **answers on arm64**, arm64-only |

The five moved rows are `s_intersection_r`, `s_difference_r`, `s_symdiff_r`,
`s_sub_r` and `s_andassign_r`; each now proves the CONTENTS (`sum` and `len`)
rather than only the length, and each is `BACKEND_ONLY['…'] = 'x86_64'`. The
operator group's `o_xor`/`o_and` are now arm64-refused-x86-64 rows
(`BACKEND_ONLY = 'arm64'`), since arm64 answers them.

**What is left on item 3**: the x86-64 emitter. That backend has no set union
either (`_emit_set_union` does not exist there; `s_union` and its siblings are
arm64-only), so the x86-64 half is four emitters written from scratch over
`_emit_list_concat`'s reservation/copy machinery, not a port of the arm64 one.

- Original status follows.

**Status (pre-2026-10-08): NOT FIXED — four lowerings, one shared obstacle, and
the refusals that stand in for them are landed.**

Branch `work/formal64-container-methods`, claim `project:container-methods`. Every
number below is measured on that branch, on both `arm64` and `x86-64`, and each
has a named row in `test_formal_container_methods.py`.

## What was wrong, and what landed instead

Before this branch, ten container operators reached either the flag-setting
compare or the integer ALU holding a blob's **ADDRESS**, and answered. Measured:

| source | this path, before | CPython | outcome class |
|---|---|---|---|
| `a = [3, 1, 2]`; `1 if a == [3, 1, 2] else 0` | `0` | `1` | silent wrong number |
| `a != [3, 1, 2]` | `1` | `0` | silent wrong number |
| `s = {1, 2}`; `s & {2}` | `2` on arm64, `163061056` on x86-64 | `1` | the two architectures disagreeing about neither |
| `s - {2}` | SIGSEGV, no output | `1` | crash |
| `s ^ {2}` | SIGSEGV, no output | `1` | crash |
| `s -= {2}` | SIGSEGV, no output | `1` | crash through the *second* emitter |
| `s &={2}` | `2` / garbage | `1` | silent wrong number |
| `a += [3]` | `0` on arm64, SIGSEGV on x86-64 | `3` | wrong number / crash |
| `a *= 3` | SIGSEGV on both | `3` | crash |
| `s \|= {3}` | `1` / `0` | `3` | wrong number |
| `d \| {"b": 2}` | `1` | `2` | wrong number, via integer `ORR` |
| `[1, 2] \| [3]` | `3` | `TypeError` | answering a program CPython rejects |
| `[1] in [[1], [2]]` | `1` on arm64, `0` on x86-64 | `1` | the two architectures disagreeing |
| `b = [1]; b in [[1], [2]]` | `0` on both | `1` | wrong number |
| `a[0:1] = [9, 9, 9]` | exit 1, no output, no message | `[9, 9, 9, 1, 2]` | silent stop |
| `t = (1,2,3); t[0] = 9` | `t0=9 len=3` | `TypeError` | wrong *mutation* |
| `for k in d: del d[k]` | `1` | `RuntimeError` | wrong number |
| `for k in d: d["z"] = 5` | `2` | `RuntimeError` | wrong number |
| `d["z"]` (miss) | exit 1, no message | `KeyError` | silent stop |

All of those are refused, or stopped with a diagnostic that names the rule. The
table is not where the remaining work is.

## The obstacle, stated once

Every answer CPython gives for these is **element-wise over a per-element
STRIDE**, and this path's blob is `[count:i64][elem0][elem1]…` in 8-byte slots
with the element's own width known only at run time
(`model.blob_elem_stride`, `model.walk_shift`). The four lowerings need:

1. **`==` / `!=` between two containers** — compare lengths, then compare
   element by element at the element's stride. `container_operator_refusal`
   covers `==`, `!=`, `<`, `<=`, `>`, `>=`, `-`, `&`, `^` and the six operators
   CPython itself refuses; the refusal exists because the answer is a project.
2. **Ordering** — the same loop with a three-way compare at the first index
   where the two differ, plus the shorter-prefix rule. The refusal is older than
   this branch and its measurement is in `container_operator_refusal`'s own
   docstring.
3. **Set algebra** — `&`, `^`, `-` between two sets: a per-element membership
   scan per element of the right-hand side. arm64's `_emit_set_union` ALREADY
   does exactly that shape for `|` (copy the left, then for each right-hand
   element scan the result and append it if it is absent), so the ALGORITHM is
   written and three emitters are not: `_emit_set_intersection`,
   `_emit_set_difference`, `_emit_set_symmetric_difference`, each as the same
   two nested loops with a different keep/drop predicate. This is the cheapest
   of the four by a wide margin and it is the one to do next.
4. **A length-changing slice store** — `xs[a:b] = v` where `len(v) != b - a`:
   a memmove of the tail by `len(v) - (b - a)` elements and a count bump. The
   primitives are both already here: `_emit_del_list_range` memmoves a tail and
   shrinks the count, and `_emit_list_append` grows it past the count into
   reserved capacity. arm64's `_emit_slice_store` is a same-length copy loop and
   x86-64 has no slice store at all.

The stride is the whole of it, and it is not free: `model.blob_elem_stride`
already answers it for `list:int`, `list:str` and a dict's `list:<value-elem>`
pair stride, and a nested container's elements are **addresses**, so
`[[1]] == [[1]]` is a recursive compare and `["ab"] == ["cd"]` is a content
compare over `char *`s. Neither is the word compare the ALU would do, which is
the second reason this is a project rather than a rewrite.

## What to do, in order

1. **`&`, `^`, `-` between two sets** (item 3). **arm64 DONE 2026-10-08**
   (`_emit_set_algebra`); **x86-64 still open**, and it is the four-emitter job
   the landing note above sizes. Both backends already have `_set_vars` and the
   union gate to key on. The five `set`-group rows
   (`s_intersection_r`, `s_difference_r`, `s_symdiff_r`, `s_sub_r`,
   `s_andassign_r`) moved from `probe=None` to a probe and are arm64-only; the
   operator group's `o_xor`/`o_and` moved to arm64-refused-x86-64.
2. **`==` / `!=` between two containers** (item 1). Both backends. Bigger than
   item 3 because the answer may be a recursive descent over nested blobs and a
   content compare over `char *` elements, so it is a value-model question and
   not only an emitter one. It also has a proof obligation the others do not:
   the loop is data-dependent, where every current container loop is
   count-bounded.
3. **Ordering** (item 2). Both backends. Strictly after item 1, and it reuses
   item 1's compare — a three-way element compare is the same inner loop with a
   different exit.
4. **A length-changing slice store** (item 4). arm64 first (it is the backend
   that has the store), and only then x86-64, which needs a slice to stop being
   a materialized copy before the store can mean anything.

## The rows that must not be "fixed" by deleting the case

`test_formal_container_methods.py` asserts a refusal by matching a phrase from a
shared table, so removing a row when its lowering lands would hide the change
rather than record it. **The landing order for each is: drop the operator from
`model.CONTAINER_GATED_OPS`, move the case from `probe=None` to a probe, and
delete nothing.** The docstring of the gate is where the measurement lives, and
it has to be re-measured when the answer is right: "measured answering 0 where
CPython answers 1" is a claim about the pre-fix tree and becomes a false
statement about this one the moment it stops being true.

Three rows in that table are claims about what this path is NOT, and each has a
document saying so: `bugs/FORMAL_set_value_model.md` (a set lowers as a list, so
`for x in s` is insertion-ordered here and hash-ordered in CPython — which is
why the set walk is observed through a SUM), and the two dict-key rows in the
`dict` group, where a pair blob scans its KEYS at stride 16 and a missing key is
a stop rather than a `KeyError` with a traceback.