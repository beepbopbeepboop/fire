# CODEGEN: the prelude `sort` is not resolved without an explicit import

`sort` is a prelude name (`std/prelude/__init__.mojo:127`, `from std.builtin.sort import partition, sort`),
so Mojo code calls it with no import. `fire.py build` of

    def main() raises:
        var p = List(length=5, fill=Scalar[DType.int8](3))
        sort(p)
        print(len(p))

fails at link time with `Undefined symbols ... "_sort"`: the call lowers to a bare `sort` that nothing defines.
With `from std.builtin.sort import sort` it builds, but the call is the weak stub and prints
`sort: unavailable in compiled mode`, so the real `sort` is not compilable either.

Measured 2026-11-19. Found while landing the nested-bracket fix: `test/builtin/test_sort_issue_1018.mojo`
called it inside a generic and only failed `gcc -c` once that generic was really instantiated.
(That failure is gone: it was the instance not seeing its module's imports, a different defect.)

## What was tried

Adding `'sort': 'std.builtin.sort'` to `GimpleGen._PRELUDE_GENERICS` (the `alloc` mechanism,
`mojo/backend_gimple/emit_funcs.py::_register_imported_generics`) makes the call elaborate the real `sort`,
which then fails with `invalid conversion in gimple call` at `std/collections/counter.mojo:948` and
`invalid use of void expression` at the call. Reverted.

## Exact next step

1. Decide the contract: an unimported prelude `sort` should resolve exactly as the imported one (honest
   weak stub) until `std.builtin.sort` compiles. Make the unresolved bare name register that stub.
2. Then make `std.builtin.sort.sort` compile (the `counter.mojo:948` conversion and the `void`-used-as-value).
3. Test: the program above prints `5`, and `print(p[0])` after a sort of `[3, 1, 2]` prints `1`.

## Status 2026-11-20: step 1 landed; step 2 is still open

- The unresolved prelude `sort` no longer fails at link time. Its predeclared
  util stub (`_util_pairs` in `mojo/backend_gimple/module_gen.py`) is now the
  same honest weak definition the unknown-name path emits:
  `sort: unavailable in compiled mode`. The doc's program builds with
  `fire.py build` and runs, printing `sort: unavailable in compiled mode5` (the
  stub prints without a newline, as the unknown-name stub does) and then `5`.
- Gates: stdlib compile `FAILED: 0 (0 expected, 0 unexpected)` and the dylib
  `1203 of 1203` with no skips, both identical to master's.
- Not done: step 2 (make `std.builtin.sort.sort` compile, which is the
  `counter.mojo:948` conversion and the void-as-value). Step 3's `prints 5` /
  sorted-value test therefore does not hold yet, and this doc stays open.

## Status 2026-11-20 (second round): measured blockers for step 2, in order

Measured on master with `fire.py build` (link mode):

1. **An explicit import does not instantiate the generic.** `from std.builtin.sort
   import sort` + `sort(span)` builds and runs, and prints the weak stub, so the
   real `sort[...]` is never elaborated for an imported generic. Only the
   `_PRELUDE_GENERICS` path tries (`alloc` works that way). The first
   instantiation step is to make the import of a generic function register it for
   elaboration at the call, the way `_register_imported_generics` already does for
   the prelude table.
2. **Elaborating `sort` with the prelude table set fails in the stdlib, not at the
   call.** `std/collections/counter.mojo:948` (`sort(items, comparator)`, a nested
   `def` passed as the `Some[def(T, T) -> Bool]` argument) gives `invalid conversion
   in gimple call`. The call site in the user program gives `invalid use of void
   expression`. A user-defined generic that returns nothing (`def bump[T](mut x: T)`)
   builds and runs, so the void error is specific to the elaborated `sort`
   (overload choice between the two `sort` overloads, or the instance's return type).
3. **`sort(p)` with a `List` needs an implicit `List` -> `Span` conversion**, which
   the compiler does not perform for a generic argument. With an explicit `Span(p)`
   the call type-checks; the conversion is a separate step.
4. **`List[Int](3, 1, 2)` (variadic constructor) builds and then fails at run time
   with `IndexError: list index out of range`.** Separate from `sort`; it blocks
   writing step 3's test with a literal list, so the test uses `List(length=, fill=)`
   and item assignment for now.

Next round, in this order: (1) make an imported generic function elaborate at its
call site, measured on `sort(sp)` with an explicit `Span`; (2) fix the nested-`def`
argument conversion that `counter.mojo:948` hits; (3) the void-as-value of the
elaborated instance; (4) the `List` -> `Span` implicit conversion; (5) step 3's
test. Each step has its own program above; the bug stays open until (5) passes.

## Status 2026-11-20: the unconditional stub now reaches the closure gate (measured)

- Every `--dump-full` artifact now carries the prelude `sort` stub, whether or not
  the program mentions `sort`. A one-line program (`def f(n): return n + 1` +
  `print(f(1))`) dumps `prog.ci` with `_util_pairs`'s `sort(...)` weak stub at
  line 308 (`sort: unavailable in compiled mode`).
- That matters because master's `--dump-full` (commit 5468c8f80, "reports the
  weak stubs its .ci carries") prints `closure: <name>.ci carries an unavailable
  in compiled mode stub` on that artifact. The line contains the phrase that
  `tools/suite.py`'s `CLOSURE_INCOMPLETE` rejects, so `bootstrap-stage1-transitive`,
  `bootstrap-stage2-transitive` and `bootstrap-stage3-transitive` reject their
  output on master. Not gated yet: this was measured with the quick fixture only,
  not a bootstrap run.
- `test_dump_full_reports_closure_stubs.py` on master: `test_stub_in_artifact_is_reported`
  passes; `test_clean_artifact_is_quiet` fails on the `assert PHASE not in ci`
  line, for the reason above. The test's premise (a program with no stub) is no
  longer true until this bug's stub goes away.
- Consequence for this doc's plan: step 2 (a real `std.builtin.sort.sort`) is what
  clears it. An interim choice is open for the controller: emit the predeclared
  stub only when `sort` is referenced, which clears the closure gate sooner and
  is a separate decision from step 2.
