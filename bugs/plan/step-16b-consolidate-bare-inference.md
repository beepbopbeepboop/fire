# plan/step-16b: fold the two copies of bare-call inference into one function (behaviour-preserving)
Class: mid      Size: M      Depends: 15a      Blocks: 16c, 16d, 16e
Source: `bugs/FORMAL_known_limits.md` §1.2; CLAUDE.md "Consolidate duplicates rather than maintaining parallel implementations".

## Current state (measured 2026-11-05)
- Two parallel implementations of bare-call type-argument inference from `cd70b0fc5`: (1) `formal/monomorph.py::_bracketed_calls_pair.derive` (lines ~1062-1140, the `else:` branch for a bare callee in the CONSUMER's own module: builds `declared` from the enclosing FunctionDef params + `VarDecl` annotations, calls `elaborate.infer_type_args` / `infer_struct_type_args`); (2) `formal/monomorph.py::inferred_demands_for` (line ~1950-2166, for IMPORTED templates: a hand-written annotation matcher, with a `SIMD[...]` regex, duplicated for KIND_FN and KIND_STRUCT). Called from `formal/imports.py::instantiation_demands` (line ~2715, inside `try/except Exception: pass`).
- Only the test `a bare call to an imported template is inferred from argument annotation` (test_formal_monomorph.py ~3962) pins either path. After 15a the file has no debug litter.
- Swallowed exceptions: every inference block is wrapped in `except Exception: continue/pass`. A bug there silently turns into "refused".

## Decisions already made
- Create `formal/monomorph.py::infer_bare_call(consumer_stmts, enclosing_stmt, call, template_src, kind, module_level_values) -> tuple | None` returning the concrete type-argument tuple, or `None` for "not inferable" (caller keeps today's refusal). It reuses `elaborate.infer_type_args` / `infer_struct_type_args` as path (1) does; if those two cannot express a case path (2) handles (the `SIMD[T, w]` pattern, `Self.` prefix, default fallback via `elaborate.type_param_defaults` + `elaborate._default_type_arg`), port that case INTO the function rather than keep a second matcher. Both callers call it.
- Remove blanket `except Exception`: catch `MonomorphError` and `elaborate.ConformanceError` only; anything else propagates (a crash is better than a silent refusal during development; the sweep classifies it `backend-crash`).
- Scope helper: one `_declared_types_in_scope(stmts, enclosing_stmt) -> dict[name, annotation_string]` (the `declared` dict built twice today).
- Behaviour-preserving: same inputs -> same demands. Prove by running the test before/after and by a before/after dump of the demand sets over the two inline programs in the test file.

## Work order
1. Before editing: `python3 -c "..."` dump (write into `.tmp/before16b.txt`): for the 3 programs used by `a bare call to an imported template is inferred...`, `a bare call to an imported generic is still refused`, and `an inferred-parameter function is called without the bracket`, the outputs of `MM.all_instantiation_calls(src)` and `MM.inferred_demands_for(src, lib_src, ['widen'])`.
2. Implement `infer_bare_call` + `_declared_types_in_scope`; replace both blocks; delete `inferred_demands_for`'s body in favour of a loop over statements calling the new function (keep its name and signature: `imports.py` calls it).
3. Re-dump to `.tmp/after16b.txt`; `cmp` the two (must be identical).
4. Update the file's docstring for `inferred_demands_for` to say it is the imported-module entry to `infer_bare_call`.

## Do NOT
- Do not add any new inference ability here (16c-e do).
- Do not widen what is accepted; if the port of the SIMD case changes a dump line, the port is wrong.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
cmp .tmp/before16b.txt .tmp/after16b.txt
python3 tools/plan_index.py --check
```

## Done when
- [ ] `cmp` silent; both test files' tallies equal 15a's
- [ ] `grep -c "elaborate.infer_type_args\|infer_struct_type_args" formal/monomorph.py` shows them called from ONE function
- [ ] `grep -n "except Exception" formal/monomorph.py` shows none inside inference code

## If stuck
If removing a blanket except exposes a crash on a corpus input you cannot explain in 30 lines of reading, restore that single except with a comment naming the input, and record it in §1.2 Status.
