# CODEGEN: an unlowerable body vanishes, so callers link against a bare-name stub

Parent: `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md` (its
`## Replan (2026-11-15)` table is the measured state). This is part 5.

## Goal

When this backend cannot lower a function body, the function must still get a
definition under the name its callers use — `std_<module>_<name>` (and the
overload suffix where there is one) — instead of disappearing. The accepted
shape is the existing convention: a weak `unavailable in compiled mode` stub
that prints and returns 0, but emitted at the DEFINITION site under the
qualified symbol.

Measured cases:

    std_sys_info_is_apple_gpu
    std_sys_info_is_nvidia_gpu
    std_sys_info_is_amd_gpu          (std/sys/info.mojo)
    std_python__cpython_CPython_as_imm   (std/python/_cpython.mojo, method)

## Evidence (measured 2026-11-15, this tree)

`std/sys/info.mojo` defines `is_apple_gpu()` as
`return is_triple["air64-apple-macosx"]()` (and the other two the same way).
The module compiles without an error, but its C has NO
`std_sys_info_is_apple_gpu` definition. Its own internal calls fall back to the
call-site stub path:

    __attribute__((weak)) int64_t is_apple_gpu (...)
    { mojo_print ((char *)"is_apple_gpu: unavailable in compiled mode"); return 0; }

That definition is spelled with the BARE name. Every cross-module caller names
`std_sys_info_is_apple_gpu`, so those are undefined at link time.

`std/python/_cpython.mojo`'s method `CPython.as_imm` gets only a declaration:

    int64_t std_python__cpython_CPython_as_imm (...);

with no body and no weak definition (`std/python/python.mojo` calls it).

The call-site stub generator is `mojo/backend_gimple/emit_calls.py`
(`_is_unknown` / `_elaborated_externs`, around line 10875); the method stub is
`mojo/backend_gimple/emit_methods.py` (`_MOJO_STUB_<Struct>_<method>`, around
line 8697). Both spell the caller-visible name from `fname` alone. The
definition drop itself is a separate question: find why
`is_triple["..."]()` makes the function unimplementable and whether the
per-function lowering swallows the failure.

## Work

1. Find the per-function lowering path that drops the whole definition (search
   `module_gen.gen_module_impl`'s function loop and the `try` around a single
   function's body). It must not drop the function silently: emit a weak stub
   at the definition site, named through the same helper a real definition uses
   (`GimpleGen._func_csym` / the module qualifier, and the overload suffix
   where the function is overloaded).
2. For the method case, the stub must be a weak definition, not a
   declaration-only extern: `emit_methods` already has the
   `unavailable in compiled mode` shape for a method with no lowering.
3. Remove the call-site BARE fallback only if the definition-site stub makes it
   unreachable; do not keep two naming schemes. The name a caller emits must be
   the name the definition emits, by construction.

## Acceptance

- `std/sys/info.mojo`'s C defines `std_sys_info_is_apple_gpu`,
  `std_sys_info_is_nvidia_gpu` and `std_sys_info_is_amd_gpu` (a weak stub is a
  definition).
- `std/python/_cpython.mojo`'s C defines
  `std_python__cpython_CPython_as_imm` (weak stub accepted).
- No call in either module references a bare `is_apple_gpu` /
  `CPython_as_imm` symbol that nothing in the tree defines.
- A normal (lowerable) body is still emitted as a real definition, unchanged.

## Done when

`python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p5_unlowered` exits 0.
It compiles those two modules through `compile_module_to_c` (no gcc, no link,
~5 s) and asserts the four names have a body in the defining module's C.
