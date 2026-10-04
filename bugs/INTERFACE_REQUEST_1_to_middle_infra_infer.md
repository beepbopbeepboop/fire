## Status (2026-10-02, later — item 1 of the previous entry is FIXED: the local-rebind class, which is the one that was red in stdlib, and it was FOUR defects, not one)

The entry below ends with a three-step ordering, and **step 1 is done**. The
local rebound to more than one container kind is now the `int64_t` box, inside
a lifted closure as well as at module level, and the box survives being handed
back and forwarded. What made it four defects rather than one is the useful
part of the record: each was invisible until the previous one was fixed, and
three of the four produced a SILENT wrong answer rather than the refusal this
entry was written about.

The shape, reduced from `argparse._parse_known_args.consume_optional` — `args`
is a dict literal in the ambiguous-option arm and a list in the other two:

```python
def outer(flag):
    def consume(i):
        if i == 1:
            args = {"option": "x", "matches": "y"}   # MojoDict *
        elif i == 2:
            args = ["x"]                             # MojoList *
        else:
            args = ["y", "x"]
        return args
    return consume(flag)
```

Before, `python3 tools/memslot.py --gb 8 -- python3 fire.py run` on that
shape's own text raised `cannot coerce MojoList * to MojoDict * (incompatible
container kinds) ... value='_t12' dest='args'` and nothing was built at all.
Now it prints CPython's answer on every arm.

1. **The box was installed and then immediately UNDONE**
   (`emit_stmts.py`'s `_pin_to_ground_truth` gate). `_mixed_container_locals`
   — which asks the function's own `_cur_func_body`, and is therefore the only
   predicate that can find a rebound local inside a lifted closure — named
   `args` correctly and the declaration site boxed it. Three "trust ground
   truth" rules then pinned it straight back to this assignment's own kind,
   because their gate consulted only `ginf.multi_kind_locals`: a DIFFERENT
   predicate, filled by `resolve_shared._infer_local_var_types`, which is
   handed bare `FunctionDef`s and never records a lifted closure's name. Both
   predicates now gate the group. Neither is removed as the thing that
   DECIDES the box — `multi_kind_locals` still is, for a name only the
   pre-pass found.
2. **A boxed return was not reported**, so a function that FORWARDED one was
   relabelled `MojoList *` at its caller — another container's memory, read
   out of bounds, printing `[0]` where CPython prints `{'a': 1}`. Silent, exit
   0. `_gen_stmt_ReturnStmt` now matches three ways the disagreement arrives,
   one predicate each, because each is the only one that sees a different one
   of them.
3. **The call site's `_boxed_container_vals` marking existed only in
   `_lower_named_call`**, so a lifted closure call did not get it. Same wrong
   answer, separate omission — hence a separate regression case.
4. **The verdict was recorded DURING lowering**, so it was visible only to a
   caller emitted later, and whether it was visible depended on WHICH of two
   functions was spelled first. `module_gen._infer_multi_kind_return` and its
   `_mkrf_round` fixpoint now answer it whole-program, in the same
   whole-program-then-lower-the-callee shape `_infer_return_maybe_kinds`
   already uses, placed after `discover_closures` because the closure arm walks
   nothing before it. The lowering recording is KEPT: it is the only place the
   local-shaped verdict can be read against the actual lowered value kinds.

Verified against CPython 3.14.7 on the same text through `compile_to_gimple` +
`gcc -fgimple` + run — the path `test_gimple_runner.py` uses — on seven
variants that between them reorder the declaration, add a free-function
forwarder, add a closure forwarder, and add a closure-calling-a-sibling
closure hop. All seven match; before, five of the seven either failed to build
or printed a decimal address. Four regression cases in
`test_silent_noop_iter.py`, whose pre-existing
`multi_kind_parameter_returned_is_the_box` is this same property one
indirection in and passes unchanged. `test_gimple.py` 368/368,
`test_gimple_runner.py` 292 passed / 10 failed (the identical ten, byte for
byte, with this change reverted), `test_link_mode.py` 15/15,
`test_module_cache.py` 84 passed / 2 failed (the two size assertions, identical
reverted), `test_container_equality/ordering/membership` and
`test_dict_tuple_key.py` all green.

### What is left of this doc, unchanged

**Items 2 and 3 of the previous entry's ordering are not done, and this
change does not touch them.** The PARAMETER rule — unanimity across call
sites, beside `_scalar_obs`/`_struct_obs` in `module_gen.py`'s caller walk —
is still wanted and its home is still the same one. So is the residual cast
at `_emit_call`'s `ptype.endswith(' *') and atype.endswith(' *')`, whose
comment still points here.

**And the measurement that would close this doc is still out of reach for a
light worker**, so treat the closure as still open rather than as fixed: no
whole-program stdlib build was run, so it is NOT established that `argparse`
or `re/_compiler` now compile. What IS established is that the specific
refusal this entry was written about — the local rebound that fired on both —
no longer fires on its own shape, and that it was four independent defects
rather than one. If `argparse` still does not compile, the next reader should
look for a refusal with a DIFFERENT `dest=`, because the four defects here
are gone. `compile_to_gimple` on the real `Lib/argparse.py` is the cheapest
measurement that would answer it, and it needs no self-host build.

One deliberate non-change, recorded so the next reader does not read it as an
oversight: a returned LOCAL contributes nothing to the pre-pass's kind set
unless it is known mixed. The pre-pass has none of the local-type tables the
lowering path builds incrementally, so a guess there would file a single-kind
answer for `return names` and a caller would trust it — the same wrong answer
this mechanism exists to prevent. Contributing nothing only costs that
function the single-kind credit that would let ITS caller compare kinds, and
the lowering-time recording supplies it.

## Status (2026-10-02 — the refusal this request unblocks is LIVE, and the two failures that are live today are NOT the class this request describes)

Measured while closing `bugs/COMPILE_FAIL_ctypes_util.md`: the R2 container-kind
refusal is not a proposal any more. It fires on real stdlib modules today, and
the modules are dropped from the closure — exactly what this request's BLOCKS
section predicted for the self-host.

```
# ERROR: compiling imported module 'argparse' from .../Lib/argparse.py:
  cannot coerce MojoList * to MojoDict * (incompatible container kinds)
  at .../Lib/argparse.py: value='_t238' dest='args'
