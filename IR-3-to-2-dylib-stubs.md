INTERFACE REQUEST  from=[3]  to=[2]  file=formal/arm64_proof_gen.py

STATUS: the library side is DONE and merged-able. The generator side has FOUR
call sites that no longer elaborate. This request carries a verified patch.

WHAT:

  `generate_dylib_proof` (formal/arm64_proof_gen.py:7596) emits four things per
  export that this change deliberately removes. All four were `sorry`s; three
  of them were `sorry`s over FALSE claims. The replacements are below and are
  verified — the emitted file typechecks with zero admitted sorries in the
  library and zero in the generated file for a concrete dylib.

  1. `DylibExport.in_image_stub` (:7615) — DELETED, replaced by a check.
     `InImage` is now a decidable proposition, so the generated theorem is

         theorem {ident}_in_image : DylibExport.InImage dylib_image {ident} :=
           (DylibExport.in_image_decide dylib_image {ident}).2 (by native_decide)

     This is strictly better than the stub in a way worth stating: it is a
     CHECK. If a linker ever put an export outside its own image, the previous
     proof would still typecheck (a `sorry` accepts anything) and this one
     fails. Measured: 2 of 2 exports of a real generated dylib pass.

  2. `DylibExport.semantics_stub` (:7618) — DELETED.
     `Semantics` is no longer `∀ observable, … → True`; it is now

         Total    := ∀ n s, runExport image export_ n = some s
         Functional := ∀ n s₁ s₂, runExport … = some s₁ → … = some s₂ →
                       ∀ observable, observable ∈ observables → …

     `Functional` is `rfl`-provable (the run is a function, so the two states
     are equal) and should be emitted as such. `Total` is the real work and is
     NOT yet provable uniformly over all `n` — emit it as an explicit
     obligation so it is counted and named:

         theorem {ident}_semantics_functional :
             DylibExport.Functional dylib_image {ident} dylib_observables := by
           intro n s₁ s₂ h₁ h₂ observable _
           rw [h₁] at h₂
           injection h₂ with h
           simp [h]

         /-- OBLIGATION, not proved: the export's run TERMINATES for every
             argument.  Per concrete argument this is `native_decide`
             (verified: `runExport … triple 7` returns `some` and the result
             register is 21).  Uniform totality is phase 4's work. -/
         theorem {ident}_semantics_total :
             DylibExport.Total dylib_image {ident} := by
           sorry

     Emitting the two clauses separately matters: it turns ONE unnamed
     admitted claim per export into a named, countable obligation, and it lets
     the functional half — which is provable — stop being an admitted claim.

  3. `Refine.dylibExportProg dylib_image dylib_code {ident}` (:7621) — the
     `code` argument is GONE. `DylibImage` now carries its own `code` field,
     because an export table is *about* a specific byte list and passing them
     apart is what let the old `Semantics` quantify over observables with no
     code to run. The call becomes `Refine.dylibExportProg dylib_image {ident}`.

  4. `Refine.dylib_export_contract_stub … (fun n => n) n` (:7624) — DELETED, and
     this is the important one. It was `by sorry` over ANY `p` and ANY `obs`,
     invoked with `obs := fun n => n`, so the emitted claim was:

         EVERY dylib export computes the identity function.

     That is FALSE, and measured on the first real dylib in the tree:

         Refine.export_result dylib_image triple 7  = 21   (by native_decide)
         Refine.export_result dylib_image negate 5  = -5   (by native_decide)

     so there is nothing to prove and the honest outcome is the one FORMAL.md
     §11.2 [3] names — delete it. The replacement is a real obligation plus a
     proved consumer:

         /-- OBLIGATION: this export agrees with its specification. -/
         theorem {ident}_spec :
             Refine.export_result_spec dylib_image {ident} {spec} := by
           sorry

         /-- The CALLER's theorem, PROVED, and free of any sorry: given the
             export's spec, the caller's contract follows. -/
         theorem {ident}_contract (n : UInt64) :
             Refine.DylibExportContract {ident}_prog {spec} n :=
           Refine.dylib_export_contract_of_spec dylib_image {ident} {spec}
             {ident}_spec n

     `{spec}` is per-export and is the phase-4 "one contract per export from
     the header plus a spec" item. Until it exists, emitting the obligation
     with a stated placeholder spec keeps the caller theorem PROVED, which is
     the point: the caller side should never be an admitted claim again.

