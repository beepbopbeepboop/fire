# plan/step-18a: DESIGN MEMO — what the one-field by-reference mutator's Lean contract may say
**Status: DONE 2026-11-07 (measured).** The §6.3 section in `bugs/FORMAL_known_limits.md` is corrected: `inc`/`pop`/`set2` give `None` (the 2026-11-05 table said `inc` was misclassified `set`; it is not), D1 is already in `_frame_methods` so 18b reduces to pinning four negative rows in `test_formal_frame_method_finder.py`, the D2 premise is `FrameFits p 1` + `s.sp.toNat + W <= p.toNat` (NOT `FrameBelow`, wrong side for a caller-owned cell) with a real Lean skeleton for 18d, and D3 is stated (no producer emits >1 RET today). The (A) sweep was not re-run; the 7-line historical figure holds only 2 real frame-escape refusals.
Class: hard      Size: M      Depends: 15a, 01b      Blocks: 18b, 18c, 18d
Source: `bugs/FORMAL_known_limits.md` §6.3 lever #2 (97 direct / 68 actionable); deleted `bugs/formal/FORMAL_a_one_field_mutator_has_no_method_contract.md` (last text: `git show 0fa4255bb^:bugs/formal/FORMAL_a_one_field_mutator_has_no_method_contract.md`, 306 lines; §3 the three open questions, §4 x86, §4.2 the guard-window finding).
Output: ONE committed section "§6.3 Design: the by-reference one-field mutator contract" in `bugs/FORMAL_known_limits.md`; no code.

## Current state (measured; verified 2026-11-05)
- Two DIFFERENT things share the words "frame escape" and must not be conflated:
  (A) the CODEGEN refusals (a `X` receiver is returned from ... / `frame address is passed to len()` ...): a build-time refusal that `--no-prove` sweeps count. `bugs/sweeps/sweep-arm-14.txt` has 7 direct `CODEGEN:` lines mentioning "frame address"/"receiver" (`grep -E '^CODEGEN' bugs/sweeps/sweep-arm-14.txt | grep -c 'frame address\|receiver'`). The doc's 97/68 is from 2026-09-27 and is stale. A Lean contract CANNOT move this count.
  (B) the Lean contract for a receiver passed by reference: `formal/arm64_proof_gen.py::_frame_methods` (line 13803) and `_generate_frame_proof` (:14410); `lib/Refine.lean`, `lib/Contracts.lean`; `formal/contracts.py`.
- The deleted doc's "step 0" and "exclusion" are GONE: commit `0fa4255bb` (2026-11-03) made `_frame_methods` accept by-reference one-field mutators (`is_byref_onefield = bool(f._recv_ref_receiver) and is_one_field`, lines 13835-13866), with the body-start taken from the `{fname}_sf{k}_ok` label and branches allowed for by-reference one-field methods (`if not is_byref_onefield: continue`, line ~13897). `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_frame_method_finder.py` passes (5 tests; the new one `test_one_field_mutator_by_reference_gets_contract` classifies `Box_set_v` as `kind="set"`).
- BUT lines 13857-13866 are a placeholder: for a multi-statement by-reference mutator `src = [(field, True)]  # placeholder, will be adjusted`, and `kind="set"` is then asserted whenever all machine accesses are stores (line ~13915 `all(stores) and (len(f.body)==1 or is_byref_onefield)`). Whether the Lean contract generated for such a method is TRUE is unmeasured. A false contract is worse than none (ProofLib header).
- The three open questions (deleted doc §3), still open: (1) the cell is the CALLER's frame and nothing bounds its depth (`Frame.FrameFits`); (2) constant propagation starts from `{0: 0}` and the new lowering's first instruction is `LDR X19, [X0]` (a LOAD through the receiver): `_frame_slot_accesses` (:13633) must learn a load-first rule; (3) the write-back repeats on EVERY exit, so the store peel `_frame_store_writes` (:13933; it only recognises idx 31 `STR [Xn,#imm]`) needs a per-exit case obligation.
- x86-64: `grep -n "frame_methods\|_self_accesses" formal/x86_64_proof_gen.py` returns nothing (re-run to confirm); no frame-contract machinery.
- `lib/Scaffold.lean` and `formal/proof_gaps.py::SCAFFOLD_HOLES` exist (step 01); scaffold `sorry` goes there only (plan S1/S2).

## Decisions already made
- The memo's job is measurement + three decisions. Defaults (take unless measurement refutes):
  D1 (soundness of today's placeholder): build `Box`-like programs (one-field struct; mutators: single store `set_v`; `inc` = `self.v = self.v + 1`; `pop` = read-modify-write-return with two exits via `if`), call `_frame_methods` as the test does, and for each print `kind`, `pairs`, `stores`. Where the classification does not match the source (e.g. `inc` has a LOAD then a STORE but is labelled `set`), the decision is: **restrict `_frame_methods` to exactly the verified shape (a body that is one assignment of a parameter) and drop the placeholder branches** (18b).
  D2 (depth bound): **state it as a hypothesis, not an axiom**: the contract takes the caller's cell address as a universally quantified `p` with premise `Frame.FrameBelow`-style bound written as an explicit hypothesis of the theorem (`h_cell : cell_in_caller_frame p`), and the generated theorem is `sorry`-free ONLY IF the hypothesis is a theorem premise; the discharge at call sites is a scaffold (18d). Rejected: an axiom (invariant 3).
  D3 (multiple exits): contract states the write-back as a per-exit disjunction over the RET addresses the finder collected; 18c implements the peel for 1 exit, scaffolds >1.
- x86-64 is explicitly out of scope: record that it refuses/has no contract and which test shows it (the sweep with `--backend=x86_64 --prove`? UNVERIFIED: find a `test_formal_x86*` that builds a by-reference one-field mutator with proof; if none, say so).

## Work order
1. Run the D1 programs (write them to `.tmp/18a/*.mojo`; use the pattern in `test_formal_frame_method_finder.py::test_one_field_mutator_by_reference_gets_contract`, `fn` -> use `def`; it spies `G.generate_arm64_proof` to avoid Lean). Record a table: program | `_frame_methods` result | does the classification match the source.
2. Run the family re-measure for (A): `export PATH=/opt/homebrew/bin:$PATH; python3 tools/memslot.py --gb 32 --label sweep -- python3 tools/formal_sweep.py -j 4 -t repo=600 -t stdlib=120 > .tmp/sweep18a.log 2>&1` then `grep -E '^CODEGEN' .tmp/sweep18a.log | grep -c 'frame address\|receiver'` and list them. Record the count (this replaces the 97/68 everywhere).
3. Write the section: table from 1, count from 2, D1-D3 each with the chosen reading and the exact theorem statement skeleton for D2 (Lean text, to be placed in `lib/Scaffold.lean` by 18d), and which of 18b/18c/18d each decision feeds.
4. Commit the doc only.

## Do NOT
- Do not run `lean`, `make gate`, or touch `lib/`. Do not state a statement you have not read against `lib/Refine.lean`/`Contracts.lean`/`ProofLib.lean`'s `Frame.*` definitions (`grep -n "FrameBelow\|FrameFits\|frameWrite" lib/ProofLib.lean | head`).
- Do not claim a Lean contract moves the sweep count.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_frame_method_finder.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] the section exists with: classification table, new (A) count, D1/D2/D3 chosen, theorem skeleton
- [ ] each of 18b/18c/18d can be executed from it

## If stuck
If the sweep cannot finish, use the old log's 7 and say "re-measure pending"; do not stall the memo on it.
