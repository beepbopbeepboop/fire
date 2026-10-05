# The proof verdict cache cannot see the proof's DIRECTORY, so a run whose `LEAN_PATH` did not resolve is served forever

**Area:** FORMAL (`formal/lean.py::proof_verdict_key` and `_run_lean`). Found
2026-10-04 on `work/formal29-3` while trying to typecheck a generated arm64
proof, and bitten by it twice before I understood it.

## What was run

```python
# .tmp/sc/iter.py — generate the proof, then ask for its verdict
ok, detail, cached, n = L.check_proof_cached(".tmp/scroot/nested_or_proof.lean")
```

with `repo_root='.'` on the FIRST attempt, which makes `proof_census` compute
`lib_dir = "./lib"` and hand that to `_run_lean`, which puts

```
LEAN_PATH = <the proof's own directory> : ./lib
cwd       = <the proof's own directory>
```

`./lib` does not resolve from `.tmp/sc`, so Lean answered

```
error: unknown module prefix 'ProofLib'
No directory 'ProofLib' or file 'ProofLib.olean' in the search path entries:
  /Users/mrs/net/chatgpt/claude/work-437/.tmp/sc
  ./lib
```

and `check_proof_cached` **published that failure to the CAS**. The second
attempt, from `.tmp/scroot` and with the default absolute `repo_root` — where the
same bytes resolve the library perfectly — got `cached=True` and the same
`./lib` error text back, because

```python
def proof_verdict_key(proof_path, lib_dir, lean):
    parts = [_VERDICT_VERSION, lean_version(lean).encode()]
    for stem in LIBRARY_MODULES: ...        # the .olean digests
    with open(proof_path, "rb") as f:
        parts.append(f.read())               # the proof's BYTES
    return "proof/" + cas.hash_parts(*parts)
```

covers the toolchain, the library artifacts and the file's content — **and not
the directory**, while `_run_lean` puts that directory FIRST on the search path.
A proof and a byte-identical copy of it in another directory are therefore two
different propositions to Lean and one key here, and the cached answer to the
first is served for the second.

## Why it matters more than "a corner case"

* **A failure cached from an unresolvable `LEAN_PATH` is permanent for those
  bytes.** Deleting the library, rebuilding it, editing the generator — none of
  it changes the key, so nothing but a hand `rm` of the CAS entry clears it. That
  is the shape `CLAUDE.md`'s `checked_run.py` rule exists to prevent for the
  ordinary result cache ("a cached red that no fix can clear is worse than
  spending the time to find out"), and this is the verdict cache doing it.
* **It is silent about which of the two it was.** `cached=True` with a `detail`
  naming a path the caller never used is the only clue, and the detail is the
  stale one.

## The next step

One line of key material — `os.path.dirname(os.path.abspath(proof_path))`, which
is what `_run_lean` puts on the path — plus a test that two byte-identical proofs
in two directories with a `ProofLib.olean` in neither get two keys, or one that
asserts the key changes when only the directory changes. `_VERDICT_VERSION` goes
up with it, so every entry published under the old key is simply not looked up
again, which is the other half of the fix: **the poisoned entries already in the
machine-wide CAS are unreachable once the key changes, and no sweep is needed.**

**What is NOT claimed:** that this is what any *committed* caller triggers. Every
caller I read passes an absolute `repo_root` (`fire.py build`,
`test_formal_short_circuit_cond.py`'s `repo_root=HERE`, `formal/build.py`), so
the failure needs a relative root — which is what I did by hand. The hole is
still real for the search-path reason, and it is one line, but it is not a red
anyone is currently seeing.