# ERROR: compiling imported module '._compiler' from .../Lib/re/_compiler.py:
  cannot coerce MojoBytes * to MojoList * (incompatible container kinds)
  at .../Lib/re/_compiler.py: value='_t387' dest='data'
```

**And neither is the class this request asks for.** `dest='args'` is a LOCAL in
`argparse._match_argument`, and the traceback puts the refusal in
`_gen_stmt_AssignStmt` → `_safe_coerce_emit`, not in a call's argument
coercion: that one name is assigned a dict literal at argparse.py:2131 and list
literals at 2189 and 2207, so it is a local bound to three container kinds in
one function. Same shape for `re/_compiler.py`'s `data`. This request's rule is
"a PARAMETER observed at two or more CALL SITES"; the INTEGRATOR NOTE below is
right that the rule cannot live in `infra_infer.py` and right that it would live
in `module_gen.py`'s caller walk — and neither half of that is what is breaking
stdlib modules today.

**The principle is the same one this tree has already applied twice**: a name is
not a read, so `_declare_var`'s first-decl-wins is wrong for it. §4.3 of
`bugs/PARTIAL_WORK_HANDOFF.md` did it for a `for` target (`_declare_var(force=…)`
in `_gen_for_set`), and this is the assignment form of the same fix.

**On the two sites this request names**, measured as far as a light worker can:
`compile_to_gimple(ownership_check.py)` is CLEAN today (1 s, 8721 lines of
output), so the `state = {}` versus `MojoDict *` disagreement does not reproduce
in the only measurement available without a whole-closure self-host build. The
second site, `cpp_async.py`'s `known_structs`, is inside the compiler's own
closure and cannot be measured at all without `fire.py build fire.py`, which a
light worker must not run. **So this request's premise — that the cast at
`emit_infra.py` stays until those two sites stop disagreeing — is now the
smaller half of the problem**, and the call-site cast at `emit_infra.py:1974`
is still there with its comment still pointing here.

**What would actually move it, cheapest first:**

1. the LOCAL-rebind class above, in `_gen_stmt_AssignStmt`: when an assignment's
   value kind disagrees with the destination's already-declared container kind,
   re-declare rather than coerce (mirroring `_gen_for_set`'s `_fl_retype`). That
   un-blocks `argparse` and `re/_compiler` today, and it is one pass;
2. then this request's parameter rule, which is still wanted and whose home is
   unchanged (`module_gen.py`'s caller walk, beside `_scalar_obs`/`_struct_obs`);
3. only then the cast at `emit_infra.py:1974`, whose comment says it goes with
   them.

Not attempted by the worker that measured this: `emit_stmts.py` and
`module_gen.py` are both mid-merge under other claims, and this is one of the
places where a wrong choice is a silent wrong value in a stdlib module rather
than a build failure.

INTERFACE REQUEST  from=[1]  to=[owner of mojo/middle/infra_infer.py]  file=mojo/middle/infra_infer.py

WHAT: `_infer_param_types` should not commit to a CONTAINER KIND for a
      parameter unless every call site's observation agrees, and should box
      the parameter to `int64_t` when they do not. Right now a parameter
      whose call sites pass different container kinds is typed as whichever
      kind was observed, and the other call sites are then made to fit by a
      pointer cast at `mojo/backend_gimple/emit_infra.py`'s
      `_emit_call` (`ptype.endswith(' *') and atype.endswith(' *')`).

      Concretely, the rule to add is the container analogue of the
      unanimity rule `_scalar_obs` already applies to `char *`/`double`
      (see that observer's docstring, which explains why a struct pointer
      mixed into the set must SUPPRESS an otherwise-unanimous `char *`
      rather than lose it): for a parameter observed as a container at two
      or more call sites, take the kind only if the observed set is a
      single element; otherwise fall back to the `int64_t` default, which
      the backend already has a working runtime-dispatch path for
      (`_gen_for_iter`'s `mojo_is_registered_dict` /
      `mojo_is_registered_list` arms).

WHY: Two modules in the compiler's own self-host closure hit exactly this
     today, and each one is a genuine inference disagreement rather than a
     type-confused program. Measured, both reproducible from
     `python3 fire.py build fire.py` with a container-kind guard live at the
     `_emit_call` site:

     1. `ownership_check.py`
        ```
        cannot coerce MojoList * to MojoDict * (incompatible container kinds)
          at ownership_check.py: value='state' dest='_t56'
        ```
        `state = {}` at ownership_check.py:589. The empty-container literal
        is genuinely ambiguous — `reify_empty_container_literal` /
        `_EMPTY_CONTAINER_CTOR` (mojo/middle/types.py:260) exist precisely
        because `{}` could be either — and it is inferred `MojoList *` at
        one site while `_check_block` / `_check_stmt` / `_walk_expr`'s
        `state` parameter is inferred `MojoDict *`. `state` is a dict
        throughout that file.

     2. `mojo/backend_gimple/cpp_async.py:829`
        ```
        cannot coerce MojoSet * to MojoDict * (incompatible container kinds)
          at mojo/backend_gimple/cpp_async.py: value='_known_structs' dest='_t956'
        ```
        `_known_structs = frozenset(gen.struct_field_types.keys())` is
        correctly inferred `MojoSet *` and passed as `known_structs=` to a
        parameter inferred `MojoDict *` (cpp_async.py:849, and the same
        shape at :1247).

     Today both survive only because `_emit_call` casts. The cast does not
     crash, because neither callee dereferences the wrong layout — which is
     luck, not a property, and is the same failure mode already recorded
     for this guard (a 26 ms SIGBUS 34 GB past a slot array,
     ast_rewriter.py's `bindings`).

BLOCKS: Turning the R2 refusal on at the `_emit_call` site. With the guard
        live, `python3 fire.py build fire.py` fails with 738 gcc errors —
        not from the two refusals themselves (the driver handles those
        gracefully, one `# ERROR: compiling imported module` line each) but
        because the two modules are dropped from the closure and every
        symbol they define then loses its declaration. So the residual
        container-kind CAST in `mojo/backend_gimple/emit_infra.py`
        (`_convert_container_kind` returning `None`) has to stay until this
        lands, and its comment says so and will be removed with it.

       This is not a request that blocks anything else of [1]'s. The other
       three fixes in this round (the `void *` iterable that never reached
       the boxed runtime dispatch, `reversed()` over an untyped value, and
       the `re.findall` lowering) are independent of it and are already
       landing.

