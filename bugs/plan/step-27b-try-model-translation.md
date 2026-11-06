# plan/step-27b: `TryStmt` in the semantic model (`arm64_proof_gen.py`): the sound flat slice
**Status: DONE (verified by agent, work landed)**

Class: mid      Size: M      Depends: 27a      Blocks: none
Source: `bugs/FORMAL_no_exceptions.md` item 2 and the 27a section; `formal/arm64_proof_gen.py` `_stmts_go` :1786, `_stmts_go_t` :2249, `_stmts_ast` :3921

## Current state (measured; file:line verified 2026-11-05)
- P0: `python3 -c "import formal.model"` must work (see step-26 P0).
- None of the three translators has a `TryStmt` arm (grep `TryStmt` in `formal/arm64_proof_gen.py` finds only lines 1690-1702 etc. in build.py, none here). `_stmts_go` ends with `raise NotImplementedError("model: a {type} has no translation in the semantic model ...")` (:~2023); `_stmts_go_t` is the typed twin (:2249; read its tail for the same raise); `_stmts_ast` ends with the "ast model: a X has no MojoStmt form" raise (:~3985). So every function containing a `try` fails proof generation.
- Codegen of a try that builds: body, then else, then finally, handlers skipped (`arm64_codegen.py:3491 _emit_try`). A `try` with handlers builds only if its guarded body/else cannot raise (`build.py:_refuse_try_handlers`). Therefore the emitted code of every buildable `try` IS the straight-line sequence body;else;finally.
- `lib/ProofLib.lean:966` `MojoStmt` has NO try/raise constructor, and editing ProofLib is expensive and pinned (S4).

## Decisions already made
- Translate a `TryStmt` as the FLAT sequence `body ++ else_body ++ finally_body ++ rest` in all three translators, via ONE helper `_try_flatten(st)` in `arm64_proof_gen.py` returning that list or raising `NotImplementedError`. No new Lean constructor, no ProofLib edit.
- `_try_flatten` raises `NotImplementedError("model: try ... (step-27b): <reason>")` when: any handler has a non-None `.name` (`as e`); body/else/finally contains a `ReturnStmt`, `BreakStmt`, `ContinueStmt` or `RaiseStmt` (`finally` must run before them, which flat order gets wrong); or the guarded region can raise (use `formal.build._raises_somewhere(stmts, raisers=set(), nested_ok=False)` is NOT enough alone — a call to a local raiser needs the module's raiser set; since the build already refused those, assert-and-raise only on a literal `RaiseStmt`). Handlers' bodies are DROPPED from the model, and the reason this is sound is the build-time guarantee above; the comment at the arm says so and cites `_refuse_try_handlers`.
- The hole: this is a SOUND translation of the buildable subset, so no `sorry` is introduced here. The Lean-side statement (`try_flat_sound`, `raise_terminates`) is 27a item 6's later step; this step adds no Scaffold theorem and no ledger row. State that in the commit message.

## Work order
1. Add `_try_flatten` near `_if_expand` (grep `def _if_expand`) with a docstring naming the three conditions.
2. In `_stmts_go`: before the final raise, `if isinstance(st, TryStmt): return _stmts_go(_try_flatten(st) + rest, ...)` (copy the argument list of the `Pass/ExprStmt` arm at :1809). Same in `_stmts_go_t` (:2256+ pattern) and `_stmts_ast` (extend `parts` with `_stmts_ast(_try_flatten(st), scope)`). `TryStmt` must be imported the way `IfStmt` is (read the import block at the top of the file; the module aliases AST names).
3. Test: new `test_formal_try_model.py` modelled on `test_formal_call_proof_gen.py` (read its setup for how it parses a source string and calls the generator). Rows: (a) `try: x = 1 ... finally: y = 2` returns x+y: translation succeeds, Lean text contains both bindings in order; (b) `try` + `except ValueError: pass` over a non-raising body: succeeds, handler absent; (c) `except ValueError as e`: raises NotImplementedError mentioning `as e`; (d) a `return` inside the body: NotImplementedError; (e) the generated model for (a) evaluated by Python `exec` of the same source gives the same value (oracle: CPython).
4. Run the generated Lean for row (a) through the normal pipeline ONLY if cheap: `python3 fire.py build --formal <file>` (proving) on the program of row (a); record whether Lean accepts; if Lean is slow (> 5 min) skip and say so.
5. `tools/formal_proof_census.py` baseline: if its examples gain a `try` program, update the baseline from the tool's measured output only (read `tools/formal_proof_census.py --help`); add NO example in this step.

## Do NOT
- Do not translate handler bodies. Do not model `raise`. Do not edit `lib/ProofLib.lean`/`X86.lean`/`Peephole.lean`.
- Do not widen any allowed-gap set (item 4 of Method) — nothing here adds a gap.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_try_model.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_exceptions.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
```

## Done when
- [ ] `test_formal_try_model.py` rows (a)-(e) pass; `test_formal_exceptions.py` has the same pass count as before (record both)
- [ ] `grep -n "TryStmt" formal/arm64_proof_gen.py` shows the helper and three arms
- [ ] no `lib/` file changed

## If stuck
If `_stmts_go_t`'s tail differs from `_stmts_go` so that one flat arm cannot be shared, land the untyped + AST arms only and write the typed gap into the 27a section's Status; stop.
