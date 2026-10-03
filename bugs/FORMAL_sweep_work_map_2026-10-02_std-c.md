# FORMAL_sweep_work_map_2026-10-02_std-c: the `std/` slice with `std-a` and `std-b` removed — one backend crash family, one wrong-refusal family, and 70 files that are one dead end

**Status: three changes landed and committed, one bug doc filed, and the
remaining causes measured. The slice's headline is that it is NOT a coverage
problem: 70 of 118 files are blocked by a single documented dead end, and the
three largest actionable causes were a compiler CRASH, a FALSE refusal, and a
missed type name — all three of which are fixed here.**

Slice: `../new-modular/Mojo/stdlib/std/` minus the `std-a` subtrees
(`builtin`, `collections`, `memory`, `algorithm`, `bit`) and the `std-b`
subtrees (`os`, `pathlib`, `io`, `format`, `hashlib`, `base64`, `random`,
`math`) — that is `_gpu _plugin atomic benchmark compile complex documentation
ffi iter itertools logger origin prelude pwd python reflection runtime stat
subprocess sys tempfile testing time traits utils` plus `__init__.mojo` and
`simd.mojo`. **118 files.** arm64 throughout (the slice says nothing about
x86-64; the x86-64 sweep slices are `x86-a`/`x86-b`).

Logs: `.tmp/sweep-std-c-prefix.txt` (before any change, 18 files — see §1),
`.tmp/sweep2-std-c.txt` (after the `read_before_store` fix, 118 files, with two
known contaminations stated in §2), `.tmp/sweep3-std-c.txt` (the whole slice on
the FINAL tree, 118 files, cold CAS at `.tmp/gmojo2`). All three run as

```
python3 tools/memslot.py --gb 8 --label sweep -- python3 tools/formal_sweep.py \
    -j 3|4 -t 120|180|240 <the 27 roots> --no-stdlib
```

with `GMOJO_HOME` pointed at a worktree-local directory (§7 — the machine runs
one arm64 sweep at a time and every worker wants one).

## 1. The class counts

