# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED 2026-10-08 — item 3 (the set algebra) is LANDED ON
BOTH BACKENDS; items 1, 2 and 4 are still open.**
`formal/arm64_codegen.py::_emit_set_algebra` / `_emit_set_filter` and the
x86-64 twin of the same two methods now lower `&`, `-` and `^` between two sets
as the per-element membership scan item 3 prescribed, and the five rows in
`test_formal_container_methods.py`'s `set` group (`s_intersection`,
`s_difference`, `s_symdiff`, `s_sub`, `s_andassign`, plus the operator-matrix
rows `o_and`/`o_xor`) moved from `probe=None` to answer probes measured against
CPython on BOTH architectures — no `BACKEND_ONLY` rows remain for them.  The
`|` union rows are still `BACKEND_ONLY` on x86-64 (a separate gap: x86-64 has
no union emitter), but item 3 is not about `|`.  The gate's own docstring and
the `CONTAINER_GATED_OPS` comment now say that arm64 and x86-64 intercept before
`container_operator_refusal` for two sets and that the operator set is NOT
narrowed, because the refusal is still correct for a list/tuple/dict operand and
for everything the set test does not take.  Items 1 (`==`/`!=`), 2 (ordering)
and 4 (a length-changing slice store) are unchanged and still open.  The rest of
this document is the 2026-10-06 analysis and stands as written.

## The set algebra as landed (`_emit_set_algebra`)

The one algorithm item 3 named — "copy the left, then for each right-hand
element scan the result and append it if it is absent" — is now written as a
generic `_emit_set_filter(offset, src, scount, other, ocount, keep_found)` on
each backend: the outer loop walks the source blob, the inner loop scans the
other blob for the element, and `keep_found` picks INTERSECTION (keep the
present ones) from DIFFERENCE (keep the absent ones).  Symmetric difference is
the two differences appended to one result blob.  The result starts EMPTY and
grows one append at a time, unlike `_emit_set_union`, which starts by copying
the left operand; the reservation is `nL + nR` for all three (a symmetric
difference can hold every element of both sides) and goes through the same
`_emit_blob_growth_guard` the union, concatenation and repetition sites use.

**Elements are compared as words**, so a set of `char *` compares addresses
exactly as `_emit_set_union`'s dedup does — the divergence
`bugs/FORMAL_set_value_model.md` already documents, not a new one, and the
reason the landed cases use integer elements.  A recursive/content compare is
item 1's value-model question, not this one's.

**Measured, both architectures, against CPython**
(`test_formal_container_methods.py set` and `operator`, green; `s = {1, 2}`):
`s & {2}` → sum 2 len 1, `s - {2}` → sum 1 len 1, `s ^ {2}` → sum 1 len 1,
`s -= {2}` → sum 1 len 1, `s &= {2}` → sum 2 len 1.  The 2026-10-06 "before"
table below is unchanged history.

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

1. **`&`, `^`, `-` between two sets** (item 3). **DONE ON BOTH BACKENDS
   2026-10-08** — `formal/arm64_codegen.py::_emit_set_algebra` /
   `_emit_set_filter` and the x86-64 twins of both, with the five `set`-group
   rows and the two operator-matrix rows moved to answer probes measured against
   CPython on both architectures and NO `BACKEND_ONLY` row for them. The
   original plan was "arm64 only, then x86-64; both already have `_set_vars` and
   `container_union_refusal` to gate on", but the shared
   `container_operator_refusal` is asked by both backends, so each backend
   intercepts before it with `_expr_is_set_like` on both operands. The x86-64
   port is not a line-for-line translation — its register plan follows
   `_emit_list_concat` and the counts become end pointers in
   `_emit_set_filter` — but it is the same two loops and the same
   `keep_found` predicate. Each row in `test_formal_container_methods.py`'s
   `set` group (`s_intersection`, `s_difference`, `s_symdiff`, `s_sub`,
   `s_andassign`) is now an answer case on both backends.
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