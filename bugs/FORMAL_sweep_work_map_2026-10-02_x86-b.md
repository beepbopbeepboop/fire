# FORMAL_sweep_work_map_2026-10-02_x86-b: an x86-64 sweep of `../new-modular/Mojo/stdlib/std`, and the three causes it closed

**Status: three causes closed and committed (§3), the remaining ones mapped with
a next step each (§4). The sweep of the slice's FULL 252 files did NOT complete
on this machine — §1 says what was reached and why, so nothing here is a claim
about the 210 files it did not.**

Slice `x86-b`, claim `sweep:x86-b`, branch `work/formal4-sweep-x86-b-r2`. This
continues `formal4-sweep-x86-b`, which died of a network error; its `x^` fix
(`d24bf8cf`) is on this branch and is reviewed in §3.4.

## 1. The run, and what it actually reached

```
python3 tools/memslot.py --gb 8 --label sweep-x86-b -- \
  python3 -u tools/formal_sweep.py -j 2 -t 60 --arch x86_64 \
  ../new-modular/Mojo/stdlib/std --no-stdlib --allow-concurrent
```

`-j 2` and `-t 60` because this is a light worker sharing a machine with at
least four other sweeps (measured: `-j3` runs over `std/{os,pathlib,io,format,
hashlib,base64,random,math}`, one over 28 other subtrees, and one over the repo,
all live at once). **At `-t 60` that is the wrong timeout, and the log says so:**
the first seven files classified were all `tool`/`timeout (> 60s)` —
`std/_gpu/{__init__,globals,host/__init__,intrinsics,primitives/__init__,
primitives/id,primitives/warp}.mojo` — because a single
`fire.py build --formal` of one `binary_heap.mojo`-closure file measured **over
two minutes** wall clock on that machine. The tool's own `--help` says of a
timeout "a timeout says raise -t"; these were not slow files.

The run was restarted at `-j 4 -t 500` over a 71-file sub-scope
(`std/collections` + `std/builtin`) and reached **42 of 71** before it was
interrupted. Log: `.tmp/sweep-x86-b2.txt`. **Every count below is over those 42
files and is labelled as such.** The full 252-file run, at `-t 500`, is the
integrator's: it needs an unloaded machine, and this document is written so that
the numbers can be replaced without re-deriving anything below them.

| class | files |
|---|---|
| `pass` | 6 |
| `codegen` | 5 |
| `codegen/dependency` | 30 |
| `backend-crash` | 1 |
| `not-answerable/*`, `tool`, `unknown` | 0 |

`not-answerable` is 0 because the 42 files are all real Mojo; the classes the
tool reports as facts about the target (`host-import` and friends) have not
started appearing yet in this sub-scope, which is itself a reason not to read
these counts as the slice's.

## 2. Ranked terminal causes, over the 42 classified files

Terminal reason, not class: `codegen/dependency` is a chained refusal, so the
only useful number is the reason at the bottom of the chain.

| files | cause | example | status |
|---|---|---|---|
| 21 | **`binary_heap.mojo` exports nothing as a dylib** | `std/builtin/{_coroutine,_stubs,const,device_passable,float_literal,int,int_literal,range,sort,string_literal,variadics}.mojo`, all of `std/collections` | open, §4.1 — a true limit, and the slice's largest by a factor of three |
| 7 | **a false value-position method refusal** on `self._inner.write_to(w)` | `std/builtin/builtin_slice.mojo`, reached from `std/builtin/{error,globals,int,rebind,tuple,value}.mojo` | **CLOSED**, §3.2 |
| 3 | an MLIR dialect construct (`__mlir_op` / `__mlir_type`) | `std/builtin/simd_length.mojo` via `std/utils/_select.mojo`; `std/collections/_conditional.mojo` via `std/sys/_assembly.mojo` | open, §4.2 — a true limit |
| 1 | **`AttributeError` — the wrong owner table in `_frame_receivers`** | `std/builtin/reversed.mojo` | **CLOSED**, §3.3 |
| 1 | `binary_heap.mojo` in file: `len(self._data)` on a field with no default | `std/collections/binary_heap.mojo` | open, §4.1 — same module as the row above, one level shallower |
| 1 | a one-field struct's mutator both writes its receiver and returns | `std/builtin/float_literal.mojo` | open, §4.3 — an honest limit with a measured repair in the message |
| 1 | a `...` in a plain function | `std/builtin/len.mojo` | true limit, already in `bugs/FORMAL_known_limits.md` |
| 1 | a user method on a multi-field struct's receiver | `std/builtin/none.mojo` (`writer.write_string()`) | true limit, refused on purpose (§4.3) |
| 1 | a module-level `comptime` bound to an MLIR type template | `std/builtin/type_aliases.mojo` | true limit, refused on purpose |

