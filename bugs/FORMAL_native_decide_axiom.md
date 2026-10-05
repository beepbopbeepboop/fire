# The axiom is NOT `Lean.ofReduceBool`, and **67** of `lib/`'s **520** theorems is what the sites are

The `native_decide`/`bv_decide` sites put a GENERATED axiom in a theorem's
closure — one per USE, named after the declaration that used it — and §7's
inventory had no row for them at all.

**Status 2026-10-04 (`work/formal29-3`): items 3 and 4 are DONE, and the CENSUS
that item 2 produced was reporting the wrong thing — both of its halves.** The
four cheap sites `§5` left in `X86` are gone (they are `decide`-discharged
closed facts, and removing them freed a FIFTH theorem's closure through
`x86_mask_eight`), every ceiling moved with the measurement, and
`test_formal_admitted.py` — **RED on master** while this was worked on, on four
rows, all of them drift this doc's subject explains — is green. Read this before
§"The measurement, which is the point", whose table is measured on an instrument
that has since been fixed, and before `AXIOM_CLOSURE`, whose figures were all
wrong.

### What landed, and what it is worth in this document's units

**1. Four `native_decide` sites in `lib/X86.lean` are `decide` now** —
`@[simp] theorem x86_mask_{one,two,four,eight}` on four lines side by side at
`:503..506`, which is where the red came from: they landed after the ceilings
were written and `LIBRARY_TRUST`'s `X86` row (3) had not moved with them, so the
file reported 7 against a ceiling of 3. They are CLOSED facts —
`x86_mask n` is `if n ≥ 8 then 0xffff… else UInt64.ofNat (2^(8n) - 1)` and every
argument is a literal — so `decide` discharges them and **the KERNEL checks the
answer**. Measured standalone through `formal/lean.py::run_lean` (0.3 s,
168 MB): all four elaborate, and `#print axioms` answers *"does not depend on
any axioms"* for each — not even `propext`/`Quot.sound`.

**Worth FIVE theorems and four sites**, and the fifth is the argument for
measuring the closure at all: `X86.x86_step_movsx_r64_r8` names no decide tactic
of its own and reached `x86_mask_eight._native.native_decide.ax_1_N` **through**
it, so it is kernel-checked now. `X86` goes 6 theorems reaching → 2.

| | before | after |
|---|---|---|
| `lib/X86.lean` sites | 7 | **3** (all `bv_decide`, all `∀ w, …`) |
| `lib/` sites, whole tree | 711 | **707** |
| theorems reaching a decide axiom (of 520 asked) | 71 | **67** |
| `REPLACEABLE_THEOREMS`, item 3's work list | 8 named, 22 live | **0** |

### 2. The census was wrong in BOTH halves, and a false `clean` is the one thing
### a trust census may not produce

**`AXIOM_SITE_RE`'s declaration group was `[^.]+`.** It cannot match a DOTTED
name at all — so every namespaced declaration's axiom read as "not one of ours",
and `axiom_census_summary` reads the classifier's answer as "this closure has no
site", which turned a false `None` into a false `clean`. `formal/lean.py`'s
`GENERATED_AXIOM_RE` is the only other place this shape is matched, it uses a
greedy `.+`, and its comment already says why: *"a lazy `.+` would hand
`DylibExport` to `decl` and fail to match at all."* Two copies of one pattern
with different greediness is how a §7 figure comes to be 53 when the answer is
67.

| module | `reaches` with `[^.]+` | `reaches` with `.+` | what the difference was |
|---|---:|---:|---|
| `IEEE754` | **0** (`text_only` **19**) | **19** (`text_only` 0) | every one of its declarations is namespaced |
| `ProofLib` | 43 | **46** | `DylibExport.*` and `Frame.*` |

