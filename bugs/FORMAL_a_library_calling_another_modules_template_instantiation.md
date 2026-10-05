# FORMAL_a_library_calling_another_modules_template_instantiation: a LIBRARY that applies ANOTHER module's template is refused by name

**Area:** FORMAL (monomorphization, the dylib path) · **Status:** OPEN, not
fixed · **Found 2026-10-04** while landing §9a of
`bugs/FORMAL_generic_monomorph_scope.md` on `work/formal18-4`, which is the
document this one is adjacent to and does not cover

**This is the CROSS-MODULE half of the library path, and it is not a regression
and not §9a.** §9a was "a module that applies its OWN template and is built as
a dylib", and it is FIXED (see the Status at the foot). This is `libb` calling
`liba`'s template, which no document had named, and which was refused before
§9a, is refused after it, and for a different reason with a different
sentence.

## What was run and what it said

Three files, each its own module, built on BOTH architectures with
`fire.py build --formal --no-prove`:

    # liba.mojo — the template, and nothing else
    struct Pair[T]:
        var first: T

        def get_first(self) -> T:
            return self.first

    # libb.mojo — a library that APPLIES it
    from liba import Pair

    def make_pair() -> Int:
        var a = Pair[Int]()
        a.first = 7
        return a.get_first()

    # main.mojo — imports nothing but `make_pair`
    from libb import make_pair

    def main():
        print(make_pair())

`--backend=arm64` and `--backend=x86_64`, byte-identical text:

    build: main.mojo imports 'libb', which cannot be built either: libb.mojo:
    make_pair: `Pair` is called, and it is imported from `liba`, so the call has
    to bind a symbol `liba` exports. That module does not export it, and the
    reason is `doc/ABI.md`'s export rule rather than anything about this call:
    a name with a leading `_` is private, a generic template is not one symbol
    but one per instantiation (`_get_kgen_string[asm]()` is the measured case —
    both at once), an overload has no single symbol, and a C library name like
    `exit` or `write` is provided by libSystem. … A generic template's
    instantiations ARE compiled into that module's library when an importer asks
    for them (`formal/monomorph.py`), so this call is one that asked for none —
    it names no type argument, or names one that is a value rather than a type,
    or spells the template as `module.Pair`.

**CPython answers 7. Both machines refuse.** So this is a refusal and not a
wrong answer, which is the safe direction; it is a capability that is half
present, and the message's own last sentence is FALSE about this call: it does
name a type argument, and an importer asked for it — `libb` is the importer, of
`liba`, and `build_module_dylib` computed exactly that demand set before this
build reached the refusal.

## Why it is refused, in three facts

