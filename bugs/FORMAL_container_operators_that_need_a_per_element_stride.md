# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED — item 3 (set algebra) is LANDED on arm64, and so is
item 4 (a length-changing slice store) for a name bound to a list literal, in
both directions; items 1 (container `==`/`!=`) and 2 (ordering) are unchanged,
and so is item 4's x86-64 half.** `test_formal_container_methods.py` measures
the whole surface against CPython on both architectures and is green; this doc
is about the rows in it that are green *as refusals*, which is a different thing
from green as answers. More of those rows are answers now.

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

**2026-10-13 (`formal342-docs`): item 4, a LENGTH-CHANGING slice store, is
lowered on arm64 for a name bound to a list literal.** Measured, both
directions, `test_formal_container_methods.py list`: `a = [3, 1, 2]` then
`a[0:1] = [9, 9, 9]` answers `9 9 9 1 2` and `a[0:1] = []` answers `1 2`, where
before both **exited 1 with nothing on stdout and nothing on stderr** — the
silent-stop class this file exists to record, and the last row of the "What was
wrong" table below that is still a stop. The lowering is
`formal/arm64_codegen.py::_emit_slice_store`'s RESIZE arm: `delta = len(value) -
(stop - start)`; a positive delta memmoves the tail `[stop, count)` UP, walking
`i` from the count down so each source is read before the higher slot it moves
into is written, a negative delta moves it DOWN from `stop`, and the count is
bumped by `delta`. Both directions are pinned as separate rows because a resize
that moved the tail the wrong way passes a length-only reading — the group
prints all five elements of the grow and the two of the shrink — and so are the
two boundary shapes: an EMPTY range (`a[1:1] = [9]`, an insertion whose `delta`
is the whole value length) and a BACKWARDS one (`a[3:2] = [9]`, which CPython
normalizes to an empty range at `start`; the resize clamps `stop` up to `start`
the way the other bounds are clamped rather than stopping on it).

**The room a growth needs is a reservation, not a heap, and it comes from the
append machinery rather than a second one.** `model.slice_store_growth_slots`
returns `len(value)` (an upper bound on `len(value) - range`, since the range is
never negative) and `_scan_list_caps` counts the store beside the appends that
grow the same literal, so `_emit_list` reserves the room and the store's
capacity guard (`model.blob_growth_overflow_message`, the same sentence a `+`
and an `|` write) stops a grow past it. A store whose value length is not
build-time known reserves nothing and keeps the run-time guard; a store on a
receiver that is not a name bound to a literal — a parameter, a member, a
bound name that is not a literal — keeps the SAME-LENGTH replace and its
diagnostic, which is the same split `list.append` already makes. The x86-64
half is untouched: a slice there is a materialised copy, so
`slice_store_refusal` refuses the store outright and the rows carry
`BACKEND_ONLY["x86_64"]`.

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
| `a[0:1] = [9, 9, 9]` | exit 1, no output, no message | `[9, 9, 9, 1, 2]` | silent stop — **FIXED on arm64 2026-10-13** (item 4) |
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
   a memmove of the tail by `len(v) - (b - a)` elements and a count bump.
   **LANDED on arm64 2026-10-13** (see the Status note): `_emit_slice_store` now
   emits the memmove (up for a grow, down for a shrink) and the count bump, and
   `_scan_list_caps` reserves the room the way `_emit_list_append`'s growth
   already did. x86-64 has no slice store at all and still refuses the whole
   construct.

The stride is the whole of it, and it is not free: `model.blob_elem_stride`
already answers it for `list:int`, `list:str` and a dict's `list:<value-elem>`
pair stride, and a nested container's elements are **addresses**, so
`[[1]] == [[1]]` is a recursive compare and `["ab"] == ["cd"]` is a content
compare over `char *`s. Neither is the word compare the ALU would do, which is
the second reason this is a project rather than a rewrite.

## What to do, in order

1. **`&`, `^`, `-` between two sets** (item 3) — **DONE on arm64
   (2026-10-06).** The rows moved to probes and the augmented forms desugar onto
   the binary lowering; x86-64 still refuses all three, so the rows carry
   `BACKEND_ONLY`. What did NOT happen is the prescribed removal from
   `CONTAINER_GATED_OPS`: that table is shared, and dropping an operator there
   would send x86-64 into the ALU on two addresses. The backend intercepts
   first, the way `|` already splits `_emit_set_union` from
   `set_union_refusal`. The remaining x86-64 half is item 3's second half and is
   not started. See the Status at the top for the measurements and the emitters.
2. **`==` / `!=` between two containers** (item 1). Both backends. Bigger than
   item 3 because the answer may be a recursive descent over nested blobs and a
   content compare over `char *` elements, so it is a value-model question and
   not only an emitter one. It also has a proof obligation the others do not:
   the loop is data-dependent, where every current container loop is
   count-bounded.
3. **Ordering** (item 2). Both backends. Strictly after item 1, and it reuses
   item 1's compare — a three-way element compare is the same inner loop with a
   different exit.
4. **A length-changing slice store** (item 4). **DONE on arm64 for a name
   bound to a list literal (2026-10-13)**; see the Status note above for the
   emitter and the reservation. What is left is x86-64, which needs a slice to
   stop being a materialized copy before the store can mean anything, and the
   arm64 readers that cannot be resized in place — a name that is not bound to a
   literal, a member, a parameter — which keep the same-length replace and its
   diagnostic, the same split `list.append` makes.

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