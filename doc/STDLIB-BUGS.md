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

**FIXED (mostly).** Free-function C symbols are now overload-mangled by their
parameter types (`_func_csym` in gimple_codegen, mirrored in reflect.py), routed
through every emission site, so same-named overloads in different modules get
distinct symbols. This removed the `reduce` collision. The `input` alias was
fixed separately (weak runtime symbol).

**Residual** (handled by the build's collision-dedup stopgap — 3 modules
excluded; the dylib still links):

- `mojo_abs` — math `abs(SIMD)` and complex `abs(Complex)` both lower to the same
  C signature (`int64_t`), so the C-parameter-type hash is identical. Needs
  Mojo-source-type or module-qualified mangling to distinguish (the C types have
  collapsed by codegen time). SIMD/Complex scalarization limit.
- `_all_trivial_copyinit`, `_get_dylib_function` — these are **generic** functions
  (`def _all_trivial_copyinit[*Ts: AnyType]()`), defined in two modules each and
  emitted as type-erased zero-arg duplicates. Needs monomorphization
  (elaboration), not parameter-type mangling — a zero-arg erased generic has no
  parameters to hash.

**More instances found 2026-07-20 (BUG-2026-036 investigation) — broader than
previously known, and NOT all handled by the collision-dedup stopgap:**

- `std/gpu/host/_nvidia_cuda.mojo`'s `CUDA(DeviceContext)` /
  `CUDA(DeviceStream)` — a **same-module** (not cross-module) overload
  collision; `gen_module`'s own "overloaded top-level functions ... drop
  them here" pass never compiles a body for it at all (it relies on
  elaboration at a call site, which never happens when
  `build_stdlib_dylib.py` compiles each module standalone). Was crashing
  **every** `mojo.py` invocation at `dlopen` because `reflect.py`'s mirror
  of that drop condition had a separate bug (only matched `fn`, not `def`
  — fixed) and kept advertising it as an export anyway. `build_stdlib_dylib.py`'s
  `build()` now has a general safety net that drops any export whose
  mangled symbol has no compiled definition, so a *reflection-table*
  instance of this bug degrades to "that function falls back to source"
  instead of crashing dlopen — but it does not fix the underlying
  same-module-overload/no-elaboration gap.
- `std/builtin/coroutine.mojo`'s `_coro_destroy_fn` — a genuinely different
  flavor: not overloaded (one `def`), not exported (leading underscore), but
  its mangled symbol differs depending on which file computes it
  (`coro_destroy_fn_0c85c9` when `coroutine.mojo` compiles it standalone vs.
  `coro_destroy_fn_fa7153` expected by at least one other module's call
  site) — the two files' independently-boxed views of `AnyCoroutine`'s C
  type disagree. This is a **call-site** reference baked into a compiled
  function body, not a reflection-table entry, so the safety net above
  cannot catch or drop it; it still crashes `dlopen` today. Confirms the
  `mojo_abs` diagnosis generalizes beyond same-signature collisions to
  cross-file mangling *disagreement* — the real fix is the same one already
  called for above (canonical Mojo-source-type or module-qualified
  mangling), not yet attempted (large surface: touches every
  `_func_csym`/`overload_suffix_for` call site in gimple_codegen.py and its
  reflect.py mirror; needs a full self-host + stdlib-build verification
  pass before landing).
- Roughly **35 more exports** across many stdlib modules (`mojo_max`,
  `mojo_min`, `mojo_sum`, `MojoList_append`, `tuple`, `any`, several
  `Parser`/`Interpreter` methods, …) were found to have zero compiled
  definitions anywhere in a from-scratch dylib build — presumably more
  unresolved-cross-module-struct-collapses-to-`int64_t` collisions like
  `mojo_abs`, just never previously visible because `dlopen` aborts the
  whole process on the *first* unresolved symbol it binds, and `CUDA`
  happened to be first. Now silently dropped from the reflection table by
  the safety net (source-fallback instead of a crash) rather than
  individually root-caused.

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

## SB-4 — `setvbuf` external_call arity vs the system `<stdio.h>` prototype

**Symptom:** `std/sys/_libc.mojo:105` — `too few arguments to function 'setvbuf';
expected 4, have 2`. The wrapper carries all four params but its `external_call`
forwards only two:

```mojo
def setvbuf(stream, buffer, mode: c_int, size: c_size_t) -> c_int:
    return external_call["setvbuf", c_int](stream, buffer)
```

**Not a naive "forgot the args" bug — `setvbuf` is a *special* FFI case.** Mojo's
buffered-IO model deliberately keeps the libc binding lean: the C status return is
dropped and re-surfaced as `raises` (check the code internally, panic on failure
instead of returning an ignorable int), and the buffer crosses the boundary as a
lifetime-tracked type (not a raw pointer), so the compiler enforces that the buffer
outlives the stream. The thin `external_call` is intentional within that design.

The blocker for our backend is purely the **C-level arity clash**: our prelude
includes `<stdio.h>`, whose `setvbuf(FILE*, char*, int, size_t)` prototype is in
scope, so a 2-arg call is rejected. The compiler-side resolution is to not let the
system prototype constrain this call — e.g. emit the `external_call` target with a
matching/variadic local prototype (as we already do for other reserved libc
wrappers) rather than deferring to `<stdio.h>` — so the intentional Mojo binding
compiles. (If `mode`/`size` are genuinely meant to reach libc, that part is a
source question for upstream; the design above is why they may not be.)

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
