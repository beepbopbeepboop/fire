# plan/step-15b: restore the ALIASED import of a template (`from m import Pair as P` then `P[Int]()`)
Class: mid      Size: M      Depends: 15a      Blocks: none
Source: deleted `bugs/formal/FORMAL_generic_monomorph_scope.md` §2 (`git show 4fdf0a95d^:bugs/formal/FORMAL_generic_monomorph_scope.md`, search "ALIASED"); `bugs/FORMAL_known_limits.md` §1.2.

## Current state (measured 2026-11-05)
- The fix existed twice (`7f8629084`, an ancestor of HEAD; `4440853a2` "restore the ALIASED import of a template", on `origin/work/bug-formal-formal-generic-monomorph-scop-5902`, NOT an ancestor). HEAD has neither: `grep -n "alias" formal/monomorph.py` shows only a comment at :1040; there is no `local_defining_names` and `test_formal_monomorph.py` has no case `an aliased import of a template is instantiated`.
- The dotted module-alias spelling `L.Pair[Int]()` IS fixed in HEAD (`5ae6e3a6e`; cases at test lines 241, 268, 308). Not this step.
- `4440853a2` is written "in the current code shape": `git show 4440853a2 -- formal/monomorph.py formal/model/__init__.py test_formal_monomorph.py` is the work list (53 + 29 + 69 lines). Its `formal/model/__init__.py` hunk edits `dotted_specialization_refusal`, which now lives in `formal/model/cfg.py:2727`.

## Decisions already made
- Re-apply by hand (re-type each hunk into the current file); do NOT `git cherry-pick`/`checkout` (dirty tree, forbidden). Skip the hunk for `bugs/formal/*.md` paths.
- Mechanism (from the commit message): `formal/monomorph.py::local_defining_names` maps a local spelling to the DEFINING name through `formal/imports.py::imported_bindings(stmts)` (line 1846); `FromImportStmt` only (`import m as n` binds a module, not a template). `_bracketed_calls_pair` keys the demand on the defining name; `rewrite_instantiation_calls` (the `rewrite_instantiation_uses` family around line 1588) maps both member reads and call sites through the same table. A name the reading scope binds by VALUE (a `var P = 5`) is not an alias (`_shadowed_here`, `_names_bound_in`).
- The module-alias dotted spelling stays refused with its current text.

## Work order
1. `git show 4440853a2 -- formal/monomorph.py` and re-apply to HEAD's `formal/monomorph.py` (function names may have moved; locate by name with grep).
2. Apply the `dotted_specialization_refusal` wording change to `formal/model/cfg.py:2727` (docstring + sentence: the aliased BARE spelling lowers; the module-alias DOTTED spelling is refused). Keep `5ae6e3a6e`'s dotted behaviour unchanged: re-run the three dotted cases.
3. Re-add the test case from `git show 4440853a2 -- test_formal_monomorph.py` (name `an aliased import of a template is instantiated` plus the decision-only case `an aliased bracket is attributed to the template` if present in that diff) to the file AND to `TESTS`. Case takes `tmpdir`.
4. Update `bugs/FORMAL_known_limits.md` §1.2 Status (one dated paragraph): aliased import restored, pinned by the case name.

## Do NOT
- Do not rewrite the call's base in the AST (that was the failed `formal19-3-r2` design: the demand walk re-parses TEXT and never sees an AST rewrite).
- Do not touch `collect_module_symbols`: a bare read of the defining name must stay refused.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] `test_formal_monomorph.py` prints PASS for `an aliased import of a template is instantiated` (arm64 and x86_64 inside the case) and no new FAIL vs 15a's tally
- [ ] `test_formal_imports.py` tally unchanged vs 15a
- [ ] `grep -n local_defining_names formal/monomorph.py` shows the definition and both users

## If stuck
If a hunk no longer applies because the function it edited is gone, write the function name and what replaced it into §1.2 Status and stop.
