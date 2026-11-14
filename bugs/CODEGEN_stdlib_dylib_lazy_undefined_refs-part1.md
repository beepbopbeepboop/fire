# A re-exported free function's qualifier is the defining module, not the re-exporting `__init__` (part 1)

Part 1 of `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md`.
Class: easy. One home-module registry entry resolved wrong; no lowering change.

Measured 2026-11-13 on this tree. Compiling `std/memory/maybe_uninit.mojo`
standalone (the same per-module `compile_module_to_c` path
`build_stdlib_dylib.py` uses) emits

    extern int64_t std_memory___init___unsafe_memset_zero (...);  /* from std.memory */
      std_memory___init___unsafe_memset_zero (result, 1);

while `unsafe_memset_zero` is DEFINED in `std/memory/memory.mojo`
(`def unsafe_memset_zero`, two overloads), whose symbols are
`std_memory_memory__unsafe_memset_zero*`. The home module was recorded as
`std_memory___init__` — the re-exporting package's `__init__.mojo`
(`from .memory import ...`) — not the module the definition compiles under.
The parent doc lists the same shape measured on the production dylib:
`..._unsafe_destroy_n_2dbb98`, `..._forget_deinit_9f63a2`,
`..._alloc_dealloc_9f63a2`, `_std_time___init___sleep` (sleep is defined in
`std/time/time.mojo`), `_std_os___init___listdir_9f63a2` (`std/os/os.mojo`),
`_std_pwd___init___getpwnam_d719e0`/`getpwuid_9f63a2` (`std/pwd/pwd.mojo`),
`_std_random___init___seed` (`std/random/random.mojo`).

Root cause, located: `mojo/backend_gimple/emit_infra.py::_emit_stdlib_import_externs`
resolves the import statement's own module with
`module_loader._module_loader.resolve_module_path(mod)` — which for
`std.memory` returns `.../std/memory/__init__.mojo` — and records
`_note_own_func_home(sym, module_name_for_path(that __init__))` WITHOUT
asking whether that module defines the name. The re-export hop chain already
has a walker, `_find_symbol_home_module` in `mojo/middle/funcs_shared.py`
(it follows `from .sub import f` transitively to the defining module), and
the function-body path and the dylib-inline path already use the resolved
home (`_fi_eff_mod`) instead of the importing module.

## Goal

When a free function is imported through a package whose `__init__.mojo`
only re-exports it (`from .memory import unsafe_memset_zero`), every
reference this compiler emits for the function — call site, forward
declaration, `#ifndef` guard, variadic extern — carries the DEFINING
module's qualifier (`module_name_for_path` of the defining file), never the
re-exporting `__init__`'s, and never the bare `std.memory` prefix either.

## Acceptance

- `maybe_uninit.mojo`'s emitted C contains no occurrence of
  `std_memory___init___unsafe_memset_zero`, and at least one occurrence of
  `std_memory_memory__unsafe_memset_zero` (any overload suffix; this part
  does not require the suffix to be present or non-variadic — the suffix
  half is part 2).
- The same holds for the other names in the parent doc's qualifier group
  (unsafe_destroy_n, forget_deinit, sleep, listdir, getpwnam/getpwuid,
  seed): the emitted reference is prefixed with the defining module's
  qualifier (e.g. `std_time_time__sleep`, `std_pwd_pwd__getpwnam`).
- A function imported DIRECTLY from the module that defines it keeps today's
  qualifier (this change does not touch `_func_qualifier`'s direct tiers).
- An import of a name that exists in NO reachable module keeps today's
  behavior (no invented home; `_find_symbol_home_module`'s honest-`None`
  case stays a fallback, it is not an error).
- No special-casing of any package or function name; the re-export walk is
  generic via the existing `_find_symbol_home_module`.

## Done when

File: `test_stdlib_dylib_lazy_undefined_refs_probes.py` (repo root).

Command: `python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p1_reexport`

It runs `test_p1_reexport_home_module_is_the_defining_module` (red today:
the emitted C carries `std_memory___init___unsafe_memset_zero` — the
extern, its `#ifndef` guard and the call — and no
`std_memory_memory__unsafe_memset_zero`). It must pass.

## Where to start

`mojo/backend_gimple/emit_infra.py::_emit_stdlib_import_externs` — the
`_imp_path = resolve_module_path(mod)` / `_note_own_func_home(sym, _qual)`
block (around lines 1475-1500) records the importing statement's own
module path as the home even when that module is a re-export-only package
`__init__`. Resolve the defining module instead (e.g. through
`_find_symbol_home_module(gen, mod, name, 'fn')`, which needs no new
machinery and already powers the function-body and dylib-inline paths) and
derive `_qual` from the defining module's path. The early extern block and
the call site both read the same home registry (`_own_imported_func_home` /
`_imported_func_home`), so one fix covers both. Do not touch the symbol
mangling or the suffix machinery — that is part 2.
