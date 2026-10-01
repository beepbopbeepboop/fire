# FORMAL_sweep_work_map_2026-10-01_b3: the b3 tree swept on BOTH architectures, and the first same-tree arm64-vs-x86-64 comparison

**Status: measured. Both arms are COMPLETED 630-file runs on ONE tree
(`e695183a`, `formal-batch3`), so §4 is a real architecture comparison for the
first time — the previous map (§6 of `FORMAL_sweep_work_map_2026-10-01.md`)
compared two different trees and could only compare the instrument. The
instrument was fixed in the same branch (`fbaed39b`) and §3 is what it found.**

Logs: `.tmp/sweep-arm-b3.txt`, `.tmp/sweep-x86-b3.txt`. Both written with

```
python3 tools/memslot.py --gb 16 --label sweep -- python3 tools/formal_sweep.py -j6 [ --arch x86_64 ]
```

`-j6 -t 30`, 4 GB per-file ceiling, cold CAS (2 hits / 628 misses on arm64,
3 / 627 on x86-64), peak 0.6 GB across 14 processes on arm64 and 0.5 GB across
15 on x86-64. Both runs exited 1, which is the sweep's own "there were
findings" exit, not a crash.

## 1. The runs

| | arm64 | x86-64 | was (2026-10-01) |
|---|---|---|---|
| files | 630 | 630 | 623 / 623 |
| pass | **114** | **106** | 113 / 106 |
| codegen | 178 | 176 | 187 / 184 |
| codegen/dependency | 125 | 176 | 118 / 164 |
| not-answerable/host-import | 198 | 153 | 192 / 153 |
| not-answerable/unresolved-extern | 5 | 3 | 5 / 9 |
| not-answerable/unresolved-import | 1 | 1 | — / — |
| not-answerable/target-limit | 5 | 5 | 5 / 5 |
| tool | 4 | 10 | 3 / 2 |
| codegen coverage | **114/417 = 27.3 %** | **106/458 = 23.1 %** | 27.0 % / 23.3 % |
| wall clock | ~9 min at `-j6` | ~9 min at `-j6` | ~13 min / not measured |

**The denominators moved and the pass counts are not comparable to the old
column without saying so.** 623 → 630 is six files, all of them `test_formal_*`
added by the batch-1 branches this tree carries
(`type_application`, `specialized_method_call`, `trait_module`, `platform`,
`recursion_contract`, `eval_eq_mojo_bridge`); four are host-import facts and
two are `codegen` on `hasattr(recv)`. None of the six could pass, so the arm64
gain of +1 is not them: it is a real file that moved, and §2 says which.

**The x86-64 pass count is still a FLOOR, and the instrument now says so in its
own summary line** — 7 of its 10 `tool` rows are
`this arm64 host cannot check whether their imports resolve`, i.e. the
cross-architecture dlopen limit documented in the previous map §4. The previous
x86-64 report's 106 was also a floor for the same reason; this run's 106 is
reached by a different set of files (§4).

## 2. Ranked causes, arm64 (`tools/formal_sweep_causes.py --min 4`)

281 of 303 `codegen`/`codegen/dependency` lines accounted for, in 11 causes of
26. **This table is the one to read; the previous map's row 1 was not, and
§3 says why.**

`FILES BLOCKED` is an UPPER BOUND — a file's terminal cause is the first
refusal the walk reaches — and `uses:` says whether a row is work or a
Stage-5 dependency.