**`library_theorems` could not see an ATTRIBUTED declaration.** It carried its
own `heads`/`opens`/`closes` triple rather than projecting `_declarations`, and
its head pattern had no `@[...]` prefix — so **98** attributed declarations
(`ProofLib` 31, `X86` 66, `work` 1) were never asked about at all, and each was
filed as `clean`: a clean row for a proof nobody asked Lean about. Four of the
X86 ones are `@[simp] theorem x86_mask_*`, on four lines side by side. Sharing
the walk fixes it, and `test_formal_admitted.py` now asserts the agreement in
the direction that was missing — every attributed THEOREM visible to the census,
plus the four named, because a count moves when the corpus grows and a name is
what a reader goes and looks at.

**A corollary worth keeping: the instrument's own bug was being counted as a
finding.** §"The measurement" below praises "`text_only` … a place where a
replacement would have changed nothing", and 22 of its rows were `IEEE754`'s and
`ProofLib`'s namespaced declarations landing in the wrong bucket. With the group
greedy, **`text_only` is 0 across all of `lib/`** — the SITE census is *exact* at
theorem granularity, which is a stronger statement than "both directions are
non-empty", and `test_formal_sweep_truth.py` now pins that direction at 0 with
the bug's own numbers in the message.

### 3. Every ceiling moved with the measurement, and `FORMAL.md` §7 row 10 is a
### LEDGER

`test_formal_admitted.py` was **red on master** on four rows before this change
(`the Lean library's trust counts are pinned`, `native_decide is only where
decide cannot go`, `the replaced native_decide count is what it claims`, `the
census is attributed to theorems, not only to lines`) — 711 sites against a
published 688, 40 one-site theorems against a ceiling of 19, and four
`native_decide` in `X86` that `NATIVE_DECIDE_ALLOWED` does not name. All four
are now green, and `AXIOM_CLOSURE` is re-measured over **six** modules:

| | asked | reaches | clean | text_only | closure_only | `ofReduceBool` |
|---|---:|---:|---:|---:|---:|---:|
| `Contracts` | 7 | 0 | 7 | 0 | 0 | 0 |
| `IEEE754` | 24 | 19 | 5 | 0 | 0 | 0 |
| `ProofLib` | 297 | 46 | 243 | 0 | 8 | 0 |
| `Refine` | 29 | 0 | 29 | 0 | 0 | 0 |
| `X86` | 144 | 2 | 141 | 0 | 1 | 0 |
| `work` | 19 | 0 | 17 | 0 | 2 | 0 |
| **total** | **520** | **67** | **442** | **0** | **11** | **0** |

(5.7 s and 1.1 GB for the whole thing, through `formal/lean.py::run_lean`.) One
declaration is unanswered and by design: `ProofLib.ifUpdate_congr`, the
`private theorem` at `lib/ProofLib.lean:7364`, whose name Lean mangles — so
`theorem_axiom_census` now asks only about the `public` rows and REPORTS the
rest rather than dropping them, and `test_formal_admitted.py` checks that no
unaskable declaration carries a site (this one does not).

