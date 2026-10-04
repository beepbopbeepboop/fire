# The axiom is NOT `Lean.ofReduceBool`, and 53 of `lib/`'s 375 theorems is what the sites are

**Status: the closure census is DONE and it corrected the name.** What is left
is the replacement plan, which is a debt being paid down and is not a patch.

Claim: `sweep20:admitted-audit`. Not any `formal19` doc.

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

`formal/admitted.py::theorem_axiom_census` — one `#print axioms` line per
theorem, ONE Lean run per module, all of `lib/` in **4-5 s** through
`formal/lean.py::run_lean` under the library bounds. **375 of 375 answered**, and
the four columns partition each module:

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

## What this is not

Not a soundness bug, not a false theorem, and not a reason to distrust a green
proof about machine semantics. What moved is WHERE the trust sits — from the
kernel to the generated C code and the C compiler — and 304 of `lib/`'s 375
theorems never moved at all, which is a better answer than the 0 this file
previously implied was impossible to state.