| files blocked | in-file | cause | owner / next step |
|---|---|---|---|
| **93** | 2 | a bracketed specialization of a callee this unit does not compile | `construct:debug-assert-and-local-imports` (`formal2-assert-imports`). **85 of the 93 are the one `debug_assert[…]` in `std/collections/binary_heap.mojo`.** Marginal effect measured: **0 of 12 sampled dependents reach `pass`** — all 12 move to the export-gate refusal, whose ceiling is already measured at 0 in `FORMAL_dylib_export_gate_ceiling.md` |
| 50 | 26 | other refusal | a bucket, not a cause. Down from 183/68 — see §3 |
| 28 | 28 | callee has no definition on this path | `FORMAL_callee_no_def_ceiling_zero.md`; the `formal-callee-no-def-2` claim is integrated |
| 24 | 24 | receiver passed at argument position 0 | one construct, all in-file |
| 24 | 15 | MLIR dialect construct (`__mlir_attr`/`__mlir_type`/`__mlir_op`) | `construct:mlir-hoist-and-comptime-receiver` (`formal2-mlir-comptime`) and `construct:mlir-and-gpu-globals`. The 15 in-file are work; the 9 behind `_assembly.mojo` name nothing it declares |
| 24 | 24 | receiver stored in a field of a struct that outlives it | **unowned.** `formal/build.py:4735`. Reproducer: `bugs/FORMAL_receiver_stored_in_a_field.md` |
| 13 | 13 | a parameter's declared type contradicts every call site | **unowned.** `formal/model.py:7110` (`frame_declared_parameter_refusal`). Reproducer: same doc |
| 9 | 9 | value with no representation on this path | one construct, all in-file |
| 8 | 8 | frame address passed where a value is wanted | `FORMAL_wide_receiver_by_reference.md` |
| 5 | 5 | a module-global name has no storage | `FORMAL_module_state_no_storage.md` |
| 5 | 5 | a module-level name of ANOTHER module is not exported as a word | all five are `sys`; `FORMAL_module_state_no_storage.md` |

The same table on x86-64, in 10 causes of 25, is the arm64 one with `re.mojo`
added (51 files, §4) and `a module-global name has no storage` absent.

## 3. The instrument fix, and why the previous map's biggest row was not actionable

`formal_sweep_causes.py` had **no marker for four shapes**, and `other refusal`
— the bucket its own docstring calls "unclassified" — read **183 files / 68
in-file** on this run. Every one of the four was a marker MISSING rather than
one that had gone stale, which is the quieter of the tool's two documented rot
modes: the table still summed to the total, and the number a planner would act
on was wrong.

