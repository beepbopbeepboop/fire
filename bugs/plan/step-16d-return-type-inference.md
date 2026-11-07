# plan/step-16d: bare-call inference through declared types (the `dealloc(allocation^)` row)
Class: mid      Size: L      Depends: 16a, 16b      Blocks: 16f
Source: 16a's committed design section (Q1) in `bugs/FORMAL_known_limits.md` §1.2; `bugs/FORMAL_known_limits.md` §1.2 2026-10-04 (dealloc 29 files, `std/memory/alloc.mojo:99`, `dealloc` declared `:904`).

## Current state (verify first: `grep -n "Design: inferring" bugs/FORMAL_known_limits.md` must find 16a's section; if absent STOP)
- 71 of 115 call sites are in the "argument type not written" bucket: the argument is a `UnaryOp`/transfer (`allocation^`), a call, a field read (`self._data`).
- Machinery that exists: `model.struct_field_type` (declared field type), function declarations' `return_type`, `F.VarDecl.type_ann`. Nothing computes a result type from a body (and this step must not).

## Decisions already made
- Implement exactly the reading 16a chose for Q1 (default R1: DECLARED types only). Add `_declared_type_of_expr(expr, scope) -> str | None` to `formal/monomorph.py` handling, in this order: identifier (annotation), `x^` transfer / `UnaryOp` wrapping an identifier (type of the identifier), `self.f` field read (declared field annotation of the enclosing struct), call to a function/ctor with a declared return annotation (that annotation, with the callee's own template parameters substituted if the call itself was inferred); a local `var a = <call>` gets the call's type. Anything else -> `None`.
- `infer_bare_call` (16b) calls it for every deciding argument that has no written annotation.
- Unification of the declaration's parameter annotation (e.g. `Allocation[T, ...]`) with the argument's type string: only equal head names with the same bracket arity; bind each template parameter that appears at a position to the corresponding argument; any `_`/unresolved position -> `None`.

## Work order
1. Implement `_declared_type_of_expr` + head/arity unifier; wire into `infer_bare_call`.
2. Unit cases (decision-only, no build) in `test_formal_monomorph.py` using `MM.infer_bare_call`/`inferred_demands_for` on small sources: transfer arg (`consume(x^)`), field read, call-initialised local, and the refusals (`x = something_untyped()`, a body-only return).
3. One end-to-end case on both arches with CPython twin: library `struct Box[T]: var v: T`, `def make() -> Box[Int]`, `def unwrap[T](var b: Box[T]) -> T`; program `var b = make(); print(unwrap(b^))` -> prints the value. (Adapt syntax to what the existing cases in the file accept; copy `test_an_inferred_parameter_function_is_called_without_the_bracket`'s skeleton.)
4. Census re-run; paste bucket deltas into §1.2 Status. Then run ONE real file for the alloc row: `python3 tools/memslot.py --gb 8 --label fmt -- python3 fire.py build --formal --no-prove -o .tmp/alloc16d.aout ../modular/mojo/stdlib/std/memory/alloc.mojo` and record the (new) terminal message verbatim; the refusal advancing one level is expected and is a valid result.

## Do NOT
- Do not read function bodies for a return type.
- Do not cache an inferred instantiation under the bare name: the CAS key is `(template, concrete args)`.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] the new unit and end-to-end cases PASS; earlier tallies unchanged
- [ ] §1.2 Status states census before/after and the new terminal message of `alloc.mojo`

## If stuck
If the real stdlib `dealloc` row needs a fact not in 16a's list, write it into §1.2 Status as the next concrete blocker and stop after landing what passes.
