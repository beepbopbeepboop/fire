# HARD BUG: bare imported-module name collides across modules in a do_imports=True build (`_global_to_module` is name-only, first-registration-wins)

## Status

Found 2026-08-07 during the Track A generator-codegen re-verification
sweep, while re-diagnosing `bugs/CODEGEN_generator_function_Lib_glob.md`.
NOT fixed — this is a sibling of the already-deferred
`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
(task #141): same architectural shape (a single, name-keyed-only,
first-registration-wins map shared across every module compiled in one
`do_imports=True` build), same broad blast radius (this specific map,
`self._global_to_module`, is read at 4+ separate call sites —
`gimple_codegen.py:6572`, `:8019`, `:16857`, `:22157` — every one of
which is the general-purpose "which module's globals struct does this
bare name live in" lookup used for ALL module-level global/import-name
reads project-wide, not something generator- or glob.py-specific).
Deliberately not attempted under this task's time budget, for the same
reasons #141 gives: fixing it properly means making ownership
CONTEXT-SENSITIVE (a `(compiling_module, name) -> owning_module` map,
where each module should prefer ITS OWN import of `name` over some
other module's, with correct fallback when a module reads a name it
never imported itself) touching every registration site AND every
consumption site — a real, multi-site dataflow change to core shared
preamble-emission machinery, not a narrow one-line fix.

## Symptom

`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/glob.py`:

```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:175:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
```

(gcc's reported line number is itself misleading — see "How this was
diagnosed" below; the real offending statement is a few lines later in
the same function.)

## Root cause

`glob.py` does `import contextlib` at module scope (line 3) and uses it
in `_listdir`:

```python
def _listdir(dirname, dir_fd, dironly):
    with contextlib.closing(_iterdir(dirname, dir_fd, dironly)) as it:
        return list(it)
```

`Lib/subprocess.py` (transitively reachable from glob.py's own import
graph in a `do_imports=True` whole-program build) ALSO does `import
contextlib` at its own module scope. Both modules' compiles share the
SAME `self._global_to_module: dict[str, str]` (`gimple_codegen.py:3907`,
explicitly shared into every nested/imported-module sub-compile at
`gimple_codegen.py:4525-4526`: `temp_gen._global_to_module =
self._global_to_module`). The registration site
(`gimple_codegen.py:31202-31210`, inside the module preamble-building
pass) does:

```python
elif isinstance(stmt, ImportStmt):
    for _tm, _ta in _import_targets(stmt):
        local_name = _ta if _ta else _tm
        if local_name not in _declared_globals:
            ...
            if local_name not in self._global_to_module:
                self._global_to_module[local_name] = current_mod_name
```

— a plain `name not in self._global_to_module` guard, keyed ONLY by the
bare imported name, with NO module qualification. Because `do_imports=
True` recursively compiles every transitively-imported module (each its
own `gen_module` pass with its own `self.module_name` context) BEFORE
the root file's own preamble-building pass runs, and because
`subprocess` (via `os` in glob.py's import graph) happens to get its own
recursive compile — and therefore its own `contextlib` registration —
processed earlier than `glob.py`'s own root-level scan, `contextlib` in
the shared map ends up permanently mapped to `"subprocess"`. glob.py's
own `import contextlib` registration is then silently skipped (`if
local_name not in self._global_to_module` is already false), so every
later read of the bare name `contextlib` anywhere in glob.py's own
compiled code resolves through the READ side of the exact same map
(`gimple_codegen.py:8019`: `global_module = getattr(self,
'_global_to_module', {}).get(name, self._current_module_ctx or
"root")`) to `_subprocess_globals.contextlib` instead of glob.py's own
(root) globals struct.

`_subprocess_globals.contextlib`'s real declared C field type does not
agree with what `_listdir`'s locals expect (glob.py's own `contextlib`
usage), so the resulting 3-address-code assigns a mismatched-type value
into an `int64_t` temp — hence the GCC `-Wint-conversion` error.
Semantically this is a **silent cross-module data corruption bug**: had
the two modules' `contextlib` fields happened to share a compatible C
type, this would have compiled cleanly while reading the WRONG module's
global state at runtime, with no diagnostic at all.

## How this was diagnosed (methodology note for whoever picks this up)

The originally-reported GCC line (`glob.py:175`) is a red herring —
`_glob2`/`_rlistdir`/`_iterdir` (the actual generators occupying that
source-line range) compile via the C++20-coroutine path and never emit
any `.ci` text at all for that range, so there is no `#line 175
".../glob.py"` directive anywhere in the generated `.ci`. GCC's line
counter is simply incrementing forward, uncorrected, from the last real
`#line` stamp (`#line 165`) through several un-stamped declaration/
statement lines emitted for the NEXT function (`_listdir_132aaf`) that
happens to follow immediately in the `.ci` text — i.e. the reported
`165 + N` "line" is an artifact of physical-line counting, not a real
source position. Root-caused instead by: reproducing the exact `mojo.py
build_executable` call directly (`gimple_codegen.compile_to_gimple_with_
cpp(src, do_imports=True, filename=input_file)`), then grepping the
resulting `.ci` for `_subprocess_globals` reads inside a function
compiled from `glob.py`'s own source — `_listdir_132aaf`'s body reads
`_subprocess_globals.contextlib` twice (once per `with`-statement
sub-expression touching `contextlib`), which is the actual, unambiguous
signature of this collision. Also confirmed the isolated,
`do_imports=False` compile of glob.py alone (no other module in the
mix) produces a CORRECT `_root_globals`-based reference and compiles
`_listdir` cleanly — the bug only manifests once a second module sharing
the same bare import name enters the same `do_imports=True` build.

