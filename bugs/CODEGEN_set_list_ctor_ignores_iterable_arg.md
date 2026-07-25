# CODEGEN: `set(iterable)`/`list(iterable)` silently produce an EMPTY collection in compiled code

## Repro

```python
def f():
    s = set([1, 2, 3, 3])
    print(len(s))          # prints 0 instead of 3
    for x in s:
        print(x)            # prints nothing

def g():
    l = list([1, 2, 3])
    print(len(l))           # prints 0 instead of 3

f()
g()
```

- `python3 mojo.py run repro.py` (interpreter): correct — prints `3`, then
  `1`/`2`/`3`, then `3`.
- `python3 mojo.py build repro.py -o out && ./out`: compiles with NO error
  or warning, but silently prints `0` for both `len(s)` and `len(l)`, and
  the `for x in s:` loop prints nothing — the constructed collection is
  empty. This is a silent-wrong-result bug, not a compile failure, so it's
  especially dangerous (no diagnostic at all).

Real stdlib trigger: `Lib/test/test_type_cache.py:55` (`len(set(all_version_tags))`
where `all_version_tags` is a list) actually surfaces as a DIFFERENT,
loud compile-time error there (`error: invalid conversion in gimple call`,
`bugs/COMPILE_FAIL_test_test_type_cache.md`) rather than this silent-empty
symptom — likely because that call site's exact surrounding shape (nested
inside an f-string default-arg / assertEqual call) hits a different
downstream inconsistency stemming from the same root cause. Also found via
`Lib/test/test_largefile.py`-adjacent investigation that `list(iterable)`
has the identical bug.

## Root cause

`gimple_codegen.py`'s `_lower_builtin_set` (~line 8965-8968):

```python
def _lower_builtin_set(self, node: CallExpr) -> tuple[str, str]:
    t = self._new_val('MojoSet *', 'mojo_set_new ()')
    for a in node.args: self.lower_expr(a)
    return 'MojoSet *', t
```

and `_lower_builtin_list` (~line 8984-8985):

```python
def _lower_builtin_list(self, node: CallExpr) -> tuple[str, str]:
    return 'MojoList *', self._new_val('MojoList *', 'mojo_list_new ()')
```

Both unconditionally create a brand-new EMPTY collection and either lower
the constructor argument's code for side effects only and discard the
result (`set`), or don't even look at the argument at all (`list`) —
neither ever actually populates the new collection from the argument
iterable. Compare `_lower_builtin_dict` (~line 8970-8982), right between
them, which correctly handles being passed an existing iterable
(`mojo_dict_from_pairs` for a `MojoList *` of pairs, `mojo_dict_copy`
otherwise) — `set`/`list` never got the equivalent treatment.

