# plan/step-16e: bare-call inference against a trait bound (the `FormatStruct(writer, ...)` row)
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
