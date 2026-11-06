# plan/step-01b: the proof-gap ledger and its census test
**Status: DONE (verified by agent, work landed)**

Class: mid      Size: M      Depends: 00a, 01a      Blocks: every step that adds a hole (02+)
Source: `doc/finish-formal.md` Method #3, Shared mechanics S1/S2.

## Current state (measured; verified 2026-11-05)
- `formal/lean.py::library_census(lean, lib_dir, ...)` (line ~1163) returns `stem -> (n_sorries, (decl names...))` by elaborating each library module; cached as `.libcensus` beside the `.olean`.
- `formal/admitted.py` is the precedent for "a table a test reads": `@admitted` contracts, counted by `test_formal_admitted.py`.
- `FORMAL.md` §7 is the trust inventory; row 8 = admitted host contracts, row 10 = `native_decide`/`bv_decide` sites. A scaffold hole is a NEW kind of entry (§7 needs a new row).
- `tools/formal_proof_census.py` + `tools/formal_proof_census_baseline.json` ratchet GENERATED proofs per example; they are a different thing and are NOT replaced.

## Decisions already made
- Ledger: `formal/proof_gaps.py` with
  ```python
  from dataclasses import dataclass
  @dataclass(frozen=True)
  class Hole:
      step: str      # "step-03c"
      reason: str    # one line: what is unproved and why it is believed true
      kind: str      # "scaffold" | "control"
  SCAFFOLD_HOLES: dict[str, Hole] = {"scaffold_canary": Hole("step-01a", "census positive control; delete when the first real scaffold lands", "control")}
  ```
  Keys are Lean declaration names exactly as `library_census` reports them (check the real spelling from a census run, namespaces included).
- Pure comparison function `diff_holes(census: dict[str, tuple], ledger: dict) -> list[str]` (no Lean) returns human-readable problems; the Lean-touching test just feeds it the real census. This is what makes the negative probes cheap.
- Rules enforced: (a) Scaffold's sorry'd declarations == ledger keys, both directions; (b) every OTHER library module has 0 sorries; (c) every ledger `step` names an existing `bugs/plan/step-*.md` (prefix match on the id).

## Work order
1. Create `formal/proof_gaps.py` as above plus `diff_holes`.
2. Create `test_formal_proof_gaps.py` (style: `test_formal_axiom_closure_pinned.py` + the `unittest`/`-v` layout of `test_formal_peephole.py`). Tests: 
   - pure: `diff_holes` is empty for an equal pair; names an unledgered hole; names a stale ledger row; names a hole in a non-Scaffold module — four synthetic-dict cases;
   - real: call `library_census` through `formal.lean` the way `test_formal_axioms.py` does (copy its setup; never call `lean` directly) and assert `diff_holes(...) == []`.
3. Add a row to `FORMAL.md` §7's inventory table (after row 10): "scaffold holes — `lib/Scaffold.lean`, counted by `test_formal_proof_gaps.py`, ledger `formal/proof_gaps.py`". Keep it to one table row + one short paragraph.
4. Cite the policy: `CLAUDE.md` (a short paragraph in the formal-lane note: "scaffold holes live only in lib/Scaffold.lean and are ledgered"), and `doc/finish-formal.md` already does. **Do NOT edit the headers of `lib/ProofLib.lean`/`X86.lean`/`Peephole.lean`** (S4). The Scaffold header (01a) is the Lean-side citation.
5. Add `test_formal_proof_gaps.py` to `tools/suite.py`'s registry in the same bucket as `test_formal_axiom_closure_pinned.py` (grep it for the exact registration shape; run `python3 tools/suite.py --list | grep proof_gaps` to confirm; `test_suite.py` fails if a test is in no bucket).

## Do NOT
- Do not scan `lib/*.lean` with grep for `sorry`: comments contain the word and an up-to-date olean hides real ones. Use `library_census`.
- Do not allow wildcard/"count only" ledger entries.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_proof_gaps.py -v
python3 tools/suite.py -j1 --list | grep proof_gaps
python3 test_suite.py
```
Then prove the negative control by hand: temporarily add `theorem probe_x : True := by sorry` to a scratch COPY of Scaffold.lean is NOT possible with the real census, so the four pure `diff_holes` cases ARE the negative control; also run the real test once with the canary row removed from the ledger and confirm it fails naming `scaffold_canary`, then restore the row.

## Done when
- [ ] `test_formal_proof_gaps.py` passes (pure cases + real census)
- [ ] removing the canary ledger row makes it fail naming `scaffold_canary`
- [ ] `FORMAL.md` §7 row and `CLAUDE.md` paragraph added; `test_suite.py` passes (registered in a bucket)
- [ ] `git diff --stat lib/` shows only `lib/Scaffold.lean`

## If stuck
If `library_census`'s reported names don't match Lean declaration names (namespacing), record the actual spelling in the ledger comment and normalise in `diff_holes` — never loosen to counts. If the census cannot be obtained under the memory bound, stop and write the numbers you did get into this file.
