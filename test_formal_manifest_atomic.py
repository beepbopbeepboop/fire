#!/usr/bin/env python3
"""A dylib manifest is never observed half-written.

`formal/build.py` and `formal/imports.py` did a read-modify-write cycle on
`<dylib>.manifest.json` in four places and all four wrote IN PLACE, with
`open(path, "w")`. That truncates the file AT THE OPEN, so between the open and
the first byte `json.dump` writes, the manifest is 0 bytes — and a reader in
that window gets exactly

    json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

`char 0` is the empty-file signature, and `json.JSONDecodeError` is NOT an
`OSError`, so none of the three `except OSError` handlers around these reads
catch it: it propagates out of the build driver, and the sweep files the file as
`tool: the build driver raised: json.decoder.JSONDecodeError`.

The dylib WRITE is serialised — `formal/imports.py`'s `_dylib_lock` takes an
exclusive `flock` and holds it across the compile and the manifest record. The
READER takes no lock at all, so the pair exists inside ONE sweep: two workers
that import the same stdlib module both build its dylib, and one links it while
the other rewrites its manifest. Measured twice, against exactly the old code and
a real manifest of 11.6 kB: **357 of 882 concurrent reads (40 %) landed in the
0.21 ms window** in the original report, and **1804 failures in 4095 reads** in
this file's own reproducer — 1759 of them the empty-file `char 0` signature —
against **0 in 12792** after the fix.

What is asserted here:

  1. the atomic-write path, against the REAL readers (`load_dylib_manifests`
     and `formal.imports.dylib_chain`) with a real payload, under a reader loop
     racing a writer loop — zero failures, and every read a complete payload;
  2. that all FOUR writers go through it, which is the "consolidate rather than
     maintain parallel implementations" half: four copies of a read-modify-write
     is four chances to leave one of them truncating;
  3. that the `except OSError` around a manifest that is not there yet is still
     a no-op rather than a refusal — widening it to `ValueError` would convert
     the race into a silent "this module exports nothing", which is the exact
     false finding `load_dylib_manifests` warns about;
  4. that the payload round-trips: what the writers write is what the readers
     read, for all four of them.

Usage:
    python3 test_formal_manifest_atomic.py [-v]
"""
import argparse
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import formal.build as B  # noqa: E402
import formal.imports as I  # noqa: E402

# Enough exports that the manifest is the size a real one is: the window is
# `json.dump`'s own duration, so a payload too small to be worth racing would
# pass a reader loop for the wrong reason.
N_EXPORTS = 60
WRITES = 300
READ_TIMEOUT = 60.0


def exports(n=N_EXPORTS):
    return [{"module": "std.collections", "name": f"fn_{i}",
             "symbol": f"_std_collections__fn_{i}", "arity": 1,
             "signature": "(Int) -> Int", "kind": "function",
             "frame_params": []}
            for i in range(n)]


def seed(dylib, tmpdir, install="@rpath/libstd.dylib"):
    """Write the manifest a real dylib build leaves behind; return its path."""
    path = B.write_dylib_manifest(dylib, install, exports(), module="std.x")
    assert os.path.exists(path), path
    return path


def reader_loop(paths, stop, failures, reads):
    """Read every path the way the build does, until told to stop."""
    while not stop.is_set():
        for path in paths:
            if stop.is_set():
                return
            try:
                if path.endswith(".dylib"):
                    B.load_dylib_manifests([path])
                else:
                    I.dylib_chain(path)
                reads[0] += 1
            except Exception as e:  # noqa: BLE001 — the thing being measured
                failures.append(f"{type(e).__name__}: {e}")


def test_the_writers_and_readers_never_disagree(tmpdir):
    """The race itself, with the real readers on both sides."""
    dylib = os.path.join(tmpdir, "libstd.dylib")
    manifest = seed(dylib, tmpdir)
    before = len(json.load(open(manifest))["exports"])
    if before != N_EXPORTS:
        return check("the_seeded_manifest_has_its_exports", False,
                     f"{before} exports")

    stop = threading.Event()
    failures = []
    reads = [0]
    # Both readers, not just one: `load_dylib_manifests` is the executable
    # build's reader and `dylib_chain` the link-line walker's, and the sweep
    # runs both against the same manifest.
    threads = [threading.Thread(target=reader_loop,
                                args=([manifest, dylib], stop, failures, reads))
               for _ in range(2)]
    for t in threads:
        t.start()
    t0 = time.time()
    try:
        for i in range(WRITES):
            # The two shapes the four writers use: a whole fresh payload (what
            # `write_dylib_manifest` does) and a read-modify-write that touches
            # one key (what the other three do).
            if i % 2:
                def _bump(payload, i=i):
                    payload["links"] = [{"install_name": "@rpath/x.dylib",
                                         "path": f"/tmp/x{i}"}]
                B.update_dylib_manifest(manifest, _bump)
            else:
                B.write_dylib_manifest(dylib, "@rpath/libstd.dylib", exports(),
                                       module="std.x")
            # And the fourth writer, reached through its own module.
            I._record_depends(manifest, [("std.collections", "/src/c.mojo")])
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=READ_TIMEOUT)
    secs = time.time() - t0
    ok = check("no_reader_saw_a_half_written_manifest", not failures,
               f"{len(failures)} failure(s), first: {failures[:1]}")
    ok &= check("the_readers_actually_ran", reads[0] > WRITES,
                f"{reads[0]} reads over {secs:.1f}s — too few for the race "
                f"to have been live")
    return ok


