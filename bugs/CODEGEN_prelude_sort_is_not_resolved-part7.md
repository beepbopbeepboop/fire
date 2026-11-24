# CODEGEN: register the prelude `sort` so the bare call runs the real `std.builtin.sort`

Part 7 of `CODEGEN_prelude_sort_is_not_resolved` (see its SPLIT line). Depends on parts 1-6: register
`sort` only once the one-argument instance compiles, or the honest stub becomes a silent miscompile.

## Goal

Add `'sort': 'std.builtin.sort'` to `GimpleGen._PRELUDE_GENERICS` (`gimple_codegen.py:4702`), the table
`mojo/backend_gimple/emit_funcs.py` (around line 5412) registers for elaboration, so the bare prelude name
elaborates the real one-argument `sort` (`std/builtin/sort.mojo:530`, `sort[T: Copyable & Comparable, ...](span: Span[T, origin])`)
instead of the weak stub. Select the overload by arity through `elaborate.extract_fn_source(..., arg_count=1)`,
which already exists; do not special-case the name `sort`.

First check the one remaining blocker from the 2026-11-20 second-round list: an explicit
`from std.builtin.sort import sort` plus `sort(span)` must elaborate the real generic at its call site.
If it does not, fix that (the import must register the generic for elaboration, as `_register_imported_generics`
does for the prelude table) in this part, since it is the same registration path.

## Acceptance

- The program in the doc's Done-when, run through `fire.py build` and executed, prints `1` and does NOT print
  `unavailable in compiled mode`:

      def main() raises:
          var p = List(length=3, fill=0)
          p[0] = 3
          p[1] = 1
          p[2] = 2
          sort(p)
          print(p[0])

- The `test_prelude_sort_without_import_is_an_honest_stub` contract becomes "the real sort runs"; that test is
  updated accordingly, not deleted.
- Landing this clears the `closure: ... carries an unavailable in compiled mode stub` finding that
  `--dump-full` reports on every artifact, so `test_dump_full_reports_closure_stubs.py::test_clean_artifact_is_quiet`
  should pass. Verify that, do not assume it.

## Not in scope (record, do not fold in)

- `Some[def(T, T) -> Bool]` comparator arguments (`std/collections/counter.mojo:948`, the two-argument `sort`).
- The variadic `List[Int](3, 1, 2)` constructor, which builds and then fails at run time with
  `IndexError: list index out of range`.

Both stay in `bugs/hard/CODEGEN_prelude_sort_is_not_resolved.md`'s Status until they get their own docs.

## Done when

Add `test_prelude_sort_runs_the_real_sort` to `test_gimple.py`: build and run the program above and assert
stdout is exactly `1` and that `unavailable in compiled mode` is absent. Then run:

    python3 -m pytest test_gimple.py -k "test_prelude_sort_runs_the_real_sort or test_prelude_sort_without_import_is_an_honest_stub" -q

Both must pass.
