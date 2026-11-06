# plan/step-27a: EH runtime design memo (exception object storage, `as e`, superclass matching)
**Status: DONE (verified by agent, work landed)**

Class: hard      Size: M      Depends: 25      Blocks: 27b, 27c
Source: `bugs/FORMAL_no_exceptions.md` "The next step" item 2; `formal/model/types.py` (`handler_arm_matches` :2712, `CPYTHON_EXCEPTION_BASE` :2490, `exception_base_chain` :2608); `formal/model/module.py` (`try_handler_refusal` :6687, `unemitted_handler_arm` :344, `uncatchable_raise` :830)

## Current state (measured; file:line verified 2026-11-05)
- P0: `python3 -c "import formal.model"` must work (HEAD: `NameError: threading` at `formal/model/layout.py:3155`; fix = `import threading` in layout.py, own commit).
- A `raise` lowers to evaluate-the-expression + run enclosing `finally` + `exit(1)`: arm64 `arm64_codegen.py:1142` (`RaiseStmt`), x86-64 `x86_64_codegen.py:997`. `_emit_try` (arm64 :3491, x86 :3081) emits body, else, finally and SKIPS handlers. The exception object is never built.
- Where handlers are refused today: `formal/build.py:_refuse_try_handlers` (:~17270) refuses a `try` WITH handlers whose guarded body/else contains a `raise` or a call to a local function that raises (`M.try_handler_refusal`); a `try` with handlers over a region that cannot raise BUILDS (handler dead, correct). `except X as e` is refused by `unemitted_handler_arm` (module.py:344; `test_formal_exceptions.py` REFUSALS row `an_except_as_binding_is_refused_by_name`, the ONLY refusal row left; the doc's other two rows are gone).
- SUSPECT, UNVERIFIED — worker must check first: `module.py:344-380` (`unemitted_handler_arm`) and `cfg.py:1326-1335` carry comments "Handlers ... can now be emitted" and `pass  # Can now be emitted`, yet both `_emit_try` skip handlers. Measure: build `def main():\n    try:\n        printf("a")\n    except ValueError:\n        printf("b")\n    return 0\n` on both backends (`python3 fire.py build --formal --no-prove [--backend=x86_64] f.mojo`) and confirm it builds and prints `a` (correct: the body cannot raise). Then the same with `raise ValueError("x")` in the body: expect the `try_handler_refusal`. If instead the arm is silently dropped for a raising body, that is a TRUTH BUG: record it at the top of the memo as the first fix (restore the refusal) and continue.
- Superclass matching is NOT an open question in the tree: `handler_arm_matches(arm_name, flying_name, kinds, structs)` returns True/False/None via the CPython builtin hierarchy, oracle-tested 71x71 by `test_formal_exceptions.py::run_matching_oracle` (:1311). The draft was stale on this.
- What `except A as e` binds IS open: nothing in the tree gives `e` a value.
- Storage precedent: `FORMAL_module_state_no_storage.md` is deleted; every value is one 64-bit word in a function's stack scratch; a container lives in the frame of the function that made it and a return value does not outlive it (os/__init__.mojo header, `listdir` bullet); `malloc` is how a value outlives a frame (blob pattern).
- A status-word design is sketched in the deleted `FORMAL_a_try_handler_arm_is_still_never_emitted.md`; the sizing it recorded: hand-dispatching a same-function arm moves 0 files (every arm wraps a CALL, and a call's raise is the callee's to decide).

## Decisions already made
- This step produces ONE committed section, no code: "## EH design (step-27a)" appended to `bugs/FORMAL_no_exceptions.md`. (Doc edit only; run `python3 tools/dangling_doc_refs.py --ratchet`.)

## Work order  (the memo MUST contain each of these; each ends in a RECOMMENDATION line the next steps will implement verbatim)
1. Run the SUSPECT check above; record result.
2. Q1 — exception object storage. Lay out the readings with costs: (R1) a malloc'd record `[class_id:i64][msg:char*][cause:i64]` addressed by a status word returned in a dedicated register/slot; (R2) a per-thread global slot (no storage exists for module state — cite the deleted doc's reason); (R3) caller-allocated frame record passed as a hidden argument. Recommended default to evaluate first: R1 with class_id from `exception_class_ids` in types.py (find with `grep -n "class_id\|exception_ids" formal/model/types.py`; the id ranges are described at types.py:~2336-2370) so `handler_arm_matches` supplies the match table.
3. Q2 — what `except A as e` binds: recommend `e` = the R1 record's address as an opaque word, usable ONLY for `str(e)`-free operations; every other use stays REFUSED by name. State which operations on `e` are in the first slice (none) and keep `as e` refused until a later step.
4. Q3 — superclass matching: record that it is answered (`handler_arm_matches`), and specify how a landing pad uses it: a pad table row per (try region, arm) with the list of `class_id`s `handler_arm_matches` returned True for, computed at BUILD time over `CPYTHON_EXCEPTION_BASES` plus the module's declared classes; None (undecidable) => refuse the image.
5. Propagation: status-word convention for calls that may raise (which functions get it: those in the `raisers` set computed by `build.py:_raises_somewhere`; imported callees via `CrossModuleRaises` in imports.py). Specify the ABI change as a proposal for `doc/ABI.md` (do not edit ABI.md).
6. The proof-side plan: how `RaiseStmt`/`TryStmt` become `MojoStmt`/model terms. `lib/ProofLib.lean` `MojoStmt` (:966) has no raise/try constructor; list the minimal constructors and the Scaffold.lean theorems (stated, `sorry`, ledgered in `formal/proof_gaps.py` per S1/S2) that a later step adds: at least `try_flat_sound` (a `try` whose region cannot raise is its body;else;finally) and `raise_terminates`. Do NOT add them now.
7. Slice order: list the next 3 execution steps (27d..) with files; each must be independently testable by `test_formal_exceptions.py`.

## Do NOT
- Do not write code. Do not edit `lib/*.lean`. Do not guess `as e` semantics beyond "opaque word, still refused".
- Do not claim the hand-dispatchable slice is worth files; cite the 0-file sizing.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/dangling_doc_refs.py --ratchet
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_exceptions.py   # must be unchanged (no code touched; 331 checks per the doc, re-record the count)
```

## Done when
- [ ] section "EH design (step-27a)" exists with Q1, Q2, Q3, propagation, proof plan, slice order, each with a RECOMMENDATION line
- [ ] SUSPECT check result recorded (builds/prints `a`; raising body refused)
- [ ] no source file changed

## If stuck
If the SUSPECT check shows a silently dropped arm, make the restoring fix the whole round (revert to refusal via `_refuse_try_handlers`/`try_handler_refusal`, add a `REFUSALS` row to `test_formal_exceptions.py`), and defer the memo.

## Safe for iceman
NO. Opus/sonnet only (design). 27b and 27c are iceman-safe once this memo exists.
