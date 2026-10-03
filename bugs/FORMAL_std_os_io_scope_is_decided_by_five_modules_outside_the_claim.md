# the `std/{os,io,pathlib,sys,time,hashlib,base64,ffi}` scope is 46 files, 3 of which build, and every link of the chain that blocks the other 43 is in someone else's claim

**Area:** FORMAL (new-modular stdlib breadth). Found 2026-10-03 on
`work/formal14-std-os-io`, claim `sweep14:std-os-io`. **Not a bug in this scope's
files** — that is the finding, and it is the answer to the question the sweep
cannot answer. What is left open is the chain, link by link, with an owner per
link.

**Status (2026-10-03): the one IN-FILE refusal in this scope is FIXED.**
`std/sys/debug.mojo` moved `codegen` → `pass` on both architectures and the
scope's `codegen` class is 0; the scope's codegen coverage went **4.3 % → 6.5 %**
(2/46 → 3/46). That is the whole of what this claim could move, and §3 says why.

---

## 1. The sweep, both architectures, and what it does not say

`../new-modular/Mojo/stdlib/std/{os,io,pathlib,sys,time,hashlib,base64,ffi}` is
**46 `.mojo` files**. Swept whole, `-j 2 -t 120`, both architectures, on
`work/formal14-std-os-io` at `cabcc936` (after the fix in §2):

```
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 120          <the 46 files>
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 120 --arch x86_64 <the 46 files>
```

| class | arm64 | x86-64 |
|---|---|---|
| **pass** | **3** | **3** |
| built-with-admitted-contracts | 0 | 0 |
| **codegen** (a refusal IN the file) | **0** | **0** |
| codegen/dependency | 43 | 43 |
| **codegen coverage** | **3/46 = 6.5 %** | **3/46 = 6.5 %** |
| peak RSS | 0.3 GB over ≤6 procs | 0.3 GB over ≤6 procs |

The three that build, read off the same builds: **`std/os/pathlike.mojo`,
`std/sys/_io.mojo`, `std/sys/debug.mojo`** — and the third of those is the one
this branch fixed. The two architectures agree on every file, which is the same
result `…_b7.md` §2.5 reports for the whole 668-file scope: this backend's
remaining coverage is not a per-architecture question.

**The sweep reports ONE link of a chain**, the terminal refusal its build walk
reaches, so these 43 lines are 43 answers to "what is the FIRST thing this file
cannot build" and not 43 answers to "what is wrong with this file". §2 is the
chain; §3 is why the chain cannot be walked by the worker holding this claim.

## 2. The chain, measured link by link

`tools/formal_sweep.py` has no `--depth` flag, so the chain was measured with
`tools/formal_chain_probe.py`: it copies the stdlib to `.tmp/chain-probe`, asks
every path for its terminal refusal, replaces the refusing module in the COPY
with a stub plus a dropped import line, and asks again. The original
`../new-modular` tree is only ever read, and the tool's own docstring states the
limit that decides how far its numbers are worth reading (neutering a module
also removes the names its users call).

| link | refusing module | files | what it refuses | owner |
|---|---|---|---|---|
| **1** | `std/collections/binary_heap.mojo` | **40** | `BinaryHeap.pop() both changes its receiver and returns a value` — a PREP-time refusal (`mutating_receiver_return_refusal`), so it preempts every emitter refusal in that file | `sweep14:std-collections`; `FORMAL_binary_heap_mojo_after_the_len_value.md` §3 row 0 already names this as "the cheapest real step … a decision about the ABI" |
| **2** | `std/algorithm/backend/tile.mojo` | **40** | `workgroup_function[…](…) calls a name this unit does not compile` — a bracketed specialization | `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value` (`formal13-6`) |
| **3** | `std/builtin/builtin_slice.mojo` | **3** | two different refusals in the same function: `self is assigned other in StridedSlice___init__()` (receiver rebind), and `StridedSlice___init__ returns a frame address, so it cannot be compiled into a dylib` | `FORMAL_one_field_receiver_rebound_propagates` (`formal13-5`) and `FORMAL_builtin_slice_optional_field_is_a_frame_holder` (`formal13-3`) |
| 4+ | `std/format/format_int.mojo`, `std/reflection/function.mojo`, `std/reflection/reflect.mojo`, `std/builtin/{rebind,constrained,movable,copyable,deinitable,globals}.mojo` | 1–22 each | a bracketed `b[…](…)`, `__mlir_attr` comptime bindings, a re-export of `downcast` nothing publishes, `pop.global_constant` | `sweep14:std-builtin-math`, `formal13-6`, `FORMAL_stdlib_tile_row_…` |

**Links 4 and beyond are a lower bound on the depth, not a measurement of it**,
and the reason is a real limit of the method rather than a caveat to wave at:
neutering a module removes the names its USERS call, so from link 4 the probe is
measuring what the neutered module's users need rather than the next link in the
chain. Links 1–3 were each measured with the whole closure intact and are the
part worth acting on; `round 2` of the output is where the two readings part
company, and it says so in its own counts (22 files move to a different module
the moment `tile.mojo` is stubbed, which is a probe artefact and not a chain).

