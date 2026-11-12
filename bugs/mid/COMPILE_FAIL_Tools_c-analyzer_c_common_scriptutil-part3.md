# COMPILE_FAIL: scriptutil.py part 3 — callable-parameter signature discovery in generator bodies

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md` (SPLIT)

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

## Scope

`_iter_filenames` (scriptutil.py:561) is refused because it calls its unannotated
parameter `process` as `process(filenames, relroot=relroot)` inside a compiled
generator body. The emitter cannot resolve the callee (no declared callable ctype for a
parameter; existing callable ctypes do not cover this signature/keyword form).

This part implements **Decision 1 (A)** from the parent doc: discover the callable
parameter's signature from call sites and give the parameter a declared callable ctype
matching the call shape, so such calls lower in generator/coroutine bodies.

Out of scope: downstream iterator/helper shapes still used by `_iter_filenames`
(`iterutil.peek_and_iter`, `next` on rebound list-iterator locals, `iterutil.iter_many`,
`yield from fsutil.process_filenames(...)`, lambda-in-tuple-yield, `yield from` on a
non-generator local), and `traceback_cm`.

## Implementation notes

- As sketched in parent: a pass (e.g. in `module_gen.py` before per-function emitters)
  to collect callable-param signatures for generator/coroutine-relevant callees
  (`_iter_filenames`, `main_for_filenames`/`iter_files` callers passing concrete
  functions like `process_filenames`), plus a callable ctype/emit path that can carry
  the needed positional+keyword signature.
- Touch emitter callee resolution in `mojo/backend_gimple/cpp_core.py` /
  `cpp_async.py` as needed so the parameter is treated as a declared callable value.

## Acceptance check

- A compiled reproducer (e.g. as suggested in parent): a generator that takes an
  unannotated callable parameter and calls it with a positional argument and a keyword
  argument, passed a concrete module function at call sites, compiles and its output
  matches CPython (`cpp_coroutine_callable_param_keyword_call_compiled_vs_cpython`-style
  test in `test_gimple_generator_runner.py` or equivalent narrow location).
- Narrow verification only, wrapped in `python3 tools/memslot.py --gb 8 --label <what> -- <cmd>` if it compiles.

## Not in this part

- `traceback_cm` (parts 1-2).
- Remaining `_iter_filenames`/scriptutil closure shapes after `process(...)` resolves
  (part 4).
