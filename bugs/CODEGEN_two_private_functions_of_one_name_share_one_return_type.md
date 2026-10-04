# two private functions of one name in a translation unit share ONE return type

## Status: OPEN, not fixed — measured, isolated to one line of one pass, and the
## fix needs module attribution that `gen_module_impl` does not carry. Found
## 2026-10-03 by `work/gatefix4` while unblocking `selfhost`; the two fixes that
## unblocked the layer above it are on that branch and their docs are deleted
## with them.

## What I ran

The fast loop from
`bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`,
against the self-host closure, after the `elaborate.py` inference fix and the
`_c_names` lifted-closure fix had removed every other gcc error:

    python3 tools/memslot.py --gb 8 --label sh-build -- python3 .tmp/sh_build.py
    cd .tmp/sh && sed 's/^#line .*$//' fire.ci > fire_nl.ci
    /opt/local/bin/gcc-mp-15 -x c -fsyntax-only -fgimple -w -std=gnu11 \
        -I../../runtime fire_nl.ci 2>&1 | grep ' error: '

    fire_nl.ci:885606:8: error: assignment to 'MojoList *' from 'int' makes
        pointer from integer without a cast [-Wint-conversion]

**One** error, down from the two the layer started with.

## What it is

`mojo/middle/offload.py::_mentions(node, name: str) -> bool` and
`mojo/backend_gimple/elab_intu.py::_mentions(ann)` are two different private
functions with the same bare name, in two modules of one translation unit. The
second returns a list, the first a bool.

`gen.func_return_types` is keyed by the BARE name, and `module_gen.py`'s Pass 1.3
(`for s in all_functions:` — `all_functions = stmts + imported_stmts`, i.e. the
whole transitive closure as one FLAT list with no module attribution) writes

    self.func_return_types[_as_s_p1.name] = inferred

**only for functions with no return annotation** (`if isinstance(s, FunctionDef)
and s.return_type is None`). So:

* `elab_intu._mentions` is unannotated, so it writes `_mentions -> MojoList *`;
* `offload._mentions` is annotated `-> bool`, so it contributes **nothing** — and
  its call sites read the only `_mentions` entry there is.

Measured in the emitted C (not inferred):

    int mojo_middle_offload__mentions_c2eb2a (int64_t node, char * name)   <- definition, annotation honoured
    MojoList * mojo_backend_gimple_elab_intu__mentions_d719e0 (char * ann) <- definition, inferred

    /* offload.py's `if _mentions(call.args, str(st.target)):` */
    _t92 = mojo_middle_offload__mentions_c2eb2a (_t93, _t91);   /* _t92 is MojoList * */
    _t95 = mojo_list_len (_t92);                               /* so the test is a LIST test */

So the call site tests a `bool` with `mojo_list_len` on a value that was never a
list. `elab_intu`'s own call sites get `MojoList *` and are right — by luck, not
by resolution.

The C symbols are module-qualified and correct
(`mojo_middle_offload__mentions_c2eb2a` vs
`mojo_backend_gimple_elab_intu__mentions_d719e0`), so the *naming* layer already
resolves this. Only the return type is bare-keyed.

## Why the three cheap fixes are not fixes

Recorded because each was tried or reasoned through and each is wrong.

1. **Honour the annotation in Pass 1.3.** It moves the error rather than fixing
   it: whichever of the two writes the bare slot last, the OTHER one's call
   sites are then mistyped, and by symmetry the failure is the same
   `-Wint-conversion` on a `MojoList *` temp holding an `int`.
2. **First-writer-wins / last-writer-wins (any ordering rule).** Still one
   arbitrary module's answer in a slot two modules need. There is no ordering
   that is right for both, which is the actual statement of the defect.
3. **Delete the bare entry when the name is ambiguous (fall back to the box).**
   Honest about the ambiguity, and `_gen_for_iter` already recovers a boxed list
   with `_coerce_to_type('int64_t', 'MojoList *', it_val)` — but the policy has a
   measured blast radius, below, and adopting it needs the
   `stdlib-dylib` skip-count and `stdlib-syntax` unexpected-failure comparisons
   that only a full gate can give.

