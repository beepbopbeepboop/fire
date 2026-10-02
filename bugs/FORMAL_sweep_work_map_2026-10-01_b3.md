# FORMAL_sweep_work_map_2026-10-01_b3: the b3 tree swept on BOTH architectures, and the first same-tree arm64-vs-x86-64 comparison

**Status: measured, and continued. Both arms are COMPLETED 630-file runs on ONE
tree (`e695183a`, `formal-batch3`), so §4 is a real architecture comparison for
the first time — the previous map (§6 of `FORMAL_sweep_work_map_2026-10-01.md`)
compared two different trees and could only compare the instrument. The
instrument was fixed in the same branch (`fbaed39b`) and §3 is what it found.

§8–§14 are the r2 continuation: a second pair of runs on the same tree, the
instrument's SECOND split of what §3 left as a bucket (`other refusal` 50 → 4 on
arm64 and 104 → 4 on x86-64), the 20-file Optional row's ceiling measured at 0
rather than guessed, the 4-file residue listed by hand, two more workers
enqueued, and a real bug the regression floor turned up — the cross-image frame
contract is not published for a free function, which was 4 of the floor's 5
failures and was filed as
`FORMAL_cross_image_frame_contract_is_not_published_for_a_free_function.md` —
**since fixed, and that filing is deleted** (see §14; the contract is published
for every export now). Two numbers in §2 were corrected there (§2's footnote).**

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
| 22 † | 22 | receiver stored in a field of a struct that outlives it | **unowned.** `formal/build.py:4735`. Reproducer: `bugs/FORMAL_receiver_stored_in_a_field.md` |
| 13 | 13 | a parameter's declared type contradicts every call site | **unowned.** `formal/model.py:7110` (`frame_declared_parameter_refusal`). Reproducer: same doc |
| 9 | 9 | value with no representation on this path | one construct, all in-file |
| 8 | 8 | frame address passed where a value is wanted | `FORMAL_wide_receiver_by_reference.md` |
| 5 | 5 | a module-global name has no storage | `FORMAL_module_state_no_storage.md` |
| 6 † | 6 | a module-level name of ANOTHER module is not exported as a word | all six are `sys`; `FORMAL_module_state_no_storage.md`; enqueued in §12 |

The same table on x86-64, in 10 causes of 25, is the arm64 one with `re.mojo`
added (51 files, §4) and `a module-global name has no storage` absent.

† **Two numbers in this table are corrected by the r2 run** (§8): the
field-store row is **22**, not the 24 printed here, and the `sys` row is **6**,
not 5. The r2 run of the SAME tree moved one file out of the `tool` class on
each architecture, which is where the difference comes from; §8 has the
before/after per class.

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
count** — hand-counted by `set`-diffing the two logs, because the cause table
could not see it (§9 says why; the tool now reports **57**, the extra one being
`formal/macho.py`'s own `_build_segment_64`, which the hand count missed).
Measured, on the same tree, same sweep, same tool:

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
---

# 8. The r2 continuation: the same tree, swept again, and what moved

The r2 run is a REPEAT of §1 on the same tree (`e695183a`, `formal-batch3`) plus
this branch's three commits, which touch no `formal/` file: two
`tools/formal_sweep_causes.py` marker sets and one `test_refusal_taxonomy.py`.
So the pass counts below are a re-measurement, not a result, and where they
differ from §1 the difference is the sweep's own `tool` class moving, not the
backend.

```
python3 tools/memslot.py --gb 16 --label sweep -- python3 tools/formal_sweep.py -j6 \
        > .tmp/sweep-arm-b3-r2.txt
python3 tools/memslot.py --gb 16 --label sweep -- python3 tools/formal_sweep.py -j6 --arch x86_64 \
        > .tmp/sweep-x86-b3-r2.txt
```

Every number in §8–§11 is re-derivable from those two logs:

```
python3 tools/formal_sweep_causes.py --min 4 .tmp/sweep-arm-b3-r2.txt
python3 tools/formal_sweep_causes.py --min 4 .tmp/sweep-x86-b3-r2.txt
python3 test_refusal_taxonomy.py
```

(the two logs are in `.tmp/`, which is git-ignored, so a reader who wants to
re-run the table needs a sweep first — 630 files at `-j6` is about nine minutes a
side and under 1 GB)

| | §1 (first run) | r2 | was (2026-10-01, other trees) |
|---|---|---|---|
| arm64 | 114/417 = 27.3 % | **114/418 = 27.3 %** | 113/418 |
| x86-64 | 106/458 = 23.1 % | **106/459 = 23.1 %** | 106/459 |
| arm64 `tool` | 4 | **2** (2 files got no verdict at `-t 30`) | 3 |
| x86-64 `tool` | 10 | **9** (9 files got no verdict) | 2 |

**The headline numbers are unchanged and the denominators moved by one**, in the
direction §1's `tool` row predicted: a file that times out at `-t 30` is in no
rate, and which files time out varies with what the CAS already holds. r2 was a
WARM CAS (616 hits / 14 misses on arm64, 618/12 on x86-64, against §1's cold
2/628), so r2 is the faster and slightly luckier of the two runs and §1's cold
numbers are the ones to quote for a ceiling.

**Change since 113 / 106: arm64 +1, x86-64 +0**, and per §1 neither is the six
new `test_formal_*` files. The r2 sweep's own verdict history is the honest
witness: `tool -> codegen: 1`, `tool -> not-answerable/host-import: 1`,
`unchanged: 628` on arm64, and `tool -> codegen/dependency: 1`, `unchanged: 629`
on x86-64. **Not one file changed class for a reason in this tree**, because
this tree changed no `formal/` file. The +1 over the 113 baseline is the
batch-1 work; the ±1 between §1 and r2 is the timeout class.

# 9. The instrument's second split: `other refusal` 50 → 4 and 104 → 4

§3 took `other refusal` from 183 to 50 (arm64). §3 also said, of the 50: "a
bucket, not a cause … 26 in-file" and the previous map said of its own 59
in-file ones that they "need splitting before they can be worked". That is this
section: fifteen rows the table could not see, every one of them a marker that
was MISSING rather than one that had gone stale — the same disease as §3, one
layer down. `other refusal` is now **4 files on each architecture**, and §11
lists those 4.

| files | arm64 in-file | the shape that was invisible |
|---|---|---|
| **20** | 0 | `builtin_slice.mojo`'s `self.step.or_else()` — one Optional unwrap, 20 files, and `uses:` reads 0 of 20 name anything it declares. §10 measures its ceiling |
| **5** | 5 | a field the struct does not declare — which is TWO constructs, 3 of them source bugs (§12) |
| 3 | 3 | the slot would have to hold a frame address, and no type says so |
| 3 | 3 | a slot holding a frame address, rebound by a later assignment (two wordings, two walkers) |
| 3 | 1 | a NUMBER compared with a string (`strcmp` would dereference it) |
| 3 | 3 | a module-global container with storage and no initializer |
| 2 | 2 | `field(default_factory=F)`: nowhere to keep a per-instance value |
| 2 | 2 | a constructor body that reads `self` is not inlined |
| 2 | 0 | a module whose API is its top-level statements, imported by another |
| 1 | 1 | a local read before its first assignment (has its own doc) |
| 1 | 1 | a class-level default that is not a value this build can materialize |
| 1 | 1 | a String method that returns a SHORTER string (has its own doc) |

and on **x86-64 only**, which is the point of running both arches through one
table:

| files | the shape | why it is worth a row |
|---|---|---|
| **57** | too many parameters for the register ABI | §4 counted this by hand, 56. Both backends build the sentence from the same f-string with their own constant interpolated (`_ABI_ARG_REGS` = 8, `len(ARG_REGS)` = 6), so a marker on `exceeds the 8` matched arm64 and nothing on x86-64. The row is now keyed on the ABI NAME, so changing either constant cannot silently blind it |
| 1 | `unsupported unary operator` on the x86-64 path | `std/builtin/swap.mojo` **BUILDS on arm64** and is refused here |
| 1 | `unsupported call target` on the x86-64 path | `std/math/polynomial.mojo`, refused on BOTH arches for the same `comptime` line under two different names |

The last two are the arch drift `bugs/FORMAL_known_limits.md` §6.5 has measured
("two files whose message differs between architectures on an otherwise
class-identical sweep") and that the table could not show. **That is now the
second thing this instrument has found that a hand-read of two logs had to find
first**, and it is the argument for keeping §4's same-tree comparison as a
routine step rather than a one-off.

**ONE ROW DIED AS A CONSEQUENCE**, and it is the rot the sibling test exists to
catch: `a slot's declared type is not declared by its struct` measured **0 files
on both architectures**. Its site reworded the tail of its message, both its
markers were in that tail, and nothing failed anywhere. The sentence the two
wordings SHARE now keys the row that supersedes it; the old wording is kept as a
sample in `test_refusal_taxonomy.py` so a second reword cannot pass silently,
and the dead row stays in the table with its 0 stated rather than being deleted —
a table that forgets an old wording reads an old log as unclassified.

# 10. The Optional row's marginal effect, measured before anyone invests

§5 measured the 93-file bracket row's ceiling at 0 and said the standing
instruction applies everywhere else too. The 20-file Optional row is the
second-largest unclassified row and it is a value-model change, so it is worth
the same five minutes.

With the refusal lifted behind a temporary guard
(`formal/model.py`'s `_shape_guarded_refusal`, `if method in UNWRAP_METHODS:` →
`if False and …`), the same 20 files:

```
$ python3 tools/memslot.py --gb 8 --label sweep -- python3 tools/formal_sweep.py \
      --no-stdlib -j6 -t 60 <the 20 files>
codegen coverage: 0/20 = 0.0%

$ python3 tools/formal_sweep_causes.py --min 1 .tmp/unwrap20-after.txt
   20       0  method call on a value receiver is not one of the lowered methods
        refused in: builtin_slice.mojo x20
        uses:        0 of 20 blocked by builtin_slice.mojo name anything it declares (slice)
```

**0 of 20 reach `pass`, and all 20 land on the generic
`lowers only append, close, write` refusal** — i.e. the same `or_else()` call
falling through to the last-resort message. So the Optional refusal is not
sitting in front of a lowering; the call has none, and the refusal that follows
is strictly WORSE (it names a set of methods instead of the real reason). That
is the answer a planner needs and it is the opposite of the usual outcome:

* **`self.step.or_else()` is worth 0 files on its own**, like the 93-file row,
  and for the same underlying reason — `uses:` reads 0, so the 20 files are
  blocked by an import closure rather than by the construct.
* **The value-model change is still real** (`formal/model.py:5879`'s comment
  says what it is: Optional needs a niche, a discriminant or a tag word) and it
  is owned: `formal2-re-and-slice` holds `builtin_slice.mojo`, and
  `bugs/FORMAL_struct_construction_shapes.md` records the landing of the same
  line when its refusal changed from a false reason to a true one.
* Read the two rows together, exactly as §5 says to: the bracket row and the
  Optional row are both `std/collections`/`std/builtin` boundary effects, and
  neither is worth anything until the module behind it exports something.

The guard was reverted; `formal/model.py` is unmodified in this branch.

# 11. The residue: 4 files, the same 4 on both architectures, one construct each

Left in the bucket on purpose, and listed here because a bucket a reader cannot
open is the thing this instrument exists to remove. All four are 1 file, in-file,
and identical on both architectures:

| file | the construct | site | doc |
|---|---|---|---|
| `std/io/io.mojo` | a method call handed ANOTHER struct's frame as its receiver — "a method is rewritten to take its OWN struct's frame, and passing a different struct's address has the callee read one object's fields out of another's storage" | `formal/build.py:2795` | — |
| `bootstrap_test_classes.mojo` | a frame address returned from the image's ENTRY, whose caller is the C runtime and passes no block address | `formal/model.py:13871` | — |
| `formal/arm64.py` | `len()` of an operand nothing types: "the source does not say what this operand holds", and `len` on this path tells a string from a blob by what the operand IS | `formal/arm64_codegen.py:2856` | — |
| `tools/autointegrate.py` | `!=` on a module-level name holding `None`: one untagged word cannot say whether the 0 arrived as a `None` or as the integer 0 | `formal/build.py:7077` | `FORMAL_none_is_not_a_literal.md` |

Two constructs here are worth a reader's attention beyond the count, because both
are the same failure wearing different clothes: `io.mojo`'s is a dispatch
question (methods are dispatched by NAME, so `recv.m(x)` carries no type) and
`formal/arm64.py`'s is a layout question (the two things `len()` can answer are
told apart by what the operand IS). Both are the one-word value model saying so,
and both are recorded in `FORMAL_known_limits.md` at the level of the limit
rather than of the file.

Four more rows would be four rows nobody reads. A list in a document someone
reads is the better trade, which is the whole argument of this section — and the
bar that produced it is the tool's own: a cause earns a row at 5 files, or with a
doc of its own, or as the sibling of a row above it (three of §9's one-file rows
are in the table for exactly those two reasons).

# 12. Enqueued, and one row that is two

## The 5-file field row is 2 files of work and 3 source bugs

`a field the struct does not declare (missing, or a comptime member)` — one
marker, one message, **two constructs**, and no marker can tell them apart
because the sentence is identical. Split per file by reading each name's
declaration in this tree:

| file | the construct | who |
|---|---|---|
| `std/iter/__init__.mojo` (`res._InjectedValues`) | correct Mojo: line 509 declares `comptime _InjectedValues = Tuple[*Self.Ts]` and line 538 reads it. `StructDef.comptime_aliases` is read by **no table on this path** | **enqueued** below; the measurement and the next step were in `FORMAL_comptime_class_attribute_read_through_a_receiver.md`, which is **fixed and deleted** — the field census now reaches an IMPORTED module's classes (`formal/imports.py`'s `_attach_declared_census`), so what is left in that arm is a member whose VALUE is not a literal |
| `std/python/numpy.mojo` (`shape.is_flat`) | same construct: `std/utils/coord.mojo:220` declares `comptime is_flat = …` | as above |
| `analyze_benchmarks_types.py`, `check_benchmarks_types.py`, `test_type_system_integration.py` (`gen.type_checker`, `gen._strict_type_checking`) | **not a backend gap.** `grep -rn 'self.type_checker\|self._strict_type_checking' --include='*.py'` over the whole tree returns nothing, so CPython raises `AttributeError` at that line deterministically | source bugs; named here so nobody spends the row's budget on them |

The message's own clause — "In Python this is an AttributeError at run time, so
the program is very likely already raising here" — is **false for 2 of the 5**,
which is why the row's label claims neither. This is the same lesson
`FORMAL_subscripted_method_callee_and_three_level_nested_frames.md` records for
an earlier row ("row 12's four files are two unrelated gaps"), and the first time
it has been worth correcting the table's own LABEL for.

## Enqueued

`python3 tools/control.py enqueue … --base formal-batch3`, each with the
measurement instruction attached:

* `formal2-receiver-field` — `construct:receiver-stored-in-a-field`, the 22-file
  row (§2, §7 of the first run).
* `formal2-declared-param` — `construct:declared-param-vs-call-sites`, the
  13-file row.
* **`formal2-comptime-alias`** — `construct:comptime-class-member-through-a-
  receiver`, the 2 real files of the 5-file field row above.
* **`formal2-sys-word`** — `construct:module-name-as-a-value`, the 6-file `sys`
  row (§2), which is `import sys` then `sys.argv` — using an imported MODULE
  NAME as a value. `FORMAL_module_state_no_storage.md` §(2)/(4) is the design
  and says what is still open.

## Owned rows, restated against the current claims

| row | claim that holds it |
|---|---|
| 93, `debug_assert[…]` | `formal2-assert-imports` |
| 57, register ABI (x86-64) | `formal2-x86-parity` (`FORMAL_x86_64_hostmods_that_do_not_build.md` §Failure 2) |
| 28, callee has no definition | first-layer, integrated; `FORMAL_callee_no_def_ceiling_zero.md` |
| 24, MLIR dialect | `formal2-mlir-comptime` + `formal-mlir-gpu` |
| 24, receiver at argument position 0 | `formal-receiver-novalue` |
| 20, Optional unwrap | `formal2-re-and-slice`; ceiling measured at 0 in §10 |
| 22 + 13 | enqueued above |
| 1, swap.mojo / polynomial.mojo arch drift | `FORMAL_known_limits.md` §6.5; x86-64-side work of a sitting each |

# 13. What the regression floor says, and it is not about the sweep

The floor this task must run before finishing, on this tree:

```
python3 test_formal_run.py   → PASS=484 FAIL=5        (4 of the 5: §14)
python3 test_formal_imports.py → PASS=41 EXPECTED=0 FAIL=0
python3 -m unittest test_formal_sweep_truth → Ran 31 tests, OK
python3 test_formal_link_accounting.py → 170 passed, 0 failed
python3 test_refusal_taxonomy.py → PASS (154/154 checks, 52 causes)
python3 test_formal_sweep.py → Ran 75 tests, OK
```

## 14. One bug found by running the floor: the cross-image frame contract is not published for a free function

**Filed here as
`bugs/FORMAL_cross_image_frame_contract_is_not_published_for_a_free_function.md`,
since fixed and since deleted — `_export_frame_contract` publishes a contract
for every export, and `test_formal_cross_module.py` pins it.** Four of the
floor's five failures were ONE construct, and it is a
first-layer fix's own positive cases rather than a stale expectation: the three
cross-module **method** cases pass with the right answers (36, 68, 70) and the
three **free-function** cases do not. `formal/build.py:2646`'s publication loop
opens with `if not hs: continue` and skips `fn._frame_param_contract =
…` at `:2990`, and `hs` is a CALL-SITE fixpoint — so a free function in a dylib
module, whose every call is in the importer, publishes no contract at all. The
manifest shows `take_it` listed with `frame_params: []`, and the refusal then
reports it as `not-exported`, which points at the wrong layer.

Two consequences a reader of this map should carry:

* **`FILES BLOCKED` is not the only upper bound in this document; the floor is
  not green.** `formal-run` is in the registry's `proofs` bucket — in neither
  `check` nor `gate` — so this is not gate-red, but a green gate does not cover
  the cross-module frame hand-off either.
* **§1's and §8's coverage numbers are unaffected by it**: this construct never
  lowered, so no file's class in either sweep depends on it.
