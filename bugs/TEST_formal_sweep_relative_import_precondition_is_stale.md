# `test_formal_sweep.py`'s relative-import precondition asserts a module spelling that stopped existing

**Area:** FORMAL / TEST. Found 2026-10-02 on `work/formal5-mlir-constructs`
while working the sweep5 `comptime does not fold to a constant` row, by
running `formal-sweep` as a regression check. **NOT FIXED — not this branch's
change** (the branch's subject is the comptime folders in
`mojo/middle/comptime.py` and `formal/model.py`, and this is a stale assertion
in a suite neither of them is read by).

## What was run

    $ python3 test_formal_sweep.py TestDyldProbe.test_a_relative_imports_underscored_symbol_resolves_and_the_image_runs
    FAIL: test_a_relative_imports_underscored_symbol_resolves_and_the_image_runs
    ...
    AssertionError: False is not true : precondition: every bind name is
    underscore-prefixed, got ['relpkg__helper_twice_9f63a2']
    Ran 1 test in 0.433s
    FAILED (failures=1)

The whole file: `Ran 76 tests in 22.0s / FAILED (failures=1)` — this is the
only failure in it. Confirmed **pre-existing**: measured with this branch's diff
reverse-applied (`git apply -R`), so the failure is not a consequence of the
comptime-folding change that was in the tree at the time.

## The defect, which is in the ASSERTION and not in the thing it asserts

`test_formal_sweep.py:439-451`:

    names = [name for _ordinal, name in S._binds(self.relative_img)]
    self.assertTrue(names, "precondition: the image binds something")
    self.assertTrue(all(n.startswith("_") for n in names),
                    f"precondition: every bind name is underscore-prefixed, "
                    f"got {names}")

The comment above it states the reason the assertion exists, and the reason is
still sound:

> A relative import's ABI prefix begins with an underscore, so this image's bind
> names do too — that is the precondition, asserted rather than assumed,
> because if it stops holding the test would pass for the wrong reason and stop
> covering anything.

That sentence is now FALSE, and it became false legitimately rather than by
regression. `formal/imports.py:_module_identity` qualifies a relative import
against the module that spelled it, so `from ._helper import twice` inside
`relpkg/__init__.mojo` has module identity `relpkg._helper`, not `._helper`:

    $ python3 -c 'import formal.model as M; print(M.abi_module_name("._helper"),
                                                 M.abi_module_name("relpkg._helper"))'
    __helper
    relpkg__helper

`_module_identity`'s own docstring is explicit that this is the intended
behaviour and not a side effect: "which is what makes two different
`a/sub.mojo` and `b/sub.mojo` two different libraries instead of one name
written twice." So the export is `relpkg__helper_twice_9f63a2` and the
assertion that it starts with `_` can no longer hold.

## What is NOT wrong — measured, because this is what the test is for

The three assertions that carry the test's weight all still pass. Driven
through the class's own fixtures (`.tmp` scratch, the image built exactly as
`setUpClass` builds it):

    binds:       [(2, 'relpkg__helper_twice_9f63a2')]
    unresolved:  []
    rc:          42
    stderr:      ''

so the relative import's symbol still resolves, nothing is reported missing, and
the image loads and runs `main()` returning `twice(21)` as the test expects.
The `lstrip("_")` bug the comment above the precondition cites — the probe
stripping leading underscores off a name before handing it to `dlsym`, which
reported a load failure for an image that loads — is still closed: that is what
`_unresolved_imports` returning `[]` and dyld's silence are. Its doc is gone
because the fix landed, which is the rule in `CLAUDE.md`'s "Bug docs"; only the
three assertions that carry the test's weight had a spelling to move, and two of
them are name-independent.

## The next step

One edit, in `test_formal_sweep.py:449-451` — assert the property that is still
true instead of the spelling that stopped being produced. The property is that
the bind name is the imported module's ABI prefix, the function's name, and the
source digest, joined by `_`: `relpkg__helper`, `twice`, `9f63a2`. Something
like

    head, _, tail = names[0].rpartition("_")
    self.assertTrue(head.endswith("_helper"),
                    f"precondition: the bind name carries the imported "
                    f"module's ABI prefix, got {names}")

with the comment rewritten to say WHY the prefix is `relpkg__helper` and not
`__helper` (a relative import is qualified by its package, `formal/imports.py`'s
`_module_identity`) — otherwise the next reader re-derives `abi_module_name` from
the `.` spelling and gets the same wrong answer this assertion did.

Deleting the precondition is NOT the fix and is the thing to avoid: it is
asserted rather than assumed precisely so that the test cannot pass for the
wrong reason, and dropping it would make the three assertions below it the only
things standing between a mangled-name regression and a green run. The other
option — pinning the old spelling by changing `_module_identity` — would undo
the two-distinct-libraries property that function's docstring says it exists
for, and is the wrong direction.