`runtime/mojo_runtime.h` has no `mojo_set_from_list`/`mojo_list_copy`-style
helper for this either (grepped `mojo_set_*`/`mojo_list_*` — only
`mojo_set_add_int`/`mojo_set_add_str`/`mojo_set_union`/etc. and presumably
similar per-element list helpers exist, no bulk "copy all elements from
this generic iterable" entry point for either).

## Impact

`list(x)`/`set(x)` (used to copy or convert a collection — e.g. `list(some_tuple)`,
`set(some_list)` to dedupe, `list(other_list)` to shallow-copy) are
extremely common Python idioms. Silently producing an empty collection
instead of erroring is a correctness bug that could easily go unnoticed
(no compiler diagnostic, no crash — just wrong output), and is likely to
affect a large number of real stdlib files.

## Suggested fix

Give `set(iterable)` and `list(iterable)` the same kind of treatment
`_lower_builtin_dict` already has: when called with an argument, actually
populate the new collection from it. Since Python's `set()`/`list()`
constructors accept ANY iterable (not just another list/set — could be a
tuple, range, dict (iterates keys), generator, string, etc.), figure out
what iterable shapes this codegen already knows how to iterate generically
(check how `for x in <iterable>:` loops / comprehensions are lowered
elsewhere in `gimple_codegen.py` for the general iteration mechanism used
across different source types) and reuse that same mechanism to walk the
argument and insert each element (via `mojo_set_add_int`/`mojo_set_add_str`
dispatched by element type for `set`, or whatever the equivalent
list-append runtime call is for `list`), rather than inventing a
new, narrower iteration scheme just for this. At minimum, handle the common
`MojoList *` argument case (list/tuple-backed) correctly; use your
judgment (per CLAUDE.md, favor the production-quality general fix over a
narrow one, but don't over-engineer past what this codebase's existing
iteration infrastructure already supports elsewhere) on how broadly to
support other iterable argument types in one pass.

## Status
**Fixed**

`_lower_builtin_set`/`_lower_builtin_list` (`gimple_codegen.py`, ~8965-8987)
now both delegate to a new shared helper, `_lower_ctor_from_iterable`, which
synthesizes a `{x for x in <arg>}` / `[x for x in <arg>]` `Comprehension` AST
node and hands it to the EXISTING `_lower_comprehension` — the same generic
iteration mechanism already used for real comprehensions and (via its
sibling per-type `_gen_for_*`/`_compr_*_loop` helpers) `for x in <iterable>:`
loops. This reuses `_lower_comprehension`'s existing range/`MojoList
*`/`MojoStr *`/`MojoDict *` (keys)/`MojoSet *` dispatch — including its
int64_t-boxed-pointer resolution fix — instead of inventing a third, narrower
iteration scheme, per CLAUDE.md's consolidation guidance. No new runtime
helper was needed; `mojo_list_copy`/`mojo_set_copy` (which already existed in
`runtime/mojo_runtime.c`) are reachable transitively when the iterable
happens to already be the same collection kind, but the common case (a
`MojoList *` argument, e.g. `set([1,2,3,3])`) goes through
`_compr_list_loop`'s per-element `mojo_set_add_int`/`mojo_set_add_str` /
`mojo_list_append_*` calls, which correctly dedupe for `set` and preserve
order for `list`.

Fixing this exposed a second, unrelated latent bug in the self-host quality
gate: `_compile_imported_module`'s per-submodule `temp_gen` did not share
`_funcptr_builtins_needed` (the set of "used as a bare value" builtins
needing a `static void * _funcptr_X = (void *)X;` declaration) with the
parent gen or with sibling submodules' `temp_gen`s. Making `set()`/`list()`
compile further than before let two previously mid-lowering-abandoned
functions (one each in `myinterpreter.py` and `build_stdlib_dylib.py`) reach
a bare `dict` reference for the first time in the same self-host build as
`regex_compile.py`'s pre-existing one, and since every module's generated C
is textually concatenated into one translation unit for the self-hosted
build, three independent `static void * _funcptr_mojo_make_dict = ...`
declarations collided ("redefinition of '_funcptr_mojo_make_dict'"). Fixed
by sharing `_funcptr_builtins_needed` across all `temp_gen`s (matching how
`_emitted_ptr_helpers`/`_emitted_structs`/etc. are already shared) plus a new
companion `_emitted_funcptr_builtins` "already declared" set so each name is
declared exactly once across the whole transitive closure, not once per
submodule that happens to need it.

Quality gate (all green):
- `python3 test_gimple.py`: 179 passed, 0 failed (added `set_ctor_from_list`/
  `list_ctor_from_list` compile-only cases).
- `python3 test_gimple_runner.py`: 9 passed, 0 failed (added
  `gimple_set_ctor_from_list`/`gimple_list_ctor_from_list` — genuine
  behavioral checks: build, run, and assert on the actual `len()` +
  iterated-element-sum of the compiled binary's output, not just "does it
  compile").
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes (`mojo.py` compiling itself, 1 passed / 0
  failed) — this is what caught the `_funcptr_builtins_needed` sharing bug
  above; it was NOT visible via `test_gimple.py`/`test_module_cache.py`.
- From-scratch stdlib dylib build (`rm -f build/libmojostdlib.dylib` +
  `build_stdlib_dylib.build_stdlib(jobs=8)`): 0 skipped modules both before
  and after (no regression), build output byte-for-byte identical aside from
  the fix itself; `build/libmojostdlib.dylib` produced successfully.

Manual verification: building and RUNNING (not just compiling) the repro at
the top of this file now prints `3` / `1`,`3`,`2` (set iteration order) / `3`
— matching the interpreter's `3` / `1`,`2`,`3` / `3` in element content
(sets are unordered) instead of the old silent `0` / (nothing) / `0`.

`Lib/test/test_type_cache.py:55`'s `len(set(all_version_tags))` case
(tracked separately in `bugs/COMPILE_FAIL_test_test_type_cache.md`) is
**unaffected** by this fix — rebuilding it still produces the exact same
`error: invalid conversion in gimple call` at the same line/col. Confirmed
this is a genuinely separate root cause (the surrounding f-string
default-arg call shape), not the same bug in a different shape; left as-is
per that bug's own tracking.