**Zero links are in this scope's own packages.** Not one of the 46 files' own
refusals survives once the shared modules are out of the way, which is the same
shape `…_b7.md` §3.1 found for `binary_heap.mojo` (164 of 165 files were
closure) and it is worth the same reading: **the row is closure, and the work is
one file per link.**

## 3. Why this claim cannot walk its own chain, which is the part to act on

**Link 1's repair is a STDLIB edit, and a repository worktree cannot make one.**
`mutating_receiver_return_refusal` names its two repairs — split the method into
a mutator and a reader, or make it read the receiver instead of writing it — and
both are edits to `../new-modular/Mojo/stdlib/std/collections/binary_heap.mojo`,
which is outside every worker worktree and outside this repository. So for the
one link that gates 40 of 46 files in this scope:

* the source repair is not deliverable from here, and
* the backend repair — a one-field mutator gets a second return word, or its
  receiver is passed by reference — is `FORMAL_wide_receiver_by_reference`
  (`formal13-7`) and needs a `lib/work.lean` step for the extra register, which
  is exactly the kind of change a light worker must not make unverified.

**And closing link 1 does not move the row.** `FORMAL_binary_heap_mojo_after_the_len_value.md` §2 measured it: past every codegen refusal in that file the module-dylib build fails at the **export gate** (`binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares only the generic struct template(s) BinaryHeap`), which costs a monomorphizer. That is 40 files waiting on a project, not on a patch, and link 2 (`tile.mojo`) is what 40 files see the moment link 1 is out of the way.

**The three files behind link 3 are the cheapest thing here and they are still
not free.** `std/ffi/unsafe_union.mojo`, `std/io/file.mojo` and
`std/pathlib/__init__.mojo` reach `builtin_slice.mojo` without `binary_heap`
at all, so their chain is one link shorter — and it ends in
`std/builtin/globals.mojo`'s `pop.global_constant` ("its value is the
linker-resolved content of a symbol, and this path compiles each module to its
own image"). Whoever takes link 3 gets three files; that is the whole prize and
it is worth stating so nobody re-derives it.

## 4. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
S=../new-modular/Mojo/stdlib/std

# the scope sweep, both arms (2 min each; the CAS makes a re-run ~free)
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 120 $S/{os,io,pathlib,sys,time,hashlib,base64,ffi}
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 120 --arch x86_64 $S/{os,io,pathlib,sys,time,hashlib,base64,ffi}

# one link at a time, on a COPY of the stdlib
python3 tools/memslot.py --gb 8 --label chain -- \
  python3 tools/formal_chain_probe.py 9 arm64 $S/{os,io,pathlib,sys,time,hashlib,base64,ffi}
```

**Links 1–3 are the ones a reader should trust**, and they are the first three
rounds of that last command:

```
round 0:  3 built, 2 refusing modules    40 binary_heap.mojo   3 builtin_slice.mojo
round 1:  3 built, 2 refusing modules    40 tile.mojo          3 builtin_slice.mojo
round 2:  3 built, 2 refusing modules    22 format_int.mojo    21 tile.mojo
```

Round 2 is where the reading changes: stubbing `tile.mojo` moved 18 files from
it onto `format_int.mojo`, which is the probe's own artefact (the stub removed
names `tile.mojo`'s users call) rather than a link in the chain, and it is the
round the doc's §2 table stops at.

`…_b7.md` §1.1's caveat applies and is worth repeating: **a `-t` is a CPU budget
divided by the load.** These 46 files are refusals, so they are cheap — ~2 s of
build each — and `-j 2 -t 120` answered the whole scope in 2m08s per arm on an
idle box. `…_b6.md` projected half a day for the same shape of work at load 90.

## 5. What landed on this claim, and what is left

**Landed** (`cabcc936`): a dialect EFFECT used as a statement of its own lowers,
so `std/sys/debug.mojo` — `__mlir_op.`llvm.intr.debugtrap`()()` and nothing
else — builds on both architectures, and the scope's `codegen` class is 0. The
same change reaches `std/sys/info.mojo:702`, `std/os/os.mojo:242` and
`std/_plugin/selector.mojo:74` as their NEXT refusal rather than this one; none
of those three files moves, because each is behind link 1.

**Measured and available, deliberately not done here:** `std/sys/compile.mojo:34`
is `__mlir_op.`kgen.codegen.reachable`[…]()` as a statement, and it is refused as
an effect. It could honestly lower to NOTHING — the operation asserts a block is
reachable for code placement, and this path places every instruction it emits, so
the assertion holds by construction — which is a second table beside
`MLIR_EFFECT_DIVERGENCE_OPS` with a different meaning (satisfied, not diverged
through) and its own `EMITTED`-style check that the image is unchanged against a
control. **It moves no file**: `std/sys/compile.mojo` is behind link 1. Recorded
because it is cheap and the next worker on this scope will otherwise re-derive it.

**Left, with the owner for each:** links 1–4 of §2. None of them is in this
claim, and §3 says why each one is not a patch.
