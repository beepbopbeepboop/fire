# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED — item 3 (set algebra) is LANDED on BOTH backends
(`&`, `^`, `-` between two sets; x86-64 landed 2026-10-12, see §"2026-10-12");
items 1 (container `==`/`!=`), 2 (ordering) and 4 (a length-changing slice
store) are unchanged.** The one gap item 3 still has is `|` on x86-64, which is
a SEPARATE pre-existing emitter (`set_union_refusal`) and not item 3's three
operators. `test_formal_container_methods.py` measures the whole surface
against CPython on both architectures and is green; this doc is about the rows
in it that are green *as refusals*, which is a different thing from green as
answers. The three item-3 operators are answers on both machines now.

## 2026-10-12: item 3's x86-64 half landed — the three set operators answer on
## both backends, and the rows left `BACKEND_ONLY`

**What landed.** `formal/x86_64_codegen.py` grows the three emitters item 3's
arm64 half already had, as the x86-64 twins of them:
`_maybe_emit_set_binop` (the binary AND augmented predicate, so `s -= {2}`,
`s &= {2}` and `s ^= {2}` desugar onto the same lowering), `_emit_set_op` (the
capacity and guard rules are arm64's: `&` and `-` reserve `nL`, `^` reserves
`nL + nR`), and `_emit_set_filter_pass` (the per-element membership scan, run
twice swapped for `^`). The `_emit_binop` site asks it before the shared gate,
exactly as arm64 does, and `model.set_algebra_refusal`'s call site now passes
`backend_has_emitter=True`, because the backend has one.

**Measured, `test_formal_container_methods.py set operator`, both
architectures.** `set` on x86-64 moved **4 → 9 answers** (the five rows
`s_intersection_r`, `s_difference_r`, `s_symdiff_r`, `s_sub_r`, `s_andassign_r`
are no longer `BACKEND_ONLY`); `operator` is **11 answers on both backends**
(`o_xor`, `o_and` left `BACKEND_ONLY` too), 0 backend-only rows in either group.
arm64 is unchanged. The five set rows are observed through a SUM and a length,
so a result with the right count and the wrong element still fails.

**The structural half is pinned per backend, and that is the new part.** The
arm64-only `_BLOB_GROWTH_PROBES` rows for `sin`/`sdf`/`ssd` gain an `x86_64`
twin each, because the two emitters are separate implementations and a guard on
one says nothing about the other. `check_blob_growth_guards` reports
`PASS=11 FAIL=0`, and each new site's guard is 17 x86-64 instructions (against
the `_BLOB_GROWTH_MIN_WORDS = 8` floor), so a site that kept its call and
emitted nothing would still be caught.

**What did NOT move, and why it is not this item.** `|` on two sets is still
refused on x86-64 — that is `_emit_set_union`'s gap, a different emitter with a
different reservation, and the four `s_union*` rows keep their
`BACKEND_ONLY["x86_64"]`. Items 1 (element-wise `==`/`!=`), 2 (ordering) and 4
(the length-changing slice store) are untouched; item 1 is still the next
prescribed step and is still the largest of the four.

**2026-10-06 (`formal109-docs`): `&`, `^`, `-` between two SETS are lowered on
arm64.** Measured, both architectures, `test_formal_container_methods.py set`:
13 answers equal CPython on arm64 (up from 10 — `s_intersection_r`,
`s_difference_r`, `s_symdiff_r`, `s_sub_r`, `s_andassign_r` moved), x86-64
unchanged at 4 with the same 9 refusals. The five rows were observed through a
SUM and a length rather than a length alone, so a result with the right count
and the wrong element fails. The three emitters are
`formal/arm64_codegen.py::_emit_set_op` and `_emit_set_filter_pass`, with the
union's reservation and growth guard (an intersection or a difference reserves
`nL`; a symmetric difference `nL + nR`); the augmented `-=`/`&=` desugar onto
them through `_maybe_emit_set_binop`, which is asked by BOTH the binary and the
augmented emitter — the augmented one used to reach the shared gate first, and
`s -= {2}` and `s = s - {2}` are the same operator and must not get two answers.

**The gate did NOT narrow the way §"What to do, in order" item 1 prescribed, and
the reason is a correction worth keeping.** Item 1 said to drop `&`/`^`/`-` from
`model.CONTAINER_GATED_OPS` and move the rows to probes. That table is SHARED by
both backends, so dropping an operator there would have made x86-64 — which has
no set emitter at all — fall through to the integer ALU on two addresses, which
is exactly the wrong answer the gate was widened for. Instead arm64 intercepts
the two-set shape in `_emit_binop` (and the augmented emitter) BEFORE
`string_binary_refusal`, and the shared gate is untouched: it still refuses
`[1] - [2]` (CPython's `TypeError`) and still refuses all three for x86-64, which
is the same split `|` already had (`_emit_set_union` vs `set_union_refusal`).
The five rows therefore carry `BACKEND_ONLY[...] = "x86_64"`, and the `operator`
group's duplicate `o_xor`/`o_and` rows were re-pointed at probes the same way
(`o_sub`, a LIST difference, stays a refusal on both backends). The structural
half is pinned by four new `_BLOB_GROWTH_PROBES` rows, so each new site has to
keep emitting its capacity guard.

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

1. **`&`, `^`, `-` between two sets** (item 3) — **DONE on BOTH backends
   (arm64 2026-10-06, x86-64 2026-10-12).** The rows moved to probes and the
   augmented forms desugar onto the binary lowering; the five `set` rows and the
   two `operator` rows left `BACKEND_ONLY`. What did NOT happen is the
   prescribed removal from `CONTAINER_GATED_OPS`: that table is shared, and
   dropping an operator there would send a backend with no emitter into the ALU
   on two addresses. Each backend intercepts first, the way `|` still splits
   `_emit_set_union` from `set_union_refusal`. `|` itself is still arm64-only
   and is a separate emitter, not one of these three. See the Status at the top
   and §"2026-10-12" for the measurements and the emitters.
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