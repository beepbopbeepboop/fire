# FORMAL_sweep_work_map_2026-10-02_std-b: slice `std-b` of the arm64 formal sweep

**Area:** `formal/` (the shared build pass and the value model). Slice
`std-b` = `../new-modular/Mojo/stdlib/std/{os,pathlib,io,format,hashlib,base64,random,math}`
— 40 files, arm64, `build --formal --no-prove`.

**Status: three fixes landed (all measured, all with a differential test), and
the binding constraint on this slice is measured to be something this slice does
not own.** §4 is the finding worth reading first: the largest cause is a gate in
another module, and §5 shows that satisfying that gate moves **zero** files in
this slice, because what is behind it is a documented MLIR limit and a
monomorphisation project. Read §5 before working anything in §4.

## 1. The runs

All three are `python3 tools/memslot.py --gb 8 --label sweep -- python3
tools/formal_sweep.py -j N -t 600 --allow-concurrent <the eight directories>
--no-stdlib` through `tools/memslot.py`. `--allow-concurrent` is safe on this
tree: the manifest write is already atomic (`formal/build.py`'s
`_write_json_atomic`, measured 0 of 12792 torn reads after the fix), and the two
sweeps racing for the arm64 lock are other workers' slices.

| | run A (before) | run B (fix 1) | run C (fixes 1+2) | run P (gate probe) |
|---|---|---|---|---|
| log | `.tmp/std-b/prefix.log` (A1+A2, 29/40) | `.tmp/std-b/sweep3.log` | `.tmp/std-b/sweep4.log` | `.tmp/std-b/sweep_probe2.log` |
| pass | — | 2 | 2 | 2 |
| codegen (in file) | 1 | 2 | 2 | 2 |
| codegen/dependency | 28 | 34 | 36 | 36 |
| backend-crash | — | **2** | **0** | 0 |
| codegen coverage | — | 2/38 = 5.3 % | 2/40 = 5.0 % | 2/40 = 5.0 % |
| `-j` / stdlib | 2+3, real | 3, real | 3, real | 2, **patched copy** |

The 2 pass files are `std/math/constants.mojo` and `std/os/pathlike.mojo`; the
sweep counts passes without printing them, so both were identified by elimination
against the per-directory class counts.

**The coverage rate went DOWN from 5.3 % to 5.0 %, and that is the tool working.**
The two files that moved were in `backend-crash`, which is in no rate at all
because a crash is a compiler bug and produced no verdict; they now have a real
verdict, so the denominator grew from 38 to 40 and nothing else moved. Reading
the rate as a regression here would be reading it exactly backwards.

Per directory, run C:

| dir | files | codegen | codegen/dependency | pass |
|---|---|---|---|---|
| `os` | 11 | — | 10 | 1 (`pathlike.mojo`) |
| `hashlib` | 5 | — | 5 | — |
| `io` | 5 | — | 5 | — |
| `math` | 6 | 1 (`polynomial.mojo`) | 4 | 1 (`constants.mojo`) |
| `random` | 4 | — | 4 | — |
| `format` | 4 | 1 (`repr.mojo`) | 3 | — |
| `base64` | 3 | — | 3 | — |
| `pathlib` | 2 | — | 2 | — |

## 2. What landed

Three fixes, all in `formal/`, each with a differential test that fails without
it. Commit subjects carry the full argument.

**(a) a method call on `self.<sole field>` was refused by a name the compiler
invented** (`2f7e8921`). A one-field struct's receiver IS its field, so
`self._inner.write_to(writer)` is a call on the word `self` — but
`_rewrite_method_calls` only recognised a NAME receiver, and
`_rewrite_self_fields` then collapsed the spelling to `self.write_to(...)`,
which reads as a method of the receiver's own struct. Two diagnostics refused it
in two different words depending on whether the outer struct happened to declare
the same method name. Census of the shape over `stdlib/std`: **61 call sites in
14 files**, 6 in `std/pathlib/path.mojo`, 7 in `std/random/_rng.mojo`, 1 in
`std/io/file_descriptor.mojo`; 16 of the 61 are on a method name two structs in
the module declare, and the receiver's declared type is what resolves those.
Measured: `std/builtin/builtin_slice.mojo` moves a level deeper (three
`StridedSlice` methods stop being refused).