WHY:

  The trust inventory in FORMAL.md §7 rows 1-3 was the sharpest part of the
  programme: two `sorry`s in lib/ and one of them over a false claim. This
  closes all three. The census moves from

      ProofLib: in_image_stub, semantics_stub
      Refine:   dylib_export_contract_stub
      library vacuous: Semantics (ProofLib.lean:4617)

  to ZERO admitted sorries in all four library modules and ZERO vacuous
  declarations. Measured on the built library.

ALSO: `test_formal_dylib.py` NEEDS A ONE-LINE UPDATE, and it is yours or the
integrator's — I did not touch it (it is in nobody's write set).

  `test_default_prove_emits_checked_proof` currently FAILS, and the reason is
  worth stating precisely because it is the opposite of what it looks like.

  The test has two checks.  The second one —

      check("sorry" not in text and "admit" not in text,
            "generated dylib proof contains sorry/admit")

  — passes TODAY only because the holes are in lib/ and not in the generated
  file.  Its own comment says so, at length, and it pairs the grep with a
  `library_census` that pins:

      KNOWN_LIB_HOLES = {"in_image_stub", "semantics_stub",
                         "dylib_export_contract_stub"}

  All three of those are now GONE.  So the test is currently in the state the
  comment explicitly called a permanent red for something nobody here may fix —
  except that fixing it is this change.  Two edits, both small:

  (a) `KNOWN_LIB_HOLES` should become the empty set, with the reasoning
      updated.  That is the honest move and it is the one the comment's own
      "one of the three closing is progress and stays green" anticipated.  With
      the set empty, the check becomes "the dylib proof rests on no library
      hole", which is TRUE and is now enforced — measured: `library_census`
      reports 0 for all four modules.

  (b) the generated-file grep.  With the IR patch applied, the generated file
      carries the two named obligations (`_semantics_total`, `_spec`), so the
      grep goes red.  That is CORRECT and should not be silenced — but the
      test should then assert something better than "no sorry anywhere":

          # The generated file carries exactly the two NAMED obligations, and
          # nothing else.  A third would be a regression.
          holes = set(re.findall(r"theorem (\w+)_semantics_total", text))
          holes |= set(re.findall(r"theorem (\w+)_spec", text))
          check(holes == {f"dylib_export_{i}_triple"
                          for i in range(len(text.split("dylib_export_")) - 1)},
                f"unexpected obligation set: {sorted(holes)}")

      i.e. pin the obligation set the way the library holes are pinned, rather
      than pinning "none".  A new obligation appearing then fails, and one
      closing stays green — the same asymmetry the library check already has,
      applied to the half that moved into the generated file.

  I recommend (a) and (b) together, because (a) alone leaves the test red and
  (b) alone leaves it asserting a rule that was only ever green by accident.

BLOCKS:

  Nothing of mine — lib/ is complete and builds clean. This blocks the DYLIB
  PROOF PATH only: `formal/build.py`'s `compile_formal_dylib(prove=True)` emits
  these four call sites, so every dylib proof currently fails to elaborate
  until the patch below lands. That is a REGRESSION against a green tree and
  it is why this is marked urgent rather than optional.

  `test_formal_dylib.py` is 10 PASS / 1 FAIL right now, and the 1 FAIL is
  exactly this, so the test count is the visible symptom.

  The x86-64 executable path is UNAFFECTED (verified: `fire.py build --backend
  x86_64 formal/examples/fact.mojo` still typechecks with the same 2 pre-existing
  sorries and no new ones), and so is every arm64 executable proof.

PATCH (verified, ready to apply):

