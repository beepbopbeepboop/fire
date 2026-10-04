# 749 `native_decide`/`bv_decide` sites put a GENERATED axiom in every theorem's closure, and §7's inventory had no row for it

**Status: the CLOSED-FACT half is DONE and MEASURED; the quantified half is
refuted, not deferred.  The figure this doc opened with — 749 — was wrong, and
wrong in the instrument rather than in the file: it is 751.**  What is left is
written down at the end.

Claim: `sweep20:admitted-audit` was the original. The 2026-10-04 work here is
`project22:native-decide`.

## What I ran

```
$ python3 -c "
import sys; sys.path.insert(0, '.')
from formal import admitted as A
for line in A.library_trust_lines(A.lean_dir('.')): print(line)"
Contracts: axiom_tactic=1 at 336
ProofLib: axiom_tactic=744 at 1198,1227,2223,2224,2225,2226,+738
X86: axiom_tactic=4 at 2336,2383,2385,2407
```

## What I saw

- **0** `axiom`/`opaque` declarations and **0** `sorry` in all five `lib/`
  modules — so FORMAL.md §7's "no Lean `axiom` and no `opaque` anywhere;
  everything is assumed in the `sorry` sense" is true of the SOURCE TEXT.
- **749** proof sites closed by `native_decide` (64 in `ProofLib`) or `bv_decide`
  (680 in `ProofLib`, plus 1 in `Contracts` and 4 in `X86`). Neither goes through
  the kernel. `OPUS.md` §1 already says this about a generated theorem ("plus the
  project's usual `native_decide`/`bv_decide` step-lemma axioms") — §7's
  inventory, which is the document whose whole job is "what a proof currently
  rests on", had no row.

## Why it is not a hole

Neither tactic can prove a **false** statement: it evaluates the goal's decision
procedure and answers `True` only when the evaluation says so. What they move is
where the trust sits — from the kernel to the generated C code and the C compiler —
and that is why a machine simulation with millions of steps finishes at all.
Every other `sorry` in this project is a hole over a claim somebody might have got
wrong; this is not.

## What the 2026-10-04 work did (this file's Status, kept current)

### 1. THE FIGURE WAS AN UNDER-COUNT, AND THE INSTRUMENT WAS THE REASON

`formal/admitted.py::lean_code_regions` blanked comments and string literals so
the census would count code and not prose. Lean 4 identifiers may contain `'`,
and `lib/ProofLib.lean` has `fieldTag_inj'`, `fieldTag_inj''` and about forty
more. The scanner read the first apostrophe as the opening of a `Char` literal,
blanked everything to the next apostrophe in the FILE — which lands in the middle
of an unrelated docstring — and from there was inside a string it had invented,
so it blanked REAL CODE.

Measured on `lib/` before the fix:

| | before | after |
|---|---|---|
| declaration headers starting at column 0 that the stripper blanked as prose | **74** (62 `ProofLib`, 11 `Refine`, 1 `Contracts`) | **0** |
| `axiom_tactic` sites in `lib/` | **749** | **751** |

Among the blanked ones: `private def stmtsSize` and the `end` that closes a
`mutual`, both of which the per-declaration census needs. And two sites were
simply not counted — `lib/ProofLib.lean:1579` and `:1582`.

`test_formal_admitted.py::check_the_stripper_sees_every_declaration` is the
assertion, and it was run against BOTH scanners: it reports 74 on the pre-fix
one and 0 on this one.

### 2. THE AXIOM IS NOT `Lean.ofReduceBool`

Step 1 of the original plan below predicted that `#print axioms` would report
`Lean.ofReduceBool`, and on the pinned toolchain (`leanprover/lean4:v4.32.2`) it
does not:

```
$ cat .tmp/probe4.lean <<'EOF'
import Lean
theorem t_native : ¬ ((0xd65f03c0 : UInt32) &&& 0xffe00000 = 0x2a00fa00) := by native_decide
#print axioms t_native
EOF
't_native' depends on axioms: [propext, Quot.sound,
  t_native._native.native_decide.ax_1_1]
```

`ofReduceBool` is DEPRECATED there — "in-kernel native reduction is deprecated;
assert native evaluations with axioms instead" — and each **use** elaborates to a
**fresh axiom named after the declaration that used it**. The trailing index is a
counter over reflection uses in the whole MODULE, so deleting one site's axiom
renumbers every later one in the file: `arm64_step_bl` went from
`…ax_1_6, …ax_1_11, …` to `…ax_1_5, …ax_1_10, …` when one site went away, and no
test may pin an index.

`Lean.ofReduceBool` is still exported and still deprecated, so a census that
matched it would read CLEAN over a library that reaches an axiom at every one of
its sites. `formal/lean.py::GENERATED_AXIOM_RE` is the shape that is actually
matched, and `formal/lean.py::AXIOM_FOUNDATION` (`propext`, `Quot.sound`,
`Classical.choice`) is the rest of what a Lean proof may rest on. FORMAL.md §7's
preamble asserted the wrong name twice and is corrected.

### 3. 63 OF THE SITES WERE CLOSED FACTS AND ARE NOW KERNEL-CHECKED

Every replaced site was a proposition over literals, so `decide` discharges it
and the KERNEL checks it:

| shape | sites | before | after |
|---|---|---|---|
| `¬ (0xd65f03c0 &&& 0xffe00000 = 0x2a00fa00)`-style, via `exact absurd … (by …)` | 54 | one generated axiom each | none |
| closed positive `have` over `UInt32` literals (`hM`, `hcmp`, `hand`) | 5 | one each | none |
| `(1 : UInt64).toNat = 1`, `(2 : UInt64).toNat = 2` | 2 | one each | none (`rfl` — no axiom at all) |
| `¬ ((fun n : UInt64 => n * 3) 7 = 7)` | 1 | one | none |
| `lowMask 8 = 0xFFFFFFFFFFFFFFFF` (8 `\|\|\|`/`<<<` on `UInt64`) | 1 | one | none |

61 in `ProofLib`, 1 in `Contracts`, 1 in `X86`. **Every statement is byte-for-byte
unchanged**; only the tactic inside the proof differs, and in most cases only
inside the `(by …)` that closes a closed goal.

`#print axioms`, before and after, through `formal/lean.py::print_axioms`:

| theorem | before | after |
|---|---|---|
| `work_step_mov` | `[propext, Quot.sound, work_step_mov._native.native_decide.ax_1_1]` | `[propext, Quot.sound]` |
| `arm64_step_add_reg` | `+ …ax_1_1, …ax_1_2` | `[propext, Quot.sound]` |
| `arm64_step_sub_reg` | 3 generated | `[propext, Quot.sound]` |
| `arm64_step_mul` | 5 generated | `[propext, Quot.sound]` |
| `arm64_step_cmp_sp_reads_sp` | 7 generated | `[propext, Quot.sound]` |
| `arm64_step_and_xzr_reads_zero` | 8 generated | `[propext, Quot.sound]` |
| `toNat_sub_one`, `toNat_sub_two` | 1 each | `[propext, Quot.sound]` |
| `arm64_step_bl` | 16 `bv_decide` + 1 `native_decide` | 15 `bv_decide` |
| `Contracts.spec_triple_ne_identity` | 1 generated | none |
| `X86.lowMask_eight` | 1 generated | none |

**Cost: none measurable, and measured A/B rather than asserted.** Both libraries
rebuilt from cold in a scratch directory with no cas to serve from, each module
through `formal/lean.py::run_lean` with `library_bounds()`'s 1800 s wall / 1800 s
CPU:

| | `ProofLib.lean` wall / CPU / peak | all five modules, wall / CPU | `ProofLib.olean` |
|---|---|---|---|
| `master` | 102.2 s / 76.1 s / 7.94 GB | 110.2 s / 89.3 s | 30.5 MB |
| this change | 98.7 s / 75.2 s / 7.87 GB | 106.3 s / 88.1 s | 30.4 MB |

So 63 replacements cost **−3.9 s** (inside the noise of a 100 s build) and 0.1 MB,
and the whole `#print axioms` census over all 600 askable declarations is **0.8 s**
in one Lean process. The reason is not luck: the replacement changes PROOF TERMS,
not the amount of Lean work, because `decide` on a 32-bit literal is a few
heartbeats of kernel reduction where `native_decide` was a C compile and a
`dlopen`.

### 4. WHAT REMOVED, AND WHY IT STAYS

Three `native_decide` in `namespace DylibExport`, named in
`test_formal_admitted.py::NATIVE_DECIDE_ALLOWED`:

- `DylibExport.Semantics_refutable` — `runExport` over the empty 0-byte image is
  `none`;
- `DylibExport.backward_branch_in_image` — `InImage` over a concrete export table;
- `DylibExport.backward_branch_run_none` — `runExport … 0 = none`, and
  `lib/ProofLib.lean:5587` already says why: `decide` would have to reduce
  `arm64_step`'s whole decode chain over a ground `Arm64State` in the kernel. It
  is correct and enormously slower than the compiled path, which is the reason
  the compiled path exists.

`NATIVE_DECIDE_ALLOWED` makes this a ratchet **by declaration**, which
`LIBRARY_TRUST` cannot be: that table is per MODULE, so 685 new `native_decide`
sites would have to appear before it noticed anything, and it cannot tell a
closed bit-pattern fact from a ground `runExport`. A `native_decide` added
anywhere else — including to one of the 43 theorems that used to carry several
and now carry none — now fails by name, and a row that stops describing a site
fails as a stale marker.

### 5. THE QUANTIFIED 685 ARE NOT A DEFERRED TASK; THEY ARE THE RIGHT TOOL

Step 3 of the original plan said to leave the `bv_decide` sites alone because
"`decide` is often out of its depth". That is true and it is not a matter of
degree:

```
$ grep -n "bv_decide" lib/ProofLib.lean | head -3
3979:  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
3981:  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
```

`w` is a FREE 32-bit variable, so the statement is `∀ w, w &&& mask ≠ value` and
`decide` would have to enumerate 2^32 cases. `bv_decide` bit-blasts it. The
useful way to say this is that these are **not the same claim as the 63**: 63 of
them were a lookup in a table that happened to be written as a tactic, and 685
are genuine universal bit-vector facts where a decision procedure is the honest
tool. `NATIVE_DECIDE_ALLOWED` and `SITES_NEEDING_NO_AXIOM` are the two tables
that say which is which, and they are the reason the number is a debt with a
shape rather than a debt with a backlog.

**One of the 688 produces no axiom at all**, which is worth knowing because it
means the site count is an UPPER bound: `X86.lean:2491` proves
`∀ w : UInt64, w &&& 0xFFFFFFFFFFFFFFFF = w` by `bv_decide`, and Lean discharges
it INSIDE THE KERNEL because the mask is all ones. Three identical `bv_decide`
proofs of that statement, asked directly, each report
`[propext, Classical.choice, Quot.sound]` and no `._native.bv_decide.…`.
`test_formal_axioms.py::SITES_NEEDING_NO_AXIOM` pins it.

### 6. THE ARITHMETIC NOW CLOSES, AND IT IS A TEST

`test_formal_axioms.py` asks `#print axioms` for all 600 askable declarations of
`lib/` in one Lean process and requires:

- every axiom is `AXIOM_FOUNDATION` or matches `GENERATED_AXIOM_RE` naming a
  declaration the text census attributes a site to;
- and **per declaration**, the number of axioms named after it equals its own
  site count less `SITES_NEEDING_NO_AXIOM`.

Result: **687 generated axioms for 688 counted sites**, every theorem's own count
equal to its sites. Three ways that measurement can lie bit during this work and
are checked rather than tolerated:

- `import A B C` is **not Lean** — it reads the first module and then finds the
  second where a command was expected, so four of the five modules were
  unimported and 230 of 513 declarations came back `Unknown constant`;
- a declaration whose name ends in `'` **cannot be spelled** in `#print axioms`,
  because the parser reads the apostrophe as a `Char` literal's opening (5 in
  `lib/`);
- and a `private` declaration's name is mangled (`lib/` has one, and it carries
  no site — checked, not assumed).

## Why it is not a hole

Neither tactic can prove a **false** statement: it evaluates the goal's decision
procedure and answers `True` only when the evaluation says so. What they move is
where the trust sits — from the kernel to the generated C code and the C compiler —
and that is why a machine simulation with millions of steps finishes at all.
Every other `sorry` in this project is a hole over a claim somebody might have got
wrong; this is not.

## What this is not

Not a soundness bug, not a false theorem, and not a reason to distrust a green
proof about machine semantics — the semantic-model layer is proved, and the
`native_decide` sites were its arithmetic. It was an inventory gap in the document
whose purpose is to have none, and then a measurement gap under it.