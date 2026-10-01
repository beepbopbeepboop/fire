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
  succeeds), and the symbols are absent from the `.ci` entirely — `grep -c
  __mojo_middle_offload_toplevel stage1/fire.ci` is 0, not "present but
  malformed".
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

## Where to look next

Five modules, one symptom, so it is systemic rather than five bugs. The common
feature is that each has module-level statements that must run at import, so the
compiler is asked to emit a per-module `<module>_toplevel` — and `_main`
references all five while the definitions are not emitted. The question to
answer is therefore in the *emission* of module toplevels, not in any of the
five modules:

1. Does the self-hosted codegen path (the one that built `stage1/fire.ci` via
   the compiled `mojoc`, not the python3 reference) take a different branch for
   module-level statements? The python3 reference path clearly emits them, or
   the `.ci` would not reference them.
2. Is there a size or complexity cap past which a toplevel body is dropped
   without a diagnostic? `offload.py` is the largest of the five, and the
   failure is silent — consistent with a cap, and worth checking first.
3. Compare `mojoc`'s emission of one of these five against the reference's for
   the same module; a single module diff should localise a systemic fault fast.

## How to confirm a fix

`make stage2/mojo` must link, and then the gate's `selfhost`, `mojoc` and
`bootstrap-stage2-cc` rows go from FAIL/SKIP to passing. Until then the gate is
**red for a reason that has nothing to do with the GPU offload work**, which is
worth saying out loud whenever those three rows are quoted.
