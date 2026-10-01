# FORMAL_dylib_manifest_written_in_place: a manifest is truncated to zero bytes before it is rewritten, so a concurrent reader sees an empty file and the build dies on `JSONDecodeError: char 0`

**Status: found and MEASURED, not fixed.** The mechanism below is measured, not
inferred, and the fix is named. It is not in the area this session changed
(`tools/formal_sweep.py`), so it is handed over rather than taken.

This replaces the hypothesis in `bugs/FORMAL_sweep_tool_json_decode_error.md`,
which guessed "the child was killed or its output was truncated". The child was
not killed. The file it was reading was empty, and something else on the machine
had emptied it 0.2 ms earlier.

## What is wrong

`formal/build.py` and `formal/imports.py` do a read-modify-write cycle on
`<dylib>.manifest.json` in **four** places, and all four write in place:

| site | reads | writes |
|---|---|---|
| `formal/build.py:7055` `write_dylib_manifest` | — | `open(path, "w")` |
| `formal/build.py:8157` `_record_link_deps` | `json.load`, catches `OSError` | `open(path, "w")` |
| `formal/build.py:8314` `_mark_namespace` | `json.load`, catches `OSError` | `open(path, "w")` |
| `formal/imports.py:1254` `_record_depends` | `json.load`, catches `OSError` | `open(path, "w")` |

and read it in three more, none of which holds any lock:

* `formal/build.py:7105` `load_dylib_manifests` — catches `OSError`
* `formal/imports.py:1250` `_record_depends` — catches `OSError`
* `formal/imports.py:1283` `dylib_chain` — catches `OSError`

`open(path, "w")` truncates **at the open**. Between that open and the first
byte `json.dump` writes, the file is **0 bytes**, and a reader in that window
gets exactly

```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

`char 0` is the empty-file signature. And `json.JSONDecodeError` is **not** an
`OSError`, so none of the three `except OSError` handlers catches it: it
propagates out of the build driver and the sweep files the file as
`tool: the build driver raised: json.decoder.JSONDecodeError: …`.

The dylib *write* is serialised — `formal/imports.py`'s `_dylib_lock` takes an
exclusive `flock` on `<out>.lock` and holds it across the compile and the
manifest record. The **reader** takes no lock at all. So the flock prevents two
writers and does nothing about a reader, which is the whole bug: a program build
in worker B reading the manifest of a dylib that worker A is rebuilding.

## Why it is intra-sweep, not cross-sweep

This is the part that changes where to look. Two workers in ONE `-j6` sweep that
import the same stdlib module both build the same dylib and both link it, so the
reader/writer pair exists without any second sweep. Measured, on this tree,
arm64, one sweep at a time:

| run | `-j` | JSONDecodeError files |
|---|---|---|
| first `-j6` sweep of the session, before any edit | 6 | 1 (`scripts/check_resolved_bugs.py`) |
| `-j18` sweep | 18 | 0 (nearly all cache hits — 615/623) |
| `-j6` sweep after the sweep-tool change | 6 | 5 |

so it scales with **contention**, not with the number of sweeps. The 18-worker
run showed none only because the CAS was warm and 18 workers finished in
milliseconds each.

## The measurement

Against a real 11,668-byte manifest from
`~/.gmojo/cas/formal-imports/arm64/`, doing exactly what `formal/build.py` does
— 300 × `open(path,"w")` + `json.dump` — with a reader thread doing
`json.load` in a loop:

```
manifest os_path___syscalls.7266bd1070c7.arm64.dylib.manifest.json (11668 bytes)
300 rewrites in 0.12s = 0.40 ms each
concurrent reads: 882, of which EMPTY ('char 0'): 357
json.dump alone: 0.21 ms (this is the whole vulnerable window)
```

**357 of 882 concurrent reads — 40 % — landed in the window.** The window is
0.21 ms wide, and it is hit or missed essentially at random. Nothing about
`flock` narrows it, because the reader does not take one.

## The smallest reproducer

No compiler and no Mojo source; the race is in the file handling:

```python
import json, threading
# write a real manifest, then:
#   thread A, 300x:  json.dump(payload, open(path, "w"))
#   thread B:        json.load(open(path))
# 357/882 reads raise JSONDecodeError "Expecting value: line 1 column 1 (char 0)"
```

## The fix, and why it is the fix

**Write every manifest through a private temp file and `os.replace`.** That is
already the established mechanism in this repository — `cas.publish` does
precisely this and its own comment says why ("Hash-named files are immutable, so
a racing identical write is harmless (`os.replace` is atomic)"), and a manifest
is content-addressed by path in exactly the same way. A reader then sees either
the whole old file or the whole new one, and never a 0-byte one.

The production-quality shape, per this repo's "consolidate duplicates" rule, is
**one** helper rather than four fixed call sites — four copies of a
read-modify-write is four chances to leave one of them truncating:

```python
# formal/build.py, next to dylib_manifest_path / write_dylib_manifest
def update_dylib_manifest(dylib_path: str, mutate) -> None:
    """Read <dylib>.manifest.json, apply `mutate` to the payload, write it back
    ATOMICALLY. A temp file plus os.replace, because a manifest is read by other
    processes with no lock: an in-place rewrite truncates the file to 0 bytes at
    the open, and a reader in that 0.21 ms window gets
    `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` —
    which is not an OSError, so none of the `except OSError` around these reads
    catches it. Measured: 40% of concurrent reads landed in the window."""
```

and then `_record_link_deps`, `_mark_namespace`, `_record_depends` and
`write_dylib_manifest` all go through it. Two things to keep while doing that:

* **The `except OSError` handlers stay.** They are catching a genuinely
  different thing (a manifest that is not there yet). Widening them to
  `ValueError` would be the wrong fix: it would convert a race into a silent
  "no manifest", which reads as a module that exports nothing — the exact false
  finding the `load_dylib_manifests` comment at formal/build.py:7100 warns
  about. The fix removes the race; it does not paper over it.
* **Take the lock in the reader, or do not.** Once the write is atomic the reader
  needs no lock, and adding one would put every program build behind every dylib
  rebuild in the tree. Atomicity is the fix; a reader-side lock is not.

## Verification, when it is done

1. The reproducer above stops raising, at `-P6` and at `-P18`.
2. `python3 tools/formal_sweep.py -j6 -t 30` twice in a row on a cold CAS: the
   `tool` count contains no `JSONDecodeError` row. Before the fix, one to five
   per cold run (measured above).
3. `formal-imports` manifests still round-trip: `load_dylib_manifests` and
   `dylib_chain` are the two readers, and `test_formal_imports.py` /
   `test_formal_dylib.py` exercise both.