**(b) `_frame_receivers` was handed the dispatch table where the owner table
belongs** (`3bf697e7`, `d27b676b`). `_prepare_functions` passed `owners`
(`{method name: struct NAME}`, keys do not overlap with function names) where
`method_owners` (`{Struct_method: StructDef}`) was meant, so
`method_owners.get(fn.name)` almost always MISSED — until a module-level function
shared a name with a method in the same module AND held a frame struct, and then
it handed a string to code that calls `.name` on it.
`AttributeError: 'str' object has no attribute 'name'`, classified
`backend-crash`: `std/math/math.mojo` (4035 lines) and `std/random/random.mojo`.
Both now reach the import diagnosis, which is the more fundamental fact. This
was a filed bug — `FORMAL_frame_receivers_is_handed_the_method_name_table.md` —
so that doc is deleted by `d27b676b` and the local renamed `dispatch_owners` as
it asked. `test_dataclasses_formal.py`'s corpus case, already red in every gate,
is the independent check: **53 passed / 0 failed** with the fix, **52 / 1** with
the call site put back, same traceback.

**(c) a NULLABLE pointer extern return was refused for a width it does have**
(`50cadc5a`). `external_call_return_kind` refused `OptionalPointer` /
`OpaquePointer` — `std/memory/pointer.mojo`'s names for
`Optional[Pointer[…]]` — with "no value of that kind to put in the return
register", which is false at a C boundary: one address, and a null pointer IS
the absent answer. `std/os/env.mojo`'s `getenv` writes exactly that spelling, and
the refusal sat on the path that decides whether the variable is absent.
Measured: `env.mojo`'s own body no longer refuses.

## 3. Where the previous instance of this task got

Commit `9c104ed0` (the controller's WIP snapshot, kept): `_build_cfg` added an
edge from the entry block to the LAST block of the body, which is a path no
source takes, and the entry's OUT set is exactly the parameters — so every name
stored before the last control-flow statement stopped being definitely stored at
it. It took the whole `std/collections` closure out of the build via
`binary_heap.mojo`'s `_heapify_up`. Reviewed and kept: the direction is the safe
one (an edge is removed, never added) and it carries 5 differential rows.

## 4. The remaining causes, ranked

`files` is the number of this slice's 40 a cause is the terminal for; `in-file`
is how many of those the construct is actually IN, which is the number that says
whether the row is work or a dependency. Measured by
`tools/formal_sweep_causes.py` over the run-C log.

| files | in-file | cause | terminal module | next step |
|---|---|---|---|---|
| 32 | 0 | `binary_heap.mojo` exports nothing (only the generic template `BinaryHeap`) | `std/collections/binary_heap.mojo` | **nothing — measured ceiling 0 for this slice, see §5.** `bugs/FORMAL_dylib_export_gate_ceiling.md` owns the decision not to change the export rule; `bugs/FORMAL_module_exports_nothing.md` says the refusal itself is true |
| 3 | 0 | `StridedSlice___init__` returns a frame address, so it cannot go into a dylib | `std/builtin/builtin_slice.mojo` | fix (a) reached it. A dylib importer binds the symbol and cannot reserve the block the object must be built in, so the open question is whether a ONE-FIELD struct needs a caller-owned block at all — it is one word, and the word is its field. `bugs/FORMAL_frame_receiver_handoff.md`'s "returned frame — the three limits" section is the account of the convention and of what it does not cover |
| 1 | 0 | `__mlir_op` is an MLIR dialect construct | `std/sys/_assembly.mojo` | documented true limit (`bugs/FORMAL_known_limits.md` §1.1); nothing to do |
| 1 | 1 | `value.write_repr_to()` — a method call on a **generic parameter's** value | `std/format/repr.mojo` | §6 |
| 1 | 1 | `comptime num_coefficients = len(coefficients)` does not fold — the initialiser is over a **comptime parameter** | `std/math/polynomial.mojo` | §6 |

## 5. What is BEHIND the gate, measured (run P)

The 32-file row is a property of the import graph, not of any of these 40 files,
so the next question is what a file lands on once the gate stops firing. Run P
answers it exactly as `bugs/FORMAL_dylib_export_gate_ceiling.md` §7 describes: a
copy of the stdlib at `.tmp/std_b_patched` with ONE public declaration appended to
`binary_heap.mojo` (`def binary_heap_export_probe() -> Int: return 0` — a probe,
**not** a proposed stdlib change), reached through `MOJO_STDLIB`, with an
isolated `GMOJO_HOME` so its `formal-imports/<arch>` directory and verdict cache
cannot race the real tree's. (Both seams are load-bearing: the sweep's children
do not inherit a patched `module_loader`, and two sweeps sharing a dylib
directory is what `FORMAL_sweep_killed.md` and the manifest race are about.)

