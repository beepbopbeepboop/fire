# TEST_sweep_truth_names_math_which_now_has_a_host_module: a gate test's premise went stale when `formal/hostmods/math.mojo` landed

**Status: OPEN, measured, one line. NOT fixed here because
`test_formal_sweep_truth.py` is the formal sweep's own truth test and
`formal8-12` holds that claim — a fix belongs with whoever owns it, and this
document is the measurement so that they do not have to re-derive it.**
Found 2026-10-02 while running the narrow suites for an unrelated change (the
stack-floor guard, whose doc has since been deleted with its fix); it is **not**
caused by that change and reproduces on the tree as committed.

**It is in the everyday gate**: `tools/suite.py` registers `formal-sweep-truth`
with `deps=['preflight']` and it is in `[check,gate,proofs]`, so every
`make check` is red until it is fixed.

## What I ran

```console
$ python3 -m unittest test_formal_sweep_truth
FAILED (failures=1)
FAIL: test_a_message_naming_a_host_member_is_a_target_fact
AssertionError: '' != 'math'
```

## What I saw

The test asserts that `tools/formal_sweep.py`'s `_system_module_call` rule
answers `math` for the message `"build: math.floor() cannot be lowered: math is
not available here"` against a source that imports `math`. It answers `""`.

**The premise is stale, and the rule is right.** The test's own comment says why
it picked `math`:

> `math` and not `json`: `json` used to be the host module named here, and
> `formal/hostmods/json.mojo` landed in 2026-09-30, so a `json` that is "not
> available here" is no longer a fact about anything. `math` has no Mojo source
> in this tree, so the message this rule reads is still true.

`formal/hostmods/math.mojo` landed on 2026-10-02 (`9c7ec795`, "math: the seven
integer-valued functions, plus the five float constants as bit patterns"), so
`math` is now the same case `json` was — and the rule's *second* arm cannot
answer it either, because that arm requires `mod in HOST_MODULES`, and `math` is
not in it:

```console
$ python3 -c "from formal.imports import HOST_MODULES; print('math' in HOST_MODULES)"
False
$ python3 -c "import tools.formal_sweep as S; print('math' in S.IN_REACH_HOST_MODULES)"
False          # `math` HAS a hostmod, so it is IN REACH
```

`IN_REACH_HOST_MODULES` being False while `formal/hostmods/math.mojo` exists is
the confirmation: a module with a Mojo source is in reach, so the message the
test feeds the rule ("is not available here") is not a fact about anything. The
rule is doing the right thing and the fixture is describing a world that ended.

## The fix, measured

One module name, in the fixture's `SRC` and in the message, chosen from the set
`_declared_host()` still reports unreachable. All four are in `HOST_MODULES`,
imported by the fixture, and the rule answers their name (measured):

```console
$ python3 -c "
import tools.formal_sweep as S
for mod in ('errno','gzip','textwrap','warnings'):
    src = f'import {mod}\nimport math\n\ndef main():\n    pass\n'
    print(mod, repr(S._system_module_call(f'build: {mod}.floor() cannot be lowered: {mod} is not available here', src)))"
errno 'errno'
gzip 'gzip'
textwrap 'textwrap'
warnings 'warnings'
```

`errno` is the one to use: it is in `_declared_host()`'s set (so "no Mojo source
anywhere on this path" is still true of it), it has no `formal/hostmods/` entry,
and it is the shortest. `unicodedata` does NOT work — it is not in
`HOST_MODULES` either, so the structural arm cannot fire for it, which is worth
knowing because "a module nothing declares" is not the same predicate as "a
module this rule can name".

**And the comment above the fixture needs rewriting with it**, because the
sentence "`math` has no Mojo source in this tree, so the message this rule reads
is still true" is the thing that went stale, and a comment that explains a
choice which has been silently invalidated is how the next hostmod makes this
red again without anybody noticing why.

## Why it is not fixed here

`test_formal_sweep_truth.py` is the sweep's own truth test and `formal8-12`
holds the sweep claims (`FORMAL_sweep_memcap_death_is_filed_as_codegen`,
`FORMAL_sweep_sigterm_drains_the_whole_scope`, …). A one-line edit in a file
another worker is plausibly working in is a conflict for a fix that is one
character-class of edit and fully specified above, and the rules for this
session are explicit: do not work on someone else's problem, file it instead.