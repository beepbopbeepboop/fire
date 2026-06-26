# STDLIB-BUGS.md — issues that look like stdlib / build-structure bugs

Tracks things encountered while making the stdlib **fully compile** (`-fgimple -c`
→ `.o` → `libmojostdlib.dylib`) that feel like stdlib-source or build-structure
issues, as distinct from compiler/codegen bugs (those live in BUGS-AST.md /
BUGS-STDLIB.md). Updated as found.

**Goal: 100% of the stdlib in the dylib.** The dylib is a speed hack — a client
uses a symbol from it if present, else falls back to source — so today the build
*skips* the 16 modules that don't yet compile and *excludes* 4 that collide on a
C name, and those fall back to source. **That fallback (and the collision
exclusion) is a stopgap**, not the design endpoint. Closing it needs the real
fixes: free-function overload mangling (SB-1) and the elaboration/feature work
for the 16 non-compiling modules (see BUGS-STDLIB.md). Until then the dylib links
and accelerates everything it does contain.

---

## SB-1 — Cross-module C-name collision for overloaded free functions

**Symptom:** dylib link fails with `duplicate symbol '_mojo_abs'`.
`abs` is defined as a free function in **two** modules — `std/math/math.mojo`
(scalar `abs`) and `std/complex/complex.mojo` (`abs` for `Complex`). Both lower
to the same C symbol `mojo_abs` (the `abs`→`mojo_abs` keyword rename does not add
overload disambiguation), so linking both objects collides.

**Nature:** compiler — the C-name mangler must distinguish overloads of a free
function by parameter types (as it already does for some struct-method overloads
via the `_<hash>` suffix). Belongs in elaboration/overload resolution.

Same shape, other symbols: `_reduce`, `_input`, `_get_dylib_function`
(`std/ffi/__init__.mojo` + `std/gpu/host/_tracing.mojo`), and the codegen trait
helpers `_all_trivial_copyinit/_moveinit/_del` (`std/ffi/unsafe_union.mojo` +
`std/utils/variant.mojo`).

---

## SB-2 — Per-OS modules define the same symbols (FIXED at build level)

**Symptom:** dylib link failed with `duplicate symbol '__c_stat___init__'`,
`__stat`, `__lstat`, `__build_pw_struct`.
The stdlib ships per-OS variants that define identical symbols:
`os/_macos.mojo` vs `os/_linux_x86.mojo` vs `os/_linux_aarch64.mojo`;
`pwd/_macos.mojo` vs `pwd/_linux.mojo`. The dylib builder linked **all** of them.

**Nature:** build structure — only the host OS's variant should be in the dylib.
**Fixed** in `build_stdlib_dylib.py` (`_excluded_platform` filters non-host
`_linux`/`_macos`/`_windows` modules).

---

## SB-3 — `unlink`-style raising wrappers share a name with the libc symbol

**Observation (not a bug, documents an interaction):** Mojo's `os.unlink` is
`raises` and returns nothing; internally it calls
`external_call["unlink", Int32]` to read the C status and raises on failure.
The Mojo wrapper (`mojo_unlink`, void) and the libc `unlink` (Int32) share the
bare name `unlink` in the codegen's `func_return_types`, which let the void
wrapper's type shadow the external call's `Int32` and silently drop the status
into a `void` temp. Fixed in codegen (BUGS-STDLIB / commit: `_emit_call` never
coerces a used result through a `void` shadow). Recorded here because the
name-sharing is a property of the stdlib's libc-binding pattern.