Terminal causes with the gate satisfied, run P:

| files | cause | terminal module | what it is |
|---|---|---|---|
| 17 | MLIR dialect construct | `std/sys/_assembly.mojo` (10), `std/sys/info.mojo` (4), `std/reflection/function.mojo` (3) | documented true limits (`bugs/FORMAL_known_limits.md` §1.1, §2) |
| 9 | module exports nothing | `binary_heap.mojo` (7), `std/sys/_io.mojo` (2) | the gate did not fully lift for 7 of them — see the caveat below |
| 6 | a slot's declared type is not a value this path can supply (`len(self._data)` on a `List[Self.T]` field) | `binary_heap.mojo` | `FORMAL_dylib_export_gate_ceiling.md` §3, verbatim; needs a value a running statement puts in the slot |
| 3 | `external_call['getenv', OptionalPointer[…]]` return width | `std/os/env.mojo` | **fix (c), landed after run P was measured** — this row is closed by `50cadc5a` |
| 1 | returned frame address | `std/builtin/builtin_slice.mojo` | §4 |
| 2 | the two in-file rows | `std/format/repr.mojo`, `std/math/polynomial.mojo` | §6 |

**The number that decides the slice: 0 files move.** Satisfying the gate takes
the 32 from one refusal to another, and every one of the refusals behind it is
either a documented MLIR limit (17), `binary_heap.mojo`'s own body (6), or the
same gate reached again (9). The headline coverage for this slice is therefore
**not** gated on `binary_heap.mojo`, and work spent on the export rule buys
nothing here. That is `FORMAL_dylib_export_gate_ceiling.md`'s verdict, now
measured on a fourth slice.