| files | shape | source |
|---|---|---|
| 93 | `f[…](x)` on a callee this unit does not compile | `formal/model.py:2377` |
| 24 | a receiver stored in a FIELD (the container row's sibling) | `formal/build.py:4735` |
| 13 | a parameter whose DECLARED type contradicts every call site | `formal/model.py:7110` |
| 5 | `__mlir_type.` — the MLIR row's LABEL already named it | `formal/model.py:1081` |

`other refusal` is now **50 files / 26 in-file**. Fixed in `fbaed39b`, with a
real-message sample per new cause and four precedence assertions in
`test_refusal_taxonomy.py`, each verified to fire by breaking its marker.

Two of the four are worth a note on their own:

* **The 93-file row was the largest row in the sweep and the table could not
  see it at all.** `formal/model.py` computes the MLIR row's "attribute" vs
  "type" from the node, so the type wording (`__mlir_type.`!kgen.target``)
  matched none of that row's three markers — a cause whose LABEL names a
  construct and whose MARKERS cannot match one is a row that reads as covering
  something it does not.
* **The field-store row is the largest one this map adds and it is genuinely
  unowned.** It is a sibling of the existing "receiver stored in a container"
  row, not an alternative of it: a container has no owner, a field outlives
  the call that filled it. 22 files in-file on both architectures.

**Re-running the previous map's log through the fixed table** moves its
row 1 ("other refusal", 83 files, of which the map itself said "the 59 in-file
ones need splitting before they can be worked") to 42 files with the split
done. The map's second-largest row, "a TYPE name placed as a value", 82 files,
is **0 on this tree**: the batch-1 `construct:type-name-as-value-2` fix landed,
and the 81 dependents moved onto the bracket row. That is progress with the
count unchanged, which is exactly what the upper-bound warning predicts.

## 4. arm64 vs x86-64, on the same tree

**56 files are x86-64-only, and all 56 are one construct: the register-argument
count.** Measured, on the same tree, same sweep, same tool:

```
93  both arches, same terminal message          (the classified rows of §2)
56  x86-64 only   — 51 behind re.mojo, 3 behind hashlib.mojo, 2 in-file
 0  arm64 only
```

Reproduced in six lines, on both architectures, on this tree:

```mojo
def seven(a: Int, b: Int, c: Int, d: Int, e: Int, f: Int, g: Int) -> Int:
    return a + b + c + d + e + f + g
def main(n: Int) -> Int: return seven(1, 2, 3, 4, 5, 6, 7)
```

| | arm64 | x86-64 |
|---|---|---|
| built? | **yes** | refused |
| run | exit **28**, which is the answer | — |

The refusal is `call seven(): 7 arguments exceeds the 6 the formal x86-64 ABI
passes in registers`, and it is **not a bug**: `formal/x86_64.py:65` is
`ARG_REGS = (RDI, RSI, RDX, RCX, R8, R9)` — the six SysV x86-64 integer
argument registers — against `formal/arm64_codegen.py:60`'s
`_ABI_ARG_REGS = 8` for AAPCS64's x0–x7. The two numbers are the two ABIs.

It is still worth a row in the map, for the reason the previous map's §4 gave:
**it is the largest single-file-per-file difference between the two backends on
this tree, and it costs 51 files behind `re.mojo` alone** — one function with
seven parameters. The honest reading is that a host module with a 7-parameter
helper is not lowerable to x86-64 and is; the honest caveat is that 51 files
are counted in x86-64's denominator and would not be in arm64's.

The remaining x86-64-specific rows are small and are not backend differences:
3 `tool` rows that are `-t 30` timeouts on `re.mojo`'s import closure, and the
7 unprovable-dylib rows of §1.

## 5. The marginal effect of the largest row, measured before anyone invests

The task's standing instruction is that `FILES BLOCKED` is an upper bound and
the effect must be measured first. For the 93-file row it is measured, and it
is **zero**:

```
$ python3 tools/formal_sweep.py --no-stdlib -j6 -t 60 <12 sampled dependents>
codegen coverage: 0/12 = 0.0%
```

with `formal/build.py`'s `debug_assert` refusal lifted behind a temporary
guard, the same 12 files:

```
codegen coverage: 0/12 = 0.0%
```

**12 of 12 moved, every one onto `binary_heap.mojo: formal dylib has no public
functions`** — the export gate, whose own doc
(`bugs/FORMAL_dylib_export_gate_ceiling.md`) records a measured ceiling of 0
files for every candidate, because 34 of its 35 blocked files do not contain
the string `BinaryHeap`. So the 93-file row is real work (a builtin with no
lowering at all, `FORMAL_debug_assert_bracket_has_no_lowering.md`) and it is
**worth 0 files on its own**: the module behind it has nothing to export. The
guard was reverted; `git status` is clean and `formal/build.py` is unmodified.

**Read that as two rows, not one 93-file row.** Fixing `debug_assert` is worth
0 files until the export gate is answered, and the export gate is worth 0 files
until `binary_heap` exports something. Two unowned workers on one number is the
wrong plan; §7 enqueues them as what they are.

## 6. What this document does not establish

* It does not price any row beyond §5. `FILES BLOCKED` remains an upper bound
  everywhere else, and §5 is the only place a ceiling was measured.
* It does not rank the two backends. §4 is a count of files, not a quality
  claim: the x86-64 numbers are a floor (§1) and the 56-file difference is one
  ABI constant, not 56 findings.
* It does not claim the +1 arm64 pass is a fix. §1 says what moved and §2 says
  the row it moved onto.
* It does not price the 24-file field-store row or the 13-file declared-type
  row beyond their reproducers; both are unowned and both are enqueued in §7
  with that stated as the first thing to measure.

## 7. Enqueued

Two causes in §2 are unowned (`python3 tools/control.py claims` at the time of
writing), and both are enqueued with the measurement instruction attached:

* `formal2-receiver-field` — `construct:receiver-stored-in-a-field`, the
  24-file row, base `formal-batch3`. §3 and this map's §2.
* `formal2-declared-param` — `construct:declared-param-vs-call-sites`, the
  13-file row.

Both have `bugs/FORMAL_receiver_stored_in_a_field.md` with the reproducer and
the measured landing of each.