1. **The DEMAND is computed and the DEPENDENCY publishes the body.**
   `build_module_dylib` asks `instantiation_demands(source_path=libb,
   consumer_src=libb's text, own_templates=libb's own templates)`, which walks
   `liba`'s re-export closure and returns `{<liba path>: {"Pair": [("Int",)]}}`.
   That goes into `below`, `liba`'s dylib is built with it, and `_instantiated_
   sources` writes `struct Pair_1_T_3_Int` into the CAS as an extra source of
   **liba's** library. Measured: `liba`'s manifest carries
   `liba_Pair_1_T_3_Int_get_first`. So half the mechanism runs, correctly.
2. **The CALL SITE is not rewritten**, because nothing on this path rewrites it.
   `libb`'s own source still spells `Pair[Int]()`, and `formal/monomorph.py::
   rewrite_instantiation_calls` is reached on the dylib path only for a
   module's OWN demands — as of §9a (`016d938f`), and deliberately restricted to
   the templates the module DECLARES, because those are the only ones whose
   instantiation that library publishes.
3. **So the refusal is `imported_callee_refusal`,** which asks "does `liba`
   export `Pair`" and gets "no, and the export rule says why". The sentence
   names the template and the rule; it cannot name the half of the pipeline that
   ran.

The EXECUTABLE path has all three halves and has had them since the mechanism
landed: `formal/build.py::_imported_structs` → `formal/imports.py::
imported_instantiations` collects the instantiated `StructDef` from the
declaring module's GENERATED source (attaching the census from that source, for
`imported_struct_defs`' own reason) AND rewrites the call sites, from one
demap. `test_formal_monomorph.py`'s headline case
(`from pairlib import Pair` + `Pair[Int]()` in the PROGRAM) is that, and it is
green on both architectures.

## Why it is not a patch

`imported_instantiations` does two things a dylib needs and one thing it must
NOT do:

  * it collects the instantiated declarations — needed, because a library's
    `library_structs` is what the codegen recognises an `S(...)` constructor by;
  * it rewrites the call sites in place — needed, and already solved for the
    own-template case by `compile_formal_dylib(statements=…)`;
  * **it APPENDS the instantiated bodies to `stmts`** for the own-template half
    only (`_own_instantiations`' own docstring: "an imported template's body is
    compiled into the library that declares it"). Compiling `liba`'s
    instantiation body into `libb` as well would publish the struct's METHODS
    under `libb`'s prefix and give the image two definitions of one struct —
    and §9's own record is that "a declaration without its body makes the
    diagnostic worse, so the body is not optional to this change", which is the
    trap in the other direction.

So the refactor is to split `imported_instantiations` into "declarations and the
demap" and "append the bodies", hand the first half to `compile_formal_dylib`
alongside the rewrite, and keep the second half on the executable path. That is
a genuine separation of two facts that are currently one function, and doing it
by hand in `build_module_dylib` would put a third copy of the demap
construction in the tree — which is the thing
`monomorphize.mangle`'s single-mangler rule exists to prevent.

The demap's NAME is not the hard part and should not be re-derived here:
`monomorph.demap_from(made)` reads `instantiate_all`'s first list, and
`build_module_dylib` already has that list for `libb`'s OWN demands; the
cross-module entries come from the same reader asked about `below[liba]`, and
`instantiate` is the one mangler either way.

## The exact next step

1. In `formal/imports.py`, split `_own_instantiations` (the append) out of
   `imported_instantiations`, and give `imported_instantiations` a keyword
   (`append_bodies=True`) that `build_module_dylib` passes as False. Return the
   demap as well as the declarations, so the two callers cannot build different
   tables out of one `made`.
2. In `build_module_dylib`, ask `imported_instantiations` for THIS module's own
   text with `append_bodies=False`, take its demap, filter it to the templates
   this module IMPORTS (the own ones are already there and are disjoint by
   `imported_struct_defs`' precedence), and hand the union to
   `compile_formal_dylib(statements=…)` beside the own one. The declarations go
   in as `library_extra`, which is what §9a widened `extra_structs` for — and
   the per-file attribution filter `compile_formal_dylib` now has will keep
   `Pair_1_T_3_Int`'s methods qualified by the generated source's prefix rather
   than by `libb`'s, which is the property that has to hold.
3. Pin it with `test_formal_monomorph.py`'s `lib=None` option inverted: the
   existing harness already writes a library and a program, so this is one
   `run_pair_case` with a THREE-file tree (`extra={"liba.mojo": …}` beside a
   `libb.mojo` library), a CPython differential, both architectures, and two
   instantiations so the two cannot collapse onto one symbol.

## Verified, no Lean

* the reproducer above, `fire.py build --formal --no-prove` on both
  architectures, byte-identical refusal text;
* `test_formal_monomorph.py` 20/20, `test_formal_dylib.py` 24/24,
  `test_formal_imports.py` 72/72, `test_formal_cross_module.py` 35/35 on the
  tree §9a landed on — so the adjacent paths are green and this is a gap rather
  than a regression.

## Status

OPEN. Measured 2026-10-04 on `work/formal18-4` at `c466b3ee`. §9a of
`bugs/FORMAL_generic_monomorph_scope.md` — the OWN-template half — is fixed and
pinned (`test_formal_monomorph.py`'s "a module that applies its own template
publishes it", `test_formal_dylib.py`'s "a library source can use a sibling
source's struct", which is the second thing §9a was blocked on and is a bug in
its own right); this document is the third.
