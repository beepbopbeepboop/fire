# GIR selfhost: an importer's extern return type is the scanned `int64_t` default

Part of the whole-closure self-host failure (`python3 test_selfhost.py`, gcc over the one
closure translation unit). See `doc/GIR.md`, section "Selfhost closure: remaining errors".
The fix is stage S1 of `bugs/GIR_type_solver.md`. Read that doc first: this one
specifies only how the solver's answer is consumed.

## Symptom

A function defined in one closure module and called from another gets an extern
prototype in the importer that says `int64_t`, while the definer emits `char *`,
`MojoList *` or `MojoDict *`. gcc reports `conflicting types for 'mojo_middle_<module>_<name>_<hash>'`.
The hash suffix (the overload hash over the parameter ctypes) is the same on both
sides; only the return type differs.

Measured 2026-11-24 on `e9e4ea4a9^` (the tree before the WIP). A
`python3 fire.py --dump-full fire.py` run, then gcc over the TU, gives 61 errors. 30 of
them are `conflicting types`, for 13 distinct functions:

| module | functions (definer's real return) |
|---|---|
| `mojo/middle/calls_shared.py` | `_callable_value_symbol` (MojoList *), `_isinstance_type_name` (char *), `_py_box_expr` (MojoList *) |
| `mojo/middle/funcs_shared.py` | `_parsed_import`, `_published_def_pts`, `_resolve_reexported_closure_func`, `register_module_member_function`, `register_module_member_value` (MojoList *); `_resolved_export_entry` (MojoDict *); `_sanitize_cname_qualifier`, `module_receiver_ref`, `resolve_module_attr_ref` (char *) |
| `mojo/middle/resolve_shared.py` | `_body_pybox_locals` (MojoList *) |

All 13 are unannotated `def`s, and each returns a tuple, a dict, or `None`-or-a-string.

## Root cause (established, do not re-investigate)

**Import-cycle back-edges.** The self-host closure has one strongly connected import
component of 76 of its 107 modules. `gen_module_impl`
(`mojo/backend_gimple/module_gen.py`) compiles a module's imports in
`_gmp_compile_imports`, near the top. That happens before the module's own
return-type passes run (`_gmp_infer_return_types`, ...,
`_gmp_infer_return_types_late`). So when module A imports B and B imports A, B is
generated completely inside A's import step. B's extern for `A.f` and B's call-site
temps for `A.f(...)` are written while `_home_def_return_types` has no entry for
`A.f`. The scanned default `int64_t` is used, and A later defines `f` with its
measured type.

A probe (2026-11-24, in a scratch copy, not committed) logged every read of
`_home_def_return_type` that missed for an unannotated definer. There were 32 such
back-edge reads in the closure; 13 of them surface as gcc errors.

The probe also ran the existing `gen._infer_return_type` on each definer from inside
the importer. It agreed with the definer's final answer on 29 of 32 functions, but
it changed the generated C of the whole closure (temp, label and string-pool numbering
shifted, plus 1,369 lines). The existing engine is not pure, so it cannot be the
early resolver. That is why the resolver is the new solver.

## Why the WIP (`e9e4ea4a9`, merged as `913aa3780`) is wrong

It wrote a text placeholder `MOJO_EXTERN_RET_<n>_` into the prototype and substituted
it after the outermost `gen_module`. Text is the wrong layer: the importer's
call-site temps, `func_return_types`, and every decision that reads them (boxing,
container dispatch, tuple unpacking) still saw `int64_t`. So it traded 30 errors for
about 37 `makes integer from pointer` errors. The type has to be known when the
importer is generated, which only a pre-pass can provide.

## The design

One fact, the return type of `(definer path, name)`, gets one early decision. Every
reader sees it and the definer obeys it:

1. **Pre-pass.** `compile_to_gimple` (`gimple_codegen.py`, just before
   `code = gen.gen_module(stmts)`) runs `mojo.tsolve.solve_closure(...)` when
   `do_imports or link_mode`, and stores the result on `gen._tsolve`.
2. **Early decision at the one read point.** `emit_funcs._home_def_return_type` is
   already the read that the extern emitters, `_func_csym`'s mirror into
   `func_return_types[<csym>]`, and `_func_return_type_for_call` go through. On a
   store miss whose definer is **in progress** (started but not yet analyzed), it
   asks the solution. "In progress" means its module has started compiling, has not
   finished its return passes, and is not the module doing the read. If the solution
   has an answer, it stores it, marks it frozen,
   and returns it. Because the answer is in the store, the call-site temps get the
   right type too, which is what the WIP was missing.
3. **The definer obeys.** `emit_funcs._record_home_def_return_type` becomes the
   single writer and returns the effective ctype. For a frozen key it keeps the
   frozen value, and records a ledger entry if its own measurement differs. Its five
   callers assign the returned value, so `func_return_types[name]`, `gen.func_ret_type`
   and the emitted definition all say the frozen type.
4. **Ledger.** Every decision and every conflict is a line in `gen._tsolve_ledger`.
   With `FIRE_TSOLVE_LEDGER=<file>` set, `compile_to_gimple` writes the ledger there.
   It is how the acceptance test proves 0 conflicts and 0 undecided.

Programs without an import cycle never have an in-progress miss, so their generated C
is byte-identical by construction. `tools/c_oracle.py` checks it.

## Implementation plan (in this order; one commit per step)

**Step 0: revert the WIP.** `git revert --no-edit e9e4ea4a9`. It touches only
`gimple_codegen.py`, `emit_funcs.py`, `emit_infra.py` and `module_gen.py`, and later
commits did not touch those hunks. This removes `_GEN_MODULE_DEPTH`, the
`_EXTERN_RET_TOKEN` / `_PENDING_EXTERN_RETS` machinery,
`resolve_extern_return_placeholders`, `export_return_is_default`,
`extern_return_ctype` and the three `GimpleGen` wrappers. Do not use
`git checkout -- <file>` (CLAUDE.md). Commit the revert on its own.

**Step 1: `mojo/tsolve/`** per `bugs/GIR_type_solver.md` §2, with `test_tsolve.py`
(§4 there), registered in `tools/suite.py` in the `check` bucket as `tiny`. No
compiler file imports it yet. Commit.

**Step 2: one parse helper.** Add `funcs_shared.parse_module_file(path) -> list`
(read, `py_tokenize`, `Parser(...).parse_module()`, `ast_rewriter.rewrite`) and make
`emit_resolve._compile_imported_module` call it in place of its inline parse. Then
write the compiler's `load(ref, importer_path)` for the solver in `funcs_shared.py`
on top of `imports.resolve_source(ref)` and `parse_module_file`. Relative refs
(leading dots) resolve against `importer_path`'s directory, the same way
`_collect_import_modules` resolves them. Commit.

**Step 3: the state, shared by reference.**
- `GimpleGen.__init__` (`gimple_codegen.py`, beside `_home_def_return_types` at about
  line 3410) adds four fields: `self._tsolve = None`,
  `self._qualifier_paths: dict[str, str] = {}`, `self._analyzed_paths: set = set()`,
  `self._tsolve_frozen: dict[str, str] = {}` (pair-key to ctype), and
  `self._tsolve_ledger: list = []`.
- `emit_resolve._compile_imported_module`'s share block (where
  `temp_gen._home_def_return_types = gen._home_def_return_types` is) shares all five,
  in the same way.
