# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status 2026-10-07 (`work/formal149-docs`): item 3 — SET ALGEBRA — is FIXED on
arm64, which is the landing order this doc prescribes ("arm64 only, then
x86-64").** `_emit_set_algebra` in `formal/arm64_codegen.py` lowers `&`, `-`
and `^` between two sets over the same `[count][element]…` word blobs
`_emit_set_union` already handles, with one shared inner scan
(`_emit_blob_word_scan`) and one shared pass (`_emit_set_pass`) for the three
operators; the augmented forms (`s &= {2}`, `s -= {2}`) route through the same
emitter via the existing `aug_assign_operands_are_blobs` desugaring. The gate
moved: `model.CONTAINER_GATED_OPS` no longer holds the three, and the new
`model.container_set_algebra_refusal` (asked beside `container_union_refusal` at
the `|` site) refuses every pair that is NOT two sets — `[1, 2] & [3, 4]` is a
`TypeError` in CPython and still a refusal here — while `model.SET_ALGEBRA_OPS`
is the one spelling of the set. x86-64 has no emitter for any of the three (it
has none for `|` either), so `model.set_algebra_backend_refusal` names it and
the five set-group cases plus `o_and`/`o_xor` are `BACKEND_ONLY` there.
Measured: `test_formal_container_methods.py` `set`+`operator` groups green on
both architectures, `{1,2,3,4,5} & {2,4,9}` = `{2,4}`, `{1,2,3}-{9}` = all
three, `{1,2}^{3,4}` = `{1,2,3,4}`, and the loop cases hold their counts.

**What is still open, and it is items 1, 2 and 4 of "What to do, in order"
below:** `==`/`!=` between two containers (item 1), ordering (item 2), and a
length-changing slice store (item 4). None is touched by the set-algebra change
and all three are still refused exactly as measured below.

**The original status: NOT FIXED — four lowerings, one shared obstacle, and the
refusals that stand in for them are landed.** `test_formal_container_methods.py`
measures the whole surface against CPython on both architectures and is green;
this doc is about the rows in it that are green *as refusals*, which is a
different thing from green as answers.

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

1. ~~**`&`, `^`, `-` between two sets** (item 3).~~ **DONE on arm64
   2026-10-07 (`work/formal149-docs`); x86-64 still refuses.** arm64 lowers all
   three over the union's blob shape, with the augmented forms desugared onto
   the same emitter; each row in `test_formal_container_methods.py`'s `set`
   group (`s_intersection_r`, `s_difference_r`, `s_symdiff_r`, `s_sub_r`,
   `s_andassign_r`) and the two in `operator` (`o_and`, `o_xor`) became answer
   cases, and the three left `model.CONTAINER_GATED_OPS` for the new
   `model.container_set_algebra_refusal`. x86-64 has no union emitter to build
   on, so it refuses a set operation by name
   (`model.set_algebra_backend_refusal`) and those seven cases are
   `BACKEND_ONLY` there — that backend is the remaining half of this item.
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