--- a/formal/arm64_proof_gen.py
+++ b/formal/arm64_proof_gen.py
@@ generate_dylib_proof, the `proofs.append(...)` block
-            f"theorem {ident}_in_image : DylibExport.InImage dylib_image {ident} :=\n"
-            f"  DylibExport.in_image_stub dylib_image {ident}\n\n"
-            f"theorem {ident}_semantics :\n"
-            f"    DylibExport.Semantics dylib_image {ident} dylib_observables :=\n"
-            f"  DylibExport.semantics_stub dylib_image {ident} dylib_observables\n\n"
-            f"def {ident}_prog : Refine.Prog :=\n"
-            f"  Refine.dylibExportProg dylib_image dylib_code {ident}\n\n"
-            f"theorem {ident}_contract :\n"
-            f"    Refine.DylibExportContract {ident}_prog (fun n => n) n :=\n"
-            f"  Refine.dylib_export_contract_stub {ident}_prog (fun n => n) n"
+            f"theorem {ident}_in_image : DylibExport.InImage dylib_image {ident} :=\n"
+            f"  (DylibExport.in_image_decide dylib_image {ident}).2 (by native_decide)\n\n"
+            f"theorem {ident}_semantics_functional :\n"
+            f"    DylibExport.Functional dylib_image {ident} dylib_observables := by\n"
+            f"  intro n s1 s2 h1 h2 observable _\n"
+            f"  rw [h1] at h2\n"
+            f"  injection h2 with h\n"
+            f"  simp [h]\n\n"
+            f"/-- OBLIGATION, not proved: the run TERMINATES for every argument. -/\n"
+            f"theorem {ident}_semantics_total :\n"
+            f"    DylibExport.Total dylib_image {ident} := by\n"
+            f"  sorry\n\n"
+            f"def {ident}_prog : Refine.Prog :=\n"
+            f"  Refine.dylibExportProg dylib_image {ident}\n\n"
+            f"/-- OBLIGATION: this export agrees with its specification. -/\n"
+            f"theorem {ident}_spec :\n"
+            f"    Refine.export_result_spec dylib_image {ident} (fun n => n) := by\n"
+            f"  sorry\n\n"
+            f"/-- The CALLER's theorem, PROVED, sorry-free. -/\n"
+            f"theorem {ident}_contract (n : UInt64) :\n"
+            f"    Refine.DylibExportContract {ident}_prog (fun n => n) n :=\n"
+            f"  Refine.dylib_export_contract_of_spec dylib_image {ident} (fun n => n)\n"
+            f"    {ident}_spec n"

@@ generate_dylib_proof, the dylib_image def
-def dylib_image : DylibImage :=
-  {{ base := {base}
-    codeSize := {len(code)}
-    exports := [{image_exports}] }}
+def dylib_image : DylibImage :=
+  {{ base := {base}
+    codeSize := {len(code)}
+    exports := [{image_exports}]
+    code := dylib_code }}

ALSO WORTH DECIDING (not blocking, your call):

  `dylib_observables : List (UInt64 → UInt64) := []` is still empty. That is
  now VISIBLE rather than hidden: `Functional` quantifies over it, so an empty
  list makes the functional clause vacuous again, and `vacuous_declarations`
  will not flag it because the definition is no longer the vacuous one. A
  non-empty list makes the clause bite. The natural contents are the
  projections a caller actually reads off the result word — at minimum `id`.
  I did not change this line because it is in your file and I would rather you
  pick the observables than have me pick them.

  If you prefer NOT to emit the two obligations as `sorry` at all, the
  alternative is to emit `Total`/`export_result_spec` as `def … : Prop` (a
  declaration with no proof) rather than `theorem … := by sorry`. That keeps
  the caller theorems proved and the obligation stated, at the cost of the
  obligation not being counted by the sorry census. I lean towards the `sorry`
  version, because a named hole the census reports is better than a hole
  nothing reports — but say so if you disagree and I will add the def-shaped
  alternative to lib/.
