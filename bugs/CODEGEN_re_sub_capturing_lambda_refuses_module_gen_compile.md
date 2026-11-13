# CODEGEN: `re.sub(..., <capturing lambda>, ...)` now REFUSES the compiler's own `module_gen.py`, so the sanctioned single-module repro cannot finish

Status: OPEN. Filed 2026-11-12 by the worker that fixed the import-extern
arity class (an imported function whose partly unannotated parameters got the
text scan's short arity; that bug's doc was deleted with its fix). That fix is
verified with this refusal worked around in a scratch copy; the workaround is
NOT part of the fix and nothing here is committed. Not a duplicate: no other
doc names this refusal (searched `bugs/` for `re.sub`, `capturing`,
`LambdaExpr`, `generated_cpp`).

## Symptom

The vehicle the arity doc sanctions for the whole compiler —

```python
from build_stdlib_dylib import compile_module_to_c
from pathlib import Path
p = Path('mojo/backend_gimple/module_gen.py')
compile_module_to_c(p.read_text(), str(p), 'module_gen', linkable=False)
```

— raises before returning any C:

```
  File "mojo/backend_gimple/module_gen.py", line 15974, in gen_module_impl
    func_parts.append(self.gen_func(stmt))
  ...
  File "mojo/backend_gimple/emit_methods.py", line 3189, in _lower_method_call
    fn_ptr_t, env_t = gen._lower_re_sub_callback(cb_arg)
  File "mojo/backend_gimple/emit_loops.py", line 356, in _lower_re_sub_callback
RuntimeError: re.sub(..., <capturing lambda>, ...) is not supported: a
capturing lambda is a MojoBoundMethod, not a bare function pointer, and this
codegen cannot wire its env into the regex callback ABI. Use a non-capturing
lambda or refer to a closure (IdentExpr) instead.
```

The offending source is `mojo/backend_gimple/module_gen.py`'s
`@@CSYM:` placeholder resolution (around line 19937):

```python
self.generated_cpp = re.sub(
    r'@@CSYM:([A-Za-z0-9_]+)@@',
    lambda _m: self._func_csym(_m.group(1)), self.generated_cpp)
```

The lambda captures `self`, so `_re_sub_repl_is_callback` (emit_loops.py)
answers False for it since `99d4fe467` (2026-11-12 17:55, the
`CODEGEN_re_sub_inline_lambda_used_as_replacement_string` fix), and
`_lower_re_sub_callback` raises on the capturing lowering. Before that commit
the same call compiled on the replacement-string path (wrong semantics, but it
compiled), so this is a regression in *compilability* introduced by that fix,
not by the arity fix above.

## Expected

`compile_module_to_c` on the compiler's own modules returns C. `module_gen.py`
is in the self-host closure, so a refusal here is not a fallback point: the
dylib build's only remedy is a `skip <module>:` line and a source fallback,
and the single-module repro used by the import-extern bug docs cannot measure
anything at all.

## Measured with the refusal worked around (scratch copy only)

Replacing the `re.sub(..., lambda ...)` above with a `re.findall` +
`str.replace` loop (in the worktree's git-ignored `.tmp/` scratch, never
committed) makes the compile return 21.7 MB of C, and gcc
`-fgimple -Os -g -ftrivial-auto-var-init=zero -Iruntime -c` then reports
**7 errors, 0 `too many arguments`** — all belonging to other, already-filed
bugs:

* 6 at `module_gen.py:10111`: `exprtypes_module_qualifier_d719e0` declared
  under the local alias (`CODEGEN_aliased_function_scoped_import_extern_
  declared_under_alias_name`);
* 1 at `module_gen.py:13899`: unpacked loop variable unified to `char *`
  (`CODEGEN_unpack_loop_var_unified_to_char_star_loses_slot_store_cast`).

Before the arity fix and with the same workaround the unit had 41 error lines,
15 of them `too many arguments`.

## Next step

1. **Simplest, and enough to unblock the repro:** stop using a capturing
   lambda at that one site. Either a nested `def _csym_sub(_m)` closure (the
   shape `_lower_re_sub_callback`'s `IdentExpr`/`_closure_envs` branch already
   supports and wires an env for) or the `re.findall` + `str.replace` loop
   used for the measurement (no regex callback at all).
2. **Root fix if the refusal should not exist at all:** give
   `_lower_re_sub_callback` the same env wiring its `IdentExpr` branch has
   (`_closure_envs` / `_cb_statics`), so a capturing `LambdaExpr` is passed as
   (fn ptr, env) instead of refused. The regex callback ABI already takes both
   (`char *(*)(void *, char *)`), so the ABI is not the blocker.
3. **Quick test:** add `mojo/backend_gimple/module_gen.py` to
   `test_dict_slot_read_selfhost_modules.py`'s `MODULES` list — that test
   already compiles three self-host modules through the same entry point and
   misses this one, so it is the natural home. It must raise pre-fix and pass
   post-fix. A two-line `test_gimple.py` case that compiles
   `re.sub(pat, lambda m: x + m.group(1), s)` (a CAPTURING lambda) would pin
   the general behaviour if option 2 is taken.

## Done when

`compile_module_to_c` returns non-empty C for
`mojo/backend_gimple/module_gen.py` (the new self-host-modules case passes),
and the `@@CSYM:` placeholder resolution still works — the existing generator
tests (`test_gimple_generator_runner.py`, `test_gimple_async_runner.py`) stay
green. Then delete this doc in that commit.
