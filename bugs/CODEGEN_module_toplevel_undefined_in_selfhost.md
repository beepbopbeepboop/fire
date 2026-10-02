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

## Status (2026-10-30 — still masked; the two compile-time blockers are being
fixed elsewhere, and the link-time symptom is NOT reproducible from a small
package)

Measured on this tree, in this order:

1. **Blocker 1 (`py_tokenize`'s arity) is fixed on two other branches.** The
   source is `def py_tokenize(src: str)` (`fire_compiler.py:1325`, whose
   docstring explains the ABI in full); `gimple_codegen.py`'s `_KNOWN_SIGS`
   and `runtime/fire_runtime.h:1751` still declare the two-argument form, so
   `test_gimple.py`'s
   `handwritten_selfhost_signature_tables_match_the_source` row is RED here
   with exactly the diagnostic this doc predicted. It is fixed in `05d8c42a`
   ("codegen+runtime: `py_tokenize`'s pinned C ABI is ONE parameter, in both
   tables", on `work/bugs3-codegen-2-r2`) and in `222e4dee` (on
   `work/master-selfhost-fix2`). **Deliberately not duplicated here** — the
   same two lines in the same two files, which would leave two parallel fixes
   to merge. If neither branch is merged, this doc's blocker 1 is a two-line
   change with a test already pointing at it.
2. **Blocker 2 (`l.sort()` via the variadic stub) does not reproduce for a
   boxed receiver.** `ident(d).sort()` — `d` a list reached through an
   unannotated parameter, so the receiver is a boxed `int64_t` — lowers to
   `mojo_list_sort (_t10, 0, 0, NULL)`, i.e. the CORRECT four-argument MojoList
   method path (`emit_methods.py:4227`), not the `('sort', 'void sort(...);')`
   stub. The stub is still declared in the preamble (`module_gen.py:8245`) and
   unused for this shape. The doc's `cas.py:424` case is a value out of
   `os.walk()`, with no static container type at all, which is a different and
   unreached path; the narrowing measurement (does the generic stub route fire
   for a receiver whose type NOTHING knows?) is one `probe3.py` run over an
   `os.walk()`-shaped fixture and is worth doing before anyone changes the
   stub list.
3. **The link-time symptom itself is not reproducible from a small package.** A
   package whose imported sibling has module-level statements (`pkg/sub.py`
   with a module-level assignment, a `print`, and a function; `pkg/main.py`
   importing it) compiles under `do_imports=True` with BOTH
   `void __sub_toplevel(void);` and `void _toplevel(void);` declared and BOTH
   bodies present — `gcc -fgimple` clean, and the linked binary's stdout is
   byte-identical to CPython's. So the "57 declarations, 0 bodies" asymmetry
   is NOT reachable through one sibling. It is presumably a scale or
   depth-dependent effect in the whole-closure path.

**What still needs a heavy run, and cannot be answered by a light worker:**
the whole-closure shape is only observable in `fire.py --dump-full`'s output,
so the "Localised" section's counts (`57` declarations, `0` bodies) cannot be
re-measured, and `make stage2/mojo` cannot be used to tell whether blockers 1
and 2 being cleared exposes the original defect or retires it. The integrator
should run, in this order, once blockers 1 and 2 have merged:

    make stage2/mojo

and then, to turn the answer into a fact rather than an interpretation:

    python3 - <<'EOF'
    import re
    s = open('stage1/fire.ci').read()
    d = re.findall(r'^void _mojo_\w*_toplevel\(void\);$', s, re.M)
    b = re.findall(r'^void _mojo_\w*_toplevel\(void\) \{$', s, re.M)
    print(len(d), 'declarations', len(b), 'bodies')
    EOF

`d == 0` or `d == b` means retired; `d > b` reproduces it and the counts name
the blast radius. `make stage2/mojo` reaching the LINK at all is itself the
answer to blocker 1/2: a compile error there means a blocker is still live,
not that this bug is fixed.

## Status (2026-10-02, `work/bugs4-3`) — the same emission area, measured, and it is
## NOT only about function bodies

Run once on this tree, as the one heavyweight check my compiler-source changes
owe:

    python3 tools/memslot.py --gb 8 --label selfhost -- python3 test_selfhost.py

`selfhost` is RED, and it is red at `HEAD` too: the same command over
`git archive HEAD` extracted to a scratch tree produces **the same 168 gcc
errors, the same set** (compared as sorted, line-number-normalised error
lines; the only differences are line numbers, which my edits shifted). So
none of it is mine, and none of it is new. What it does give this doc is a
measurement of the defect's shape that the three sections above could not get,
because they all need the symptom to be a LINK error.

**58 of the 168 errors are one family, and it is not the function-body one:**

    build_config.py: error: 'struct _build_config_toplev' has no member named 'TEST_PATH'
    build_stdlib_dylib.py: error: 'struct _build_stdlib_dylib_toplev' has no member named 'STDLIB_PATH'
    build_stdlib_dylib.py: error: 'struct _build_stdlib_dylib_toplev' has no member named '_IN_PROGRESS'
    mojo/backend_gimple/emit_calls.py: error: 'struct _mojo_backend_gimple_emit_calls_toplev' has no member named '_SCALAR_FLOAT_TYPES'
    mojo/backend_gimple/emit_exprs.py: error: 'struct _mojo_backend_gimple_emit_exprs_toplev' has no member named '_BIN_OPS'
    mojo/backend_gimple/emit_funcs.py: error: 'struct _mojo_backend_gimple_emit_funcs_toplev' has no member named '_FIXED_ARRAY_ANN_RE'
    mojo/backend_gimple/solvers.py: error: invalid use of undefined type 'struct _mojo_middle_solvers_toplev'

A module-level **constant** is read from a function body in the SAME module
(`build_stdlib_dylib.py:355` reads `STDLIB_PATH`, which that file defines at
line 13) through the module's `<module>_toplev` globals struct, and the
struct has no such member. So whatever populates that struct does not
populate it with the module's own module-level assignments — the same pass
that drops the `_toplevel` FUNCTION bodies these sections document is also
dropping the module's DATA. Two different consumers of one omission, which is
why the sections above only ever saw the function half: a missing data
member is a COMPILE error with the module's own name in it, so it never
reaches the linker, and the link error this doc is titled for is the residue.

The 31 remaining errors are two more families the same run makes visible, both
unclaimed and both worth reading before touching the toplevel emission: 59
`'_mojo_elem_repr_<Node>' undeclared` (the per-node element-repr statics
`mojo_list_set_elem_repr`'s family declares nowhere), and 20 `passing
argument 1 of '_mojo_repr_list' makes pointer from integer without a cast` in
`mojo/backend_gimple/device_glue.py`.

**Narrowing that costs nothing: it does NOT reproduce from a small package**,
which is consistent with the third section and now has a second reason. Two
modules where one defines a module-level constant and the other imports it
(`consts.py`'s `NAMES`, `main.py`'s `from consts import NAMES`, both under
`do_imports=True`) compiles with **zero** gcc errors, and the emitted C puts
the root's globals in an `extern struct _root_toplev _root_globals` — an
incomplete type provided elsewhere — rather than in a concrete struct it has
to fill. Only the whole-closure shape gives every module a concrete
`<module>_toplev` struct, which is why nothing small reaches this.

**Exact next step**, in this order:

1. Find the pass that emits `struct <module>_toplev { ... }` and its
   initialiser, and check what it iterates. The declarations come from
   `gen_module_impl`'s `_sub_toplevels` block and the module's own globals
   from `_gmi_global_init_code`; if the struct's member list and the
   initialiser's value list are built from two different sources, one of them
   is missing module-level `AssignStmt`s. That is a much smaller question than
   the function-body one, and it is answerable by reading those two lists
   side by side.
2. `_SCALAR_FLOAT_TYPES` and `_BIN_OPS` are IMPORTED (`from mojo.middle.types
   import ...`, `from generated_dispatch import ...`), while `STDLIB_PATH` is
   the module's own. So whichever source is missing has to be checked against
   both — an "own module assignments only" explanation is already ruled out by
   the first pair.
