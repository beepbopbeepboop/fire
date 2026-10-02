# The self-host closure stops on three gcc errors in `mojo/middle/offload.py`

**Status: OPEN, not fixed. Found and measured 2026-10-01 on
`work/master-selfhost-fix2` at 222e4dee+fe09cd46, while making `selfhost`
green.** Pre-existing: `mojo/middle/offload.py` arrived with the GPU/offload
work (it is +1099 lines against `968c4fc6`) and has never compiled; nothing
in this branch caused it. It was simply unreachable before, because two
earlier layers of the same red failed first (the stale `py_tokenize`
declaration and the stale `Parser__parse_expr` return type, both fixed on
this branch) and then a third (`cannot coerce MojoSet * to MojoDict *` in
`module_gen.py`, also fixed here).

## What I ran

    python3 tools/suite.py selfhost

`selfhost` is the cheapest job that reaches this: `test_selfhost.py` calls
`fire.build_executable(fire.py)`, which is `compile_to_gimple` on the whole
closure + `gcc -fgimple` + link. 150 s, 2.3 GB peak, `small` class.

## What I saw

The closure is now generated and gcc is reached. Every C error in
`fire_compiler.py`, `myinterpreter.py`, `gimple_codegen.py`,
`module_gen.py` and the other 56 modules is gone. Three remain, all in
`mojo/middle/offload.py`, which is in `cas.selfhost_inputs()`:

    mojo/middle/offload.py:1621:9: error: '_t32' undeclared
        (first use in this function); did you mean '_t31'?
        in function 'mojo_middle_offload_rewrite_gemm_d45836'

    mojo/middle/offload.py:1747:8: error: assignment to 'int64_t' from
        'int64_t *' makes integer from pointer without a cast
        [-Wint-conversion]
    mojo/middle/offload.py:1747:15: error: assignment to 'int64_t *' from
        'int64_t' makes pointer from integer without a cast
        [-Wint-conversion]
        in function 'rewrite_fused_loop_walk'

Source:

* 1621 is inside the `for attr in ('body', 'then_body', ...)` line of
  `_walk_stmts`, a generator nested in `rewrite_gemm`. So `_t32` is a temp
  the coroutine lowering declares on one path and reads on another — the
  declaration is emitted where the value is FIRST assigned inside a branch,
  and the read is outside it. `gen.decls` is the whole function's
  declaration list, so a temp must be declared in `gen.decls`, not inline
  beside its first assignment; whatever is emitting `_t32` inline is the
  defect. `_t31`/`_t32` are adjacent, which is the signature of a temp
  counter that advanced between the declaration and the read.
* 1747 is `fused = fusable(st)`. The declared local is `int64_t *` and
  `fusable`'s C signature says it returns `int64_t *` while this call site
  is typed `int64_t` — the same "a hand-written declaration disagrees with
  the definition the codegen infers" class as
  `bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md`'s neighbours and
  as the `Parser__parse_expr` table entry fixed in a5b655a0. `fusable` and
  `rewrite_fused_loop_walk` are both nested `def`s inside one enclosing
  function, so check `_all_closures` / `_gen_lifted_closure`'s
  `current_func_name` and the `func_return_types` key the closure is
  registered under (`f"{outer}_{inner}"`) against what `_lower_call`
  resolves at the call site.

## Why I stopped here rather than fixing it

Two reasons, both about ownership rather than difficulty.

1. **It is not the whole red.** With these three fixed, `selfhost` reaches
   LINK and then fails on the pre-existing, fully-analysed
   `__mojo_*_toplevel` cluster documented in
   `bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md` — which is
   claimed by another worker (`bugs3-codegen-4`). So `selfhost`, `mojoc` and
   `bootstrap-stage2-cc` cannot go green on this branch whatever I do about
   `offload.py`; they need that other fix.
2. **`mojo/middle/offload.py` and `mojo/backend_gimple/device_glue.py` /
   `emit_metal.py` are GPU/offload area**, carried in by 23 formal branches
   at once, with ~100 open `CODEGEN_*` docs in the same tree. Fixing
   codegen defects in newly-landed GPU code without the gate to check the
   blast radius is exactly the change the integrator should sequence, not
   one to land blind from a light worker.

## How to confirm a fix

    python3 tools/suite.py selfhost

`test_selfhost.py`'s static half already prints, before the expensive
build:

    self-host closure: 1373 functions, 1 of them declared in
    fire_runtime.h under a pinned C name; every such declaration matches
    its definition: True

That half is the cheap place to add a per-nested-`def` signature check (the
same shape as `pinned_prototypes_match_their_definitions`), so the
`fusable` disagreement is caught in milliseconds instead of after a
150-second closure compile. The `_t32` undeclared-temp defect needs a
regression test too, and the cheapest reproduction is a nested generator
whose `for x in tup:` body both assigns through a temp and reads one
outside the branch — `mojo/middle/coro.py`'s own `_walk` note is the
existing precedent for why that shape is worth a test.

## Related, already fixed on this branch

* `runtime/fire_runtime.h` + `gimple_codegen._KNOWN_SIGS` said
  `py_tokenize` takes two parameters while `fire_compiler.py` defines one
  (`222e4dee`).
* `gimple_codegen._SELFHOST_SIGS` said `Parser__parse_expr` returns
  `UnaryOp *` while the codegen infers `int64_t` (`a5b655a0`).
* A local rebound to a different container kind was refused outright
  (`fe09cd46`).