# test_gimple.py aborts at the self-host signature check, so everything after it never runs

**State: OPEN.** Found 2026-10-29 while adding a regression to
`test_gimple.py` for `COMPILE_FAIL_decorator_application_dropped` (the
refusal in `module_gen.py`'s `_gmi_refuse_scalar_decorator_rebind`).

## What I ran and what I saw

    python3 tools/memslot.py --gb 8 --label test_gimple -- python3 test_gimple.py

Exit 1, 384 PASS lines, then an uncaught traceback:

    File "test_gimple.py", line 12708, in run_tests
      test_handwritten_selfhost_signature_tables_match_the_source()
    File "test_gimple.py", line 9513, in test_handwritten_selfhost_signature_tables_match_the_source
      _emitted = selfhost_emitted_return_type(_mod, _struct, _method)
    File "test_gimple.py", line 169, in selfhost_emitted_return_type
      c_src = compile_to_gimple(src, do_imports=False, filename=module)
    ...
    ValueError: method `__exit__` of class `_AR` reads `contains`, a parameter
    or local of `assert_raises`, which declares the class; ...

The module compiled is `fire_compiler.py`. Its `assert_raises` (line 35)
declares a class `_AR` whose `__exit__` reads the enclosing parameter
`contains`. That is the refusal added by commit 61e8f8c2b
(`CODEGEN_nested_class_method_cannot_reach_an_enclosing_local.md`), and it is
the RIGHT answer for that code: unrefused, the read would silently be 0.

The same run on the tree without my change exits 1 at the same place, so
this predates the decorator work.

## Why it matters

`run_tests()` calls every test in one straight-line list. An uncaught
exception in one of them stops the run, so every test registered after
line 12708 never executes and the run exits 1 with no summary. The
decorator regression is one of those, which is how it was found. Any test
added below that call is silently unexercised.

## Expected

`test_handwritten_selfhost_signature_tables_match_the_source` should either
compile the defining module, or the refusal should not fire on
`fire_compiler.py`. Either way `run_tests()` should contain each test's
failure rather than letting one exception hide the rest.

## Next step

1. Decide: the real fix is to thread the enclosing frame into a nested
   class's methods (the refusal's own TODO). Until then, rewrite the
   `fire_compiler.py` `assert_raises` helper so it does not declare a class
   inside a function (it is a 3-line helper; the class can be module-level
   and take `contains` as an instance field). Confirm the refusal no longer
   fires with `python3 -c "from gimple_codegen import compile_to_gimple; ..."`
   on `fire_compiler.py`.
2. Make `run_tests()` isolate each test (try/except, record FAIL) so one
   crash cannot hide the rest of the list.
