# FORMAL_a_dylib_export_whose_constructor_returns_a_callee_built_frame: the manifest publishes a frame layout the callee does not use

**Class:** soundness. **Area:** the dylib export set and the frame-return
refusal — `formal/build.py`'s `_frame_return_status` / `_check_frame_escapes`
and `_writeback_rebound_receivers`, which
`bugs/FORMAL_one_word_ctor_of_a_nested_frame_is_unexportable.md` (owned by
`formal13-5`, claim `bug:FORMAL_one_word_ctor_of_a_nested_frame_is_unexportable`)
describes. **NOT FIXED HERE — that area is another worker's, and this doc is the
measurement that says its §0 table's second row is no longer true.**

Found 2026-10-04 while running `test_formal_dylib.py` as the narrow test for
`bugs/PERF_formal_import_asks_are_products_of_the_closure.md`'s cost work. That
test's case `a receiver write-back is not a returned frame` FAILS, and it fails
at `HEAD` as well as before it, so it is not a regression from this branch.

## What I ran

    python3 tools/memslot.py --gb 8 -- python3 test_formal_dylib.py
    #   FAIL  a receiver write-back is not a returned frame
    #         a constructor that ASSIGNS a frame to its own one word was built
    #         as a dylib: the frame it hands back is one the CALLEE built, and
    #         an importer has no way to learn the width of the block it must
    #         reserve
    #   formal dylib: PASS=22 FAIL=1

The failing check is the FIRST of the case's two, at
`test_formal_dylib.py:1583`: it asserts `result.returncode != 0`, and the build
succeeds. Reproduced on its own, outside the test, from
`test_formal_dylib.py`'s own `rebinds` half:

    $ cat .tmp/rb/rebinds.mojo
    struct Inner:
        var a: Int
        var b: Int

    struct Box1:
        var inner: Inner

        def __init__(out self, a: Int, b: Int):
            self.inner = Inner(a, b)      # ← the ASSIGNING shape

    def mk(x: Int) -> Int:
        return x + 1

    $ python3 fire.py dylib --formal --no-prove -o .tmp/rb/rebinds.dylib \
          .tmp/rb/rebinds.mojo
    Built: .tmp/rb/rebinds.dylib                       rc=0

## What I saw

**The library is emitted AND `Box1___init__` is in its manifest**, with a
published frame contract:

```json
{"name": "Box1___init__", "kind": "method", "arity": 3,
 "signature": "Box1.__init__", "symbol": "rebinds_Box1___init__",
 "call": {"positional": ["self", "a", "b"], "required": ["self", "a", "b"]},
 "frame_params": [["Inner", "Inner"], null, null]}
```

So an importer reads `frame_params[0] == ["Inner", "Inner"]` and reserves a
two-word block of `Inner` for the `self` parameter. **The callee does not use
that block**: `self.inner = Inner(a, b)` is a store the one-word elision
collapses onto `self`, so the callee binds a frame IT built and hands its
address back — which is precisely the case the refusal exists for. The
contract and the code disagree, and the disagreement is published rather than
refused.

## What I expected

`bugs/FORMAL_one_word_ctor_of_a_nested_frame_is_unexportable.md`'s §0 table,
row 2, says of this exact source:

| constructor | before | after |
|---|---|---|
| `self.inner = Inner(a, b)` — ASSIGNS a frame to its own one word | refused | **still refused**, with the same sentence |

and the sentence it quotes is the one the test still asserts on
(`"returns a frame address" in text`). **Measured now: built, rc=0, with a
frame contract in the manifest.** Either the table is stale or the rule moved;
nothing in that doc's Status says which, and `git log` on the files it names
does not show a change that would explain it.

The sibling shape — `self.inner.a = a`, writing THROUGH the caller's block —
is still handled the way the same table's row 1 says (builds, exports `mk`,
no refusal), so the split between the two shapes is intact and only row 2's
"after" is wrong.

## Why this is worth a doc rather than a shrug

The failure mode is a **published ABI contract that does not describe the
emitted code**, and the two consumers of that contract are in other trees:
`formal/imports.py`'s importer side reads `frame_params` to size the block it
reserves before a cross-module call, and the dylib gate
(`formal/build.py::no_public_api_reason`) is what is supposed to stop a symbol
crossing the boundary in the first place. A wrong `frame_params` is worse than
a refusal in this backend's own terms — the same "wrong answer instead of a
refusal" shape `doc/ABI.md` exists to prevent, and the same one
`FORMAL_generic_monomorph_scope.md` records for a mangled name.

## The exact next step

1. **Decide which of the two is the fact**, by reading the current
   `_writeback_rebound_receivers` / `_frame_return_status` pair against
   `bugs/FORMAL_one_word_ctor_of_a_nested_frame_is_unexportable.md`'s §0:
   either the rule still says "a write-back whose receiver was REBOUND is a
   frame return" and something stopped consulting it, or the rule moved and the
   doc's table (and `test_formal_dylib.py`'s expectation with it) is what should
   change. **The measurement that decides it is one line**: does
   `_frame_return_status` still see `_receiver_writeback` on the `return self`
   that `build.py::_return_the_receiver` appends for THIS body? Print the tag
   rather than infer it from the verdict.
2. **If the refusal is still the intended answer**, the fix is to make
   `_check_frame_escapes`/`_frame_return_status` fire again for the assigning
   shape, and the test needs no change — it is already right and is currently
   red.
3. **If the refusal is NOT the intended answer**, then the published
   `frame_params` must stop claiming a callee-built block is the caller's: an
   exported constructor whose `self` is a frame the CALLEE builds cannot have a
   `frame_params` entry at all, because the block does not exist when the
   importer reserves it. That is a change to what the manifest may SAY, which is
   an ABI question and not a local one — so it wants `doc/ABI.md` next to it.
4. **Test either way:** `test_formal_dylib.py`'s existing case is the right
   home and it is already written; what is missing on this tree is any assertion
   about the MANIFEST for this shape. Whichever way step 1 goes, add the
   `frame_params` of the assigning constructor to the case, because that is the
   half that is wrong today and a `returncode` check alone would pass on a
   library that publishes a contract it does not honour.

## Not measured here

* **x86-64.** `dylib --formal` is arm64-only — `fire.py` refuses
  `dylib --formal --backend=x86_64` with "x86_64 has no per-export contract, so
  there is nothing --formal could prove". So this is an arm64 export-set
  question and there is no x86-64 counterpart to check.
* **Whether an importer actually mis-sizes a block today.** The manifest says
  the wrong thing; whether anything reads it that way on a path that gets this
  far was not established. Step 1 does not depend on the answer, and step 3 is
  the one that does.
* **The cost work this turned up in.** `bugs/PERF_formal_import_asks_are_products_of_the_closure.md`
  is the change this branch carries; it is byte-identical on both architectures
  over a 43-file spread and is not implicated in this failure (the failure is
  identical at `HEAD~2`, before it).