# CODEGEN: `for x in <list literal>` inside a nested generator emits a range-for over a `MojoList *`

Observed 2026-11-12 on `work/bug-codegen-nested-generator-method-incl` at HEAD 5950448db:
`python3 tools/memslot.py --gb 8 --label nested -- python3 test_gimple_generator_runner.py`
gives `478 passed, 4 failed`. Two of the four are this defect:

- `nested_recursive_generator_runtime_getattr_default`
- `nested_recursive_tuple_generator_runtime_getattr`

Both fail with gcc errors in the generated C++:

    prog_gen.cpp:151:189: error: 'begin' was not declared in this scope
    prog_gen.cpp:151:189: error: 'end' was not declared in this scope

The offending line is
`for (auto fld : [&]() -> MojoList * { MojoList *_mg_lit_2 = mojo_list_new (); ... return _mg_lit_2; }()) {`

The source is a nested recursive generator that loops over a literal tuple of strings:

    def walk(xs, depth: Int):
        for i, st in enumerate(xs):
            yield i
            for fld in ('v', 'missing'):
                sub = getattr(st, fld, -1)
                yield sub

The literal is lowered to a `MojoList *` (a boxed list pointer), but the range-for
over it is emitted as a C++ range-for, which needs `begin`/`end` on a pointer. A
`MojoList *` is not a C++ range.

## Expected

The generated C++ iterates the literal through the runtime list API (index loop
over `mojo_list_len` / `mojo_list_get_*`, or the existing boxed-list iteration the
emitter uses for a non-literal `MojoList *`), and both tests print the CPython
stdout.

## Where to look

- `mojo/backend_gimple/cpp_core.py`: the range-for fallback. Comments near lines
  9887, 10026 and 10058 say the generic `for (auto x : ...)` range-for is the path
  that cannot take a bare `MojoList *`. The list-literal lowering is
  `_cpp_boxed_list_literal_expr` (around cpp_core.py:2145-2170).
- Each of the two tests fails singly; reproduce with a one-test driver before editing.

## Exact next step

1. Dump the C++ for `nested_recursive_tuple_generator_runtime_getattr` via
   `gimple_codegen.compile_to_gimple_with_cpp` and confirm the range-for line above.
2. Find the emitter that writes `for (auto <target> : <iterable>) {` for a
   list-literal iterable and route a list-literal (or any `MojoList *`) iterable
   through the existing index-based boxed-list loop instead. Do not special-case
   the test names or the `getattr` shape.
3. Verify both tests pass, then `python3 test_gimple_generator_runner.py` shows no
   `g++ compile` failure for them.
4. Delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