- `module_gen.gen_module_impl`, at the line that writes
  `self._inline_module_qualifiers[os.path.abspath(self._current_filename)] = self.module_name`
  (about line 15099), also writes
  `self._qualifier_paths[self.module_name] = os.path.abspath(self._current_filename)`.
- Right after `_gmp_infer_return_types_late(self, all_functions)` (about line 20414),
  add `self._analyzed_paths.add(os.path.abspath(self._current_filename))` when a
  filename is set.
- `compile_to_gimple`: build the solution as in design item 1. Write the ledger at
  the end of the function when `FIRE_TSOLVE_LEDGER` is set.

Commit.

**Step 4: decide and obey.** In `mojo/backend_gimple/emit_funcs.py`:

```
def _early_return_decision(gen, qualifier: str, bare_name: str):
    """The solver's return ctype for a definition whose module has started but
    not finished its return-type analysis (an import-cycle back-edge), stored
    and frozen; None otherwise."""
    sol = gen._tsolve
    if sol is None:
        return None
    path = gen._qualifier_paths.get(qualifier)
    if not path or path in gen._analyzed_paths:
        return None
    # A module reading its OWN functions before its own return passes have run
    # is not a back-edge (its passes are about to answer). Deciding there would
    # freeze every program's functions, not just cyclic ones.
    if gen._current_filename and path == os.path.abspath(gen._current_filename):
        return None
    ctype = sol.ret_ctype(gen, path, bare_name)
    key = _pair_key(qualifier, bare_name)
    if ctype is None:
        gen._tsolve_ledger.append('undecided ' + qualifier + '.' + bare_name)
        return None
    gen._home_def_return_types[key] = ctype
    gen._tsolve_frozen[key] = ctype
    gen._tsolve_ledger.append('early ' + qualifier + '.' + bare_name + ' ' + ctype)
    return ctype
```