---

## INTEGRATOR NOTE — the addressee is wrong; the fix is [1]'s own, in a file [1] owns

Added at the merge of [1]+[2] (468fc8a). [1]'s text above is unaltered.

**The rule as worded cannot be implemented in `mojo/middle/infra_infer.py`,
because the data it needs is not in that scope.** Verified, not inferred:

* `analyze_param_usage(nodes, param_name)`
  (`mojo/middle/infra_infer.py:318`) takes the CALLEE's own statement nodes and
  one parameter name. It is a body scan.
* `_infer_param_types` (`:213`) reads exactly these off `gen`: `_KNOWN_SIGS`,
  `func_return_types`, `struct_field_types`, `conditions`, `iterable`,
  `_param_usage_scan_cache`. Every one is callee-side. There is no call-site
  map, and "unanimity across call sites" has nothing to be unanimous about.

So "require unanimity across call sites" is not a rule `infra_infer.py` can
apply. It would have to be applied where the call sites are enumerated.

**They are enumerated in `mojo/backend_gimple/module_gen.py` — [1]'s own write
set** — in the loop over `_caller_bodies` / `all_functions` (~:4694), which
already builds two per-callee-per-parameter observation MAPS:

    _scalar_obs: dict[str, dict[str, set]] = {}   # callee -> {pname -> {types}}
    _struct_obs: dict[str, dict[str, set]] = {}

