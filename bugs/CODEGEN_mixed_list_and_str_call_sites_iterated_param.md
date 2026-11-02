# CODEGEN: an iterated parameter passed a list AND a str segfaults

Found 2026-11-01 while fixing the three red test_gimple.py cases (the
str-beside-list call-site fix, module_gen.py `_param_noncontainer_obs`).

## Repro (compiled path, exit -11, stdout cut short; CPython runs fine)

    def each(xs):
        for x in xs:
            print(x)
    each([4, 5])
    each("de")

Expected (CPython): `4`, `5`, `d`, `e`. Compiled: `4`, `5`, then SIGSEGV.

## What the generated C shows

`each_<hash>` is emitted as `void each_<hash> (MojoList * xs)`, and the
`each("de")` call site is `each_<hash> (_t7)` with `_t7` a `char *`: a str
passed where a `MojoList *` is declared. The loop then calls
`mojo_list_len(xs)` / `mojo_list_get_int(xs, i)` on the string's bytes.

## Why it is not the same fix as the print case

The print-only shape (`def show(x): print(x)`) is fixed: `show` is typed by
the call-site contract, and `_param_noncontainer_obs` (module_gen.py) makes a
mixed slot an `int64_t` box. Here the parameter's type is set earlier, by
`_infer_param_types` from the USE (iteration => `MojoList *`). Two places
still reach that guess unchallenged:

- `_gmi_apply_call_site_param_evidence` (module_gen.py ~223) only acts on
  UNANIMOUS literal evidence, so `{MojoList *, char *}` is declined and the
  usage guess stands.
- `_reconcile_param_container_kinds` / the scalar pass (`_has_cs` branch,
  ~11000) only overrides a `MojoList *` guess when every observer is `char *`.
  A mixed `{char *, container}` observation is left at the guess.

## Next step

1. Decide the representation for an iterated parameter whose call sites
   disagree on container kind. Options: (a) the `int64_t` box, with the
   for-loop lowered through a runtime kind dispatch (`mojo_cstr_or_int_*`-style,
   or the `_tagged_dyn_` machinery); (b) an honest refusal
   (`_UnsupportedGeneratorShape`-style, interpreter fallback). (b) is the
   sound minimum; (a) is the program this compiler should compile.
2. Whichever is chosen, a `for` over a boxed parameter must not be lowered as
   `mojo_list_len` on the box. Check the `for`-loop emitter
   (mojo/backend_gimple/emit_loops.py) for the lowering of an `int64_t`-typed
   iterable first.
3. Test: the repro above, as a `test_gimple.py` case through `_compiled_stdout`
   on single-TU and link-mode, next to
   `test_a_str_call_beside_a_list_call_does_not_make_the_parameter_a_list`.

## Status (2026-11-01): partial fix — the silent SIGSEGV is now a loud refusal

Landed (`mojo/backend_gimple/module_gen.py`, `_refuse_mixed_container_params`,
after `_propagate_forwarded_container_kinds`): a parameter that has BOTH a
container observation and a non-container observation (`_param_noncontainer_obs`),
and whose final inferred type is `MojoList *` / `MojoDict *` / `MojoSet *`,
raises `RuntimeError` at compile time instead of emitting a binary that casts
the str to a list header. Narrow on purpose: the print-only mix (no container
guess) keeps its `int64_t` box and is not refused.

Verified: the repro's `_run_pipeline` now raises (it returned C before);
`python3 fire.py <repro>` prints `4 5 d e` via the interpreter fallback,
matching CPython. Regression test:
`test_an_iterated_parameter_passed_a_list_and_a_str_refuses_to_compile`
in `test_gimple.py`.

Still open (the actual compile of this program): step 1(a) — a representation
that serves both kinds. The `int64_t` box cannot tell `MojoList *` from
`char *` (`mojo_cstr_or_int_str` only separates str from int), so (a) needs
either a container kind tag carried in the box, or per-kind specialization of
the function (one clone per call-site kind). Step 2 (the `for` lowering of an
`int64_t` iterable) is not needed while the refusal holds, and becomes
relevant only once (a) lands.

## Status (2026-11-01, planning round): decision and implementation guide for step 1(a)

Re-verified at HEAD 18f122b7c: `python3 tools/memslot.py --gb 8 --label
test_gimple -- python3 test_gimple.py` → 427 passed, 0 failed, including
`an_iterated_parameter_passed_a_list_and_a_str_refuses_to_compile`.

### Decision: per-kind specialization (option (a1)), not a tagged box

Reject the tagged box (a2). Carrying a `MojoList`/`char *` kind tag in the
`int64_t` box changes the box ABI that every int-box consumer reads
(`mojo_cstr_or_int_str`, `_len_of_boxed`, `_tagged_dyn_*`, the box arms in
`emit_exprs.py`/`emit_calls.py`). That is a runtime-wide change to fix one
call-site mix. (a1) reuses machinery that already exists and keeps the box
for the print-only case that works today.

