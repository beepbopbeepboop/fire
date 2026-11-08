# plan/step-16c: bare-call inference — keyword arguments and type-spelled defaults
**Status: DONE 2026-11-07 (measured).** Extended `formal/monomorph.py::infer_bare_call`/`_bind_from_annotations` for keyword arguments (matched to function parameters by name; unknown keyword -> not inferable) and type-spelled defaults (a default whose text parses as a type spelling accepted by `type_arg_text` may settle an uninferred template parameter; comptime-value defaults like `False`/`CompilationTarget.current()` leave inference refused). Defect #3 enforced: an inferred result that is the enclosing template's own parameter or `Self.T` -> not inferable (checked via `consumer_src` threaded through `_bare_call_demand`). Rewrites preserved (bare `IdentExpr` calls rewritten when a single instantiation candidate exists; args/kwargs kept). Tests: 4 cases added to `test_formal_monomorph.py` + `TESTS` (`a keyword argument decides a bare call's type argument`, `a type-spelled default settles an uninferred parameter`, `a comptime-value default leaves the bare call refused`, `a callee's own parameter is not an inference`) — all PASS on both arches; `test_formal_monomorph.py` PASS=64 EXPECTED=0 SKIP=0 FAIL=0 (was 60 at 16b). `test_formal_imports.py` PASS=89 EXPECTED=0 SKIP=0 FAIL=6 (6 failures in host-module advice/wall verdict/instrument and bounded-time sweep classification — same pre-existing class as 16b noted; not caused by monomorph changes). Census (`tools/formal_template_call_census.py`, 468 files, 120 bare calls): solvable 4, written-but-not-unify 30, not-written 72, not-in-args 6, comptime-default 8, no-type-param 0, unreadable 0 — solvable delta vs 16a baseline (4) is 0 (census classifies by its own criteria; 16c enables kwargs/type-spelled-default inference in the implementation).
Class: mid      Size: S      Depends: 16a, 16b      Blocks: 16f
Source: `bugs/FORMAL_known_limits.md` §1.2 (inference doc §5b via `git show cd70b0fc5^:bugs/formal/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`, "5b").

## Current state (measured 2026-11-05)
- `formal/monomorph.py` inference iterates `node.args` only; a KEYWORD argument lives in `call.kwargs` (census defect #1 of §5b: 20 sites misfiled). Defaults: `infer_bare_call` (16b) falls back to a default only if `elaborate._default_type_arg` returns a type.
- The two real "matcher" sites the census found: `std/collections/string/string_span.mojo:2893  is_negative(rhs)` with `var rhs: Int` -> `dtype := Int`; `std/ffi/__init__.mojo:665  dlsym(self.handle, ...)` with `result_type: AnyType = NoneType` -> `result_type := NoneType`.

## Decisions already made
- Match `call.kwargs` entries to the template's parameters by NAME, positional args by position; unknown keyword -> `None` (not inferable).
- A parameter settled by a default is bound only when the default text is a type spelling accepted by `type_arg_text`; a comptime-value default (`False`, `CompilationTarget.current()`) leaves the call refused (§5b "comptime default" bucket, 8 sites).
- A result that is the enclosing template's own parameter or a `Self.T` -> `None` (§5b defect #3).
- The call site must be REWRITTEN to the mangled name the demand carries (`rewrite_instantiation_calls`): confirm with the end-to-end case that the program RUNS (an inference with no rewrite is "a worse answer than the refusal").

## Work order
1. Extend `infer_bare_call` for kwargs and defaults per the decisions.
2. Cases in `test_formal_monomorph.py` + `TESTS` (each `run_pair_case` on both arches with a CPython twin): `a keyword argument decides a bare call's type argument` (`def widen[T: Intable](v: T) -> T`, call `widen(v=x)` with `var x: Int = 7` -> `7\n`); `a type-spelled default settles an uninferred parameter` (`def pick[T: AnyType = Int](v: Int) -> Int` bare call); controls: `a comptime-value default leaves the bare call refused` (`def masked[T: Intable, flag: Bool = False](v: T)` -> refusal, build must fail with the existing bare-call text); `a callee's own parameter is not an inference` (call inside another template with `v: T`).
3. Re-run the census: `python3 tools/memslot.py --gb 8 --label tlc -- python3 tools/formal_template_call_census.py`; paste the "solvable" delta into a dated Status paragraph in §1.2.

## Do NOT
- Do not infer from literal arguments (`widen(5)`): the pinned refusal case must stay.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] the 4 new cases PASS; `a bare call to an imported generic is still refused` still PASSES
- [ ] no other verdict change vs 16b tally

## If stuck
Record the failing case and its output in §1.2 Status and stop.
