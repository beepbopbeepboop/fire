# plan/step-15d: refuse, by name, a type argument declared only in the consumer's file
**Status: DONE 2026-11-06 (measured).** 'a consumer-declared type argument is refused by name' PASSES; `test_formal_monomorph.py` 60/0/0 on 2026-11-06.
Class: mid      Size: S      Depends: 15a      Blocks: none
Source: deleted `bugs/formal/FORMAL_generic_monomorph_scope.md` §4 and §5 (`git show 4fdf0a95d^:...`).

## Current state (documented 2026-10-12, UNVERIFIED on this tree: run the probe in Work order 1 first)
- lib declares `struct Pair[T]: var first: T` + `def get_first(self) -> T`; program declares `struct Colour: var rgb: Int` and does `Pair[Colour]()`. The doc measured: it BUILDS (the library compiles `Pair_1_T_6_Colour` with `Colour` undeclared in its own module), and the first use that needs the layout (`var v: Int = c.rgb`) refuses with "this path has no way to say what `c` holds". Without the method the export gate refuses instead. No test pinned either half. This is a layout question deferred to first use: a wrong answer waiting if a use does not need the layout.

## Decisions already made (so no design latitude)
- Refuse at the DEMAND, with a message true of the file: "`Pair[Colour]` is compiled into `<lib>`'s library, and `Colour` is declared in this file, which that library cannot see; declare `Colour` in a module both import". Layout threading across the boundary is out of scope.
- Where: `formal/imports.py::instantiation_demands(module_path, consumer_src, ...)` (line ~2640) knows both the consumer source and the defining module (`p`). After `got` is computed for module `p`, drop+record any demand whose type argument is a struct/class NAME declared by the consumer (`MM.template_struct_names`-style scan: use `fire_compiler` parse of `consumer_src`, collect `F.StructDef` names) and NOT declared by the module at `p` (parse `module_source_text(p)` the same way). Record the failure through `MM._record_failed_demands([(template, args, message)])` ONLY if 15c has landed (`grep -n _record_failed_demands formal/monomorph.py`); otherwise raise `ImportBuildError(message)` the way the neighbouring code does for a failed demand (read how `imported_instantiations` reports `failed`).
- A type argument that BOTH files declare, a builtin (`Int`, `Bool`, `String`, `Float64`), or a name the library imports is accepted as today.

## Work order
1. Probe: write the two-file program above in a tmpdir via the test helper `run_pair_case`/`build_pair_case` (see `test_a_struct_template_the_module_declares_can_itself_apply` line 468 for the call shape) and record what happens today (build/refuse + message) in a new case's docstring.
2. Implement the check at the location above.
3. New cases (in `TESTS`): `a consumer-declared type argument is refused by name` (both arches; asserts the message contains `is declared in this file`), and control `a builtin type argument is still instantiated` (copy `test_a_generic_struct_template_is_instantiated_at_the_importers_type`'s program, CPython differential).
4. Dated Status paragraph in `bugs/FORMAL_known_limits.md` §1.2.

## Do NOT
- Do not accept the type by threading its layout; do not change `type_arg_text`.
- Do not refuse a template instantiated in the consumer's OWN file (that path is local, line 468's case).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] the new refusal case and control PASS; no other verdict changes vs 15a/15c tally

## If stuck
If the probe shows the program is already refused with a true message, pin that message in the case, say so in the Status paragraph, and stop (that is a valid finish).
