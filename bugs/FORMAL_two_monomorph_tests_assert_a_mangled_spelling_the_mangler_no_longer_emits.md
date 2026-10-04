# FORMAL_two_monomorph_tests_assert_a_mangled_spelling_the_mangler_no_longer_emits

**Area:** `formal/monomorph.py` (consumer of `monomorphize.mangle`) ·
`test_formal_monomorph.py` · **Status:** OPEN, found 2026-10-04 while working
`project18:export-gate` · **Layer:** 1/5 of the formal work

Two tests in `test_formal_monomorph.py` fail on `master` (`86d60026`) with no
local change, and the doc that owns the spelling says a thing that is no longer
true. Neither is caused by the per-edge export-gate rule on
`work/formal18-export-gate` — verified by running the suite with
`formal/imports.py` and `formal/build.py` restored from `HEAD`, which fails
identically.

## 1. What is observed

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

## 2. The cause, and it is NOT a functional break

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

What fails is **two hard-coded expectations of the old spelling**, and one doc:

* `test_an_instantiation_substitutes_the_parameter_and_keeps_the_self_spelling`
  asserts `mangled == "Bag_Int"`;
* `two demand sets are two libraries` asserts a `Pair_Int` symbol in the
  library's export trie;
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

## 3. The exact next step

1. Read the boundary spelling off the mangler instead of writing it out:
   `test_formal_monomorph.py`'s two assertions should compute the expected name
   with `monomorphize.mangle` (or `MM.instantiate`'s own return), so a future
   change to the encoding moves the test with it. The `two demand sets` case
   should look the symbol up as
   `formal.model.abi_method_symbol(prefix, mangled_struct_name, method)` for
   the same reason.
2. Correct the `Pair_Int` sentences in `doc/ABI.md` §Generics, in §6 of
   `bugs/FORMAL_generic_monomorph_scope.md` and in that doc's §1 (three
   `Pair_Int` mentions) to the injective spelling, and say WHERE it is stated —
   one sentence, so the next reader is sent to `monomorphize.mangle` rather than
   to a string in a bug doc.

This is small and it is not mine: `monomorphize.py` is shared compiled-path
engine and the two tests are in the monomorphization suite, which
`formal15-generic-monomorph` landed. It is filed here rather than fixed because
`project18:export-gate` owns the import EDGE rule and not the mangler's
spelling, and a worker editing a shared mangler to satisfy a formal test would
be doing exactly the "change a shared engine on the strength of a caller" thing
`formal/monomorph.py`'s `_fold_self_params` docstring warns against.

## 4. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label t -- python3 test_formal_monomorph.py
python3 -c "import monomorphize as m; print(m.mangle('Pair', {'T': 'Int'}))"
```