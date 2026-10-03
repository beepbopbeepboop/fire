# Self-host link fails: five `__mojo_*_toplevel` symbols referenced, never defined

**Status: OPEN, pre-existing, not caused by the GPU work.** First measured
2026-10-01, immediately after merging master into the `metal` branch
(`a8c5b182`). Confirmed present at that commit with a clean worktree, so it is
the merge's, not anything layered on top.

## Symptom

`make stage2/mojo` compiles `stage1/fire.ci` cleanly and then fails at **link**:

    Undefined symbols for architecture arm64:
      "__mojo_backend_gimple_device_select_toplevel", referenced from:
        _main in cckbW7EW.o
      "__mojo_backend_gimple_emit_metal_toplevel", ...
      "__mojo_middle_metal_ops_toplevel", ...
      "__mojo_middle_module_shared_toplevel", ...
      "__mojo_middle_offload_toplevel", ...
    ld: symbol(s) not found for architecture arm64

Gate consequence: `selfhost`, `mojoc` and `bootstrap-stage2-cc` FAIL. The
`bootstrap-stage2-*` steps then SKIP because they depend on stage2, which is why
a single defect takes out seven tests.

## What is NOT the cause

Worth recording, because it is the first thing to check and it is a dead end:

- **Not a stale artifact.** `stage1/fire.ci` is regenerated (the compile step
  succeeds) and the symbol names in the error do not literally appear in it —
  the linker prints `__mojo_middle_offload_toplevel` with two leading
  underscores while the generated C uses one (`_mojo_middle_offload_toplevel`,
  `fire.ci:198` declares and `fire.ci:1077825` calls it, consistently). The
  missing thing is the BODY, not the name; do not go looking for a name-mangling
  bug on the strength of the linker's spelling.
- **Not the memory blowup in `CODEGEN_bootstrap_resource_blowup.md`.** That one
  is a resource ceiling at ~15-30 GB per call; this is a link-time symbol
  resolution failure at 1.0 GB peak.
- **Not the `mojoc`-fails/segfaults cluster** in
  `CODEGEN_noshim_dumpfull_preexisting_divergence.md` — different failure mode,
  and the currently-`expect`-marked tests are still behaving as marked.

## Evidence that it is the merge

A worktree at the merge commit, with none of the GPU work present:

    git worktree add /tmp/wt-base a8c5b182 && cd /tmp/wt-base && make stage2/mojo

fails with the **same five symbols**, and `diff` of the two sorted symbol lists
is empty. So the GPU line neither introduced nor repaired it, and bisecting it
inside the metal branch will not find it — the bisect point is inside the merge.

## SUPERSEDED PARTLY (2026-10-01, after merging master)

Merging `master` changed the failure. `make stage2/mojo` no longer reaches the
link: it now fails earlier, at COMPILE, with self-host ABI mismatches. **So this
bug is neither fixed nor disproved — it is currently masked by a different
failure, and its status is UNKNOWN until the compile errors below are cleared.**

Two concrete mismatches, both ABI-sync bugs from master's runtime change rather
than from this branch:

1. **`py_tokenize`** — `runtime/fire_runtime.h:1751` now declares
   `py_tokenize(char *source, char *filename)` (2 args, matching Python's
   `py_tokenize(src, filename="")`), but `py_tokenize` is in
   `module_gen.py:9476`'s passthrough list, so the generated C forwards whatever
   the Mojo source passed. Every 1-arg call site in the compiler's own source is
   now a type error: `monomorphize.py:194,304`, `elaborate.py:138,161,226,235`,
   `build_stdlib_dylib.py:393,431,477`.
2. **`l.sort()`** — the MojoList method path is CORRECT and emits all four
   arguments (`emit_methods.py:4227`). The failures are `dirnames.sort()` and
   friends in `cas.py:424`, which take a DIFFERENT route — the generic variadic
   stub `('sort', 'void sort(...);')` at `module_gen.py:8044` — and that route
   still emits the old 1-argument call.

Note (2) is the more interesting one: the correct code already exists in the
tree, and the bug is that some call sites never reach it. That is the same shape
as the original toplevel defect — a correct path plus a second path that skips
it — which is worth weighing when this comes back around.

## Localised (2026-10-01, after the first gate)