## 3. What landed

### 3.1 `formal/model.py` — the fall-off-the-end tail was refused as a read before store

`_build_cfg` wired the top-level `run`'s return value to the entry block as a
successor: an edge from the function's FIRST block to its last, a path that runs
nothing in between. `read_before_store` intersects a block's IN over its
predecessors, so the exit's IN became the parameters and the first read after the
last control-flow statement was reported as a read before any store.

**Why no row above is a read-before-store.** Every case in
`test_formal_read_before_store.py` ends in `return`, and a trailing `return`
makes the top-level `run` return `[]`, so the edge was never built for any of
them — 56 rows passed with the bug live. The shape needs a body that **falls off
the end**, and that is ordinary Mojo: `std/collections/binary_heap.mojo`'s
`_heapify_up` declares `var element`, loops, and reads `element` in its trailing
`unsafe_write`. Five rows added (three that the removal makes legal, two controls
that keep the answer where it belongs); measured 61/61, and 58/61 with the edge
back, the three failures being exactly the false refusals.

**What it did NOT do to this slice.** `binary_heap.mojo` still refuses, one
refusal further on (`len(self._data)`, §4.1). This was a wrong refusal, not the
one holding the slice up, and it is recorded that way rather than as a fix that
moved a file.

### 3.2 `formal/build.py` — a receiver that is a FIELD now dispatches by its declared type

`_method_call_target` required the callee's receiver to be a plain `IdentExpr`, so
`self._inner.write_to(writer)` in `builtin_slice.mojo`'s `StridedSlice_write_to`
was not recognised as a method call at all. `_rewrite_self_fields` then collapsed
`self._inner` to `self` — correctly, `StridedSlice` having ONE field — and left
`self.write_to(writer)`, a name two structs of that file declare. The refusal
that followed was entirely false:

    StridedSlice_write_to: self.write_to is not a field of StridedSlice —
    write_to is one of its METHODS …

The source says `Slice.write_to`, on a field declared `var _inner: Slice`.
`_method_call_target` has a second arm now, keyed on the field's **declared type**,
with two guards — the field must be a placed nested frame
(`model.struct_nested_frame_fields`), and the declared type must not have a
derived struct of this unit declaring the same method.

**Measured, after:** `std/builtin/builtin_slice.mojo` on `--arch x86_64` no longer
produces that sentence. It refuses with the next real one,
`StridedSlice___init__ returns a frame address, so it cannot be compiled into a
dylib` (§4.4), and the seven `codegen/dependency` files above it now reach their
own verdict instead of this one. Tests:
`test_formal_specialized_method_call.py` 14/14, three new differential cases on
both architectures against CPython, all three failing with the fix reverted.

**The first guard is load-bearing and was found by a regression, not by
reasoning.** Without it, `test_formal_run.py`'s
`byref_refuse_write_over_a_nested_frame` turned from a refusal into a build —
`P.go` assigns `self.in1`, so the slot holds a frame belonging to whichever
function ran the assignment, and `Inner_total` would read another activation's
storage.

### 3.3 `formal/build.py` — `_frame_receivers` was handed the wrong owner table, and crashed on it

Its parameter is documented `{function name: struct}` and both uses ask it by
FUNCTION name. The call site passed `owners` — `{BARE method name: struct NAME}`,
the name-based call-dispatch table, over this module **and every imported
struct**. A free function whose name is also any method's was handed a struct
NAME as if it were a struct:

    std/builtin/reversed.mojo: AttributeError: 'str' object has no attribute 'name'

`SIMD.reversed` is real (`std/simd.mojo:3475`) and that module declares a free
`reversed`. A `backend-crash` is the one class the sweep never replays from cache
and the only one that means "no verdict about the source was reached at all", so
this was the most expensive single line in the run. `refuse_none_comparisons` and
`_rewrite_class_constants` are called with `method_owners` at their **other**
site for exactly this reason; this was the one call site that disagreed.

Measured after: `reversed.mojo` is a `codegen/dependency` naming the returned-
frame limit.

### 3.4 reviewed, not changed: `x^` as an ownership-transfer marker (`d24bf8cf`)

The previous instance's commit, reviewed and kept. arm64's `_emit_expr` has asked
`M.is_ownership_transfer` since wave 5; x86-64's `_emit_unary` did not, so `^`
was refused there and lowered on arm64. It reaches the same `model.py` predicate
through the arm64 branch, so the architectures cannot drift apart on it again,
and it sits after the `string_unary_refusal` gate that keeps `s^` refused on
**both**. Nine cases in `test_formal_x86_64_parity.py`, each checked on both
backends against CPython. Verified here: 9/9.

## 4. What is left, with the next step for each

