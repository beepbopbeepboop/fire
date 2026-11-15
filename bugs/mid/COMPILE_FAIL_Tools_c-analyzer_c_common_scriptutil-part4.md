# COMPILE_FAIL: scriptutil.py part 4 — remaining _iter_filenames/scriptutil generator shapes and module closure

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md` (SPLIT)

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

## Scope

After parts 1-3 remove the two named module-level refusals (`traceback_cm` and the
`process(...)` call in `_iter_filenames`), `scriptutil.py` is still expected to hit
downstream unsupported shapes recorded in the parent doc (2026-10-29 / 2026-10-02),
notably within `_iter_filenames` and its closure:

- `iterutil.peek_and_iter` usage and `next(...)` on a rebound list-iterator local (the
  `peek_and_iter` / iterator-cursor shape referenced by the parent).
- `iterutil.iter_many`.
- `yield from fsutil.process_filenames(...)` (yield-from a module/imported generator
  call result as needed here).
- A lambda inside a tuple yield (and related small expression forms used in this path).
- `yield from items` on a non-generator/local iterator value as it appears in this
  function.
- Any residual scriptutil-local generator shape that still prevents module compilation
  once the above are addressed.

This part is the integration/closure work to make the module-level refusal list empty.

## Dependencies

- Depends on part 1 and part 2 (clear `traceback_cm`).
- Depends on part 3 (resolve `process(...)` in `_iter_filenames`).
- Some iterator behaviors may overlap with separate bugs (e.g. `iterutil`/`next` on
  bound list iterator). Implement the minimal support needed for scriptutil's shapes,
  or record/align with existing bug docs if a blocker is truly external; do not
  duplicate fixes.

## Acceptance check

- `MOJO_DEBUG=1 python3 fire.py build -o <tmp>/scriptutil <copy>/c_common/scriptutil.py`
  (sources copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`, with required
  sibling modules available per closure) completes without the module-level generator
  refusal list, producing a `.cpp`/artifact as applicable for a successful build on the
  current tree. Run wrapped in `python3 tools/memslot.py --gb 8 --label scriptutil-build -- <cmd>`.
- If a specific residual shape is isolated first, add/verify a narrow compiled-vs-CPython
  regression for it in the appropriate test file, but the end-state acceptance for this
  part is the scriptutil module build succeeding.

## Notes

- Do not run whole-closure compiles, self-host builds, or the quality gate (per worker
  rules). If verification truly requires a heavier closure run beyond the single module
  build above, finish with `CONTROL-STATUS: PARTIAL` and list the exact needed suite jobs
  under `NOT DONE`.

## Status 2026-11-15 — the generator-shape closure is CLEARED; one non-generator
## shape still refuses

The finished branch `work/bug-mid-compile-fail-tools-c-analyzer-c-2` was assessed and
its still-correct parts were re-implemented on master (Adapt; the branch itself is 434
commits behind and conflicts in `cpp_core.py`/`cpp_async.py`). What that lands:

- `yield from <opaque word local>` (`items = iter(src)`; a tuple-unpacked element) is
  typed `int64_t` and driven through `mojo_iter_word`, co-yielding boxed words. When a
  sibling tuple-yield site decides the promise is `MojoList *`, the marked site is cast
  to that pointer (`cpp_async._cpp_adapt_word_iter_yields`). This is the
  `_iter_filenames` `yield from items` shape and `iterutil.peek_and_iter`'s nested
  `chain` generator.
- A `yield from <module>.<gen>(...)` delegate (e.g.
  `yield from fsutil.process_filenames(...)`) is typed through the whole-program
  `_generator_home_api` and EMITTED as real delegation, instead of the plain-collection
  path reading a generator handle as a `MojoList *` of strings.
- A zero-argument non-capturing `lambda` yielded as a tuple element is a plain
  function-pointer word, and a tuple-unpacked `int64_t` slot is a callable word (the
  `check = (lambda: True)` / `yield ..., check, ...` shape); tuple slots normalize a
  `std::function` ctype to the word the `MojoList` stores.
- A compiled-generator call with a trailing `**dict` spread binds each parameter by
  name with a runtime dict lookup (`iter_marks(groups=groups, **mark_kwargs)`);
  `<char *>.format(...)` lowers through `mojo_str_format_words`; a boxed word argument
  to a pointer parameter of a delegated generator is reinterpreted.
- GIMPLE: a function address in the variadic-callable path goes through the
  `_funcptr_` static, and the `MojoVarargFn` counts are operands (the old
  `(void *)f` / `(void)2` spellings are not legal GIMPLE).

Verified (each wrapped in `python3 tools/memslot.py --gb 8 --label <x> -- ...`):

- `python3 test_regress_yield_from_word_iterator.py` — fails on master before the
  change ("every `yield` must carry a value ... they disagree"), passes after.
- `python3 test_regress_scriptutil_generator_closure.py` — fails before (refused, then
  an invalid `std::function`→`intptr_t` cast when typed), passes after.
- `python3 test_regress_yield_from_module_generator.py` — passes (delegation pin).
- `python3 test_gimple_generator_runner.py` — 513 passed, 0 failed.
- `python3 test_gimple.py` — 461 passed, 0 failed.

The module build now gets past every GENERATOR shape. Because it stops at the
non-generator refusal below before the generator units are emitted, the closure was
measured in memory with the same widening applied only inside a measurement script
(tree unchanged): `compile_to_gimple_with_cpp` on the copied
`c-analyzer/c_common/scriptutil.py` emits C++ coroutine impls for `traceback_cm`,
`_flatten_processors`, `_iter_filenames`, `track_progress_compact`,
`track_progress_flat`, `iter_marks`, and stack-switch `__mgco_` units for
`_parse_files`, `filter_filenames`, `main_for_filenames` — every generator in the file,
with no whole-module generator fallback.

Remaining blocker, NOT a generator shape:
`normalize_selection` mixes `return True`/`False` with pointer arms and the GIMPLE
return emitter refuses a scalar arm in a `char *` function:

```
TypeError: function 'normalize_selection' is annotated to return 'char *'
  but has a return arm of type 'int'
```

Next step (do NOT copy the old branch's fix): that branch widened the return type to
the tagged word in `infra_infer._infer_return_type_core` only, and the widened word is
never marked as a box for consumers, so `normalize_selection(None)` then returned a
set pointer printed as `4383444896` (measured; CPython prints `None`). A correct fix
must box the arms like the float-mixed path (`_is_float_mixed_return` /
`_box_float_mixed_return_arm`) AND teach the call site that the result is tagged, or
refuse this shape with a diagnostic that names the mixed arms. `frozenset(...)` has no
`mojo_box_from_*` kind, so the set arm needs an explicit decision.

