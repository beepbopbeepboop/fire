# The stdlib dylib excludes 130 modules: each generic/inline copy of `dlsym` is emitted under the same bare symbol `_dlsym`

## Status

OPEN. The dylib builds (`built ... from 249 module(s)`), but 130 modules are dropped from it as "symbol already defined",
and every drop is the same symbol. The drop is only a stopgap; the underlying naming is a correctness risk, not just
noise. Found 2026-10-29 while sorting the dylib's screen output.

## Measured

`python3 build_stdlib_dylib.py -o …` with `MOJO_DEDUP_LOG` set (the dedup log is now kept, see the commit that added it):

- `dedup.log`: 244 lines, 114 `localize` and 130 `exclude`. Every one names `_dlsym`.
- The 130 excluded modules are `std/gpu/*` and their importers; their symbols are lost from the dylib (clients fall
  back to compiling source, so the failure is silent and slow).
- The 4 `case .PASS:` skips (dtype, logger, address_space, testing/suite) are a separate bug, already on file as
  `bugs/CODEGEN_gate_stdlib_syntax_red.md`.

## Why

The stdlib defines `dlsym` as a generic, `@inline(.always)` function (`std/sys/_libc.mojo:353`):

```mojo
def dlsym[result_type: AnyType = NoneType](handle, name, out result): ...
```

Each module that calls it instantiates its own copy, and the copies are emitted as a STRONG global `_dlsym` — the
bare C name, with no instantiation or module suffix. Two modules therefore define the same symbol.

Worse than a clash: two DIFFERENT specializations (`dlsym[_EnvpType]` in `_libc`, `dlsym[NoneType]` elsewhere) share
the name `_dlsym` with different bodies. The dylib keeps the first module's copy, so a later caller of a different
specialization that is linked against the dylib can get the wrong code. The dedup is hiding that by dropping the
modules, not by making the names distinct.

## Next step (plan)

1. Give each specialization a unique, deterministic C name: the mangled name must include the instantiation's type
   arguments (the same mechanism that already gives `_struct_cname`-style unique names for generic structs), so
   `dlsym[NoneType]` and `dlsym[_EnvpType]` cannot collide.
2. Emit an inlined generic copy as `static` (file-local) in the module that instantiates it, unless it is called across
   modules; a copy a caller in another module uses gets the unique name and is exported once.
3. Test: two modules that each call `dlsym` with different specializations, linked into one dylib: no exclusion,
   each call returns its own specialization's result (run it; compare with CPython where applicable).
4. Re-run `build_stdlib_dylib.py` and check `dedup.log` has no `exclude` lines and the module count is 379, not 249.
5. Delete this doc when the exclusions are gone.