## Breadth

`contextlib` alone is `import`ed at module scope by at least 9 files
directly under `Lib/*.py` (not counting subpackages), so this collision
class is not glob.py/contextlib-specific — any pair of modules in the
same transitive-closure build that both do a plain `import <name>` (an
extremely common shape for `os`, `sys`, `re`, `functools`, `itertools`,
`contextlib`, etc.) are at risk of one silently stealing the other's
globals-struct slot for that name. Only one instance (glob.py/
contextlib/subprocess) was traced end-to-end here; not yet confirmed
which OTHER currently-failing files in the `bugs/CODEGEN_generator_
function_Lib_*.md` cluster hit this same root cause versus their own,
independent issues — flagged for whoever next investigates a "used a
plain top-level `import X`, then a completely unrelated-looking
downstream type-mismatch on `X`'s own attribute access" shape to check
this doc first.

## What a real fix would need

Same shape as task #141's plan, adapted for import-name ownership
instead of struct-name ownership:

1. Make `_global_to_module` (or a parallel structure) keyed by
   `(compiling_module, name)`, not just `name` — OR, simpler and
   probably sufficient here since imports are lexically visible per
   module: when resolving a bare name inside a function body, first
   check whether the CURRENT module's own known import list contains
   `name`; only fall back to the shared cross-module map when the
   current module never imported it itself (e.g. a name inherited via
   `from X import *` or similar indirection this codegen already
   handles some other way).
2. Audit all 4+ read sites (`:6572`, `:8019`, `:16857`, `:22157`) for
   the same fix, not just the one this doc's repro happens to hit —
   per this project's own prior-regression history (`bugs/COMPILE_FAIL_
   collections___init__.md`), a partial fix at only one site risks
   moving the corruption to a different consumer rather than fixing it.
3. Re-run the full `bugs/COMPILE_FAIL_*`/`bugs/CODEGEN_*` cluster (not
   just glob.py) afterward — given the breadth noted above, a real fix
   here plausibly unblocks or changes the failure mode of several other
   currently-failing files, for better or worse, and needs the full
   `compile_stdlib.py -j8` 664/664 gate run before/after to confirm no
   regression.

Not attempted in this session — deferred alongside #141 per this task's
explicit guidance to document precisely and move on rather than
half-fix core shared cross-module preamble machinery.

## Related

- `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
  (task #141) — identical architectural shape, different map
  (`_struct_name_owner` for class/struct names vs. `_global_to_module`
  for plain import names). Read together.
- `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md` —
  a separate, already-partially-fixed issue in the SAME general
  "reconstructing another module's globals struct" preamble area, not
  the same bug (that one is about the struct TYPE never being emitted
  at all; this one is about which module's struct instance a read is
  even directed at).
