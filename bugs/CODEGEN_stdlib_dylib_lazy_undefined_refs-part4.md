# CODEGEN: a macOS compile references the linux `_lstat`/`_stat` bodies that are never built

Parent: `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md` (its
`## Replan (2026-11-15)` table is the measured state). This is part 4.

## Goal

A macOS compile of `std/os/path/path.mojo` must reference only the macOS
`_lstat`/`_stat` bodies. The four other-target references

    std_os__linux_aarch64__lstat_d719e0   std_os__linux_aarch64__stat_d719e0
    std_os__linux_x86__lstat_d719e0       std_os__linux_x86__stat_d719e0

must be absent from the generated C, while the host pair
(`std_os__macos__lstat_d719e0`, `std_os__macos__stat_d719e0`, defined by
`std/os/_macos.mojo`) stays.

## Evidence (measured 2026-11-15, this tree)

`std/os/path/path.mojo` is lowered with `compile_module_to_c` and its object's
`nm -u` against `nm -g` shows 8 undefined `_std_` references. Four are the
linux pair above; the other four (`std_os__macos__*`, `std_pwd_pwd_getpwnam_*`,
`std_pwd_pwd_getpwuid_*`) are defined by `std/os/_macos.mojo` and
`std/pwd/pwd.mojo`, so they are ordinary cross-module references.

The linux ones can never be defined: `build_stdlib_dylib._excluded_platform`
keeps only the host's `_linux` / `_macos` variant in the dylib, so on Darwin
`std/os/_linux_aarch64.mojo` and `std/os/_linux_x86.mojo` are not compiled at
all.

The source spells the choice as a comptime chain (`path.mojo:45-65`):

    comptime if CompilationTarget.is_macos():
        return Int(_stat_macos(path^).st_mode)
    elif CompilationTarget.has_neon():
        return Int(_stat_linux_arm(path^).st_mode)
    else:
        return Int(_stat_linux_x86(path^).st_mode)

`CompilationTarget.is_macos()` / `has_neon()` fold to a constant on the host,
so only one branch is reachable; the lowering still emits a call in every
branch (and therefore a forward `extern` for each).

## Work

1. Find where a `comptime if` chain's statements are lowered — the
   `elif`/`else` bodies must be dropped when the condition folds to a constant
   false. Search `mojo/backend_gimple/` for the `IfStmt` lowering's comptime
   arm and `CompilationTarget` folding (the same fold that already resolves
   `comptime if is_apple_gpu():`).
2. Re-run the module compile after the change and confirm the linux externs
   are gone. Do not special-case `path.mojo` or the module names: the fix is
   the dead-branch rule, and every other `comptime if` chain gets it too.
3. If the fold is not available at that point in the lowering, record why in
   this doc and fix the fold rather than adding a `#if` to the C — a
   target-name test in the emitter would be a second, drifting source of truth.

## Acceptance

- The 4 linux references are absent from `std/os/path/path.mojo`'s generated C.
- `std_os__macos__lstat_d719e0` and `std_os__macos__stat_d719e0` are still
  referenced by the module and defined by `std/os/_macos.mojo`.
- A module that uses a `comptime if` over a *runtime* condition still emits all
  branches (the fold must be constant-only).

## Done when

`python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p4_target` exits 0.
It compiles `std/os/path/path.mojo` and `std/os/_macos.mojo` through
`compile_module_to_c` (no gcc, no link, ~2 s) and asserts the four linux names
are absent and both macOS names are defined.
