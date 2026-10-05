# the `std/{os,io,pathlib,sys,time,hashlib,base64,ffi}` scope is 46 files, 3 of which build, and every link of the chain that blocks the other 43 is in someone else's claim

**Area:** FORMAL (new-modular stdlib breadth). Found 2026-10-03 on
`work/formal14-std-os-io`, claim `sweep14:std-os-io`. **Not a bug in this scope's
files** — that is the finding, and it is the answer to the question the sweep
cannot answer. What is left open is the chain, link by link, with an owner per
link.

**Status 2026-10-05 (`work/formal27-5`): link 1′ is DONE, and the document's own
prediction is what happened — the module it named moved ON to row 2 rather than
to `pass`.** `List.clear` is in `formal/model.py::BUILTIN_VALUE_METHODS` with a
positive kind guard (`is_list_kind` of the receiver's kind, not the absence of a
refusal), and it is measurably RIGHT rather than merely present: a program that
does `a = [1,2,3]; a.clear(); a.append(9); print(a[0])` prints **9** on arm64
and on x86-64, and CPython prints 9 — which is only true if the clear zeroed the
count word, since `a[0]` would otherwise still be 1. `std/collections/
binary_heap.mojo` built alone is now refused at **`self.unsafe_ptr()`** on both
architectures, and its own message lists the method it used to lack: *"this
backend lowers only append, **clear**, close, write (on a file descriptor) and
the string methods"*. That is this document's §2 row 2 and §5's "row 2 is
`unsafe_ptr`, a pointer model", so the row this document called "the cheapest
thing in the whole chain" is closed and the chain is one link further along than
when it was written. The fix was `formal18-2`'s and is not this claim's; what
was missing was the record that it landed, and the message this document quotes
verbatim for row 1′ is two methods out of date.

**One measurement worth keeping with it, because it is the shape of every probe
against this value model**: a list subscript one past the count is a **silent
`exit(1)` with nothing printed**. `printf("%d %d", a[0], a[1])` after a
clear-and-append answers nothing and exits 1; the same program with only `a[0]`
answers 9. That is the same bargain `FORMAL_os_environ_is_a_view_and_the_sweep_
row_behind_it.md` records for a store past a list's end, and it is why the
differential above is written with the subscript the program can answer.