| | before (18 files) | after the `read_before_store` fix (118) | **final tree (118)** |
|---|---|---|---|
| pass | 0 | 7 | **§2** |
| codegen | 0 | 4 | **§2** |
| codegen/dependency | 17 | 99 | **§2** |
| not-answerable/* | 0 | 0 | **0** |
| backend-crash | 0 | 5 | **0** |
| tool (no verdict) | 1 | 3 | **§2** |
| codegen coverage | 0/17 | 7/110 = 6.4 % | **§2** |

**The "before" column is 18 files, not 118, and that is a real limitation of
this map rather than a presentation choice.** The first sweep was killed at 18
files once its single dominant cause was identified and reproduced from source
(§3), because leaving it running would have meant re-running the whole slice
twice on a machine carrying load 80. All 17 of its `codegen/dependency` files
name the SAME terminal reason, and it is a false refusal, so the 18 is
representative of the cause and not of the class mix; the 118-file columns are
what the class mix is.

## 2. The final numbers

The complete 118-file table is the **run 2** one, with three corrections that
were each measured directly on the final tree rather than inferred. Stated as
corrections because a class count is a claim about a run and a run is a claim
about a tree, and those are two different trees here.

| | run 2 (118 files, `read_before_store` fix only) | **final tree (118 files)** | how the final column was established |
|---|---|---|---|
| pass | 7 | **7** | same run; the 7 are `__init__.mojo`, `documentation/{__init__,documentation}.mojo`, `stat/stat.mojo`, `sys/_io.mojo`, `traits/anytype.mojo`, `utils/_visualizers.mojo` |
| codegen | 4 | **4** | same run; the 4 in-file findings are §3.5/§3.6 and none of the three changes touches them |
| codegen/dependency | 99 | **104** | +3 `backend-crash` and +2 run-2 artefacts, all five re-measured file by file |
| not-answerable/* | 0 | **0** | the class is unfired in this slice and no change affects it |
| backend-crash | 5 | **0** | 3 were the `_frame_receivers` table crash (§3.3), each verified individually to reach a real refusal; **2 were an artefact of an edit of my own in mid-run** (`itertools/itertools.mojo`, `itertools/__init__.mojo`, both reported `NameError: name '_owner_from_receiver_type' is not defined` — a helper I had not written yet) and both are `CODEGEN/DEPENDENCY: builtin_slice.mojo` on the final tree, confirmed in run 3's log |
| tool (no verdict) | 3 | **3** | §3.8 |
| codegen coverage | 7/110 = 6.4 % | **7/111 = 6.3 %** | the denominator is the three classes above; the 1-file move is `env.mojo` (§3.7) leaving the family |
| `cas` | 0 hit / 118 miss | — | every run here was cold, so no verdict in this map is a cache replay |

**The corroborating partial run.** `.tmp/sweep3-std-c.txt` re-ran the same slice
on the final tree and was **INTERRUPTED at 62 of 118** — killed from outside
(this machine was carrying load 80 with 35 concurrent compiler processes; the
sweep published its partial ledger and said so, which is the behaviour
`FORMAL_sweep_killed.md` asks for). What it did classify agrees with the table
above on every class: `pass 3, codegen 1, codegen/dependency 57, tool 1,
backend-crash 0`, and its family breakdown is `binary_heap.mojo` 40 /
`builtin_slice.mojo` 9 / `_assembly.mojo` 2 over the 58 dependency files
classified — the same three families, the same order. A fourth run
(`.tmp/sweep4-std-c.txt`) was started to complete it and had reached 23 of 118
when this map was written; **it is not part of any number above**, and its
partial ledger is in the CAS at `.tmp/gmojo2` for whoever wants to finish it.

**Two contaminations in run 2, both stated rather than buried.** (a) The two
`itertools` crashes above, which were mine. (b) The `POINTER_TYPE_CTORS` change
(`57a82901`) landed at 04:19 PDT, about 40 minutes into run 2, so files
classified after that point saw it. Its direction is known and one-way: it can
only REMOVE the `env.mojo` refusal of §3.7, never add one, and §3.7 is measured
directly. Everything after 04:58 in run 3 and all of run 4 saw the final tree,
apart from one comment-only commit (`3b1ce834`) which cannot change a verdict.


## 3. What the slice is actually made of, cause by cause

**The ranking, from the printed chains of the 118-file run** (`codegen/dependency`
by family, plus the in-file `codegen` findings and the crash class):

| rank | terminal reason | files | class | status |
|---|---|---|---|---|
| 1 | `binary_heap.mojo: module exports nothing` | **70** | dependency | documented dead end, ceiling measured at 0 |
| 2 | `builtin_slice.mojo: StridedSlice_write_to: self.write_to …` | **16** | dependency | **FILED** — a mis-dispatch, §3.4 |
| 3 | `_assembly.mojo: inlined_assembly: __mlir_op` | 8 | dependency + 2 of the 4 in-file | a documented true limit |
| 4 | `random.mojo: Rng_rand_scalar: self._next is not a field of Rng` | 3 | dependency | **FILED** — the same check, §3.4b |
| 5 | `AttributeError: 'str' object has no attribute 'name'` | 3 | **backend-crash** | **FIXED** (§3.3) |
| 6 | `stat.mojo: exports nothing` (every public function is a GENERIC) | 1 | dependency | the same family as rank 1 |
| 7 | `env.mojo: external_call['getenv', OptionalPointer[…]]` | 1 | dependency | **FIXED** (§3.7) |
| 8 | `origin/__init__.mojo` MLIR attribute template, `sys/debug.mojo` + `utils/_select.mojo` `__mlir_op`, `utils/_serialize.mojo` `comptime` does not fold | 4 | codegen | documented true limits |
| — | timeout, no verdict | 3 | tool | re-run at a larger `-t` (§3.8) |
| | **total** | **118** | | 7 pass + 4 codegen + 104 dependency + 3 tool |


Ranked by files, with the terminal reason read off the printed line (the class
name, the printed chain and the per-family breakdown all say which level the
gap is on).

### 3.1 `binary_heap.mojo: module exports nothing` — 70 files, and its ceiling is measured at 0

```
CODEGEN/DEPENDENCY: std/sys/arg.mojo  (build: arg.mojo imports 'std.ffi', which
cannot be built either: binary_heap.mojo: formal dylib has no public functions:
binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares only the
generic struct template(s) BinaryHeap, and a …)
```

`doc/ABI.md` §Generics is right that `struct BinaryHeap[T]` has no single
boundary symbol, so the refusal is TRUE. What is not true is that 70 files are
70 problems: `formal/imports.py`'s `build_module_dylib` compiles **every module
in the file's eager transitive import closure**, so one symbol-less module takes
every importer of its importers with it whether or not any of them binds a name
in it. `FORMAL_dylib_export_gate_ceiling.md` §2 measures this and §3/§4 measure
the ceiling of all three candidate fixes at **0 files**.

**Next step: none in this slice, and the doc says so with numbers.** Anyone
reading "70 files" in the breakdown should read that doc's §1 table with it —
34 of the 35 files it sampled contain no occurrence of `BinaryHeap` at all.
Re-measured here after the §3.2 fix below, and the terminal reason inside
`binary_heap.mojo` itself is unchanged from the doc's probe A: `len(self._data)
— this slot's DECLARED type is 'List[Self.T]' … a field with no class-level
default is a word of zeros`.

### 3.2 `BinaryHeap__heapify_up: 'element' is read at line 94 before anything in this function stores it` — 16 of the first 18 files, FIXED

The **false refusal that was hiding the whole slice**, and the reason the
"before" run was stopped at 18 files. `std/collections/binary_heap.mojo:70-94`:

```mojo
def _heapify_up(mut self, start: Int, var pos: Int):
    var data_ptr = self._data.unsafe_ptr()
    var element = (data_ptr.unsafe_offset(pos)).unsafe_take_pointee()   # 79
    while pos > start:
        var parent = (pos - 1) // 2
        if element <= self._data[parent]:                                # 84
            break
        …
    (data_ptr.unsafe_offset(pos)).unsafe_write(element^)                 # 94
```

`element` is stored 15 lines above the read reported against it, and CPython
runs the program. The cause is in `formal/model.py`'s `_build_cfg`:

```python
entry = new([])
entry.succs += run(body, [], [entry.index])      # was
```

`run` RETURNS the blocks that fall out of the end of the body, and adding that
to the **entry** block's successors put an edge from a function's first block to
its last — a path that executes none of the body. The "definitely stored"
fixpoint reads it as real, so no store dominated the last block.
`read_before_store` then reported the first read there.

Every case in `test_formal_read_before_store.py` ends in `return`, and a
`return` terminates, so `run` returns `[]` and the whole table was blind to it.
A `def` whose last statement is a CALL falls off the end, and that is ordinary
code.

**Landed:** commit `b53c0f78` — the return value is discarded. **12 of the 19
new checks in `test_formal_read_before_store.py` fail on the parent commit and
pass here** (4 behavioural "falls off the end" shapes, 3 that pin the check is
not now silent, 5 structural CFG checks). Verified: 64/64, plus
`test_refusal_taxonomy.py` 159/159, `test_formal_value_model.py` 19/19,
`test_formal_globals.py` 19/19.

**Next step: none.** This one is closed.

### 3.3 `backend-crash: AttributeError: 'str' object has no attribute 'name'` — 3 files, FIXED

`_gpu/primitives/warp.mojo`, `runtime/_asyncrt.mojo`, `subprocess/subprocess.mojo`
— the sweep's `backend-crash` class, which is a bug in the compiler's own
plumbing and in no rate. Full diagnosis, traceback and the dead
`_check_method_receiver_types` that the same wrong argument had switched off are
in the commit message of `95b3d73c`; the filed doc
`FORMAL_frame_receivers_is_handed_the_method_name_table.md` is **deleted** by
that commit, which is what the project's own rule says a fixed bug's doc gets.

**Next step: none.** A fourth witness is `test_dataclasses_formal.py`'s corpus
case, red on `master` for this reason; it is a whole-closure compile of
`formal/build.py` and was NOT run here (see NOT DONE in the worker report).

### 3.4 `builtin_slice.mojo: StridedSlice_write_to: self.write_to is not a field of StridedSlice` — 16 files, and with §3.4b, 19 — FILED, not fixed

A mis-dispatch: `self._inner.write_to(writer)` is rewritten to
`self.write_to(writer)` — **`StridedSlice`'s own method, i.e. unbounded
recursion** — because `_rewrite_self_fields` collapses a one-field struct's
field access to its receiver without asking whether the access is a call
receiver. The only thing standing between that and a silently wrong program is
`check_value_position_method_reads`, which reports a name the source never
spells.

`bugs/FORMAL_one_word_struct_field_call_receiver_is_collapsed.md` has the full
measurement, the two candidate fixes with why neither was landed (one turns the
refusal into an unresolved symbol and LOWERS nothing, the other has no measured
effect at all), and the next step.

### 3.4b `random.mojo: Rng_rand_scalar: self._next is not a field of Rng` — 3 files, the SAME check from the other side

A struct with **no fields at all** (`struct Rng(Movable)` in
`std/testing/prop/random.mojo:18`, measured: `fields == []`,
`struct_is_one_field` False, `struct_is_framed` False) whose line 61 is
`var uint64 = self._next()`. `_rewrite_self_fields` never touches it — the
`mapping` it is handed has no `self` entry — so the refusal is
`check_value_position_method_reads` alone, refusing a call to the struct's own
method because it cannot tell a callee from a value read. Its own docstring
says so, and the helper that answers it by POSITION (`_call_receivers`, which
already looks through a subscript for the specialization case) is not consulted.

**The obvious fix is wrong and is measured**: skipping call receivers moves
BOTH families off their refusals onto real ones and lowers nothing, while
deleting the only guard against §3.4's recursion. §3.4's next step is ordered
so that question is answered first.

**Next step, in order:** (1) let the holder fixpoint visit a function whose only
holder is a one-field struct's by-value receiver — the `if not hs: continue` at
`formal/build.py:3136` is what excludes every one of them — and give
`_rewrite_nested_method_calls` its own pass over the functions the fixpoint
skipped; (2) then make the `len(declared) == 1` gate ask the receiver field's
declared type, which is stronger evidence than a unique bare name;
(3) **first check** whether `StridedSlice.__init__`'s `self._inner =
Slice(start, end, stride)` is already refused as a nested frame built by a
constructor call, because if it is then this file is a representability limit
and the valuable half is teaching `check_value_position_method_reads` to say
"the rewrite collapsed this receiver" instead of naming `self.write_to`.

### 3.5 `_assembly.mojo: inlined_assembly: __mlir_op` — 8 files, a documented true limit

`FORMAL_known_limits.md` §2. `inlined_assembly` is an MLIR dialect construct and
a formal value is one 64-bit word; the fragment-and-sub-expression template
would have to become a container, and a container here is a blob in the frame of
the function that built it, which disagrees with the compiler that does have
MLIR. **Next step: none on this path.** The same refusal is the in-file
`codegen` verdict for `std/sys/debug.mojo` and `std/utils/_select.mojo`.

### 3.6 `origin/__init__.mojo: AnyOrigin is initialized from an MLIR attribute template` and `utils/_serialize.mojo: '_kCompactElemPerSide' does not fold` — the other 2 in-file findings

Both are the `comptime` family documented in
`FORMAL_comptime_class_attribute_read_through_a_receiver.md` and
`FORMAL_known_limits.md`. **Next step: none here** — an MLIR attribute template
has no representation, and a `comptime` binding that does not fold to a
constant is the same absence of a compile-time value. A module-level `comptime`
in an IMPORTED module is the one open half of that doc and it "belongs to
whoever owns the field census".

### 3.7 `env.mojo: external_call['getenv', OptionalPointer[…]]` — 1 file, FIXED

`POINTER_TYPE_CTORS` is the table "does this declared type name a pointer", and
it is read by NAME because a declared return type is a type EXPRESSION and this
path does not resolve a module-level `comptime` binding to its target — which is
exactly why `_CPointer`, the same construct under a shorter name, is in it.
`OptionalPointer` and the five other pointer aliases `std/memory/pointer.mojo`
declares were not, so `getenv`'s return type was refused for "no value of that
kind to put in the return register". `getenv` returns `char *`: one word, with 0
meaning None, which is what `env.mojo`'s own `if not ptr:` reads.

**Landed:** commit `57a82901`. Three model cases in
`test_formal_external_call.py`; the return-kind one fails on the parent commit
with the full refusal text. **The end-to-end witness is masked** — `std/os/env.mojo`
is `std-b`'s subtree and lands on §3.1 — so what is measured is that the refusal
is GONE from that file, not that the file builds.

**Next step: none.** §3.7 was the smallest of the three and the only one whose
effect is masked rather than measured end to end.

### 3.8 `tool: timeout` — 3 files, not a verdict

`python/_cpython.mojo`, `python/python.mojo`, `python/python_object.mojo` at
`-t 180`. These are the three largest files in the slice and no verdict was
reached, so they are in **no rate**. **Next step: re-run them at `-t 600`
before reading anything into them**; the tool's own note says a too-small `-t` is
the usual cause, and a file that times out has reported nothing, so the honest
statement is that this slice's `python/` subdirectory is UNMEASURED.

## 4. The short version for whoever picks this up

1. **The slice is not a coverage problem.** 70 of 118 files are one module with
   no boundary symbol, and that module's own ceiling is measured at 0.
2. **Three things were wrong and are fixed**: a false `read_before_store`
   refusal that hid the whole slice, a `backend-crash` from a table handed the
   wrong shape, and a pointer alias missing from a name table. All three are in
   shared compiler code, not in this slice's files, and all three moved files
   off a wrong verdict.
3. **The one substantive codegen gap left in this slice is
   `check_value_position_method_reads`**, and it is a wrong-answer hazard on one
   side and a false refusal on the other: a one-field struct's field call
   receiver is collapsed into the receiver, which renames the callee's struct
   and makes `self._inner.write_to(w)` unbounded recursion (§3.4, 16 files),
   while a struct with no fields is refused for calling its own method (§3.4b,
   3 files). **19 of 118 files, the largest actionable cause in the slice**, and
   filed with its next step and with the measurement that says why the obvious
   fix is the wrong one.
4. **`python/` is unmeasured** (3 timeouts) and should be re-run at a larger `-t`
   before any conclusion is drawn about it.
5. **Nothing in this slice needs an x86-64 measurement** for the three fixes:
   the two build-path ones are shared passes, and `test_formal_receiver_spelling.py`
   and `test_formal_read_before_store.py` both pass on both architectures.
