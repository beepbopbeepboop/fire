# TEST_sweep_dyld_probe_asserts_its_precondition_over_exit_too: the `lstrip` normalisation's replacement is red on a bind that is not the fixture's

**Area:** TEST (`test_formal_sweep.py::TestDyldProbe::test_a_bind_name_that_itself_begins_with_an_underscore_resolves`)
· **Status:** OPEN, measured 2026-10-04 on `master` at `3c3516db`

Found while running the 57 formal test files that
`bugs/FORMAL_sweep20_std_collections_2.md` §5.4 ran for its import-resolution
fix; that doc is deleted with its fix and the provenance is the symptom, not the
doc. **Not** caused by that branch's change: the same failure appears with
`master`'s `formal/imports.py` restored.

## 1. What is red

```
$ python3 tools/memslot.py --gb 8 --label tfs -- python3 test_formal_sweep.py
FAIL: test_a_bind_name_that_itself_begins_with_an_underscore_resolves
AssertionError: False is not true : [x86_64] precondition: the bind 'exit' does
not begin with an underscore, so lstrip('_') cannot change it and this fixture
tests nothing (the shape to reach for is a relative import from a module whose
own NAME begins with an underscore)

Ran 124 tests — FAILED (failures=1)
```

**The fixture is fine.** Its own message says so, and the assertion it fails is
the fixture's PRECONDITION, not its subject.

## 2. The cause, measured

The fixture is two files in a directory — `_helper.mojo` and `__pkg.mojo`, the
latter writing `from ._helper import twice` — built for both architectures.
`.tmp/lu/` (scratch) is exactly that, built here:

```
$ python3 fire.py build --formal --no-prove --backend=arm64  -o .tmp/lu/a.out .tmp/lu/__pkg.mojo
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/lu/x.out .tmp/lu/__pkg.mojo
$ python3 -c "…; import tools.formal_sweep as S; …"

.tmp/lu/a.out binds: ['__pkg__helper_twice_9f63a2']                 dylibs: [libSystem.B.dylib, __pkg__helper…arm64.dylib]
.tmp/lu/x.out binds: ['__pkg__helper_twice_9f63a2', 'exit']         dylibs: [libSystem.B.dylib, __pkg__helper…x86_64.dylib]
```

Both images bind the fixture's `__pkg__helper_twice_…`, which is exactly the
shape the test wants: a leading underscore that `lstrip("_")` would destroy.
Both run (arm64 exits 42).

**The x86-64 image additionally binds `exit`,** and the test loops over *every*
bind the image records:

```python
for name in names:
    self.assertTrue(name.startswith("_"), f"[{arch}] precondition: …")
```

so on x86-64 it reaches `exit`, which the x86-64 **entry stub calls itself**,
and a libSystem name can never begin with an underscore. The arm64 half passes
because the arm64 stub does not make that call. **The failure is the loop's
scope, not the fixture**: the precondition is about the bind the FIXTURE
creates, and it is being asked of a bind the fixture does not create.

## 3. Why it matters more than a red test

This case exists to pin `formal/macho_linker._macho_symbol`, the function that
**replaced** a `lstrip("_")` normalisation on the bind name — the defect the
deleted `FORMAL_relative_submodule_abi_prefix_off_by_one.md` recorded, and the
reason `tools/formal_sweep.py:2425` still names the bug rather than the doc.
Its own docstring calls the anti-tautology check load-bearing — *"the lstrip
normalisation is expected to be wrong … if the two agree, the fixture has
stopped reproducing the defect it exists for"* — and it is the only place
`_macho_symbol` is exercised, because the x86-64 arm is the one that goes
through the export trie on an arm64 host. So the guard that is supposed to
catch a regression is currently unable to reach its subject, and it reports that
as a failure about the fixture.

## 4. The exact next step

Scope the precondition to the bind the fixture creates rather than to every bind
on the link line. The structural way to say which one that is, without naming
`exit`: **a bind the imported library provides is the fixture's, and a bind only
libSystem provides is the stub's** — so select the names whose mangled spelling
appears in `foreign`'s export trie (`FB.macho_dylib_exports(foreign)`, already
read in this test) and require the precondition of those. A bind no library on
the link line provides is neither, and is a different test's subject.

Then re-run and confirm the arm64 and x86-64 halves both reach the two
assertions that matter: `assertIn(S._macho_symbol(name), exports)` and
`assertNotIn(S._macho_symbol(name.lstrip("_")), exports)`.

## 5. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label tfs -- python3 test_formal_sweep.py

# the fixture, outside the test
mkdir -p .tmp/lu
printf 'fn twice(a: Int) -> Int:\n    return a + a\n' > .tmp/lu/_helper.mojo
printf 'from ._helper import twice\n\nfn main() -> Int:\n    var x: Int = twice(21)\n    return x\n' > .tmp/lu/__pkg.mojo
for a in arm64 x86_64; do
  python3 tools/memslot.py --gb 8 --label lu-$a -- python3 fire.py build --formal \
    --no-prove --backend=$a -o .tmp/lu/$a.out .tmp/lu/__pkg.mojo
done
python3 - <<'PY'
import os, sys
sys.path.insert(0, os.getcwd()); sys.path.insert(0, "tools")
import tools.formal_sweep as S
for a in ("arm64", "x86_64"):
    img = open(f".tmp/lu/{a}.out", "rb").read()
    print(a, [n for _o, n in S._binds(img)])
PY

sed -n '573,582p' test_formal_sweep.py   # the loop
```
