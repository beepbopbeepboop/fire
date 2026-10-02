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