### 4.1 `binary_heap.mojo` — 21 of 42 files, and the slice's real ceiling

Two refusals, one module, and they are independent:

* **As a dependency** (21 files): `formal dylib has no public functions:
  binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares only the
  generic struct template(s) BinaryHeap, and a parametric type has no single
  boundary layout either.` This is `formal/build.py`'s documented refusal and it
  is CORRECT — `doc/ABI.md` says each instantiation of a generic is a boundary
  symbol and the base name is not, and publishing one address for a template
  would bind the wrong body at some call sites. The message's own docstring
  ("the honest answer is the refusal until the instantiation keying lands") is
  right and nothing here should weaken it.

  **The next step is upstream of it, and it is about the import graph rather than
  about the gate.** `std/collections/__init__.mojo` re-exports from eleven
  sibling modules, so `from std.collections import check_bounds` — which
  `std/collections/list.mojo:23` and `std/collections/string/string_span.mojo:18`
  both write — drags in `binary_heap.mojo`'s dylib for a name no importer in the
  slice ever uses. `formal/imports.py` already resolves `from P import a, b` to
  the module that DEFINES `a` and `b`; the fix is to build the dylib set from
  that per-name answer rather than from every module `P/__init__.mojo` names.
  That is a change in `formal/imports.py`, it is bigger than one sitting, and it
  is the single change that would move the most files in this slice. It is NOT
  filed as a bug doc because it is a feature project, not a defect.

* **In the file** (`binary_heap.mojo` itself): `len(self._data)` where
  `var _data: List[Self.T]` has no class-level default. `S()` does not run
  `__init__` on this path, so a fresh instance's slot is a word of zeros and the
  count would be read from address 0 — measured, on BOTH architectures, as a build
  that ran and died with SIGSEGV. The next step is to make a fresh instance's
  container field a real empty blob at the point `S()` is emitted, which is a
  value-model change both backends and the Lean proof share; the repair in the
  message ("build the list in the caller and assign the field after `S()`") is
  the source-level workaround and is honest.

### 4.2 MLIR dialect constructs — 3 files, a true limit

`__mlir_op` / `__mlir_attr` / `__mlir_type` name an MLIR dialect entity, and this
path lowers a Mojo program to a Mach-O image whose only value is a 64-bit word.
Refused by name, on purpose, after it produced 10 on arm64 and 0 on x86-64 for
one source. `std/sys/_assembly.mojo` reaches it through `inlined_assembly` and
`std/builtin/type_aliases.mojo` through `__mlir_type.\`!kgen.never\``. No next
step: there is no representation to add without changing what the backend is.

### 4.3 Refusals that are RIGHT, recorded so they are not re-derived

`std/builtin/float_literal.mojo`'s `FloatLiteral.__init__` both changes its
receiver and returns a value (a formal value is one word, so there is no second
one to return anything else in — the message names `model.receiver_writeback_name`
and the repair). `std/builtin/none.mojo`'s `writer.write_string()` is a method on
a multi-field struct, whose receiver is a frame address and not a file
descriptor, so lowering it as the `write` that IS honest for `open(...)` would
pass a frame address as `fd(2)`. `std/builtin/len.mojo`'s `...` in a plain
function. All three are documented limits with the next step already named in
their own messages; re-deriving them is the cost this paragraph exists to stop.

### 4.4 The next cause behind §3.2, newly exposed

`builtin_slice.mojo` now refuses with `StridedSlice___init__ returns a frame
address, so it cannot be compiled into a dylib` — the returned-frame convention
needs the CALLER to reserve the block, and an importer of a library binds a
symbol without learning the width. Reproduced in miniature (`.tmp/initcase.mojo`
in the branch's scratch, not committed): the same shape refuses even in an
executable image, one step earlier, with `constructing StridedSlice with the call
to 'Slice' as field '_inner' is refused on this path`. So this is a chain, not a
single refusal, and the next step is to decide whether a ONE-FIELD struct's
`__init__` needs the returned-frame convention at all — its receiver IS its
field, so the word it hands back is the word it was given, and that is a smaller
question than the cross-dylib one it currently answers.

## 5. A doc that needs updating and that this branch does not touch

`bugs/FORMAL_known_limits.md` §6.5 ("Arch drift, still open, still two files")
is now wrong in both halves. `std/builtin/swap.mojo` — the "`^` is refused on
x86-64" row — is fixed by `d24bf8cf`, and the `std/math/polynomial.mojo` row it
also lists was closed on 2026-09-27 and is recorded as closed in the same
document's own §3 table. That file is claimed by `formal3-5`
(`bug:FORMAL_known_limits`), so this branch does not edit it; the integrator
should fold both corrections in when that claim is free.