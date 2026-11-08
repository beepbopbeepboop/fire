# plan/step-16e: bare-call inference against a trait bound (the `FormatStruct(writer, ...)` row)
**Status: DONE 2026-11-07 (measured).** Q2 reading B1 + B2-for-concrete-struct implemented and pinned: a bare call binds a bounded parameter to a concrete declared struct (`greet_it(d)`, `d: Dog`, runs, CPython twin, both arches); a non-conforming struct is refused with `does not conform to trait 'Greet'` (the `except Exception: pass` in `formal/imports.py` swallowed the `MonomorphError`; it now re-raises conformance errors only); a `Some[...]` argument is never bound (`_inferred_binding_ok` rejects it) and the refusal names the existential argument (`imported_callee_refusal(existential_args=...)`). **Found and fixed on the way (a wrong-code bug in 16b):** the bare-call fast path passed Mojo annotations to `elaborate.infer_type_args`, which takes C types; `c_to_mojo` maps every unknown spelling (`Float64`, `Bool`, `String`, any struct) to `Int`, so `T` was bound to `Int` for anything but `Int` (the earlier cases only used `Int`). The fast path is removed; `_bind_from_annotations` binds the annotation itself; decision case `a bare call binds the declared annotation, not Int` pins Float64/Bool/String/Int. `test_formal_monomorph.py` 70/70, `test_formal_imports.py` 90 PASS / 5 FAIL (was 89/6; the 5 are the host-module/environment rows), `test_formal_runtime_link.py` 225/225. Not done: the census re-run, and the unannotated `var d = Dog()` still gives no inference (declared types only, R1).
Class: mid      Size: M      Depends: 16a, 16b      Blocks: 16f
Source: 16a's design section (Q2) in `bugs/FORMAL_known_limits.md` §1.2; `std/format/_utils.mojo:287` `struct FormatStruct[T: Writer, o: MutOrigin]`, caller `std/memory/alloc.mojo:450`.

## Current state (verify first: 16a's section exists)
- The parameter is `ref[Self.o] writer: Self.T` bounded `T: Writer`; the parser normalises it to annotation `Self.T` + conv `ref` (the `o` mention is NOT in the AST; read the declaration SOURCE, §5 of the deleted inference doc). The argument is `writer: Some[Writer]`: an existential. 28 sites, 68 files.

## Decisions already made
- Implement exactly the reading 16a chose for Q2. If 16a chose B2: bind `T := <argument's declared annotation>` only when it is a concrete struct name accepted by `type_arg_text` and `elaborate.check_bounds` (via `instantiate`) accepts it; `Some[...]`, `Self.T`, a trait name -> `None`. If 16a chose B1 (keep refusing): this step only changes the REFUSAL TEXT in `formal/model/module.py::imported_callee_refusal` (line 1996) to name the true limit ("the argument's type `Some[Writer]` is an existential; this path cannot choose a concrete `T`") and adds the case pinning it; no inference code.
- `o` (an origin parameter) is settled by its default; if it has none the call is `None`.

## Work order
1. Read 16a's Q2 answer; follow the matching branch above.
2. Cases (both arches, CPython twin, copy skeleton of `test_a_bare_call_to_an_imported_template_is_inferred_from_argument_annotation`): bounded template + argument of a concrete conforming struct -> runs; argument not conforming -> refuses with `does not conform` (needs 15c; if 15c not landed omit and say so); existential argument -> refuses with the new/old text.
3. Census delta into §1.2 Status.

## Do NOT
- Do not bind `T` to a trait name. Do not guess among several candidate writers.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] new cases PASS; no verdict regressions vs 16b tally; Status paragraph written

## If stuck
Record the blocker in §1.2 Status and stop.