- `_home_def_return_type`: on a store miss, `return _early_return_decision(gen, qualifier, bare_name)`.
- `_record_home_def_return_type(...) -> str`: return `ctype` unchanged on every
  early-return path that exists today. Where it writes the store, if the key is in
  `_tsolve_frozen`, do not overwrite it. Append
  `'conflict <qual>.<name> early=<frozen> measured=<ctype>'` when the two differ,
  and return the frozen value.
- The callers assign the return value: `module_gen.py` at about lines 12516, 13171,
  13205 and 14850 (`self.func_return_types[name] = _ggf_dup._record_home_def_return_type(...)`),
  and `gen_func` at about line 4283, where the call must move **above**
  `gen.func_ret_type = ret_type` so that `ret_type` is the effective value before
  anything uses it.
- The direct readers of the store dict go through `_home_def_return_type` instead:
  `funcs_shared.register_module_member_value` (`_as_dict(...).get(_pair_key(...))`,
  about line 1466) and `resolve_shared` at about line 213. After this step,
  `grep -n "_home_def_return_types" -r mojo gimple_codegen.py` should hit only the
  declaration, the share line, and `emit_funcs.py`. Add that check to
  `test_tsolve.py`.

Commit.

**Step 5: the regression test** `test_import_cycle_sigs.py` (in the `check` bucket).
Write two modules into a tempdir:

```
# a.py
import b
def make(n):
    return [n, n + 1]
def name_of(x):
    if x:
        return "yes"
    return None
print(b.use())

# b.py
from a import make, name_of
def use():
    xs = make(3)
    return str(len(xs)) + " " + name_of(1)
```

Build `a.py` with `fire.build_executable`, run it, and compare stdout with
`python3 a.py`. Before step 4 this fails gcc with `conflicting types`. Also assert
that the ledger (`FIRE_TSOLVE_LEDGER`) has `early` lines for `make` and `name_of`
and no `conflict` or `undecided` line. Commit with step 4 if you prefer.

## Acceptance (all required; report each number)

1. `python3 test_tsolve.py` and `python3 test_import_cycle_sigs.py` pass.
2. Self-host TU, measured exactly as `bugs/GIR_selfhost_unexplained_error_kinds.md`
   describes: a clean scratch copy, then
   `FIRE_TSOLVE_LEDGER=$PWD/ledger.txt python3 tools/memcap.py --limit-gb 24 -- python3 tools/selfhost_ci.py selfhost.ci`
   (about 5 min, 12.6 GB peak), then gcc over `selfhost.ci`. Write the ledger in
   the function that runs `code = gen.gen_module(stmts)` (gimple_codegen.py, about
   line 7018), which every real compile reaches. A CAS cache hit writes no ledger;
   the self-host path (`compile_to_gimple_with_cpp`) is uncached.
   Baselines: master `91140cc58` (WIP in) has 40 errors, 37 of them this family.
   After step 0 expect `conflicting types` back at about 30. Pass means
   `conflicting types for` = 0, `makes integer from pointer` = 0,
   `cannot convert to a pointer type` = 0, and in the ledger 0 `conflict` and
   0 `undecided` lines. Expect about 32 `early` lines, matching the probe. The 3
   `MojoList * and double` errors belong to the other doc. If a `conflict` remains, fix the
   solver rule (with a unit test) until it agrees. Do not silence it.
3. `python3 tools/c_oracle.py check --base <step-0 sha>`: identical C on both
   corpora. Any program that changes must contain an import cycle; name it.
4. `python3 compile_stdlib.py`: `FAILED: N (E expected, U unexpected)` with U not
   increased, and no new `skip` lines.
5. `python3 test_gimple_lint.py`, `python3 test_type_string_ratchet.py`,
   `python3 test_gir_builder.py`: pass.
