# FORMAL: a module dylib is unsigned at its shared CAS path for the whole of `codesign`, so a concurrent build makes every running image fail to load

**Area:** FORMAL — `formal/imports.py::build_module_dylib` / `_dylib_lock` and
`formal/build.py::compile_formal_dylib` / `_ad_hoc_sign`. The shared CAS
directory `~/.gmojo/cas/formal-imports/<arch>/` is written by every worktree on
the machine.
**Status: OPEN, reproduced deterministically (2026-10-02) on `work/formal8-1`,
NOT fixed here** — it is not one of that lane's claims and the fix is a decision
about a shared artifact's identity, not a patch.

Found by accident while re-running the case
`bugs/FORMAL_a_calcsize_image_hangs_once_in_several.md` is about, which is why
this document names it: the symptom is in the same neighbourhood (a formal image
that builds and then cannot run) and neither document's symptom was a hang.

## What I saw, once, in the wild

`calcsize("<IIQQQQQQ")` — one of the corpus formats — built and then:

```
dyld[2165]: Library not loaded: /Users/mrs/.gmojo/cas/formal-imports/arm64/struct.6cd3c815d2e8.arm64.dylib
  Referenced from: <…> .tmp/w/cs3.bin
  Reason: tried: '…/struct.6cd3c815d2e8.arm64.dylib' (missing code signature in …)
memcap: done, … child exit -6
```

Three runs later the same program answers `56` on both, which is CPython's. What
identified the window:

```
$ ls -la ~/.gmojo/cas/formal-imports/arm64/struct.6cd3c815d2e8.arm64.dylib
-rwxr-xr-x  1 mrs  staff  67680 Oct  2 23:54 …/struct.6cd3c815d2e8.arm64.dylib
$ python3 -c "import json;print(json.load(open(…+'.manifest.json'))['source'])"
/Users/mrs/net/chatgpt/claude/work-264/formal/hostmods/struct.mojo
```

Another worktree's build had republished that exact path seconds before the run,
and the manifest it left behind names **its** source file.

## Why it happens

`formal/build.py::compile_formal_dylib` ends with:

```python
with open(output, "wb") as f:
    f.write(binary)
os.chmod(output, 0o755)
_ad_hoc_sign(output)                       # `codesign -s -`, a SEPARATE process
manifest_path = write_dylib_manifest(output, install_name, [], source=source, …)
```

and `_ad_hoc_sign` is `subprocess.run(["codesign", "-s", "-", path])`. So between
the `write` and the end of that subprocess, **the path holds a complete but
UNSIGNED Mach-O**, and `codesign` then rewrites the same file in place to append
`LC_CODE_SIGNATURE`. The two versions are very different sizes, which is the
window's width:

| | bytes |
|---|---|
| as written by the linker | 49 304 |
| after `codesign -s -` | 67 680 |

`build_module_dylib` holds an exclusive `flock` on a side file for the whole
build, and that is the right mechanism for **writers** — `_dylib_lock`'s own
docstring says the library itself cannot be the lock because
`compile_formal_dylib` "truncates and rewrites the `.dylib`". But the path is
also a **shared, long-lived artifact that already-linked images load at RUN
time**, and a reader takes no lock at all. `os.replace`-style atomicity cannot
help here either, because the comment at the output name explains why a staging
path was rejected: *a dylib's install name is derived from its output path and
is baked into the load command of everything that links it*, so a file built as
`…/staging/foo.dylib` and moved afterwards no longer matches the path its
dependents were told to load.

The source digest in the name does not close it either, and this is the part
worth being precise about: two builds of the same source take the same path and
their FINAL bytes agree, which is why `cas.publish`'s docstring's "a racing
identical write is harmless" is true — of the final state. The intermediate state
is a different file, and it is the one a running image can catch.

## The reproduction, with nothing shared touched

Both artifacts were captured by wrapping `formal.build._ad_hoc_sign`, and the
dylib was built into a directory of its own (`build_module_dylib`'s `out_dir` is
a parameter) so the shared CAS was never written:

```console
$ python3 .tmp/w/spy2.py          # builds the dylib into .tmp/w/mydylibs/, captures
                                  # the pre-sign bytes, links cs6.bin against it
$ .tmp/w/cs6.bin                  # signed bytes at the load path
56
$ cp presign_struct.6cd3c815d2e8.arm64.dylib .tmp/w/mydylibs/struct.6cd3c815d2e8.arm64.dylib
$ .tmp/w/cs6.bin                  # the bytes a concurrent build leaves there
dyld[47506]: Library not loaded: …/mydylibs/struct.6cd3c815d2e8.arm64.dylib
  Reason: tried: … (missing code signature in …)
Aborted
exit=134
```

So: **built, correct, and then refused by the loader**, with a message that
names a library and says nothing about a concurrent build. That is the shape of a
thousand "flaky" test reports.

## What it costs, and what it does not explain

