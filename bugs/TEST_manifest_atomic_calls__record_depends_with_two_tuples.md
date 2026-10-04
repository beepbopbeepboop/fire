# TEST_manifest_atomic_calls__record_depends_with_two_tuples: three cases in
# `test_formal_manifest_atomic.py` cannot pass, and the failure reads as a bug in
# the manifest writer

**Area:** `test_formal_manifest_atomic.py` · **Status:** OPEN, found 2026-10-04
while working `project18:export-gate` · **Layer:** 1/5 of the formal work

**Pre-existing on `master` (`86d60026`)**, verified by reading both sides out of
that commit rather than by re-running with a reverted tree:

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label t -- python3 test_formal_manifest_atomic.py
```

```
FAIL  no reader sees a half-written manifest      ValueError: not enough values to unpack (expected 3, got 2)
FAIL  every writer goes through the atomic path   ValueError: not enough values to unpack (expected 3, got 2)
FAIL  the round trip still reads                  ValueError: not enough values to unpack (expected 3, got 2)
1/4 groups passed
```

## 1. The cause, in two lines of each file

`formal/imports.py::_record_depends` takes `(module, source, instantiations)`
triples — the third element is `demands_key`'s digest for the DEPENDENCY, added
by `c9d7685e` ("Stage 5 for the dylib path") so `dylib_chain` can look a
dependency up in `_BUILT` by `(arch, path, digest)`:

```python
payload["depends_on"] = [
    {"module": m, "source": p, "instantiations": k}
    for m, p, k in depends]                      # formal/imports.py:3382
```

and `test_formal_manifest_atomic.py` still passes pairs, at four call sites
(lines 133, 174, 192, 225):

```python
I._record_depends(manifest, [("std.collections", "/src/c.mojo")])
```

So the three failing cases die in the test's own setup, before the atomicity
assertion they exist to make.

## 2. Why it is worth a doc rather than a shrug

**The failure mode it hides is the one this suite exists to catch.**
`_record_depends` is one of the four manifest writers that
`formal/build.py::update_dylib_manifest` makes atomic, and the suite's subject
is that a concurrent READER never sees a truncated manifest — 40 % of concurrent
reads landed in the truncation window when the writers wrote in place, measured.
Three of its four groups cannot run, so the suite currently reports "1/4 groups
passed" and the gate sees a suite that fails, not a suite that is three-quarters
unverified.

**And `manifest["instantiations"]` is written by a different clause of the same
`_record`**, so the digest that `dylib_chain` looks a dependency up by is
recorded by the code path whose test cannot start:

```python
def _record(payload):
    payload["depends_on"] = [...]
    payload["instantiations"] = instantiations
```

## 3. The exact next step

Pass the third element at the four call sites: `""` for the empty demand set,
which is `demands_key`'s own answer for "no instantiations" and is what
`build_module_dylib` records for a module nobody asks anything of. Better than
`""` at the two sites that have a dependency in hand (`test_formal_monomorph.py`
already computes real digests): read it back with
`formal/imports.py::_manifest_instantiations` and assert on it, which is the
round trip the third failing case is named for and is currently not testing.

## 4. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label t -- python3 test_formal_manifest_atomic.py
sed -n '3378,3384p' formal/imports.py
grep -n '_record_depends(manifest' test_formal_manifest_atomic.py
```