# FORMAL_a_mangled_spelling_is_still_stated_as_Pair_Int_in_the_ABI_doc_and_the_scope_doc

**Area:** `doc/ABI.md` §Generics · `bugs/FORMAL_generic_monomorph_scope.md` ·
**Status:** OPEN, found 2026-10-04 while working `project18:export-gate` ·
**Layer:** 1/5 of the formal work

**The two TESTS are already fixed** — `work/formal18-tile-specialization`
(`f6e127d5`, "tests: derive two monomorph expectations from the ONE mangler")
derives both from `monomorphize.mangle` instead of writing the old literal, and
its message says they were "measured pre-existing on" the tree this doc was
written against. **What is left is the DOC half, which that commit did not
touch** and which is what this doc is for.

It was found as two red tests, for the record:

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label t -- python3 test_formal_monomorph.py
```

```
  FAIL  an instantiation substitutes the parameter and keeps the Self spelling
        the mangled name is 'Bag_1_T_3_Int'
  FAIL  two demand sets are two libraries
        pairlib.<src>.<compiler>.arm64.dylib exports no Pair_Int symbol:
        ['pairlib_Pair_1_T_3_Int_get_first', 'pairlib_Pair_get_first']
formal monomorphization: PASS=9 EXPECTED=0 SKIP=0 FAIL=2
```

(Neither failure is caused by the per-edge export-gate rule on
`work/formal18-export-gate` — both fail identically with `formal/imports.py` and
`formal/build.py` restored from `86d60026`.)

## 1. The cause, and it is NOT a functional break

`monomorphize.mangle` is deliberately injective now — its own docstring says so,
and points at `bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`:

```sh
>>> python3 -c "import monomorphize as m; \
    print(m.mangle('box', {'T': 'Int64'}), m.mangle('Pair', {'T': 'Int'}))"
box_1_T_5_Int64 Pair_1_T_3_Int
```

The old scheme (`box_Int64`) was not injective — 1512 collisions over 1752
generated `(name, type_args)` pairs, measured in `safe_suffix`'s docstring — so
every cached artifact was deliberately invalidated by that change.

**So the formal path still WORKS**: both sides of the boundary compute the name
from the one mangler. `formal/model.py::abi_method_symbol` is
`f"{module_prefix}_{struct_name}_{method}"` and `struct_name` is the mangled
`Pair_1_T_3_Int`, which is why the library exports
`pairlib_Pair_1_T_3_Int_get_first` and the importer finds it — the
end-to-end differential tests (`a generic struct template is instantiated at the
importer's type`, `an instantiation agrees with the concrete struct of the same
shape`) PASS and print CPython's answer on both architectures.

What the two red tests were asserting, and what the docs still assert:

* `test_an_instantiation_substitutes_the_parameter_and_keeps_the_self_spelling`
  asserted `mangled == "Bag_Int"` and `two demand sets are two libraries`
  asserted a `Pair_Int` symbol in the library's export trie — both now derived
  from the mangler by `f6e127d5`;
* `bugs/FORMAL_generic_monomorph_scope.md` §6 ("The mangling spelling, and
  `doc/ABI.md`'s example") states "`monomorphize.mangle` emits `Pair_Int`. …
  They are different strings and the tree has one mangler, which is the correct
  number." — the second half is still true and the first is now false, so §6 is
  asserting a spelling no code produces. §1 of the same doc also writes
  "`Pair_Int` is what the boundary symbol has to be" in three places.
* **`doc/ABI.md` §Generics says it too**: "The mangling is `monomorphize.mangle`
  — `Pair_Int`, one underscore-joined suffix — which is what the compiled path's
  `Elaborator` computes and what its objects are named." So the stale spelling
  is stated in the ABI CONTRACT, which is the one document a consumer reads to
  learn what the boundary symbol is.

`doc/ABI.md` §Generics's other example (`Generic__method__<mangled-type-args>`)
is illustrative and not wrong, so nothing in it has to change beyond the sentence
that names the mangler's output.

## 2. The exact next step

1. **Done** by `work/formal18-tile-specialization` (`f6e127d5`): both tests now
   compute the expected name from the mangler rather than writing it out, so a
   future change to the encoding moves them with it.
2. **Open**: correct the `Pair_Int` sentences in `doc/ABI.md` §Generics, in §6 of
   `bugs/FORMAL_generic_monomorph_scope.md` and in that doc's §1 (three
   `Pair_Int` mentions) to the injective spelling, and say WHERE it is stated —
   one sentence, so the next reader is sent to `monomorphize.mangle` rather than
   to a string in a bug doc.

## 3. Why it is filed and not fixed here

`doc/ABI.md` is the shared ABI contract and `FORMAL_generic_monomorph_scope.md`
is another lane's measured remainder list (`formal15-generic-monomorph` landed
the mechanism); `project18:export-gate` owns the import EDGE rule and neither of
those. Rewriting the boundary spelling in the ABI document from a worker whose
change is three files away in `formal/imports.py` is the "fix the shared
contract on the strength of your own caller" move that
`formal/monomorph.py`'s `_fold_self_params` docstring warns against — and here
the sentence is load-bearing for anyone reading the boundary symbol, so it
should change with the mangler's own next change rather than in a side commit.

## 4. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label t -- python3 test_formal_monomorph.py
python3 -c "import monomorphize as m; print(m.mangle('Pair', {'T': 'Int'}))"
```