Recommendation (a1): for a TOP-LEVEL free function whose parameter `p` is in
`_param_container_obs[f]` AND `_param_noncontainer_obs[f]` AND whose body
types it as a container, emit ONE DEFINITION PER DISTINCT CALL-SITE KIND of
`p`, and have each call site pick the definition matching its argument's C
type. Kinds are the set `{MojoList *, MojoDict *, MojoSet *, char *, int64_t}`
observed for `p`.

### Why this is cheap to express (verified anchors)

- A function's C symbol is `qualified_base + _overload_suffix(gen, name)`
  (`mojo/backend_gimple/emit_funcs.py:2668`), and `_overload_suffix` hashes
  `_effective_param_types(gen, name)` (`emit_funcs.py:2188`, `:2207`) via
  `overload_suffix_for` (`emit_funcs.py:1784`). So two definitions that differ
  only in the ctype of `p` ALREADY get distinct symbols. The suffix is a
  function of the param-type list, so a clone keyed on the kind is one more
  entry in that list, not a new scheme.
- The declared-overload path (`dup_def_signature_key`, `emit_funcs.py:1836`)
  already emits multiple same-named definitions as overloads. The clone path
  should reuse its emission loop, but key on call-site evidence, not on
  declared annotations (the overload path keys on annotations, which a
  call site does not give).
- Per-function body generation reads `self._inferred_param_types[name]`
  (`module_gen.py` ~8791-8815, ~11783). A clone is body generation run once
  per kind, with that parameter's inferred type PINNED to the kind. That is
  the only state that differs between clones.

### Implementation plan (files, functions, ordering)

1. **Collect kinds per call site, not per callee.** In `module_gen.py`, next to
   `_param_container_obs` (~9966) record `self._param_call_kinds[callee][pname]
   = set of argument ctypes` (the argument's C type as `_emit_call` sees it at
   the call). Do this in the same pass that records the container and
   non-container observations; do not re-walk the AST.
2. **Decide clone-eligibility** in a new `_plan_param_clones()` placed
   immediately BEFORE `_refuse_mixed_container_params()` (~10995). Eligible iff
   the function is a top-level `FunctionDef` (not a method, closure, generator,
   or async def), `p` is positional, the kinds set has >= 2 entries with at
   least one container, and `_inferred_param_types[f][p]` is a container. Store
   `self._param_clones[f] = {p: [kind, ...]}`.
3. **Replace the refusal with the clone plan for eligible functions only.**
   `_refuse_mixed_container_params` keeps raising for every NON-eligible mixed
   function (methods, closures, generators, passthroughs), so nothing silently
   regresses. Make the refusal the fallback arm, not the default.
4. **Emit one definition per kind.** In `gen_func` (`emit_funcs.py:2829`) loop
   over the planned kinds: pin `_inferred_param_types[f][p]` to the kind, emit
   the body, and name the symbol with `overload_suffix_for` over the
   kind-substituted param list. Emit each clone's prototype before any call.
5. **Select the clone at the call site.** In `emit_calls.py`'s user-function
   call arm (the path that calls `_func_csym`, `emit_funcs.py:2633`), when `f`
   has `_param_clones[f]`, pick the symbol whose kind matches the argument's
   ctype. A call whose argument kind matches no clone is a compile-time error,
   not a fallback to the wrong clone.
6. **Interactions to check before landing (all risks, none verified):**
   `_passthrough_param_idx` (`emit_calls.py:9687`, `:9782`) and
   `_return_elem_types` (test `test_a_string_passthrough_beside_an_int_one...`)
   key on the function NAME, so they must consult the clone that a call
   selects, not the base name. The reflection overload table
   (`reflect.func_overload_suffix`) must list each clone or the dylib export
   will miss them. `_reconcile_param_container_kinds` (`module_gen.py` ~8930)
   must see the pinned kind per clone, not the union.
7. **Do not touch step 2 yet.** The `int64_t`-iterable `for` lowering is only
   needed for the box representation, which this plan does not use.

### Tests that prove it

- Replace the refusal assertion in
  `test_an_iterated_parameter_passed_a_list_and_a_str_refuses_to_compile`
  (`test_gimple.py:8747`) with a positive case. Output must be `4\n5\nd\ne\n`
  through `_compiled_stdout` in BOTH single-TU (`do_imports=True`) and
  link-mode (`link_mode=True`), with no interpreter fallback (a fallback would
  hide a compiled-path regression).
- Assert the generated C contains exactly two definitions of `each` with
  distinct suffixes, one taking `MojoList *`, one `char *`.
- Keep the print-only mix (`test_a_str_call_beside_a_list_call_...`,
  `test_gimple.py:8697`) passing unchanged: it must still take the `int64_t`
  box and get no clones.
- Per the gate rule, this touches `module_gen.py`, `emit_funcs.py` and
  `emit_calls.py`, so the integrator owes a full `make gate` on it (it is
  the compiled path, not a single-file change). Not run here.

### Still open

Steps 1-7 are not implemented. The refusal stays the shipped behaviour until
they land. Steps 1-4 change behaviour together (the clone is emitted and
selected), so they must land as one round with the positive test from above;
landing step 1 alone would only record kinds and change nothing, which is not
a valid round output.
