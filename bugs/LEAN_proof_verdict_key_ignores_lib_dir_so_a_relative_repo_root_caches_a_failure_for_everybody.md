# LEAN_proof_verdict_key_ignores_lib_dir_so_a_relative_repo_root_caches_a_failure_for_everybody: one careless `repo_root` poisons the CAS for every other caller

**Area:** `formal/lean.py` (the proof-verdict cache). **Status: OPEN, measured,
and the failure mode is the one this project treats as its worst — a WRONG
verdict served from the cache, silently, to a caller that did nothing wrong.**
Found 2026-10-03 on `work/formal16-8` while trying to Lean-check one generated
proof, and it had already cost this machine **44** cached verdicts.

## The two facts

**1. `_run_lean` takes `lib_dir` as given and puts it in `LEAN_PATH` with the
proof's own directory as the working directory** (`formal/lean.py:1756-1760`):

```python
env["LEAN_PATH"] = os.pathsep.join(
    (os.path.dirname(os.path.abspath(proof_path)), lib_dir))
result = run_lean(lean, [os.path.basename(proof_path)], env=env,
                  ..., cwd=os.path.dirname(os.path.abspath(proof_path)))
```

and `proof_census` builds `lib_dir` as `os.path.join(repo_root, "lib")`
(`:1421`) from `repo_root or _default_root()`. `_default_root()` is absolute
(`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`), so the default
is safe. **A caller that passes a RELATIVE `repo_root` gets a relative `lib_dir`,
and since `cwd` is the proof's directory, `./lib` resolves against THAT** — so
every such check fails with

```
p.lean:1:0: error: unknown module prefix 'ProofLib'
No directory 'ProofLib' or file 'ProofLib.olean' in the search path entries:
/…/.tmp/<somebody-elses-tmpdir>      ./lib
```

whatever the real state of `lib/`.

**2. `proof_verdict_key` does not include `lib_dir`** (`:1375-1388`). It hashes
the Lean version, each library module's `.olean` digest, and the proof's bytes.
Both callers — the broken one and every correct one — read the SAME `.olean`
files and pass proofs with the same bytes, so they compute the SAME key. The
failure is published (`_publish_verdict` has no "was this a launcher failure?"
guard) and every later caller with those proof bytes reads it.

## What it cost, measured

```
$ python3 -c "… check_proof_cached('.tmp/bnot/a/t_proof.lean', repo_root='.')"
p.lean:1:0: error: unknown module prefix 'ProofLib'      # stored: ok=False

$ python3 -c "… check_proof_cached('<same bytes>', repo_root=os.path.abspath('.'))"
p.lean:1:0: error: unknown module prefix 'ProofLib'
No directory 'ProofLib' … /Users/…/work-334/.tmp/bnot/a    ./lib
                                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                          a directory that no longer exists
```

The second call is the shape of the failure: it never ran Lean (0.6 s for a file
whose uncached check is 9.5 s), and its message names a path from the FIRST
caller's temporary directory. `check_proof_cached`'s contract says a cached
verdict is a pure function of the proof's bytes and the toolchain — which is
true, and is the defect: the bytes and the toolchain did not change, but the
ANSWER did, because a third input was left out of the key.

Repair on this machine was mechanical and lossy (it invalidates good verdicts):

```sh
python3 - <<'PY'
import glob, os
for p in glob.glob(os.path.expanduser("~/.gmojo/cas/proof/*.leanverdict")):
    b = open(p, 'rb').read()
    if b.startswith(b"fail") and b"unknown module prefix" in b:
        os.remove(p)
PY
# → removed 44 poisoned verdict entries
```

**44 is the number that says this is not one careless call.** Every one of this
tree's own test files passes an absolute `repo_root` (`repo_root=HERE`), so
whichever calls produced them were ad-hoc — an interactive `python3 -c`, a
REPL, an agent — and an interactive REPL is exactly where `repo_root='.'` looks
like the right thing to type.

## The exact next step

Five changes, in order, and the first is the one that stops the bleeding. Steps
1–3 were the original three; **4 and 5 are the two the duplicate this document
replaced added**, and they are not the same fix — see the note under the list.

