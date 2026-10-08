# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED — item 3, the set algebra (`&`, `-`, `^`, and `|` on
x86-64), is LANDED on BOTH backends; items 1 (`==`/`!=` between two containers),
2 (ordering) and 4 (a length-changing slice store) remain.**
`test_formal_container_methods.py` measures the whole surface against CPython on
both architectures and is green; the set rows that were green *as refusals* are
now green as answers, and the rows for items 1/2/4 are still green as refusals —
which is a different thing from green as answers.

Branch `work/formal64-container-methods`, claim `project:container-methods`.
Every number below is measured on that branch, on both `arm64` and `x86-64`, and
each has a named row in `test_formal_container_methods.py`.

## What landed 2026-10-08 (`formal162-docs`): the set algebra, both backends

`|`, `&`, `-` and `^` between two SETS are now lowered on arm64 AND x86-64.
Before this, arm64 lowered `|` only and refused the other three; x86-64 refused
all four (`|` by `model.set_union_refusal`, the other three by
`container_operator_refusal`). The predicate is `_try_emit_set_algebra`, asked
from the SYNTAX before the shared gate, because a KIND cannot tell a set from a
list — both are a `list:<elem>` blob — so the gate's message had to stay for
every pair that is not two sets (`[1] & [2]`, `{1} - [2]`), each a CPython
`TypeError`.

* arm64: `_emit_set_op_header` / `_emit_set_append` / `_emit_set_scan` /
  `_emit_set_pass` are the shared machinery, and `_emit_set_intersection`,
  `_emit_set_difference`, `_emit_set_symmetric_difference` are three filters
  over it; `_emit_set_union` is unchanged and now also reached for `s | t`
  between two set NAMES (which the old concat branch missed, because a name
  bound to a set is not a `_is_container_expr`).
* x86-64: the same four, written fresh (`_emit_set_union` did not exist; the
  `|` branch lowered a concatenation and was then refused by
  `set_union_refusal`, which is deleted with the emitter).
* The augmented forms `|=`, `&=`, `-=`, `^=` desugar onto the binary emitters
  in both backends' `_emit_aug_assign`, before the shared gate.
* The blob-growth guard is emitted at every set site, so a reservation the
  static estimate cannot keep is a loud stop rather than a frame overrun.
  `test_formal_run.py`'s `_BLOB_GROWTH_PROBES` grew the x86-64 `uni` row.
* `test_formal_container_methods.py`: the five set rows and the two operator
  rows moved from `probe=None` to answers, and the four `s_union*` rows left
  `BACKEND_ONLY` (x86-64 is no longer a backend that cannot build them).

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

1. ~~**`&`, `^`, `-` between two sets** (item 3)~~ **DONE 2026-10-08, both
   backends** — see "What landed" above. The note below is kept because it is
   what the next item should follow, not because it is still to do: the gate
   narrows from "refuse" to "lower" without new machinery, and the refusal
   stays for every pair that is not two sets. The actual landing did NOT drop
   the operator from `CONTAINER_GATED_OPS` — a KIND cannot tell a set from a
   list, so the set-ness question is asked from the syntax in
   `_try_emit_set_algebra`, before the shared gate, and the gate keeps
   refusing `[1] & [2]` / `{1} - [2]` with the message it always had (reworded
   to name the new lowerings). Each set row in
   `test_formal_container_methods.py` became an answer case and the four
   `s_union*` rows left `BACKEND_ONLY`.
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
rather than record it. **The landing order for each is: move the case from
`probe=None` to a probe, and delete nothing.** The docstring of the gate is
where the measurement lives, and it has to be re-measured when the answer is
right: "measured answering 0 where CPython answers 1" is a claim about the
pre-fix tree and becomes a false statement about this one the moment it stops
being true. For item 3 that re-measurement is the `container_operator_refusal`
STATUS paragraph and the `&`/`-`/`^` message arm, both of which now name the
lowerings and refuse only a non-set pair.

Three rows in that table are claims about what this path is NOT, and each has a
document saying so: `bugs/FORMAL_set_value_model.md` (a set lowers as a list, so
`for x in s` is insertion-ordered here and hash-ordered in CPython — which is
why the set walk is observed through a SUM), and the two dict-key rows in the
`dict` group, where a pair blob scans its KEYS at stride 16 and a missing key is
a stop rather than a `KeyError` with a traceback.