**`ONE_SITE_THEOREMS` 19 → 36, and the rise is not new work**: 19 of the new ones
are `IEEE754`'s, which arrived with the file. **`REPLACEABLE_THEOREMS` 8 → 0**,
and that needed the LIST's definition rather than only its number: it now
excludes the declarations `NATIVE_DECIDE_ALLOWED` already justifies by name (the
19 `IEEE754` arithmetic theorems and `ProofLib`'s three `DylibExport` ones),
because a row that table answers is not on a work list. Without the exclusion
the list reported 22 items of which 22 were justified, and the next reader would
have had to re-derive that.

**Row 10's figures are now total 774 / replaced 67 / remaining 707, and the
TOTAL IS A LEDGER**: 751 when the pay-down started, 63 replaced, and **23 that
arrived afterwards** (19 with `lib/IEEE754.lean`, 4 in `lib/X86.lean`). The test
enforces `total - remaining == replaced`, which is why the total has to carry the
arrivals — a row that can only fall absorbs new debt silently, and the 4 `X86`
sites are exactly that case. `NATIVE_DECIDE_REPLACED`'s `X86` row says which
four and why they were worth five theorems.

### What is still open, unchanged

* **The 685 `bv_decide`** — `∀ w, w &&& mask ≠ value` over a free 32-bit word.
  §5's argument is a MEASUREMENT and it stands: `decide` would enumerate 2^32.
* **The 19 `IEEE754` `native_decide`** — ground binary64 facts over
  `Float.ofBits`/`toBits`, which are compiled primitives, so `decide` gets stuck
  at `UInt64.decEq`. The alternative is a bit-level IEEE implementation, which is
  a second implementation of arithmetic both machines already perform. Named one
  by one in `NATIVE_DECIDE_ALLOWED`.
* **`test_formal_axioms.py`'s own per-declaration arithmetic** is untouched and
  green: 695 declarations asked, 706 generated axioms for 707 counted sites, the
  difference being `SITES_NEEDING_NO_AXIOM`'s one row.

**Status: the CLOSED-FACT half is DONE and MEASURED, the closure census is
DONE and it corrected the name, and the quantified half is refuted rather than
deferred.** The figure this doc opened with — 749 `native_decide`/`bv_decide`
sites reaching `Lean.ofReduceBool` — was wrong twice over: the sites were 751
(wrong in the instrument rather than in the file) and the axiom was never
`Lean.ofReduceBool` at all.  63 of the sites were CLOSED propositions and are
now `decide`/`rfl` proofs the KERNEL checks; what is left is the replacement
plan, which is a debt being paid down rather than a patch.

**Status: the census part is DONE.** The audit of 2026-10-04
(`bugs/FORMAL_trust_audit_2026-10-04.md` §`lib/*.lean`) counted the sites and put
them in FORMAL.md §7's trust inventory as row 10. What is left is the measurement
this worker could not make: which theorems actually reach the axiom, and the plan
to shrink the number.

**Status 2026-10-04 (`work/formal21-5`): item 2 is DONE, and item 1 is DONE for
the half a text census can decide — the 749 sites are now attributed to the 56
THEOREMS that carry them, out of 493 declarations, and the per-tactic split says
which of them have a kernel-checked spelling standing next to them. What is left
is item 1's transitive half (`#print axioms`, a Lean run) and items 3–4, and
§"What landed" names the eight theorems item 3 should start from.** Read that
before "The exact next step", which is the plan as it was written.

**Status: the census part is DONE.** The audit of 2026-10-04
(`bugs/FORMAL_trust_audit_2026-10-04.md` §`lib/*.lean`) counted the sites and put
them in FORMAL.md §7's trust inventory as row 10. What was left is the
measurement this worker could not make: which theorems actually reach the axiom,
and the plan to shrink the number.

Claim: `sweep20:admitted-audit` was the original. The 2026-10-04 work here is
`project22:native-decide`.

## What changed, and what it corrects

Two sentences this file and FORMAL.md §7 both published were **false of the
toolchain**, and one of them was false of the tree:

1. **"the proof term reaches `Lean.ofReduceBool`" — wrong.** Lean 4.32.2's
   `native_decide` and `bv_decide` each declare a FRESH axiom per USE, named
   after the declaration and the tactic — `t32s_t8s._native.bv_decide.ax_1_5`,
   `work_step_ldr_uoff._native.bv_decide.ax_1_101`. A `#print axioms` census over
   **all 375 theorems in `lib/` reports `Lean.ofReduceBool` for NONE of them.**
   So the instruction this file gave — "`Lean.ofReduceBool` appearing is the
   confirmation" — could not have succeeded, and a reader who grepped a proof's
   axiom list for it would have found nothing and concluded the proof was
   kernel-checked. That is how a wrong name becomes a wrong conclusion, and it is
   the same version-drift shape `FORMAL_trust_audit_2026-10-04.md` records about
   `subprocess.check_call`: the obvious answer is the one that is wrong.
2. **"749 sites" — an UNDERCOUNT wearing a total's clothes.**
   `formal/admitted.py::lean_code_regions` read a `'` IMMEDIATELY after an
   identifier character as the opening quote of a character literal. It is a
   prime. Two measured casualties:
   * the apostrophe in `clang's` at `lib/ProofLib.lean:1392` opened a phantom
     literal and blanked **187 lines of real code**, `lib/ProofLib.lean:
     1392..1578`, including the `bv_decide` in `t32s_t8s` (`:1579`) and the one
     in `t32s_t16s` (`:1582`). `ProofLib`'s site count was **744** and is
     **746**; over five modules 749 becomes **751**.
   * five declarations in `lib/` have names ending in `'` —
     `ProofLib.mem_read_two_writes_adjacent'`, `mem_read_after_write_u64_slot'`,
     `u64_toNat_sub_one'`, `MF.fieldTag_inj'`, `work.s64_to_u64_toNat'` — and
     each was blanked from its name to its next quote, so none was visible to any
     per-theorem census. Lean answers `#print axioms u64_toNat_sub_one'` with
     `[propext, Quot.sound]`, so the declarations are real and the scanner was
     wrong about them.

## The measurement, which is the point

**SUPERSEDED — every number in this section was measured on an instrument that
was wrong in both halves, and the corrected table is in the Status at the top of
this file.** Read that first; this section is kept because the reasoning that
produced the instrument is what a next session needs, and because a corrected
figure with no record of the wrong one teaches nobody that the census can be
wrong at all.

`formal/admitted.py::theorem_axiom_census` — one `#print axioms` line per
theorem, ONE Lean run per module, all of `lib/` in **4-5 s** through
`formal/lean.py::run_lean` under the library bounds. **375 of 375 answered** (of
the five modules it knew about; `lib/IEEE754.lean` had arrived and was not
counted), and the four columns partition each module:

| module | theorems asked | reach a decide axiom | kernel-checked | text_only | closure_only | `ofReduceBool` |
|---|---:|---:|---:|---:|---:|---:|
| `Contracts` | 7 | 0 | 6 | 1 | 0 | 0 |
| `ProofLib` | 255 | 51 | 192 | 3 | 9 | 0 |
| `Refine` | 22 | 0 | 20 | 0 | 2 | 0 |
| `X86` | 73 | 2 | 69 | 1 | 1 | 0 |
| `work` | 18 | 0 | 17 | 0 | 1 | 0 |
| **total** | **375** | **53** | **304** | **5** | **13** | **0** |

`text_only` is the site's own text naming a decide tactic with no such axiom in
its closure — **a losing tactic alternative is still text**, so the 751-site
census overcounts at theorem granularity, and each of these five rows is a place
where a replacement would have changed nothing:

    Contracts.spec_triple_ne_identity
    ProofLib.DylibExport.Semantics_refutable
    ProofLib.DylibExport.backward_branch_in_image
    ProofLib.DylibExport.backward_branch_run_none
    X86.x86_call_return_slot_separated

`closure_only` is the direction a text scan cannot see at all: no site in the
text and an axiom in the closure, because it is reached THROUGH another theorem.
**Thirteen**, and the clearest is the `arm64_cset_*` trio, which carry
`arm64_flag_eq._native.bv_decide.ax_1_7` through it and name no tactic of their
own:

    ProofLib.arm64_cset_eq / _le / _ne
    ProofLib.u64_sub_two_toNat_le, uint64_sub_one_toNat_of_succ,
              while_dec_exit_contract
    ProofLib.work_step_ldr_pre, work_step_ldr_post, work_step_str_off
    Refine.contract_sound, Refine.contract_sound_tree
    X86.x86_call_ret_round_trip
    work.work_cset_lt_zero_iff

Both directions being non-empty is the finding, and both are asserted as
findings: a census that only ever found one would be indistinguishable from a
text scan that happens to agree with itself.

## What is pinned, and where

* `formal/admitted.py`: `AXIOM_SITE_RE` / `axiom_site_tactic` (the classifier),
  `library_theorems` (the namespace-aware, prime-aware source half),
  `parse_print_axioms`, `theorem_axiom_census`, `axiom_census_summary`. Two
  parser limits are fixed and written down rather than left to be found: the
  `does not depend on any axioms` form (a regex written for the
  `depends on axioms: [...]` shape drops every such row, and the first measured
  run parsed 193 of ProofLib's 255 because of it), and the name being matched up
  to the SENTENCE rather than up to the next quote — Lean prints
  `'u64_toNat_sub_one'' depends on axioms: …`, a prime then the closing
  delimiter, so a `[^']+` name stops inside it and four primed theorems read as
  unanswered.
* `test_formal_admitted.py` (no Lean, every run): `LIBRARY_TRUST` with
  `ProofLib` at 746 and the reason the ceiling ROSE; the new
  `AXIOM_CLOSURE` table; `test_the_source_half_of_the_closure_census_is_readable`
  (namespaces resolved, the five primes named, every dotted name under a
  namespace its file opens); `test_the_axiom_names_are_classified_not_guessed`
  (measured text, both `#print axioms` shapes); and
  `test_every_native_axiom_in_lib_is_one_this_file_knows`, which asserts the
  classifier's own limit over the source so it cannot open silently.
* `test_formal_sweep_truth.py::TestAxiomClosureCensus` (runs Lean, skips without
  it, which is that file's stated rule): `AXIOM_CLOSURE` against a live census,
  `asked == answered` per module, the four columns partitioning, the
  `Lean.ofReduceBool` count asserted at 0, and the two disagreements non-empty.
  **103 tests in the file, all passing.**
* FORMAL.md §7's preamble and row 10 corrected, with the measurement beside the
  claim.

## What is left, and it is a debt not a patch

1. **Replace the cheap sites.** The `native_decide` sites on closed
   `UInt64`/`Nat` arithmetic (`have h1 : (1 : UInt64).toNat = 1 := by
   native_decide`) are `decide` or `rfl`, and `AXIOM_CLOSURE` says which
   theorems would actually be freed: only the 53 in `reaches`, and only the ones
   whose ONLY axiom is their own. Start with `X86`'s two, which is the whole of
   that module's contribution.
2. **`closure_only` is where the leverage is not.** Thirteen theorems carry an
   axiom they never wrote, so replacing the site in `arm64_flag_eq` frees
   `arm64_cset_eq`, `_le` and `_ne` together — and a text census cannot see that
   saving, which is the argument for the closure census existing.
3. **Keep the ceiling honest.** `LIBRARY_TRUST` is a ceiling and it just went UP
   by 2 because the instrument got better. Lower it with the change and say which
   sites went; a number that only ever rises because the scanner improved is not
   a ratchet.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label axcensus -- python3 - <<'PY'
import sys; sys.path.insert(0, ".")
import formal.admitted as A, formal.lean as L
lib = A.lean_dir(".")
s = A.axiom_census_summary(A.theorem_axiom_census(L.find_lean("."), lib), lib)
for mod, v in sorted(s.items()):
    print(f"{mod:10s} asked={v['answered']:4d} reaches={len(v['reaches']):3d} "
          f"clean={len(v['clean']):4d} text_only={len(v['text_only'])} "
          f"closure_only={len(v['closure_only'])} "
          f"ofReduceBool={len(v['of_reduce_bool'])}")
PY
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_admitted.py
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
```

So the fix is not to remove them. It is to (a) count them, which is now done and
pinned, and (b) shrink them where the kernel can afford it.

## What landed: the sites, attributed to theorems

`formal/admitted.py::declaration_tally` is item 2 of "The exact next
step" — the other direction from `library_trust`, which reports lines. It walks
each `lib/*.lean` again and asks **which declaration each site is inside**, which
is the question that makes the number actionable: a file-level ceiling says "749
in `ProofLib`" and a per-theorem one says "59 of them are in `work_step_movk`".

    $ python3 -c "
    import sys; sys.path.insert(0, '.')
    from formal import admitted as A
    for l in A.library_trust_by_declaration_lines(A.lean_dir('.'), top=4): print(l)"
    Contracts: 1 declaration(s) with a hit; spec_triple_ne_identity@332 [axiom_tactic=1 (native_decide=1)]
    ProofLib: 52 declaration(s) with a hit; work_step_movk@4518 [axiom_tactic=59 (native_decide=2,bv_decide=57)]; …
    X86: 3 declaration(s) with a hit; mem_read_bytes_write_same@2452 [axiom_tactic=2 (bv_decide=2)]; …

**What it measures, on this tree:**

| | |
|---|---|
| sites, unchanged | **749** (66 `native_decide`, 683 `bv_decide`) |
| declarations in `lib/` | **493** (`ProofLib` 286, `X86` 174, `Refine` 25, `work` 20, `Contracts` 8) |
| declarations carrying at least one site | **56** — 11 % of them, carrying 100 % of the sites |
| sites in no declaration | **0** — no top-level tactic script, no head `_LEAN_DECL_RE` misses |
| median theorem that carries any | **8 sites**; the largest is `work_step_movk` at 59 |
| theorems with exactly one site | **19** — 2.5 % of the sites, 34 % of the theorems |
| …of those, the single site is a `native_decide` | **8** — and those are item 3's list |

The distribution is the finding rather than the total: **56 theorems hold the
whole census and 223 of the 749 sites (30 %) are in five of them**
(`work_step_movk` 59, `work_step_movz` 53, `work_step_svc` 38, `work_step_br` 37,
`work_step_orn` 36) — which are the `∀ w, … ≠ …` bit-pattern lemmas `bv_decide`
exists for. **Item 3's advice to replace the cheap sites first is right and its
scope is now exact**, because the per-tactic split separates the two populations
that look identical in a count of 749:

* **19 theorems with one site**, of which **ten are the `arm64_flag_*` family**
  (`_eq`, `_ne`, `_ge`, `_gt`, `_le`, `_lt` and their `_s` signed forms), and
  every one of those is `simp only [arm64_matches_condition, arm64_subs_flags];
  bv_decide` — a bit-pattern fact with no kernel-checked spelling short of
  writing the arithmetic out. **These are the ones to leave**, which is what the
  original item 3 said about the `bv_decide` population and now has names.
* **8 theorems with one site that is a `native_decide`**, and these are the
  shortlist: `Semantics_refutable`, `backward_branch_in_image`,
  `backward_branch_run_none`, `work_step_mov`, `toNat_sub_one`, `toNat_sub_two`
  (`ProofLib`), `lowMask_eight` (`X86`), `spec_triple_ne_identity`
  (`Contracts`). `toNat_sub_one` is the shape the original item 3 described —
  `have hpos : 1 ≤ n.toNat := …; omega` with a `rw` and a `calc` around it —
  where the arithmetic is closed and `decide`/`norm_num`/`omega` plausibly
  reaches it. **Nobody has run Lean on any of the eight**, so "plausibly" is the
  honest word: that is item 1's transitive measurement and it is the next step.

**Two invariants the attribution is pinned on**, both in
`test_formal_admitted.py`'s new PURE check
(`test_the_census_is_attributed_to_theorems_not_only_to_lines`, 20/20 with it):

* the per-declaration counts **SUM** to the file-level count, per module and per
  kind, so an attribution that loses a site reports a smaller plausible number
  and one that invents one reports a bigger — neither is visible without it.
  Measured as a pin: an attribution that dropped every site after line 5000
  reports `675 attributed against 744` and fails;
* the per-tactic split **sums** to each theorem's site count, which is what says
  the split (`native_decide` vs `bv_decide`) did not drift from the total;
* no site is in no theorem, and the two ceilings — 19 one-site theorems and 8
  of them `native_decide`-only — are ceilings rather than equalities, so a
  replacement lowers them and a regression raises them.

**What this does NOT establish**, and it is the half that needs Lean: a theorem
with no site of its own can still reach `Lean.ofReduceBool` through a CALLEE it
uses. So 56 is an upper bound on the theorems that reach the axiom and a *lower*
bound on the count of sites, not a measurement of the closure. That is exactly
what `#print axioms` decides and what item 1 is for.

## What is still missing, and the exact next step

1. ~~**Attribute the 749 to theorems rather than to sites.**~~ **DONE** —
   `library_trust_by_declaration`, and the measurement is in "What landed"
   above: **56 theorems of 493, with 8 named as the replaceable shortlist.**
   This item is moved to the top of the list because item 3 is now decided by it
   rather than guessed at.

2. **Measure the closure, which the text census cannot.** The one measurement
   this worker did not run, because a light worker does not launch Lean:

   ```
   cat > .tmp/ax.lean <<'EOF'
   import ProofLib
   open ProofLib
   #print axioms toNat_sub_one
   #print axioms Semantics_refutable
   #print axioms work_step_movk
   #print axioms step_lemmas_sound
   #print axioms eval_eq_mojo
   #print axioms dylib_export_contract
   EOF
   python3 tools/memslot.py --gb 8 --label axiomcensus -- \
       lake env lean .tmp/ax.lean
   ```

   **Every Lean run goes through `formal/lean.py::run_lean`**, which is what
   enforces the wall and CPU bounds; `lake env lean` above is the shape of the
   command, not an instruction to launch `lean` directly. The names are no longer
   guesses: the first three are on the shortlist "What landed" names
   (`toNat_sub_one`, `Semantics_refutable`) and the biggest theorem
   (`work_step_movk`), and the last three are the theorems whose closure matters
   most — the end-to-end soundness statement, the AST bridge and the dylib
   contract. Get the names from
   `formal/admitted.py::library_trust_by_declaration_lines` rather than from a
   grep. Expected output: `propext`, `Classical.choice`, `Quot.sound`,
   `Lean.ofReduceBool`. **`Lean.ofReduceBool` appearing is the confirmation; a
   theorem WITHOUT it is the interesting result** — and the interesting result is
   expected for at least some of the 437 declarations that carry no site, because
   a site reached through a CALLEE is still an axiom in the closure. That is the
   half the attribution cannot do, and it is why this item is still open.

3. **Replace the cheap sites first**, and the list is now exact rather than a
   population: the eight theorems in "What landed" whose single site is a
   `native_decide`. `toNat_sub_one` is the shape this item always described
   (`have hpos : 1 ≤ n.toNat := …; omega` inside a `rw`/`calc`), where the
   arithmetic is closed. The 683 `bv_decide` sites are the `∀ w, … ≠ …` bit-pattern
   lemmas, `bv_decide` is the right tool there, and ten of the 19 one-site
   theorems are the `arm64_flag_*` family — **those are the ones to leave**, now
   by name rather than by class.

4. **Keep the ceiling honest.** `test_formal_admitted.py`'s `LIBRARY_TRUST` pins
   749 as a CEILING, failing when it rises and reporting it when it falls, and
   this round added the per-theorem ceilings beside it (19 one-site theorems, 8
   of them `native_decide`-only). Land a replacement with the ceilings lowered
   and the commit saying which sites went; that is the `expect=`-discipline
   direction, and it is the only thing that makes the number mean something over
   time.

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
| `arm64_step_cmp_reg_n31_reads_zero` | 7 generated | `[propext, Quot.sound]` |
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
proof about machine semantics. What moved is WHERE the trust sits — from the
kernel to the generated C code and the C compiler — and 304 of `lib/`'s 375
theorems never moved at all, which is a better answer than the 0 this file
previously implied was impossible to state.
