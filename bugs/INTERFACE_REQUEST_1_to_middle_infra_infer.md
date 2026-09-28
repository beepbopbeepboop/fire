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