**Status (2026-10-04, `work/formal21-6`: nothing left to do here, and the reason
is worth one line.** Round 2 of this scope
(`FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md`, `sweep20:std-os-io-2`)
re-measured it on a DIFFERENT package set — round 2 drops `sys` and `time` and
adds `python` and `_gpu` — and found the whole chain gone: **zero** of the 43
refusals name `binary_heap.mojo`, `tile.mojo` or `builtin_slice.mojo`, and
every one of them is one of TWO features (`formal19-1`'s bare-call inference and
`formal16-2`'s constants-only module). **§2's table below is therefore a
HISTORICAL reading of a chain that no longer exists**, kept because it is what
told the next worker where to look; the owners it names are still the owners, and
the one link of it that could have been this claim's to move (`List.clear`,
link 1′) is `formal18-2`'s and never was this scope's. The one open item round 2
left for the INSTRUMENT — §6 item 1 there, "cannot rank this scope's causes" — is
closed as of this branch (`tools/formal_sweep.py::refusing_module`, with `uses:`
measured for the row that read NOT MEASURED on 21 of 22 groups).

**Status (2026-10-03, second pass — the chain has MOVED and two of its three
links now point at closed or mis-owned work).** Re-measured on this tree, both
architectures, the same 46 files, one `fire.py build --formal --no-prove` each
(§4 has the loop): **still 3 build, still 0 in-file refusals, still 43
dependency refusals — and the chain's links are different ones.**

| link | was (2026-10-03, first pass) | is (now) |
|---|---|---|
| 1, 40 files | `binary_heap.mojo`: `BinaryHeap.pop() both changes its receiver and returns a value` | **the EXPORT GATE**: `formal dylib has no public functions: binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares only the generic struct template(s) BinaryHeap` — the mutator-ABI refusal is GONE (`work/formal15-mutator-return-abi`) and §3 of the original doc predicted this exact wall |
| 2 | `tile.mojo`: the bracketed `workgroup_function[…](…)` specialization | unchanged, still the refusal on both architectures — and now `project18:tile-specialization` is working it |
| 3, 3 files | `builtin_slice.mojo`: two refusals (a receiver rebind, and a frame-holder return) | **`builtin_slice.mojo: self.step.or_else() is an Optional unwrap`**, which is neither of them, and is owned by `FORMAL_stdlib_optional_needs_a_representation.md` (`formal16-7`) — not by the two docs this table used to name |

**And there is a fourth refusal inside link 1's module, which this table did not
have:** `binary_heap.mojo` built on its own now reports row **1** of its own
doc's §3 table —

```
build: self.clear() is a method call on a value, and this backend lowers only
append, close, write (on a file descriptor) and the string methods count,
endswith, find, lstrip, startswith …
```

— which is `List.clear`, "count = 0, one store", missing from the emitter's
method table. It is the cheapest thing in the whole chain and it moves NOTHING
here (row 2 is `unsafe_ptr`, a pointer model), and it is not this claim's:
`bugs/FORMAL_binary_heap_mojo_after_the_len_value.md` is `formal18-2`'s and its
§3 already names it as row 1. Recorded here so the next reader of this chain
knows the link has a next row and who owns it.

The original status note stands: **the one IN-FILE refusal in this scope is
FIXED.** `std/sys/debug.mojo` moved `codegen` → `pass` on both architectures and
the scope's `codegen` class is 0; the scope's codegen coverage went **4.3 % →
6.5 %** (2/46 → 3/46). §3 says why that is the whole of what this claim could
move.

---

## 1. The census, both architectures, and what it does not say

`../new-modular/Mojo/stdlib/std/{os,io,pathlib,sys,time,hashlib,base64,ffi}` is
**46 `.mojo` files**. At the first pass they were swept whole (`tools/formal_sweep.py
-j 2 -t 120`, both arms, on `work/formal14-std-os-io` at `cabcc936`); at this pass
they were each built once with `--no-prove` (§4), which reads the same three
classes off the refusal and says which module fired:

| class | arm64 | x86-64 |
|---|---|---|
| **pass** | **3** | **3** |
| built-with-admitted-contracts | 0 | 0 |
| **codegen** (a refusal IN the file) | **0** | **0** |
| codegen/dependency | 43 | 43 |
| **codegen coverage** | **3/46 = 6.5 %** | **3/46 = 6.5 %** |
| peak RSS | 0.1 GB, one build at a time | 0.1 GB, one build at a time |

**The counts are the first pass's and they still hold**, which is the one thing
this pass measured about them: 3 build, 0 refuse in their own file, 43 refuse on
a module they import, and the 43 split 40 / 3 between two refusing modules that
are not in this scope. The three that build are the same three: **`std/os/pathlike.mojo`,
`std/sys/_io.mojo`, `std/sys/debug.mojo`** — and the third of those is the one
the first pass fixed. **Both architectures agree on every file, verified by
diffing the two runs' per-file verdicts rather than by counting them twice**:

```
$ diff <(cut -d' ' -f1,2 .tmp/scope/out46.txt | sort) \
       <(cut -d' ' -f1,2 .tmp/scope/out46_x86.txt | sort) && echo SAME
SAME
```

and the three files behind link 3 are the same three on both arms
(`std/io/file.mojo`, `std/pathlib/__init__.mojo`, `std/ffi/unsafe_union.mojo`).
That is the same result `…_b7.md` §2.5 reports for the whole 668-file scope: this
backend's remaining coverage is not a per-architecture question.

**A sweep row is a FAMILY LABEL and this doc needs a module name**, which is why
the second pass stopped using it here: `binary_heap.mojo` has two independent
walls (§2's row 1 and the binary-heap doc's §2), and a family label reads the
same for both. The refusal text names the wall; the label does not.

**The sweep reports ONE link of a chain**, the terminal refusal its build walk
reaches, so those 43 lines are 43 answers to "what is the FIRST thing this file
cannot build" and not 43 answers to "what is wrong with this file". §2 is the
chain; §3 is why the chain cannot be walked by the worker holding this claim.

## 2. The chain, measured link by link

**RE-MEASURED 2026-10-03 (second pass).** The numbers and the refusals below are
this pass's; the first pass's are kept in the Status table at the top so a reader
can see what moved. `tools/formal_chain_probe.py` is still not needed for links
1–3: every one of them is reachable by building the scope's own files and reading
the refusal, because none of them is behind another (§4 has the loop).

| link | refusing module | files | what it refuses | owner |
|---|---|---|---|---|
| **1** | `std/collections/binary_heap.mojo` | **40** | **the export gate**, not a codegen refusal: `formal dylib has no public functions: binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares only the generic struct template(s) BinaryHeap, and the template itself is not a boundary symbol. Its INSTANTIATIONS are — formal/monomorph.py compiles each one an importer asks for … so this message means nothing asked for one` | `FORMAL_binary_heap_mojo_after_the_len_value.md` §2 (`formal18-2`), and behind it §2b's measurement: lifting this wall moves 8 of 10 sampled files onto link 2 and 2 onto link 3 |
| 1′ | `std/collections/binary_heap.mojo`, built alone | (0 of this scope — it is what link 1 would hit next) | **CLOSED 2026-10-05, and what it moved to is this table's row 2**: `self.unsafe_ptr() is a method call on a value … this backend lowers only append, **clear**, close, write …` (both architectures, byte-identical). `List.clear` was the missing lowering, it is in `formal/model.py::BUILTIN_VALUE_METHODS` behind an `is_list_kind` guard, and it is right rather than present (Status at the head) | was `formal18-2`'s §3 row 1; **done** |
| **2** | `std/algorithm/backend/tile.mojo` | 0 today (behind link 1) | `workgroup_function[…](…) calls a name this unit does not compile, so the brackets cannot be bound` — re-measured on BOTH architectures, unchanged | `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value` (`formal16-7`) and `project18:tile-specialization` |
| **3** | `std/builtin/builtin_slice.mojo` | **3** | `self.step.or_else() is an Optional unwrap: it answers by knowing which of two words was the empty one, and on this path there is no way to know` | `FORMAL_stdlib_optional_needs_a_representation` (`formal16-7`) — which names this exact refusal as `builtin_slice.mojo`'s terminal cause. The two docs the first pass named here (the one-field receiver rebinding rule, `formal/build.py`'s `_collect_one_field_receiver_rebinds`, and `FORMAL_builtin_slice_optional_field_is_a_frame_holder`) are not what fires |