Not five bugs. **57 forward declarations, 0 bodies** in `stage1/fire.ci`:

    declarations matching ^void _mojo_*_toplevel\(void\);$      57
    bodies      matching ^void _mojo_*_toplevel\(void\) {$      0
    root `_toplevel` body                                          0

The root module's own `_toplevel` is missing too, so this is not about
sub-modules. Only 5 of the 57 are *referenced* (from `_main`, via
`_sub_toplevels`), and those 5 are the entire link error — the other 52 are
declared and never called, so the linker says nothing about them. **The blast
radius is 57 modules; the visible symptom is 5.**

The declarations are emitted from `gen_module_impl`'s declaration block
(`mojo/backend_gimple/module_gen.py:7623`, iterating `self._sub_toplevels`).
The bodies are emitted by `_gen_toplevel`
(`mojo/backend_gimple/emit_funcs.py:2596`) into `func_parts`, at
`module_gen.py:7380`:

    if has_toplevel_code:
        toplevel_func = self._gen_toplevel(toplevel_stmts)
        func_parts.append(toplevel_func)

with `has_toplevel_code = len(toplevel_stmts) > 0` (line 7350). So the
declaration and the body are gated on DIFFERENT conditions in different places,
and in the `do_imports=True` whole-program path the declarations get emitted
while the bodies do not. That asymmetry is the thing to explain.

## Where to look next

Five modules, one symptom, so it is systemic rather than five bugs. The common
feature is that each has module-level statements that must run at import, so the
compiler is asked to emit a per-module `<module>_toplevel` — and `_main`
references all five while the definitions are not emitted. The question to
answer is therefore in the *emission* of module toplevels, not in any of the
five modules:

1. **Why do declarations and bodies disagree under `do_imports=True`?** The
   declarations come from `_sub_toplevels`, the bodies from `has_toplevel_code`
   over `toplevel_stmts`. If a module registers its toplevel name without
   contributing to `toplevel_stmts`, it gets a declaration and no body — which is
   exactly the observed shape, and would explain all 57 at once. Check whether
   the registration at `module_gen.py:7397` can run with `toplevel_stmts` empty
   (e.g. if `emit_entry_points` is False for a sub-module while its statements
   were consumed elsewhere).
2. **Is the `do_imports=True` path dropping `func_parts` wholesale?** The root
   `_toplevel` is missing as well, and the root is not a sub-module — so
   whatever discards these bodies may be discarding ordinary function bodies
   too, which would be a much larger defect that only shows up here because
   these are the symbols `_main` actually calls.
3. Then check a size/complexity cap last. It is the least likely of the three
   now that the root toplevel is missing too: a cap that dropped exactly the
   58 largest bodies and nothing else would be a coincidence.

## How to confirm a fix

`make stage2/mojo` must link, and then the gate's `selfhost`, `mojoc` and
`bootstrap-stage2-cc` rows go from FAIL/SKIP to passing. Until then the gate is
**red for a reason that has nothing to do with the GPU offload work**, which is
worth saying out loud whenever those three rows are quoted.

## ROOT CAUSE FOUND, and the link failure it was masking (2026-10-01)

This bug is FIXED. Its two earlier "SUPERSEDED"/"masked" sections were both
right that the symptom had moved; the cause is not the asymmetry those
sections guessed at.

`mojo/backend_gimple/module_gen.py` used the name `_lens` for two locals in
two different functions of the same file:

    1257:  _lens = self._device_launch_lengths.get(_nm) or {}      # a DICT
    6114:  _lens = {len(e.elements) for e in _els}                # a SET

The compiled path froze the NAME as the set, so line 1257 raised

    cannot coerce MojoSet * to MojoDict * (incompatible container kinds)

inside `gen_module_impl` — while `module_gen.py` itself was being compiled as
an imported module. `_compile_imported_module`'s handler printed the error and
rolled back, and that rollback is where this bug's blast radius came from:

* `_compiled_modules` entries added by the failed attempt WERE discarded;
* the shared `_sub_toplevels` list was NOT — it is shared by reference across
  every gen level (`gimple_codegen.py` declares it "(shared)"), and the root
  reads it at emission time to write one forward declaration per entry;
* the exception also destroyed `module_gen`'s accumulated `imported_code`,
  which is where the BODIES of the four GPU siblings it had already inlined
  lived.

So four modules that never failed kept their declarations and lost their bodies:

    Undefined symbols for architecture arm64:
      "__mojo_backend_gimple_device_select_toplevel", referenced from: _mojo_main
      "__mojo_backend_gimple_emit_metal_toplevel", ...
      "__mojo_middle_metal_ops_toplevel", ...
      "__mojo_middle_offload_toplevel", ...

**Four modules blamed for one module's bug.** The "57 declarations, 0 bodies"
count in the section above was taken from an artifact that never finished
generating; on a complete one it is **33 declared, 33 bodies** once the
collision is gone, and **32/28** with exactly the four above missing before.

Both halves are fixed: the two locals no longer share a name, and the
rollback now truncates `_sub_toplevels` back to its pre-attempt length, so a
module that fails can no longer leave a declaration with nothing behind it
for the linker to find later.

## What that unmasked (still open)

Fixing this put four GPU modules' code into the closure for the first time —
`mojo/middle/offload.py` alone is ~2000 lines of the metal branch's offload
pass, and it has never been through the compiled path, because it was being
silently dropped. It does not compile: three errors, two shapes.

1. **`offload.py:1621`, `_t32` undeclared** — inside the module-level
   generator `_walk_stmts`, in the `for attr in ('body', 'then_body', ...)`
   loop: a loop temp is USED with no matching declaration line emitted. Valid
   everywhere else this shape appears, so this reads as a generator-body
   lowering gap rather than a general one.
2. **`offload.py:1747`, `fused = fusable(st)`** — both directions of the
   assignment are reported, i.e. `fusable`'s return type is inferred two
   different ways in one function. `fusable` is a nested closure annotated
   `-> 'gctypes.ExprStmt | None'` (a STRING annotation) whose body returns
   both `None` and a `gctypes.ExprStmt(...)` struct construction.

So the metal line's GPU work had been validated on the python-hosted path and
on the Metal benchmarks, never through the self-host closure, because
`mojo/middle/offload.py` was being silently dropped from that closure: a local
named `_lens` was a `set` in one function and a `dict` in another, and on the
compiled path the name froze as the set, so the dict assignment raised and
`_compile_imported_module`'s rollback discarded four GPU siblings the pass had
already inlined. That was filed as its own bug, is now FIXED -- the name is
distinct and `make mojoc` builds with `mojo/middle/offload.py` in fire.py's
import closure -- and its doc is deleted, so this paragraph is the record.
