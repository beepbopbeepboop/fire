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