and applies the "only if unanimous" rule to the first of them. `_scalar_obs`
IS the precedent this request cites — its own docstring at ~:4244 spells out
the exact semantics wanted here ("a struct pointer mixed into the set must
SUPPRESS an otherwise-unanimous `char *` rather than lose it"). Two working
implementations of the rule, in the same loop, in the same file [1] edits.

**So the work is:** add `_container_obs` beside those two in that loop (same
`callee -> {pname -> {types}}` shape, fed by a container-kind observer
alongside `_arg_scalar_type` / `_arg_struct_ptr_type`), and apply the unanimity
rule where the container kind is chosen — falling back to `int64_t`, which the
backend already dispatches correctly through `_gen_for_iter`'s
`mojo_is_registered_dict` / `mojo_is_registered_list` arms. No new owner, no
cross-boundary coordination, no unassigned file.

**Consequences of the repoint, stated so the next agent does not have to
re-derive them:**

* §11.2 lists `mojo/middle/*` as DELIBERATELY UNOWNED this round. As written the
  request has no addressee at all, which is why it could not land and why it
  sat. Repointed at `module_gen.py` it is [1]'s own follow-up.
* `_convert_container_kind`'s two real conversions
  (`mojo_set_to_list`, `mojo_dict_keys`) are unaffected and stay either way —
  they are exact, not casts.
* The residual cast in `emit_infra.py:1383` and its comment stay until the
  container-kind parameter is UNANIMOUS, i.e. until the two measured sites stop
  disagreeing. Do not delete the cast as part of landing this: the 738-error
  measurement in the BLOCKS section is the reason, and it is a property of the
  closure, not of the rule.
* Cheapest first step, worth measuring before writing the rule: the
  disagreement is between the callee's body-derived kind and each caller's own
  kind of the argument. So the two sites may be fixable AT THE CALL SITE (an
  explicit annotation on `state` / `known_structs`, or reordering so the empty
  literal is not the only evidence) for a fraction of the cost, with the
  inference rule as the general fix behind it. That is a measurement, not a
  claim, and it is [1]'s to make.
