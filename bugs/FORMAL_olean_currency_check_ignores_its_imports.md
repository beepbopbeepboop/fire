# FORMAL_olean_currency_check_ignores_its_imports: editing `lib/X86.lean` left `lib/work.olean` in place, and every later `lean` run recompiled the stale import inside the checker

**Area:** shared infrastructure, `formal/lean.py`. Found 2026-10-02 while
landing the `cqo` half of `FORMAL_default_int_type_typed_flag_collapse.md`,
which is what a stale `work.olean` made invisible. **Fixed in the same commit
as that fix** (`_effective_digest`); this document is the record of the defect
and of why it was silent, and it is kept because the class is wider than the
one instance.

---

## What it was

`ensure_library` decides whether a `.olean` is current by comparing a stamp
against a digest of that module's OWN source:

```python
digest = _sha256_file(source)
if _library_is_current(source, olean, stamp, digest):
    continue
```

and `_write_stamp` recorded that same own-bytes digest. **A Lean `.olean`
embeds its imports' definitions**, and the library modules import each other:

```
lib/ProofLib.lean   import Lean
lib/X86.lean        import ProofLib
lib/work.lean       import ProofLib, X86
lib/Refine.lean     import ProofLib
lib/Contracts.lean  import ProofLib, Refine
```

So editing `lib/X86.lean` changes what `work.olean`, `Refine.olean` and
`Contracts.olean` MEAN while leaving all three of their own sources
byte-identical. None of them was rebuilt.

## What it cost, measured

```
$ python3 tools/memslot.py --gb 8 --label fb -- python3 test_formal.py
memcap: BREACH  8.0 GB > 8.0 GB ceiling (100%), 37 procs -- killing fb
```

The same command on the same tree with a fresh (consistent) library:

```
Results for arm64 formal proofs: PASS=41 KNOWN-GAP=4 FAIL=0
memcap: done, peak 1.2 GB across up to 31 procs (ceiling 8.0 GB)
```

and at `--gb 32`:

```
memcap: BREACH  32.0 GB > 32.0 GB ceiling (100%), 37 procs -- killing fb
```

**Nothing anywhere reported an error.** Every individual file was fine; the
artifact the checker read was simply not the artifact its source now
describes. Lean's answer to a stale import is to recompile it, in-process, in
every one of the 37 concurrent typecheckers — which is where 32 GB went, and
why `-j 1` then ran the whole suite in 3.3 GB and reported the right verdict.

The CAS key had the same hole (`_olean_key` hashed the module's own bytes and
the toolchain, nothing else), which is worse: a hit would have served the stale
`work.olean` to every machine that shares the store, so the divergence would
have become permanent rather than local.

## The fix

`_effective_digest(stem, lib_dir)` hashes a module's own bytes **and**, for
every `LIBRARY_MODULES` name its `import` lines name, that module's effective
digest — transitively, cycle-safe, one read per module per run. The stamp, the
currency check and the CAS key all take it, and the key's version tag goes to
`lean-olean-v2` so a pre-fix entry cannot be served under a post-fix key.

The import list is read from each source rather than hard-coded, because the
import graph is the thing that has to stay right and a table beside it is a
second copy of it to forget.

Verified: after the change, one `ensure_library` pass rebuilt exactly the three
modules that import `X86` (`work`, `Refine`, `Contracts`) and left
`ProofLib.olean` — which imports nothing from the set — untouched, at 1.4 GB
peak; `python3 test_formal.py -j 1` then reports `PASS=41 KNOWN-GAP=4 FAIL=0` at
3.3 GB.

## What is deliberately NOT here

* **Not a dependency graph for the VERDICT cache.** `check_proof_cached`'s key
  already folds in "every `.olean` reachable through `LEAN_PATH`, by content"
  (`formal/lean.py`'s own docstring says so), so it never had this hole — the
  fix above only had to reach the `.olean` key and the census key, which is
  what `_olean_key` is for.
* **Not a `mtime` fallback.** A module's imports can change without its own
  bytes changing *and* with its own bytes changing at all — this is exactly
  why the check is content-based, and the effective digest keeps it that way.