## How wide it is

Measured over the 56 modules `cas.selfhost_closure_is_complete('fire.py')`
reports (the exact closure the self-host build compiles), parsing each and
collecting every `FunctionDef` and struct method:

| | count |
|---|---|
| distinct function names | 2050 |
| names with more than one definition | **444** |
| …whose DECLARED shape disagrees (return annotation or arity) | **44** |

Most of the 444 are benign (same annotation, same arity, or never called across
the module boundary). The 44 are the population a fix has to be right about, and
they include several more of exactly this class — the ones with a return-type
disagreement and no same-name sibling to hide behind:

    _mentions    mojo/backend_gimple/elab_intu.py ret=None  | mojo/middle/offload.py ret='bool'
    _walk        elab_intu ret=None | coro ret=None | lambdareduce ret=None | resolve_shared ret=None
    run          fire_compiler.py ret=None | elab_intu ret=None | myinterpreter.py ret=None
    note         determinism_trace.py ret='int' | emit_infra ret=None | infra_infer ret=None x2
    resolve      gimple_codegen.py ret=None | imports.py ret='ModuleEntry' x2
    _matching_bracket  elab_intu ret=None | exprtypes.py ret='int'
    is_signed / is_unsigned   mojo/middle/types.py ret='bool' | myinterpreter.py ret=None
    _expect      fire_compiler.py ret='Token' | regex_compile.py ret=None
    emit         fire_compiler.py ret='str' | regex_compile.py ret='int'
    build        build_stdlib_dylib.py ret='str' | monomorphize.py ret=None x2

(`ret=None` means unannotated, i.e. inferred — and an inferred `MojoList *` from
`any(<genexp>)`, which lowers to a materialized list, is the common cause. That
is a separate defect from this one and has its own honest answer: an explicit
return annotation on `offload._mentions` would remove this instance without
touching the table. It does not remove the class, which is why it is not the
fix.)

## Next step

Give `func_return_types` a per-definition key that the call site can already
compute. The pieces are all present and this is why it is a project rather than
a patch:

1. `emit_funcs._func_csym(bare)` already builds a module-qualified, suffix-free
   prefix — `qualifier + '_' + _safe_name(bare)`, where `qualifier` is
   `gen._func_qualifier(bare)` from the CALLER's module — and the call site
   therefore knows which module it is calling into. The mangled half that
   follows needs `func_param_types`, which Pass 1.3 does not have yet; the
   prefix half does not.
2. Pass 1.3 needs the DEFINING module of each `s`, and it has none:
   `all_functions` is `stmts + imported_stmts`, flattened. Either thread a
   parallel `(module, stmt)` list through the pass, or record the attribution
   where it is still known (`_compile_imported_module`'s per-module `temp_gen`,
   which already emits each module separately into the same TU) and merge the
   per-module tables instead of the flattened one.
3. Then: Pass 1.3 writes BOTH `func_return_types[bare]` (unchanged, for every
   reader that has no module context) and `func_return_types[prefix]`; and
   `_emit_call`'s "Also check func_return_types" mismatch-correction block
   (`emit_infra.py`) reads `prefix` first and falls back to `bare`. A missing
   `prefix` entry must stay a fallback, never a refusal — `_func_csym` is called
   before the callee's own definition is emitted in source order, which is the
   `glob.py::_join` case its own comment documents.

Once (2) exists, (3) is a few lines and the 44-name population becomes
measurable rather than scary: the fix's own regression coverage should be a
`test_gimple.py` case with two same-named free functions in two modules of one
package, one returning a list and one a bool, asserted on both pipelines against
CPython.

## Re-verify with

The two commands in "What I ran". `grep ' error: '` must print nothing. Then
`python3 tools/suite.py selfhost mojoc bootstrap-stage2-cc gimple` — the first
three all build this closure, so they are the same measurement by three routes.
