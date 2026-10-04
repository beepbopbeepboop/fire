# link mode: an imported function reached through TWO importers gets a `(void)` prototype

## Status: OPEN, not fixed — found 2026-10-03 by `work/gatefix5` while writing
## the regression test for
## `CODEGEN_two_private_functions_of_one_name_share_one_return_type.md` (that one
## is deleted with its fix). It is a different defect and did not block it.

## What I ran

The single-TU pipeline is where two same-named definitions collide, so the test
that covers the return-type fix is single-TU only. Adding link mode to the same
fixture is what surfaced this, and the fixture does not even need a name
collision to hit it:

    p/lister.py   def hits(items, name): return len(items)
    p/checker.py  from p.lister import hits
                  def found(items, name): return hits(items, name) + 1
    p/main.py     from p.checker import found

`python3 fire.py`-equivalent, `gimple_codegen._run_pipeline(..., link_mode=True)`,
then `gcc -fgimple`:

    p/checker.py:192:16: error: conflicting types for 'p_lister_hits_d07985';
        have 'int64_t(void)'
    p/lister.py:9:9: note: previous definition of 'p_lister_hits_d07985' with
        type 'int64_t(MojoList *, int64_t)'
    p/main.py: In function '_gimple_main':
    p/main.py:7:9: error: too many arguments to function 'p_lister_hits_d07985';
        expected 0, have 2

and the same program under `do_imports=True` compiles and prints CPython's
answer.

## What it is

The link-mode export layer emits, from the re-exporting/importing module:

    extern int64_t p_lister_hits_d07985 (void);  /* from p.lister */

A prototype with NO parameters, contradicting the definition in the same
translation unit. Every call through it is then "too many arguments", and gcc
rejects the unit. So any program where one module imports a symbol that a
SECOND module also imports fails to build, under link mode only.

Measured to be the DIAMOND and not the return type:

| fixture | single-TU | link mode |
|---|---|---|
| `main -> checker -> lister` (one importer) | compiles | compiles |
| `main -> {lister, checker}`, `checker -> lister` (two importers) | compiles | **fails** |

So the trigger is a module reached by two importers, not a same-named function,
not a return type, and not a diamond in the `__init__` re-export sense.

A second shape of the same prototype is worth recording because it is what the
two-importer fixture produces when the parameters are typed rather than
inferred — the extern disagrees on the types too, not only the arity:

    extern int64_t p_lister_hits_d07985 (void);
    int64_t p_lister_hits_d07985 (MojoList *, int64_t)

## Where to look

`external int64_t p_lister_hits_d07985 (void);  /* from p.lister */` is emitted
by the link-mode re-export/extern preamble from the IMPORTING module's export
table, whose signature for an imported name is the text scan's. The scan reads
`module_loader`'s export table for the DEFINING module; when the symbol is
reached through a second importer, the entry it finds is the one registered by
that importer rather than the defining module's own, and a registration with no
resolved parameter list becomes `(void)`.

The two readers to compare are `_imported_home_param_types`
(`mojo/middle/module_shared.py`, written at FromImportStmt registration, keyed
`_pair_key(qualifier, name)`) and the extern-preamble emission that consumes the
export table in `mojo/backend_gimple/module_gen.py`'s link-mode path. Note the
param-type half of this already has a home-qualified store
(`_home_def_param_types`) whose reader is `emit_funcs._imported_def_pts`; the
extern preamble appears to read the unqualified table instead, which would be
the same bare-key mistake in a different place.

## Next step

1. Emit the extern from the SAME store `_imported_def_pts` reads (or from the
   defining module's own export row) rather than from the importer's snapshot,
   so the two halves of one symbol cannot disagree about arity — the identical
   failure mode and the identical fix shape as the `log_match` c52cbf-vs-7a6366
   family that `_home_def_param_types` was added for.
2. Add a `test_gimple.py` case next to
   `aliased_and_reexported_imports_resolve_to_the_defining_module`: three
   modules, one diamond, run under BOTH pipelines against CPython. The
   single-TU half already passes, so it is a real two-pipeline assertion rather
   than a new expectation.

## Re-verify with

The three-module fixture above under `link_mode=True`, plus
`python3 tools/memslot.py --gb 8 --label lk -- python3 test_gimple.py`.