1. **`_run_lean` should not accept a relative `lib_dir`** — `os.path.abspath`
   it where `LEAN_PATH` is built, the way `library_census` already does
   (`:1108`, whose comment says "LEAN_PATH is resolved … and that is not
   tidiness"). One line, and it makes the launcher correct for every caller
   instead of correct for callers that pass an absolute path.
2. **`proof_verdict_key` should hash `os.path.abspath(lib_dir)`**, so two callers
   that resolved the library differently cannot share a key. Cheap, and it makes
   the cache's stated contract true.
3. **A launcher failure should not be published as a verdict.** The module
   already has the distinction — `Census.exceeded` / `detail` and the comment at
   `:1494` say "a bound is a function of the MACHINE … so caching it turns one
   slow afternoon into a permanent red that no re-run can clear" — and an
   unreadable search path is the same class of thing: a fact about this machine
   at this moment, not a function of the proof's bytes. Publishing it is what
   turned a one-line mistake into a permanent red.
4. **The key must also cover the PROOF'S OWN DIRECTORY**, not only the library
   directory. `_run_lean` puts the proof's directory FIRST on `LEAN_PATH` and
   runs with `cwd` there, so a proof and a byte-identical copy of it in another
   directory are **two different propositions to Lean** — the first is what
   `ProofLib` resolves against, and the second may resolve a different
   `ProofLib`, or none. So the key material is
   `os.path.dirname(os.path.abspath(proof_path))` **as well as** (2). This is the
   half (2) alone does not close, and it is the half that survives step 1: with
   `lib_dir` absolutised, a relative `repo_root` no longer breaks the search
   path, but a proof moved to a directory holding a different library of the same
   name still shares a key with the original.
5. **Bump `_VERDICT_VERSION` with the key change.** It is the other half of the
   fix and it is free: every entry published under the old key is simply not
   looked up again, so **the poisoned entries already in the machine-wide CAS
   become unreachable and no sweep of `~/.gmojo/cas/proof/` is needed.** Do it
   in the same commit as (2)/(4), not later — a key change without the bump
   leaves the 44 (and whatever accumulated since) exactly as permanent as they
   were, which is the property this document is about.

(1) alone fixes the next caller; (2), (4) and (5) are what stop the class from
existing. All of them are small and none of them changes a verdict that is
currently correct.

**The test that goes with (2)/(4)**: two byte-identical proofs in two directories,
with a `ProofLib.olean` in neither, must get two keys — or, more directly, one
assertion that the key changes when only the directory changes. Asserting the key
is stable across everything else matters as much, because a cache key that
changes on every call is a cache that never hits and looks like a fix.

## What is NOT the cause

* **Not the library build.** `ensure_library` was current and correct throughout
  (`lib/ProofLib.olean` present, its `.srcsha256` stamp written, the build's own
  exit 0); the failure is that the elaborator could not FIND it.
* **Not `LEAN_PATH`'s order.** The proof's own directory is first and
  `./lib` is second, which is right; the second entry is what is wrong.
* **Not a stale `.olean`.** The same file typechecked uncached, immediately
  afterwards, with an absolute `repo_root`.

## What is NOT currently observed

**No committed caller passes a relative `repo_root`.** Every caller read here —
`fire.py build`, `test_formal_short_circuit_cond.py` (`repo_root=HERE`),
`formal/build.py` — passes an absolute one, and `_default_root()` is absolute
too. So the failure needs a hand-written `repo_root='.'`, which in practice
means an interactive `python3 -c`, a REPL, or an agent — the 44 poisoned entries
are evidence that it happens, and not evidence that a gate is red.

That is a statement about how the hole is reached, not about whether it is real,
and it is the reason this document is filed rather than fixed: the next step is
five small edits to `formal/lean.py` and a test, and no red to aim at.

## The duplicate this replaced

`FORMAL_the_proof_verdict_cache_key_cannot_see_the_proof_directory.md` —
deleted 2026-10-05 — was filed on 2026-10-04 for the same root cause, found the same way (`repo_root='.'` by
hand, `cached=True` with a `detail` naming a path the caller never used) and
reached the same conclusion about the cause. It was **deleted and folded in here
on 2026-10-05**; what it added is steps 4 and 5 above — the proof's own
directory is a second missing key input beside `lib_dir`, and the version bump
is what makes the poisoned entries unreachable without a sweep. Its one further
observation is kept here as the "what is NOT currently observed" section above.