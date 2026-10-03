# A relative import's dylib export is not underscore-prefixed, and the dyld probe's own precondition fails

**Status: OPEN. Pre-existing on `24068a01` — the commit this branch started at —
and NOT caused by the admitted-contract work.**

## What I ran

    git archive 24068a01 | tar -x -C .tmp/opencode/base
    cd .tmp/opencode/base && python3 test_formal_sweep.py TestDyldProbe

**`24068a01` and not `HEAD`, and the difference is worth recording**: my first
attempt used `git archive HEAD`, which archived *my own branch* — HEAD is this
branch's tip, so the "pristine" tree contained the admitted-contract work and the
comparison proved nothing. `master` is no use either: it moved from `24068a01` to
`7f76a844` while this branch was being written, and `origin/master` is `0b6394ab`,
a state with no `formal/` directory at all. The commit the worktree was checked
out at is the only honest baseline, and pinning it by SHA is what makes the claim
checkable later.

## What I saw

    AssertionError: False is not true : precondition: every bind name is
    underscore-prefixed, got ['relpkg__helper_twice_9f63a2']

## What I expected

The test's own name says what it is about — "a relative import's underscored
symbol resolves and the image runs" — and its first assertion is that every
symbol the image BINDS is `_`-prefixed, because `doc/ABI.md`'s export rule
excludes a leading `_` and an image must not bind a name the library does not
export. A module `relpkg/helper.mojo` calling its own private `__twice` is
exported as `relpkg__helper_twice_9f63a2`: the private name has been MANGLED into
the export table with its underscores intact, so the image binds a symbol that is
in the library's export trie.

That is the interesting half of the finding and the test does not reach it: the
precondition is asserted and then the run is never attempted.

## Why it matters, and it is not cosmetic

An underscored name reaching the export table means `doc/ABI.md`'s privacy rule
is not being enforced at one boundary — the relative one. `formal/imports.py`'s
`_module_identity` is what qualifies a relative spelling (`from . import helper`
becomes `relpkg.helper`), and the mangling that produced
`relpkg__helper_twice_9f63a2` is in the export-naming path for that case. If the
rule does not hold here it does not hold for every relative import in the tree,
and the observable consequence is that a private function of one module is
callable from another — the same class of leak as
`bugs/FORMAL_relative_import_at_the_root_has_no_qualified_identity.md`, which is
the ROOT spelling of this and may already own half of it.

## The exact next step

    grep -n "9f63a2\|def export_symbol\|_module_identity" formal/imports.py
    grep -rn "export_exclusions" reflect.py formal/model.py

and read the mangling that turns `__twice` into `__twice_9f63a2`. The hash suffix
looks like a disambiguator for two same-named exports in one library, and it is
being applied to a name that should have been EXCLUDED first. The fix is an
ordering question — filter by the privacy rule, then disambiguate — and not a
change to either rule.

Then the test's own assertion becomes reachable and the run it describes can be
attempted; if the image does not load, that is the next finding in the same file.

## Why it is filed and not fixed here

It is in `formal/imports.py`'s export-naming path and `reflect.py`'s export rule,
which is shared with every dylib in the tree, and it is unrelated to the admitted
contract work that found it: that work's own regression run is
`test_formal_sweep_truth` (33 tests, OK), `test_formal_call_proof_gen` (18, OK)
and `test_formal_link_accounting` (193 checks, 0 failed), all green. Changing the
export rule from a light worker, with the integrator's gate as the only broad
check, is the wrong trade for a finding that needs a reading of two files first.