6. Then delete this doc in the same commit as the last step. Update `doc/GIR.md`'s
   "Selfhost closure" section and run `python3 tools/dangling_doc_refs.py --ratchet`.

## Status

- 2026-11-24: diagnosed (confirmed on the generated closure `.ci`). The WIP was
  committed red as `e9e4ea4a9` and merged to master by request.
- 2026-11-24 (later): root cause measured (import-cycle back-edges, 13 functions /
  30 errors, 32 back-edge reads) and the existing engine ruled out as the early
  resolver (it is not pure). The design above and `bugs/GIR_type_solver.md` were
  written. Next: step 0.

- 2026-11-24 (session 2): steps 0-2 landed (`2812a27c0`, `61fbbf591`, `fb2a9269b`). Steps 3-5 are
  in the working tree and verified as follows: the import-cycle program (`test_import_cycle_sigs.py`)
  prints what `python3 main.py` prints, and its ledger has only `early a.make` and `early a.name_of`
  (no `conflict`, no `undecided`); byte-identical C on 286 pydiff and 35 coroutine programs against
  `fb2a9269b`; `compile_stdlib.py` PASSED 610, FAILED 0, no skips.
  Deviations from the plan above, decided while implementing:
  - The solver's loader resolves through `_module_candidate_paths_from`, the lookup the compile
    uses, not `imports.resolve_source` (the plan's premise was wrong about what the compile uses).
  - `parse_module_source` lives in `mojo/middle/module_parse.py`, a leaf module (no import cycle).
  - The early decision answers only for NAMES THE CLOSURE DEFINES (`Solution.knows`). An
    imported-symbol key (`a_make_<hash>`) is a symbol, not a definition, so it is not decided.
  - A lookup by an imported alias uses the definer's `original_name` (`_func_csym`).
  NOT done: the self-host translation unit acceptance (item 2 of Acceptance above), and the
  `--ratchet` / doc deletion, which depend on it.

- 2026-11-24 (session 2, later): acceptance measured on the working tree (copy, `tools/selfhost_ci.py`
  under memcap 24 GB, peak 11.3 GB; gcc-mp-15 census). Progression: 40 gcc errors -> 12; the ledger:
  39 `early` and 35 `conflict`, 2848 `undecided`. NOT yet met (criterion: 0 conflicting types, 0
  makes-integer-from-pointer, 0 conflict, 0 undecided).
  Landed this round (verified: unit tests, c_oracle 286+35 identical, compile_stdlib 610/0, cycle test):
  - the stub lookup and the early decision recover a mangled symbol's definer name (`_definer_name`);
  - `_qualifier_paths` is keyed by `module_qualifier(module_name)` too: the store's qualifier is the
    sanitized form (`mojo_middle_funcs_shared`), which the raw dotted key never matched;
  - the summarizer parses f-string fields with the compiler's expression parser (undecidable 1626 -> 325);
    value-only nodes (cast, slice, ellipsis, imag, dotted) are dyn with their children walked;
    a store to a field no class declares flows nowhere;
  - `ModuleLoader` renamed `ClosureLoader` (collided with `module_loader.ModuleLoader`); `sty.py`
    helpers given unique names (`_sty_intern`, ...) after a C-name collision.
  Remaining, in order of what the census shows:
  1. `dyn` answers that the definer measures as `char *` / a container (35 conflicts, e.g.
     `_sanitize_cname_qualifier`: `return q.lstrip(..) if q else q`, where the parameter `q` is `dyn`
     from its mixed call sites, so the join is `dyn`). The solver must narrow a parameter by what its
     uses prove, or the dyn join must be refined; a `str`-only method on a dyn receiver is not enough
     on its own because the `else q` arm still joins dyn.
  2. `elaborate.infer_struct_type_args`: the solver says `MojoList *` (correct: `resolved[0]` is a list
     of type-argument lists), the backend measures `int64_t` (its element read is boxed). A measurement
     disagreement to settle by making the backend's read typed, not by the solver.
  3. `undecided`: `elaborate.type_param_names` (866 lines), `module_loader.module_name_for_path`,
     `build_config.find_gcc` / `find_gxx`, `module_loader.load_module`. These are decidable; their
     answer is `bot`, so no value reaches their returns. Diagnose which parameter is never fed.
  4. the 12 remaining gcc errors (a `register_module_member_value` conflicting type and the
     `dyn`-decided family members above).
