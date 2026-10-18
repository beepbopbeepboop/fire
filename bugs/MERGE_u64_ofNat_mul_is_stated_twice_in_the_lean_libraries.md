# MERGE: `u64_ofNat_mul` is stated TWICE in the Lean libraries, so two `AXIOM_CLOSURE` rows and two module costs answer the same theorem

**Area:** FORMAL, the Lean libraries — `lib/ProofLib.lean` and `lib/Specs.lean`.
Found 2026-10-18 while merging `work/formal418-docs`, after the
`work/formal405-docs` commit had already landed the same lemma in ProofLib.
**Status: OPEN, not fixed here, because the only verification it needs is the one
a light worker cannot afford (below).**

## What I ran, and what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ grep -c "theorem u64_ofNat_mul" lib/ProofLib.lean lib/Specs.lean
lib/ProofLib.lean:1
lib/Specs.lean:1

$ grep -n "u64_ofNat_mul" -A 3 lib/ProofLib.lean
770:theorem u64_ofNat_mul (a b : Nat) :
771-    UInt64.ofNat a * UInt64.ofNat b = UInt64.ofNat (a * b) := by
772-  apply UInt64.toNat.inj
773-  rw [UInt64.toNat_mul, UInt64.toNat_ofNat', UInt64.toNat_ofNat', UInt64.toNat_ofNat']
774-  exact (Nat.mul_mod a b (2^64)).symm

$ sed -n '172,175p' lib/Specs.lean
theorem u64_ofNat_mul (a b : Nat) :
    UInt64.ofNat a * UInt64.ofNat b = UInt64.ofNat (a * b) := by
  apply UInt64.toNat.inj
  simp [UInt64.toNat_mul, UInt64.toNat_ofNat', Nat.mul_mod]
```

Same statement, core-lemma-only proof, two libraries. `lib/Specs.lean` opens
with `import ProofLib`, so `Specs.u64_ofNat_mul` shadows
`ProofLib.u64_ofNat_mul` for every file that imports `Specs` — which is every
generated proof.

## Why it is a merge artefact and not a decision

* `work/formal405-docs` added it to `lib/ProofLib.lean`. Master re-pinned
  `test_formal_admitted.py::AXIOM_CLOSURE`'s `ProofLib` row to
  `(315, 62, 248, 0, 5, 0)` for exactly this declaration
  (`u64_ofNat_mul` — `clean`, proved by `UInt64.toNat.inj`, three rewrites and
  `Nat.mul_mod`, so it reaches no axiom).
* `work/formal418-docs` added it to `lib/Specs.lean` with a documented reason
  that was TRUE ON ITS OWN BASE and is FALSE ON THE MERGED TREE: a
  `ProofLib.lean` edit rebuilds that module's 27 MB `.olean`, which under
  `tools/memslot.py --gb 8` breaches the ceiling (measured 2026-10-14, 1m54s;
  `bugs/FORMAL_arm64_step_cannot_step_nine_wired_encodings.md` records the same
  measurement at 9.8 GB), while `Specs.lean` rebuilds in ~2 s / 0.2 GB. ProofLib
  had no such declaration on that branch's base, so the copy looked like the only
  copy.

## What it costs

1. **`AXIOM_CLOSURE` has two rows describing one theorem.** `Specs`'s row is
   pinned against a file that has since gained a `clean` declaration, so
   `test_formal_admitted.py`'s census is one asked/one clean out for whichever
   row moves.
2. **`lib/Specs.lean`'s module docstring promises independence from ProofLib's
   machine model, and this shim is a copy of a ProofLib theorem** — the one place
   in that file where the promise is kept by duplication rather than by maths.
3. **Two proofs to keep true** for one statement.

## The exact next step

Delete `Specs.u64_ofNat_mul` (the `theorem` and the doc comment above it) and
name `ProofLib.u64_ofNat_mul` from `formal/specs.py::ALL_INPUTS`'s `lemma=`
column, which currently reads `lemma="Specs.u64_ofNat_mul"`. A generated
all-inputs induction is emitted into a file that imports ProofLib directly
(`formal/lean.py::LIBRARY_MODULES`'s note says so), so the fully qualified name
resolves without a shim. Then two assertions move with it in
`test_formal_specs.py`:

* `test_the_all_inputs_refinement_has_its_multiplication_lemma` pins the
  STATEMENT against `lib/ProofLib.lean` already, so it needs no change;
* the `check("Specs.u64_ofNat_mul" in sec, ...)` in the factorial row's check
  becomes `ProofLib.u64_ofNat_mul`.

Re-pin the `Specs` row of `test_formal_admitted.py::AXIOM_CLOSURE` for the
removal, and re-pin nothing in `ProofLib` — its row already counts this
declaration.

**Run it as one job, with a current library:** `python3 tools/suite.py
formal-specs` after the suite's `prooflib` dep has rebuilt
`lib/ProofLib.olean`. That is the part that cannot be done as a light worker:

```console
$ python3 tools/memslot.py --gb 8 --label spec -- python3 test_formal_specs.py
memcap: BREACH  8.0 GB > 8.0 GB ceiling (100%), 3 procs -- killing spec
memcap: peak observed before the kill: 8.0 GB
memcap: this is a RESOURCE failure, not a verdict on the thing under test
```

which is the same ceiling `lib/Specs.lean`'s own comment records, and the reason
the shim was written there in the first place.

## Related

* `bugs/FORMAL_a_specification_layer_that_stops_at_a_finite_range.md` — the
  layer this lemma unblocks; its Status now names this doc as the duplicate's
  home.
* `bugs/MERGE_arm64_set_union_emitter_is_gone_and_a_set_union_raises_AttributeError.md`
  — the other merge artefact in this batch, fixed in the same merge series.