def test_every_writer_goes_through_the_atomic_path(tmpdir):
    """Four writers, one mechanism — asserted by counting, not by reading code.

    The count is what makes this a test rather than a review: a writer that
    reverts to `open(path, "w")` stops incrementing it and fails here.
    """
    dylib = os.path.join(tmpdir, "libw.dylib")
    manifest = seed(dylib, tmpdir)
    real = B._write_json_atomic
    calls = []

    def counting(path, payload):
        calls.append(path)
        return real(path, payload)

    B._write_json_atomic = counting
    try:
        B.write_dylib_manifest(dylib, "@rpath/libw.dylib", exports(3))
        check("write_dylib_manifest_is_atomic", len(calls) == 1, f"{calls}")
        calls.clear()
        B._record_link_deps(manifest, [{"install_name": "@rpath/dep.dylib",
                                        "path": "/tmp/dep.dylib"}])
        check("_record_link_deps_is_atomic", len(calls) == 1, f"{calls}")
        calls.clear()
        B._record_namespace(manifest, {"f": ("std.x", "function", "f")}, {})
        check("_record_namespace_is_atomic", len(calls) == 1, f"{calls}")
        calls.clear()
        I._record_depends(manifest, [("std.x", "/src/x.mojo")])
        check("_record_depends_is_atomic", len(calls) == 1, f"{calls}")
    finally:
        B._write_json_atomic = real
    return True


def test_the_round_trip_still_reads(tmpdir):
    """What the four writers write is what the readers read."""
    dylib = os.path.join(tmpdir, "librt.dylib")
    manifest = B.write_dylib_manifest(dylib, "@rpath/librt.dylib", exports(4),
                                      module="std.rt",
                                      constants={"sys.argv": "list"})
    B._record_link_deps(manifest, [{"install_name": "@rpath/dep.dylib",
                                    "path": "/tmp/dep.dylib"}])
    B._record_namespace(manifest, {"reexported": ("std.rt", "function",
                                                  "reexported")},
                        {"reexported": "_std_rt__reexported"}, traits=["T"])
    I._record_depends(manifest, [("std.rt", "/src/rt.mojo")])
    payload = json.load(open(manifest))
    results = [
        check("exports_survive", len(payload["exports"]) == 4),
        check("links_survive",
              payload["links"] == [{"install_name": "@rpath/dep.dylib",
                                    "path": "/tmp/dep.dylib"}]),
        check("the_namespace_kind_survives", payload.get("kind") == "namespace"),
        check("reexports_survive",
              payload["reexports"]["reexported"]["symbol"]
              == "_std_rt__reexported"),
        check("the_defining_name_survives",
              payload["reexports"]["reexported"]["defines"] == "reexported"),
        check("traits_survive", payload.get("traits") == ["T"]),
        check("depends_on_survives",
              payload["depends_on"] == [{"module": "std.rt",
                                         "source": "/src/rt.mojo"}]),
        check("constants_survive", payload["constants"] == {"sys.argv": "list"}),
    ]
    # …and through the REAL reader, which is the one that raised JSONDecodeError.
    loaded = B.load_dylib_manifests([dylib])
    results.append(check("load_dylib_manifests_reads_it",
                         loaded and loaded[0]["map"].get("fn_0")
                         == "_std_collections__fn_0"))
    return all(results)


def test_a_missing_manifest_is_a_no_op(tmpdir):
    """The `except OSError` stays: "not written yet" is not a refusal."""
    ghost = os.path.join(tmpdir, "libghost.dylib")
    manifest = B.dylib_manifest_path(ghost)
    B._record_link_deps(manifest, [{"install_name": "x", "path": "y"}])
    B._record_namespace(manifest, {}, {})
    I._record_depends(manifest, [("m", "p")])
    return check("updating_a_manifest_that_is_not_there_creates_nothing",
                 not os.path.exists(manifest), manifest)


def check(name, cond, detail=""):
    if cond:
        print(f"PASS  {name}")
        return True
    print(f"FAIL  {name}  {detail}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmpdir:
        groups = [
            ("no reader sees a half-written manifest",
             lambda: test_the_writers_and_readers_never_disagree(tmpdir)),
            ("every writer goes through the atomic path",
             lambda: test_every_writer_goes_through_the_atomic_path(tmpdir)),
            ("the round trip still reads",
             lambda: test_the_round_trip_still_reads(tmpdir)),
            ("a missing manifest is a no-op",
             lambda: test_a_missing_manifest_is_a_no_op(tmpdir)),
        ]
        failed = 0
        for name, fn in groups:
            print(f"── {name}")
            try:
                ok = fn()
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"FAIL  {name}  {type(e).__name__}: {e}")
                ok = False
            if not ok:
                failed += 1
    print(f"\n{len(groups) - failed}/{len(groups)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())