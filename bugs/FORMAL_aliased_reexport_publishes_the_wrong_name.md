# An aliased re-export is published under the DEFINING module's name, so the alias no consumer asks for is never exported

**Status: OPEN. Found while extending `formal/imports.py`'s import-binding
reader; not fixed here, because the fix changes what every dylib manifest on
disk claims its module exports, which is the integrator's gate to take.**

## What I ran

    .tmp/exp/alias/leaf/__init__.mojo   def base(x): return x * 2
    .tmp/exp/alias/pkg/__init__.mojo    from leaf import base as aliased
    .tmp/exp/alias/prog.mojo            from pkg import aliased
                                         def main(): return aliased(21)

    $ python3 fire.py build --formal --no-prove --backend=arm64 -o prog.aout prog.mojo
    build: prog.mojo: the image would bind 1 symbol(s) that nothing provides,
    so it could not be loaded: aliased. Nothing on this link line defines them:
    not the C library, and not any library this program linked.

## What I expected

`aliased(21)` is a call of a name `pkg` binds by re-export and `pkg`'s library
exports, so the image should bind `pkg`'s forwarded symbol and run with exit 42.

## What is actually happening

`formal/imports.py`'s `reexported_names` keys its table on the name the
DEFINING module gave the symbol, not on the name the re-exporting module binds:

    for _bound, name, module in _from_import_bindings(stmts):
        out.setdefault(name, (module, kind))       # `name` is the ORIGINAL

so `pkg`'s manifest publishes `base` — which `pkg` does not bind — and not
`aliased`, which every consumer of `pkg` actually asks for. The build then
refuses to emit an image whose symbol nothing provides, which is the right
behaviour and the wrong outcome: the program is correct Mojo and the backend
cannot link it.

The sibling reader added alongside it, `imported_bound_names`, records the
BOUND name (`aliased`) precisely because that is the question its caller asks
("is this bare callee a name from another module?"), and the two docstrings now
say why they differ. The asymmetry is deliberate in one direction and a defect
in the other, and it is written down in both places so it is not rediscovered as
a mystery.

## Why it is not fixed here

* `reexported_names` is the input to every manifest's `reexports` list. Changing
  which names it records changes what every module publishes, so the fix wants a
  gate run over the dylib and import suites (`test_formal_dylib.py`,
  `test_formal_imports.py`) and a cold CAS, not a worker's single file.
* Two readings of "fix it" and they are not equivalent:
  1. record the ALIAS as an additional key (`{base: (…), aliased: (…)}`) — purely
     additive, every existing manifest key stays, and a consumer of either
     spelling resolves. The forwarder would export the same symbol twice under
     two names, which costs a symbol and nothing else.
  2. record only the alias — smaller, and it breaks anything resolving the
     original spelling, which is the same class of regression as the MLIR
     template spellings noted in `formal/model.py`'s `is_mlir_template`.
  Option 1 is the one to implement; the decision is the integrator's because the
  manifest content is shared state.
* This is adjacent to `FORMAL_module_exports_nothing.md` and to
  `construct:dylib-export-gate`, neither of which this worker holds.

## The exact next step

1. `reexported_names`: record `(original, module, kind)` and
   `(alias, module, kind)` when an alias exists (option 1 above), keeping the
   `_is_inert_module` / private / locally-defined filters as they are.
2. A case in `test_formal_imports.py`: the three-file tree above, asserting
   `aliased(21)` builds, links and exits 42 — the file already has the
   `write_tree` / `build` / `run` helpers and a `CYCLE_PROG`-shaped multi-module
   case to sit beside.
3. One guard for option 1's cost: a case that imports the same symbol under its
   ORIGINAL spelling and asserts it still binds, so the additive change cannot
   quietly become subtractive.