The three files behind link 3 are the same three the first pass found —
`std/ffi/unsafe_union.mojo`, `std/io/file.mojo` and `std/pathlib/__init__.mojo`
— and they reach `builtin_slice.mojo` without `binary_heap` at all, so their
chain is one link shorter and it is the shortest one here. **Whoever takes link
3 gets three files**, which is the whole prize, and the work behind it is a
value-model decision for `Optional` shared by both backends and the Lean proof.

**Why the sweep reports ONE link and this table has three** is unchanged and is
worth restating, because it is the reason the two disagree: the sweep reports the
terminal refusal its build walk REACHES, so its 43 lines are 43 answers to "what
is the FIRST thing this file cannot build". Link 2 is not in the sweep's output
at all because link 1 fires first — not because link 2 is gone.

**Zero links are in this scope's own packages.** Not one of the 46 files' own
refusals survives once the shared modules are out of the way, which is the same
shape `…_b7.md` §3.1 found for `binary_heap.mojo` (164 of 165 files were
closure) and it is worth the same reading: **the row is closure, and the work is
one file per link.**

## 3. Why this claim cannot walk its own chain, which is the part to act on

**What was true at the first pass and is now HISTORY: link 1's codegen half is
fixed.** `mutating_receiver_return_refusal` named two repairs — split the method
into a mutator and a reader, or make it read the receiver instead of writing it
— and this paragraph argued that both are edits to
`../new-modular/Mojo/stdlib/std/collections/binary_heap.mojo`, outside every
worker worktree, and that the backend repair needs a `lib/work.lean` step. **The
second half of that is what landed** (`work/formal15-mutator-return-abi`, commit
`11558f0d`, recorded in the binary-heap doc's §0): the receiver is handed over by
reference, so no extra register was needed and the refusal is gone from the file
entirely. The first half was never the wall.

**What link 1 IS now is the export gate, and it is not a patch either.** §2's row
1 is the measurement: `binary_heap.mojo` declares only the generic struct template
`BinaryHeap`, a template is not a boundary symbol under `doc/ABI.md`, and nothing
asks for an instantiation. The binary-heap doc's §2b measured what lifting that
wall does — 8 of 10 sampled files move onto link 2 and 2 onto link 3 — and named
the decision it needs ("does the importing module bind any CONCRETE name of the
dependency?"), together with the pinned test that decision would reverse. So link
1 is a project with a named decision and a named owner, and **40 files are waiting
on it rather than on a patch.**

**The three files behind link 3 are the cheapest thing here and they are still
not free.** `std/ffi/unsafe_union.mojo`, `std/io/file.mojo` and
`std/pathlib/__init__.mojo` reach `builtin_slice.mojo` without `binary_heap` at
all, so their chain is one link shorter — and it now ends in `Optional`'s missing
representation (`self.step.or_else()`), which is a value-model decision shared by
both backends and the Lean proof, owned by
`FORMAL_stdlib_optional_needs_a_representation`. The first pass said this chain
ended in `std/builtin/globals.mojo`'s `pop.global_constant`; that is behind
link 3 now and was not re-measured, because §2's table stops at links a reader can
act on. Whoever takes link 3 gets three files; that is the whole prize and it is
worth stating so nobody re-derives it.

## 4. Reproducing

**This pass's numbers come from 46 individual builds, not from a sweep** — one
`fire.py build --formal --no-prove` per file, which is what makes the class of
each refusal readable (the refusal names the module) and costs ~4 minutes per
architecture on an idle box:

```sh
export PATH=/opt/homebrew/bin:$PATH
cd "$(git rev-parse --show-toplevel)"
S=$PWD/../new-modular/Mojo/stdlib/std
mkdir -p .tmp/scope
for f in "$S"/{os,io,pathlib,sys,time,hashlib,base64,ffi}/*.mojo \
         "$S"/{os,io,pathlib,sys,time,hashlib,base64,ffi}/*/*.mojo; do
  python3 tools/memslot.py --gb 8 --label scope -- \
    python3 fire.py build --formal --no-prove -o .tmp/scope/x.aout "$f"
done
```

which is what `.tmp/scope/sweep46.sh` does, and `--backend=x86_64` for the second
arm (`out46.txt` and `out46_x86.txt`; 6 min per arm on this box, most of it the
x86-64 arm's first pass at compiling dylibs the CAS did not have). The first pass
used the sweep and the chain probe, and both are still the right tools for a
census (`tools/formal_sweep.py -j 2 -t 120 …`) — the reason for switching is that
a sweep row is a FAMILY LABEL, so it cannot say which of the two
`binary_heap.mojo` walls fired, and this doc's whole content is which wall.

Links 1–3 are also reachable one at a time, with no probe and no copy of the
stdlib:

```sh
python3 tools/memslot.py --gb 8 --label chain -- \
  python3 fire.py build --formal --no-prove -o .tmp/scope/y.aout \
  "$S/collections/binary_heap.mojo"                       # link 1, row 1′
python3 tools/memslot.py --gb 8 --label chain -- \
  python3 fire.py build --formal --no-prove -o .tmp/scope/y.aout \
  "$S/algorithm/backend/tile.mojo"                        # link 2
python3 tools/memslot.py --gb 8 --label chain -- \
  python3 fire.py build --formal --no-prove -o .tmp/scope/y.aout \
  "$S/io/file.mojo"                                       # link 3
```

The first pass's chain probe output, kept because it is the only measurement here
of what is BEHIND links 1–3, and because its limit is the reason this doc's table
stops at three:

```
round 0:  3 built, 2 refusing modules    40 binary_heap.mojo   3 builtin_slice.mojo
round 1:  3 built, 2 refusing modules    40 tile.mojo          3 builtin_slice.mojo
round 2:  3 built, 2 refusing modules    22 format_int.mojo    21 tile.mojo
```

Round 2 is where the reading changes: stubbing `tile.mojo` moved 18 files from
it onto `format_int.mojo`, which is the probe's own artefact (the stub removed
names `tile.mojo`'s users call) rather than a link in the chain, and it is the
round the doc's §2 table stops at. The binary-heap doc's §2b re-measured the same
thing with a lighter probe (skip the library the export gate refuses) and got
8-in-10 on `tile.mojo` — the same answer, from a method that does not neuter
anything.

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

**Measured, and NOT taken: the other statement-position effect in this scope.**
`std/sys/compile.mojo:34` is `__mlir_op.`kgen.codegen.reachable`[… ]()` as a
statement, refused as an effect, and lowering it to nothing looked like the
obvious second entry beside `MLIR_EFFECT_DIVERGENCE_OPS` — "this block is
reachable" is satisfied by construction on a path that places every instruction
it emits. **It is not obvious, and the bracket is why:**

```
sys/compile.mojo:34   __mlir_op.`kgen.codegen.reachable`[
                          cond=(not cond).__mlir_i1__(),
                          message=_get_kgen_string[msg, *extra](),
                          _type=None,
                      ]()
```

`cond` and `message` are values this path COMPUTES, so "emit nothing" is either
an evaluation whose result is dropped — honest, and only available if both
operands lower — or a dropped bracket, which is the defect this backend exists to
prevent (`formal/build.py`'s own comment at the bracketed-callee arm names
`std/sys/_assembly.mojo`'s `_get_kgen_string[asm]()` as a refusal already, at
"nineteen swept files' worth"). And it moves no file: `std/sys/compile.mojo` is
behind link 1. Recorded because the next worker on this scope will otherwise
propose it, and the reason it is not a one-liner is in the source rather than
being obvious.

**Left, with the owner for each** — re-measured, so this is the whole list as of
this pass:

| what | how many of the 46 | owner |
|---|---|---|
| link 1, the export gate on `binary_heap.mojo` | 40 | `FORMAL_binary_heap_mojo_after_the_len_value.md` §2 / §2b (`formal18-2`) |
| link 1′, `List.clear` has no lowering (what link 1's module hits next) | 0 | **DONE** (Status at the head) — and the module moved ON to `self.unsafe_ptr()`, a pointer model, so this link's closure cost this scope nothing and bought the next link |
| link 2, `tile.mojo`'s bracketed specialization | 0 today | `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value` (`formal16-7`), `project18:tile-specialization` |
| link 3, `Optional`'s missing representation in `builtin_slice.mojo` | 3 | `FORMAL_stdlib_optional_needs_a_representation.md` (`formal16-7`) |

**None of the four is in this claim, and §3 says why each one is not a patch.**
The one thing this pass changed is the map: at the first pass two of the three
links named a refusal that no longer fires and an owner that does not hold it,
and a reader following the old table would have gone to fix a wall that had
already been rebuilt into a different one.