* It explains every **"builds, then dyld"** failure of a program that imports a
  module, on a machine with concurrent builds. It does NOT need a compiler bug,
  and it will not reproduce on an idle machine or in a `-j1` run — which is
  exactly why it survives.
* It does **not** explain a TIMEOUT (a hang) or a SIGKILL. Those are different
  signals and this failure is `SIGABRT`/134. So it is a THIRD symptom in
  `bugs/FORMAL_a_calcsize_image_hangs_once_in_several.md`'s neighbourhood, not
  that document's cause, and it is filed separately rather than folded into it.
* The EXECUTABLE has the same unsigned window between its own write and its sign
  (`_ad_hoc_sign(output)` at `formal/build.py:1494`, `:12197`, `:12625`) but
  nothing else ever reads that path, so it costs nothing.

## The next step — measured, because the obvious fix was tried first and does
## not work

`formal/imports.py`'s comment at the output name rejects the staging-path
answer:

> A lock, not a staging path with a rename. Renaming looked like the tidier fix
> and is wrong here: a dylib's install name is derived from its output path, and
> it is baked into the load command of everything that links it, so a file built
> as `.../staging/foo.dylib` and moved afterwards no longer matches the path its
> dependents were told to load.

**Tried, and the comment is right.** Staging beside the target with a marked
name (`out + ".tmp.<pid>"`) and `os.replace`-ing afterwards publishes a valid,
correctly signed dylib — with the WRONG identity:

```
$ otool -l .tmp/w/mydylibs2/struct.6cd3c815d2e8.arm64.dylib | grep -A2 LC_ID_DYLIB
   cmd LC_ID_DYLIB
  cmdsize 72
     name @rpath/struct.6cd3c815d2e8.arm64.dylib.tmp.999
```

because `compile_formal_dylib` computes `install_name = "@rpath/" +
os.path.basename(output)` from the path it was handed. So the fix has to keep the
BASENAME, which is free:

**Stage in a subdirectory.** Same directory tree, same basename, different
directory ⇒ the install name is unchanged and `os.replace` is still atomic
(same filesystem):

```python
# in build_module_dylib, inside the existing lock
stage = os.path.join(os.path.dirname(out), f".staging.{os.getpid()}")
os.makedirs(stage, exist_ok=True)
staged = os.path.join(stage, os.path.basename(out))
try:
    compile_formal_dylib([source_path], output=staged, …)   # writes + signs HERE
    os.replace(staged, out)                                 # bytes appear signed
    os.replace(staged + ".manifest.json", out + ".manifest.json")
finally:
    shutil.rmtree(stage, ignore_errors=True)
```

Verified mechanically on this tree (monkeypatched, nothing written outside
`.tmp/`), and the published artifact is right in every respect that matters:

```
$ otool -l …/mydylibs3/struct.6cd3c815d2e8.arm64.dylib | grep -A2 LC_ID_DYLIB
   cmd LC_ID_DYLIB
  cmdsize 64
     name @rpath/struct.6cd3c815d2e8.arm64.dylib
$ codesign -v …/mydylibs3/struct.6cd3c815d2e8.arm64.dylib && echo SIGNED-OK
SIGNED-OK
$ ls .tmp/w/mydylibs3
struct.6cd3c815d2e8.arm64.dylib  struct.6cd3c815d2e8.arm64.dylib.lock
```

Three things that run had to be got right, and each is a way to get this wrong:

* **The manifest has to move too.** `write_dylib_manifest` keys on the output
  path, so a staged build leaves `…staging.NNN/…manifest.json` behind and the
  final path has NO manifest — the dylib publishes fine and then every reader
  (`_resolve_imports`' own manifest walk, `formal/imports.py`'s
  `external_declarations`) finds nothing. Order matters: dylib first, manifest
  second, so the window is "new bytes, old manifest", which is the state the
  readers already handle, and never "manifest describing a library that is not
  there yet".
* **The `.lock` side file must NOT move** — it is the lock, and `_dylib_lock`
  opens `out + ".lock"`. It is a sibling of `out`, not of `staged`.
* **The lock stays.** Two processes racing the same `out` would each have their
  own staging directory and would race the `os.replace`; the lock is what makes
  the manifest's read-modify-write (`_record_depends`) the single-writer case it
  documents.

Two cheaper alternatives, and why they are worse: **verify-then-re-sign at run
time** treats the symptom, costs a `codesign` per run, and leaves the window open
for every OTHER image; **taking the lock on the read side** (the harness holds
`_dylib_lock` while it runs an image) makes one harness quiet and leaves
`tools/formal_sweep.py`, `fire.py build` and every other caller still racing.

**A cheap measurement worth taking first**, because it decides how much this is
worth: count how often a formal image's linked dylibs change mtime between link
and run under `-j18`. If it is a few percent, this document is a footnote; if it
is tens of percent, every flaky formal report on this machine has this in it.