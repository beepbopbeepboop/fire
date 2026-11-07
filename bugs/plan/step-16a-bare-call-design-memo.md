# plan/step-16a: DESIGN MEMO — what a bare template call's type arguments may be inferred from
**Status: DONE 2026-11-07 (measured).** The memo is `bugs/FORMAL_known_limits.md` §1.2 "Design: inferring a bare call's type arguments (2026-11-07, step 16a)": census re-run (120 calls; 4/30/72/6/8/0/0), Q1 = R1 declared-types-only, Q2 = B1 (B2 only for a concrete declared struct), Q3 = refuse by name; the deciding finding is that 25/26 `dealloc`, 17/17 `ThinAllocation`, 20/20 `FormatStruct` and 14/14 `Named` callers are themselves generic or take `Some[Writer]`, so declared-type inference unlocks only about 16 of 120 sites and the export gate row moves only with caller monomorphisation. The interface signature and per-step decisions are in the section.
Class: hard      Size: M      Depends: 15a      Blocks: 16c, 16d, 16e
Source: `bugs/FORMAL_known_limits.md` §1.2 (RE-MEASURED 2026-10-04: 123 bare calls); the deleted inference doc `bugs/formal/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md` (last text: `git show cd70b0fc5^:bugs/formal/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`, 496 lines; §5 and §5b are the census findings quoted here).
Output: ONE committed design section "§1.2 Design: inferring a bare call's type arguments" in `bugs/FORMAL_known_limits.md`, and nothing else (no code).

## Current state (measured; verified 2026-11-05)
- Landed in `cd70b0fc5` (low quality, see 16b): `formal/monomorph.py::inferred_demands_for` (line ~1950) and a second copy inside `_bracketed_calls_pair` (line ~1063) infer ONLY when every deciding argument is a bare identifier (`IdentExpr`) with a written string annotation (a parameter or a `var x: T`) and the template parameter annotation is `T`, `Self.T`, `SIMD[T, w]`, or merely mentions T. Cases it cannot do return nothing and the call keeps today's refusal (test `a bare call to an imported generic is still refused` pins `widen(5)`).
- Census (`python3 tools/formal_template_call_census.py`, buckets = the seven questions; 115 call sites over 420 files, measured 2026-10-04 §5b): solvable-from-annotations **2**; written-but-does-not-unify (trait-bounded: `FormatStruct(writer, "Allocation")`, `isnan`) **28**; argument type NOT written (`dealloc(allocation^)` — a `UnaryOp` — and `Named(...)`, `ThinAllocation(unsafe_owned_ptr=self._data)` needing a FIELD's declared type) **71**; phantom with no default **5**; comptime-default **8**; no type parameter **0**; unreadable **1**. The 123-file export-gate row is 68 `FormatStruct`, 29 `dealloc`, 13 `is_negative`, 6 `PhiloxRandom`, 3 `align_up`, 4 singles.
- Nothing in `formal/` computes a function's result type from its body. `elaborate.infer_type_args(template_src, arg_ctypes)` (elaborate.py:878) and `infer_struct_type_args` (:922) exist and are what 16b consolidates onto.
- The tool needs a fixed tree: step 15a first. The census tool also needs the stdlib checkout `../modular/mojo/stdlib` (`module_loader.STDLIB_PATH`).

## Decisions already made
- This is a memo step: the worker decides the three questions below FROM MEASUREMENT and writes the section. Defaults (take them unless the measurement refutes them, and say so if refuted):
  Q1 (arguments whose type is not written): **R1 — declared types only.** The type of an expression is read from declarations: a local's `var x: T` or the declared `->` annotation of the callee in the initialiser (`var a = alloc(...)` gets `alloc`'s declared return annotation), a parameter's annotation, a struct field's declared annotation (`self._data` -> `model.struct_field_type`). Never from a function BODY. Rejected: R2 body-based return-type inference (no machinery; invariant 3 "no fabricated value").
  Q2 (existential vs trait bound, `writer: Some[Writer]` against `T: Writer`): decide among (B1) keep refusing; (B2) instantiate `T := <the argument's declared concrete type>` only when the declared type is a concrete struct (not `Some[...]`/a trait name), refuse otherwise; (B3) bind `T := Writer` the trait itself. Default **B2**, because B3 invents a type the callee never sees and B1 leaves 68 files.
  Q3 (the callee's own parameter as the answer, `is_negative(val)` inside `def bit_width[dtype: DType, ...](val: SIMD[dtype, width])` gives `dtype := dtype`): default **refuse by name** (no instantiation can be mangled under an unbound parameter); the caller would itself have to be instantiated (that is monomorphising the CALLER; out of scope).
- Defaults/phantoms/comptime defaults: a default that IS a type spelling (`result_type: AnyType = NoneType`) settles the parameter; a comptime-VALUE default (`False`, `CompilationTarget.current()`) does not, and the call stays refused.

## Work order
1. Run the census twice for the record: `python3 tools/memslot.py --gb 8 --label tlc -- python3 tools/formal_template_call_census.py --rows 12` (write the bucket table into the memo; compare with the 2026-10-04 table above and state the delta).
2. For Q1: list the sites of the 71-bucket by callee (the `--rows` output), and for the top 5 callees (`dealloc`, `Named`, `ThinAllocation`, ...) read the call site + the enclosing declaration and state, per callee, whether R1 resolves it (yes / no + the missing fact). Count sites resolved. 
3. For Q2: read `std/format/_utils.mojo:287` (`FormatStruct`), the 3 callers' argument declarations, and state whether B2 resolves each (the argument is `Some[Writer]` for most -> B2 would REFUSE; if that is the case for >50% of the 28, say so and set the default to B1 with the 68-file row declared a true limit until a trait-object story exists).
4. Write the section: for each Q the reading chosen, the count of sites it unlocks, the rejected readings and why, and the exact interface the execution steps implement: `infer_bare_call(consumer_stmts, call_node, scope) -> tuple[str, ...] | Refusal(reason)` in `formal/monomorph.py` (16b creates the function with today's behaviour; 16c/16d/16e extend it).
5. Commit with the doc edit only.

## Do NOT
- Do not write code or edit tests. Do not leave a "decide later" in the memo: each Q ends with one chosen reading.
- Do not claim a count that the census did not print.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label tlc -- python3 tools/formal_template_call_census.py --rows 12
python3 tools/plan_index.py --check
```

## Done when
- [ ] `bugs/FORMAL_known_limits.md` has the section with Q1, Q2, Q3 each answered, counts, and the interface signature
- [ ] 16c/16d/16e's "Decisions already made" can be written from it without re-investigating (state which step each decision feeds)

## If stuck
If the census tool cannot run (stdlib checkout missing), write that and the exact missing path into §1.2 Status and stop.
