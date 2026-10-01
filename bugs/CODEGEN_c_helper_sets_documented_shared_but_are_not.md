# CODEGEN: the `sizeof`/`fnaddr` C-accessor sets are documented as translation-unit-shared and are not

## Status

OPEN. Not a live failure today, and not reachable by any of the five jobs the
batch-1 sync ran (`mojoc`, `selfhost`, `bootstrap-stage2-cc`, `gimple`,
`suite-self-test`) — all five are green on the merged tree. It is filed because
the invariant the feature rests on is written down in one place and implemented
in none: correctness currently comes entirely from six independent
per-call-site guards, and nothing says so where the next call site will land.

Found while auditing the `batch1-sync` merge of master's new-modular work
(`92a71744 support the new-modular syntax, and fix four defects found testing
it`) for cross-side incoherence. **This is master's own state, not a merge
artefact** — verified by grepping every `*.py` in `master` for both names: they
appear in `gimple_codegen.py` and nowhere else, exactly as in the merged tree.

## What is believed

`GimpleGen._c_sizeof_helper` / `_c_fnaddr_helper` register a tiny
`static` accessor and `_c_helper_def` hands back its definition once.
Both pieces of state are per-`GimpleGen` instance:

    gimple_codegen.py:2076   self._c_helpers_needed: dict[str, str] = {}
    gimple_codegen.py:2088   self._emitted_c_helpers: set[str] = set()

and both docstrings claim the opposite:

    # Shared with every _compile_imported_module temp_gen the same way the
    # _emitted_* sets are, because all modules' generated code is concatenated
    # into ONE translation unit for the self-hosted build and a duplicate
    # top-level `static` would be a redefinition.

The sharing block that does this for every other per-translation-unit set is
`mojo/backend_gimple/emit_resolve.py:590-640` (`temp_gen._emitted_structs =
gen._emitted_structs`, `temp_gen._emitted_allocs = gen._emitted_allocs`,
`temp_gen._emitted_dispatch_typedefs = ...`, and ~15 more). Neither
`_c_helpers_needed` nor `_emitted_c_helpers` is in it.

So for a closure compiled as a SIBLING MODULE (`do_imports=True`, or any
import inside the closure), `temp_gen` starts with its own empty dict and its
own empty set, and `_c_helper_def` will happily return a second definition of
a helper the root gen already emitted. Every module's `parts` land in one
`.ci`, so that is a `redefinition of '_mojo_sizeof_...'` from `gcc`.

## Why nothing has blown up yet

Each of the six `_c_helper_def` call sites is independently safe, by accident
of its surroundings rather than by the contract:

| site | what makes it safe today |
|---|---|
| `emit_calls.py:4169` (`_lower_LambdaExpr`, env sizeof) | key is `f'{lifted_name}_env'`, and `lifted_name` embeds `current_func_name`, which is module-qualified for top-level code (`_module_toplevel_name`) |
| `emit_calls.py:4260` (`_lower_LambdaExpr`, fnaddr) | same — key is `lifted_name` |
| `module_gen.py:9052` | inside `if ci.env_struct not in self._emitted_structs:` — and that set IS shared |
| `module_gen.py:9144` | inside `if sn in self._emitted_allocs:` — and that set IS shared |
| `module_gen.py:9666` | the `not self.emit_struct_defs` twin of the `9052` guard; same shared set |
| `module_gen.py:1004` (`_gmi_emit_closure_recursive`) | behind `_emitted_env_allocs`, threaded per `gen_module_impl` call; key is `ci.env_struct`, i.e. `lifted_name`-derived |

So there are exactly two independent reasons the feature is correct, neither of
them the stated one: a per-TU guard that happens to enclose the call, or a key
that happens to be module-unique. Six call sites each had to get that right by
hand. A seventh that does not is a `gcc` redefinition, and the docstring will
have told the author it was already handled.

One related sharp edge found on the way, which is NOT caused by this and is
not filed separately: `lifted_name` is `f'{outer_ctx}_lambda_{counter}'` with
`outer_ctx = gen.current_func_name`, and `emit_funcs.py:2344` sets
`current_func_name = node.name` — the BARE name, not the module-qualified one.
Two sibling modules each with a function `foo` containing a lambda would mint
the same `foo_lambda_1`. That is a pre-existing lifted-function-naming
question, independent of the helper sets; the helper sets merely add one more
duplicate of whatever that naming already duplicates.

## What was run

    $ python3 tools/suite.py mojoc selfhost bootstrap-stage2-cc gimple suite-self-test
    # 5/5 pass on the merged tree (8015108b), so this is NOT reachable from them
    $ python3 tools/suite.py gimplerunner gimplegenerators new-syntax-parse formal-ast
    # all pass
    $ grep -rn '_c_helpers_needed\|_emitted_c_helpers' mojo/backend_gimple/emit_resolve.py
    # (nothing)
    $ for f in $(git ls-tree master --name-only | grep '\.py$'); do ... done
    # both names appear in gimple_codegen.py only — master's state, not the merge's

## The next step, exactly

1. Add the two lines to the sharing block in
   `mojo/backend_gimple/emit_resolve.py`, beside
   `temp_gen._emitted_allocs = gen._emitted_allocs`, with the by-reference
   comment the neighbouring lines already carry:

       # share: a `sizeof`/`fnaddr` accessor is a file-scope `static`, and
       # every module's parts land in ONE translation unit, so two modules
       # needing the same one would be a redefinition.
       temp_gen._c_helpers_needed = gen._c_helpers_needed
       temp_gen._emitted_c_helpers = gen._emitted_c_helpers

2. Then say what sharing makes true, in `_c_helpers_needed`'s own docstring, and
   stop relying on the call-site table above: with the sets shared, a
   definition is emitted by whichever module first needs it, and because
   `_c_helper_def` is called at the point of use (into `parts`,
   `func_parts`, or `_elaborated_externs`, all file-scope lists) the
   definition still precedes its caller. Confirm that ordering claim against
   `_elaborated_externs`' flush point before relying on it — that is the one
   place the definition is NOT emitted immediately before the body that calls
   it.

3. A test belongs with it. A two-module closure where the same struct name is
   `sizeof`'d from both — the smallest honest one is two sibling modules each
   holding a lambda over a same-named local — compiled with `do_imports=True`,
   asserting the generated `.ci` contains exactly one
   `static int64_t _mojo_sizeof_`. Add it next to the lambda-lifting cases in
   `test_gimple_runner.py`.

## Related

- `mojo/backend_gimple/emit_resolve.py`'s sharing block is the pattern; it is
  the reason `CLAUDE.md`'s "no duplicated implementations" and the batch's own
  `_struct_import_aliases` (gimple_codegen.py:1469, also per-gen and also not
  in the block) are the same shape of question. `_struct_import_aliases` is
  safe for a different reason — its writer and reader are both inside one
  module's own `gen_module_impl` — which is worth a sentence in its own
  comment if anyone touches it.