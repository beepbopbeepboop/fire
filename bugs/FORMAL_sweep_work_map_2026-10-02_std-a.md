# FORMAL_sweep_work_map_2026-10-02_std-a: `std/{builtin,collections,memory,algorithm,bit}`, and three fixes

**Slice:** the 94 `.mojo` files under
`../new-modular/Mojo/stdlib/std/{builtin,collections,memory,algorithm,bit}`
(builtin 38, collections 33 incl. `collections/string/`, memory 12, algorithm 8,
bit 3). **Claim:** `sweep:std-a` on `work/formal4-sweep-std-a`.
**Status:** swept (94/94), three fixes landed, the four largest causes are all
owned by another claim or measured at ceiling 0 — §3 says which, and §5 says
what is therefore left.

## 1. The run

```
/opt/homebrew/bin/python3.11 tools/memslot.py --gb 8 --label sweep -- \
  /opt/homebrew/bin/python3.11 tools/formal_sweep.py -j3 -t 240 --allow-concurrent \
  ../new-modular/Mojo/stdlib/std/{builtin,collections,memory,algorithm,bit} \
  --no-stdlib
```

`-j3 -t 240`, per-file 4 GB ceiling, peak **0.4 GB across 8 processes**, wall
clock ~95 min at `-j3` on a machine running six other workers. Log
`.tmp/sweep-std-a-post.txt`; the log and `.tmp/` are git-ignored, so §7 has the
commands that re-derive every number here.

**Read the interpreter in that command.** The bare `python3` on this host is
3.9.6 and the tree needs 3.10+ (`bugs/INFRA_bare_python3_is_3_9_and_the_formal
_backend_needs_3_10.md`, filed here): with it the same sweep reports **94 of 94
files as `backend-crash`** with `TypeError: unsupported operand type(s) for |:
'type' and 'NoneType'` at `formal/model.py:1668`, and `codegen coverage: no
file could be answered by this backend`. That is what this task's first sweep
run produced, for about ten minutes, before it was spotted.

| class | files |
|---|---|
| `pass` | **9** |
| `codegen` (the finding: a refusal IN this file) | **7** |
| `codegen/dependency` (a refusal one level down) | **69** |
| `backend-crash` | **0** |
| `not-answerable/unresolved-extern` | 2 |
| `tool` (no verdict: `-t 240` timeout) | 7 |
| **codegen coverage** | **9/85 = 10.6 %** |

`codegen/dependency` by module — the whole of it is four modules, and 65 of the
69 lines come from the sweep's own family breakdown:

| module the refusal is in | files |
|---|---|
| `collections/binary_heap.mojo` — module exports nothing | **37** |
| `builtin/builtin_slice.mojo` — other refusal | **15** |
| `_assembly.mojo` / `_select.mojo` — MLIR dialect construct | 7 |
| `algorithm/backend/tile.mojo` — other refusal | 4 |
| `format_int.mojo`, `_unicode_lookups.mojo` | 2 |
| (the four files re-measured after this branch's third commit, §2.3) | 4 |

`FILES BLOCKED IS AN UPPER BOUND` — a file's terminal cause is the first
refusal reached, so fixing one moves the file to the next with the count
unchanged. `uses:` in §3 is what says whether a row is work or a
Stage-5 dependency.

## 2. What landed

### 2.1 `formal: the CFG entry block must not have a second successor` (fb5129f4)

**The largest false-refusal family in this slice, and it was in the sweep's own
top row.** `_build_cfg` ended with `entry.succs += run(body, [], [entry.index])`,
which edged the function's ENTRY block to whichever block its last statement
falls out of. Those blocks are already reachable — the body was emitted with the
entry as its pending predecessor — so the extra edge was a path from function
entry to the final join passing through nothing the body stores, and
`_definitely_stored`'s intersection over that join threw the body's definitions
away. It fired only when a body FALLS OFF THE END, which is why it survived.

Measured, by calling `read_before_store` over every function of every file in
the slice with and without the edge (`.tmp/rbs_scan.py`):

| | functions refused | files |
|---|---|---|
| before | 380 | 54 |
| after | 326 | **50** |
| **removed by the fix** | **54** | **26** |

and over the whole repo + stdlib (717 `.mojo` files): **520 functions across 143
files** stop being refused, **0** start. Every one of them was refused with a
message quoting CPython's `UnboundLocalError` for a program CPython runs. The
26 slice files include all five sort helpers in `std/builtin/sort.mojo`,
`_heapify_up` **and** `_heapify_down` in `collections/binary_heap.mojo`,
`collections/{dict,list,set,deque,counter,interval,linked_list,span}.mojo`, and
`algorithm/backend/cpu/map.mojo`.

Two files demonstrate the distance travelled, and neither is in the fix:

* `binary_heap.mojo`'s terminal refusal moved from *"'element' is read at line
  94 before anything in this function stores it"* to the export gate and then to
  `len(self._data)` on a `List[Self.T]` slot (§3 row 1). It is now refused for
  something true.
* `algorithm/backend/cpu/map.mojo` moved from `codegen` (a false read-before-
  store on `i`, the loop's own target) to `not-answerable/unresolved-extern`:
  **it builds now**, and the only thing left is that `func(i)` — a parameter
  used as a callee — emitted a dangling call to a symbol literally named `func`.
  That is a real, separate construct (§6, first row).

**Why it was still worth fixing at coverage-ceiling 0.** The b3 map (§5 of
`FORMAL_sweep_work_map_2026-10-01_b3.md`) measured two large rows at ceiling 0
and correctly said so. This row is different in the one number that matters: the
refusal it removes is **not a property of an import closure**, it is a false
refusal of a function the sweep's own file is compiling, and the construct it
removes is the analysis's own bookkeeping rather than a stdlib gap. Nothing
downstream of it is reachable until it is gone, and the 26 files are 26 files
that would each need re-measuring afterwards.

### 2.2 `formal: a `match` case's capture binds in ITS OWN arm` (163e9e63)

`bugs/FORMAL_a_local_read_before_its_first_assignment.md` §"A FOURTH artifact
class" names a `match` case's capture pattern as one of the two shapes the
read-before-store scan still gets wrong, and it was: the arm was refused for
reading its own capture. `_Block` gains a `seed` — names a block's IN set holds
for a reason other than its predecessors, added to the fixpoint's intersection
*after* it — because a `def` entry is visible to every successor and putting the
captures on the match head would make one case's binding visible in another
case's arm, which hides a real `UnboundLocalError`. Three rows pin the per-arm
design and all three fail if the captures go on the head.

`_match_case_binds` deliberately stops at a bare identifier: `match` in this
compiler is switch-style equality dispatch, not PEP 634 structural matching, so
`case [a, b]` evaluates the list `[a, b]` and compares it with `==` and `a`/`b`
are **reads**. A structural-pattern walk would be a second, wrong answer about
what the source means.

**Measured effect on the corpus: 0 files.** Every `case` in the repo and the
stdlib is a `case _:` wildcard — 23 of them, not one bare-name capture. So this
is a named next step closed, not coverage, and the commit says so.

### 2.3 `formal: _frame_receivers is handed the wrong method→struct map` (36b6d902)

**The slice's only `backend-crash`, and it is a bug in the compiler's plumbing
rather than a finding about a source** — which is the one class the sweep
classifies as neither coverage nor a limit, never caches, and re-runs until the
cause is gone.

`_prepare_functions` builds two method→struct maps and `_frame_receivers` was
handed the wrong one. `owners` is `{bare method name: struct NAME}` (for
`_rewrite_method_calls`, which dispatches `recv.m(...)` by name alone);
`method_owners` is `{lifted function name: struct}` (for the passes that ask
which struct's LAYOUT a body is written against). `_frame_receivers`'s
parameter is documented as the second and both its uses read `.name` off the
value:

```
AttributeError: 'str' object has no attribute 'name'
  formal/build.py:6465 in _overridden_comptime_names   st.name
  formal/build.py:6255 in publish
  formal/build.py:6232 in _constant_read_sites
```

Measured on `std/builtin/reversed.mojo`, which declares seven module-level
`reversed` functions and imports a host module whose structs have a `reversed`
method — so the wrong map's bare-name key hit. The **quiet** half is the worse
one: everywhere else the lookup missed, so `_frame_receivers` ran
`refuse_none_comparisons` and `_rewrite_class_constants` with an empty census on
every module, and the class-constant read-through-a-receiver substitution that
pass's own docstring says it needs the map for never saw a method.

After the fix `reversed.mojo` is `codegen/dependency` behind
`builtin_slice.mojo`, and the slice has **0 `backend-crash`**.

## 3. The four causes that are left, and why none of them is this slice's to work

`python3 tools/formal_sweep_causes.py --min 2 .tmp/sweep-std-a-post.txt`:

| files blocked | in-file | cause | owner / next step |
|---|---|---|---|
| **38** | 0 | **module exports no public functions** — `binary_heap.mojo x37`, `_unicode_lookups.mojo x1`. `uses:` reads **1 of 37** name anything binary_heap declares | measured at **ceiling 0** in `FORMAL_dylib_export_gate_ceiling.md` §3/§5/§6: every candidate fix (per-instantiation export, a type descriptor, an instantiation-keyed CAS entry) was measured at 0 files, because 36 of the 37 never mention `BinaryHeap`. **The doc's §8 names the real blocker and it is NOT the export table**: `binary_heap.mojo` itself cannot lower, on `len(self._data)` — a `List[Self.T]` slot whose value `S()` never puts there because premise **(B2)** `S()` does not run `__init__` on this path. See §6 row 2 |
| **16** | 1 | **other refusal** — `builtin_slice.mojo x15` (`self.step.or_else()`, an Optional unwrap) + 1 in-file | `formal2-re-and-slice` (`construct:re-merge-and-builtin-slice`). Ceiling already measured at **0** in the b3 map §10: lifting the refusal moves all 15 onto the generic `lowers only append, close, write`, so the call has no lowering at all. `FORMAL_stdlib_optional_needs_a_representation.md` is the value-model design |
| **8** | 1 | **MLIR dialect construct** — `_assembly.mojo x6` (`inlined_assembly`: `__mlir_op`), `_select.mojo x1` (`_select_register_value`), 1 in-file (`type_aliases.mojo`, `Never` from `__mlir_type.!kgen.never`). `uses:` reads **0 of 6** for `_assembly.mojo` | `formal2-mlir-comptime` (`construct:mlir-hoist-and-comptime-receiver`) + `formal-mlir-gpu`. `FORMAL_known_limits.md` §2. The 6 behind `_assembly.mojo` are closure, not work |
| **6** | 1 | **a bracketed specialization of a callee this unit does not compile** — `tile.mojo x4` (`workgroup_function[…](…)` called through a *function-valued field*), `format_int.mojo x1`, 1 in-file | `formal-mlir-gpu`. Fully specified in `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`, whose "Whose" section says this is not `formal/`'s to fix and why (the callee is not a name, so there is no declaration in hand even in principle) |

**Read the four rows as one sentence: 68 of the 72 `codegen/dependency` lines are
four modules' refusals, and every one of the four is either measured at ceiling 0
or held by a live claim.** This slice has no unowned large row left. What it has
is seven `codegen` rows (§4) that are individually small and each of which needs
a different answer.

## 4. The seven in-file findings (`codegen`), by what each one needs

| file | the construct | next step |
|---|---|---|
| `collections/binary_heap.mojo` | `len(self._data)` where the slot's declared type is `List[Self.T]`: the lowering is settled (count word at offset 0) and the **value** is missing, because `S()` does not run `__init__` (premise B2) | the value-model question `FORMAL_dylib_export_gate_ceiling.md` §8 defers to `FORMAL_class_assigns_its_fields_in_init` (a doc that does not exist) and `bugs/FORMAL_value_model_*`. **Measure the ceiling before investing**: it is the module 37 files are blocked by, and §3 row 1 is the only reason 37 files are in this class |
| `collections/type_dict.mojo` | `Self._index` reads a `comptime` class attribute whose value is `Self.keys.try_index(key)` — a non-literal, and a formal value is one 64-bit word with nowhere to keep one | a non-literal `comptime` binding. Distinct from B2: the value is a *computation*, not a container |
| `builtin/float_literal.mojo` | `FloatLiteral.__init__()` both mutates its receiver and returns a value, and on this path the word a one-field struct's mutator hands back **is** the receiver | already refused by name and already pinned (`model.receiver_writeback_name`, `test_formal_run.py`'s `one_field_mutator_with_a_return_value_is_refused`). The fix is a value-model decision about one-field mutators, not a lowering. Note the asymmetry the message names: `formal3-1-r2` landed an *owned-ctor frame reservation* for a related shape (`Alias = mod.Class` resolving to the class it names), so the two interact |
| `builtin/len.mojo` | a `...` body where this path needs instructions to emit — the language's own no-implementation marker | `len`'s builtin implementation is a stub in this tree. Either give it a body this path can lower, or teach the pass that a builtin with no body is a declaration rather than a function to emit. Cheap, and the shape is the language's own |
| `builtin/none.mojo` | `writer.write_string()` — a method on a `Writer`, a multi-field struct, so the receiver is a frame address rather than a file descriptor | the receiver-position family (`FORMAL_frame_receiver_handoff.md` §6–§13); needs a `Writer` lowering this path does not have. **Not the same as the 24-file "receiver at argument position 0" row**, which `formal-receiver-novalue` holds — this one is a `write_string` on a frame |
| `builtin/type_aliases.mojo` | `Never` is initialised from `__mlir_type.!kgen.never` | MLIR row, `formal2-mlir-comptime`. Cheapest of the seven if that claim wants it: the file is 1 of 8 and names `Never` |
| `algorithm/backend/tile.mojo` | §3 row 4 | `formal-mlir-gpu` |

## 5. The two remaining non-`codegen` classes

* **`not-answerable/unresolved-extern` (2).** `algorithm/backend/cpu/map.mojo`
  and one other: the image builds and binds a symbol nothing provides. For
  `map.mojo` the symbol is literally `func`, from `func(i)` where `func` is a
  **parameter used as a callee**. That is a real construct and a real gap, it is
  in no `bugs/` doc, and it is **unowned** — see §6 row 1.
* **`tool` (7), all `-t 240` timeouts.** `collections/{array,counter,deque,dict,
  list}.mojo` and `collections/string/{string,string_span}.mojo` — the largest
  files in the slice. A `-t` artefact rather than a finding, on the same
  evidence the b3 map §5 records for `formal/arm64_codegen.py` (29.8 s at
  `-t 30`). **Anyone reading a coverage number off this slice should re-run
  those seven at `-t 600` before quoting the denominator.**

## 6. What is left, ranked, with the measurement each one still owes

1. **A parameter used as a callee** (`algorithm/backend/cpu/map.mojo`:
   `def map(func, size): for i in range(size): func(i)` emits a dangling call to
   a symbol named `func`). Unowned, no doc, and it is a *lowering* gap rather
   than a value-model one, which makes it the cheapest real coverage on this
   list. Reproducer:
   `python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/m.macho
   ../new-modular/Mojo/stdlib/std/algorithm/backend/cpu/map.mojo`.
   **Ceiling to measure first:** `grep -rln '^\s*def [a-z_]*(func\|cb\|f,' ` over
   the stdlib — if the shape is rare, this is a one-file fix and should not be
   queued as a family.
2. **Premise (B2): `S()` does not run `__init__`.** The blocker under 37 files
   (§3 row 1) and the largest single thing in this slice. It is a value-model
   change with a `SIGSEGV`-if-emitted history (`model.frame_slot_value_refusal`
   documents the measurement), so the standing instruction applies: **measure a
   ceiling before implementing.** The cheapest probe is to make `binary_heap.mojo`
   construct its list in the caller and assign the field after `S()` — which is
   what that refusal's own text suggests — and re-sweep the 37; the doc
   `FORMAL_dylib_export_gate_ceiling.md` §4 already measured the *removal* probe
   (delete the re-export from `collections/__init__.mojo`) at 0 files, so a probe
   that only moves the one module is what is needed, not another closure probe.
3. **A non-literal `comptime` class binding** (`collections/type_dict.mojo`'s
   `Self._index`). One file in this slice; whether it is a family is a `grep`
   away (`comptime [A-Za-z_]+ *(:|=) *[A-Za-z_]*\.[a-z_]*\(` over the stdlib).
4. **A builtin whose body is `...`** (`builtin/len.mojo`). One file; the question
   is whether the pass should treat a stub body as a declaration.
5. **The seven `-t 240` timeouts** (§5). Not work — a re-measurement.

## 7. Reproducing this

```sh
# the sweep (see §1 for the interpreter, and why it is not the bare `python3`)
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j3 -t 240 --allow-concurrent \
  ../new-modular/Mojo/stdlib/std/{builtin,collections,memory,algorithm,bit} \
  --no-stdlib > .tmp/sweep-std-a-post.txt

# §3's cause table
python3 tools/formal_sweep_causes.py --min 2 .tmp/sweep-std-a-post.txt

# §2.1's before/after, function level, no builds at all (seconds, not minutes)
#   .tmp/rbs_scan.py parses every function of every file in the slice and prints
#   M.read_before_store(fn); run it with and without the one-line `entry.succs`
#   change and diff the output.
```

The per-file verdicts in §1's table are from the 94-file run above with **four
files re-measured individually** afterwards, because this branch's third commit
(`36b6d902`) landed while the sweep was in flight: `builtin/reversed.mojo` and
`std/memory/{__init__,_poison,address_space}.mojo` were classified by a build
that still carried the bug, and each was re-run through `fire.py build --formal
--no-prove --backend=arm64` afterwards. All four are `codegen/dependency`, which
is why §1 reads 69 and 0 rather than 65 and 4.

**The three `std/memory` rows in the run's own log are not reproducible and
should be believed with care**: they carry
`AttributeError: 'str' object has no attribute 'write'`, which is a temporary
`print(..., file=<a string>)` that was in `formal/build.py` while the sweep ran,
not anything about `std/memory`. **Editing a file under `formal/` while a sweep
is running makes that sweep's verdicts a mixture of two trees**, and the sweep's
own CAS key does not protect you from it — the key changes, so the files
classified before and after the edit simply land in different cache entries and
both look legitimate. Re-measure, as §1 did.

## 8. The verification this branch ran

No gate, no bootstrap, no `compile_stdlib.py` — the integrator's. What was run:

```
python3 test_formal_read_before_store.py            → PASS=65 FAIL=0  (3 CPython-oracle rows + 5 graph-shape rows added)
python3 test_formal_method_param_field.py           → PASS=21 FAIL=2  (both failures measured pre-existing on HEAD; §2.3's case added, and it is one of the 21)
python3 test_formal_globals.py                      → PASS=19 FAIL=0
python3 test_formal_value_model.py                  → PASS=19 FAIL=0
python3 test_formal_frame_len.py                    → PASS=10 FAIL=0
python3 test_refusal_taxonomy.py                    → PASS (159/159 checks, 34 families, 53 causes)
python3 -m unittest test_formal_sweep_truth         → Ran 31 tests, OK
```

`test_formal_run.py` (484 build-and-run cases, the one suite that would cover
all three fixes end to end) was **not** run — it is a heavy consumer and this is
a light worker. It is the integrator's, and §2.3's change to which
`method_owners` map `_frame_receivers` sees is a behaviour change beyond the
crash (the census is no longer empty on most modules), so it is the one thing
here that wants a full `make gate`.