# FORMAL_sweep_dyld_probe_underscore_fixture_reports_its_own_precondition_as_a_failure

**Area:** the sweep suite (`test_formal_sweep.py::TestDyldProbe`). Found
2026-10-04 on `work/formal21-6`, while verifying a change to
`tools/formal_sweep.py`. **Measured pre-existing, not a regression** — see
"What I ran".

## What I ran

```console
$ python3 test_formal_sweep.py TestDyldProbe
FAIL: test_a_bind_name_that_itself_begins_with_an_underscore_resolves
AssertionError: False is not true : [x86_64] precondition: the bind 'exit'
does not begin with an underscore, so lstrip('_') cannot change it and this
fixture tests nothing (the shape to reach for is a relative import from a
module whose own NAME begins with an underscore)
...
FAILED (failures=1)
```

**And it is not caused by the branch's change to `tools/formal_sweep.py`.**
That change is purely additive (one regex and one function,
`refusing_module`), and the row fails identically with the pre-change file
restored in place:

```console
$ git show <parent>:tools/formal_sweep.py > tools/formal_sweep.py
$ python3 test_formal_sweep.py TestDyldProbe      # same single failure
```

`test_formal_sweep_truth.py` (101 tests) and the other 123 rows of
`test_formal_sweep.py` pass.

## What is wrong

**A fixture that cannot reach the shape it is for reports it as a FAILURE
where this repository's convention is a SKIP with the reason.** The row is
about `lstrip('_')` being wrong for a bind name that itself begins with an
underscore — a Mach-O symbol and a C identifier differ by exactly that
underscore, which is what `formal/macho.py::_macho_symbol` exists to undo. On
this machine the x86-64 image's binds are ordinary C names (`exit` and
friends), so the loop has nothing that begins with `_` and the precondition
assertion fires.

Three things make the row's own message the right one to read and the wrong
thing to *do*:

* it says the fixture "tests nothing", which is true, and
* it cannot tell whether that is because the SHAPE no longer occurs (a finding:
  the underscore bug the row guards has been fixed at the source, so nothing
  binds a leading-underscore name any more) or because the FIXTURE does not
  produce the shape on this host (a defect in the fixture). Those are opposite
  findings and the row collapses them into one red.

**So the row is currently uninformative in both directions:** on a host where
the shape occurs it is a real regression net, and on one where it does not, it
is a red that says only "this machine has nothing for me to check".

## The next step

Turn the precondition into what the repository already does elsewhere for the
same situation — `test_formal_mlir_precedence.py`'s census returns SKIPPED
rather than PASS when there is no corpus to measure, and
`bugs/CODEGEN_a_callee_this_function_binds_is_a_value.md` §5.1's samples are cut
from the generator rather than from a log. Concretely:

1. **build the fixture rather than hoping for one.** The row wants "a relative
   import from a module whose own NAME begins with an underscore"
   (`from ._utils import _select_register_value` is the measured shape, from
   `std/builtin/simd_length.mojo`). Write that module and that import into a
   temp tree, build it for both architectures, and read ITS binds — then the row
   tests `lstrip('_')` on every host instead of only on hosts that happen to
   have the shape;
2. **until then, `self.skipTest(...)` on the precondition**, carrying the same
   sentence, so a host without the shape reports SKIPPED and a host where the
   shape DISAPPEARS — which is the finding worth having — is still visible as a
   skip that names it.

Nothing here is in `bugs/` yet for the underlying normalisation: `git log -S`
on `_macho_symbol` is the first command to run under (1), because a fixture
that has to manufacture the shape usually means the shape no longer occurs.