**Caveat, stated rather than hidden:** the gate did not lift for 7 of the 9 rows
in the "module exports nothing" group, so run P is a **lower bound** on what lies
behind it — `MOJO_STDLIB` does not reach every nested dylib build, which is the
same seam §7 of that document warns about, and this run had a cold `GMOJO_HOME`
so nothing was served from a stale cache. The rows it DID move are enough for
the conclusion above (17 + 6 + 3 + 1 = 27 of 40 accounted for by causes that are
not this slice's), but a re-run with the seam fully working would be needed to
close the remaining 9.

## 6. The two in-file rows, and why neither is a patch

Both are the same construct seen from two directions: **a generic parameter's
VALUE**. `formal/build.py` specializes a generic CALL (`Struct_m[T](recv, a)`,
`model.incoming_args` puts the comptime parameters first) but never a generic
BODY, so inside `def f[T](…)` nothing knows what `T` is.

* `std/format/repr.mojo` — `def repr[T: Writable](value: T)` calls
  `value.write_repr_to(string)`. The receiver is a parameter whose declared type
  is the type parameter `T`, so there is no struct to dispatch on. **And this
  file has a second blocker behind it**: `return string^` returns a `String`,
  which `std/collections/string/string.mojo` declares with three fields, so the
  receiver is a frame address and the frame-lifetime rule refuses it
  (`bugs/FORMAL_string_value_model.md`). Closing only the first leaves the file
  refused.
* `std/math/polynomial.mojo` — `comptime num_coefficients = len(coefficients)`
  where `coefficients: Span[Scalar[dtype], _]` is a comptime parameter. A
  `comptime` binding's value has to exist before the function runs; over a
  parameter it only exists per specialisation.

Next step for both, and it is the same one:
`bugs/FORMAL_known_limits.md` §1.2 (Stage 5, generics/monomorphisation) — read it
before starting, because it is a project and not a patch, and it is not this
slice's to claim.

## 7. Deliberately NOT done, and why

* **`binary_heap.mojo`'s export gate.** Another lane's decision
  (`FORMAL_dylib_export_gate_ceiling.md`), and §5 measures its ceiling for this
  slice at 0.
* **The multi-parameter type application in an `external_call` bracket.** This is
  the wall between fix (c) and `env.mojo`'s real spelling
  (`OptionalPointer[UInt8, ImmUntrackedOrigin]`): a type application is refused
  earlier, as a subscript whose index is a tuple. It is
  `bugs/FORMAL_external_call_a_multiparameter_type_in_the_bracket.md`, claimed by
  `formal3-3-r2`, and its §"Next step" already says what the fix is. Two rows of
  `test_formal_external_call.py` are sitting on it (`env_round_trip` and
  `a_nested_bracket_in_the_type_argument_is_not_a_tuple_index`); both fail before
  and after anything in this branch.
* **`Optional` as a value.** `bugs/FORMAL_stdlib_optional_needs_a_representation.md`
  is a value-model decision with a measurement behind it. Fix (c) is careful to
  answer only the C-ABI question and to leave the pointer question refused.
* **A frame address read through an aliased receiver.** A value read
  (`self._leaf.v` where `_leaf` holds a framed struct) collapses to `self.v` and
  is then refused for want of a frame-holder edge — the
  `FORMAL_method_param_field_access.md` family, which names
  `construct:receiver-handoff-method` as its owner. Only the CALL spelling is
  answered by fix (a); the test rows say so.

## 8. Traps, for whoever runs this next

* **Do not run two arm64 sweeps against the same dylib directory.** They share
  `~/.gmojo/cas/formal-imports/arm64/` and its manifests. The write is atomic now
  (`formal/build.py`'s `_write_json_atomic`: private temp + fsync + `os.replace`,
  measured 0 torn reads in 12792 after the fix), so the failure mode is not
  corruption — but `bugs/FORMAL_sweep_tool_json_decode_error.md` is the history of
  what it was, and a verdict read while another sweep is still building a dylib is
  a verdict about a half-built library.
* **`GMOJO_HOME` is the whole isolation.** `formal/build.py` derives the dylib
  directory from `cas.cas_dir()`, so a separate `GMOJO_HOME` gives a separate
  `formal-imports/<arch>` AND a separate verdict cache. Use it for any probe that
  changes a `.mojo` file. The sweep's verdict key does fold in the import closure
  the build reads (`cas.formal_build_key`'s `_imports_digest`, per
  `tools/formal_sweep.py --help`), but a separate `GMOJO_HOME` also means a COLD
  cache, which is what makes the probe number trustworthy rather than a mix of
  fresh and replayed verdicts.
* **`MOJO_STDLIB` is the seam that reaches nested dylib builds**, but it did not
  reach all of them in run P (§5's caveat). Verify with one file before trusting
  a 40-file number.
* **The slice sweep is slow**: 40 files at `-j 3 -t 600` is ~50 min, and
  `std/math/math.mojo` alone is minutes. Run it in the background and do
  something else.
* `std/python/bindings.mojo` builds from other workers' trees were still running
  at 14+ hours when this ran. `bugs/FORMAL_sweep_killed.md` records that file as
  a build that does not terminate at a flat 0.06 GB. They hold CPU and nothing in
  this slice.
