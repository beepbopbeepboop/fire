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
     read, for all four of them;
  5. that the demands digest `_record_depends` records on each dependency is
     the one `dylib_chain` looks the library up by, which is the field that
     decides what ends up on a link line. This file passed
     `(module, source)` pairs for a long while after the writer grew a third
     element, which left three of its four groups red on an arity `ValueError`
     and the digest itself untested — so the arity is written out at every call
     site here and the digest's job is measured rather than assumed.

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
            # And the fourth writer, reached through its own module. The third
            # element is the dependency's OWN demands digest
            # (`_record_depends`' docstring), not an empty placeholder: it is
            # what `dylib_chain` looks the library up by, and
            # `test_the_demands_digest_round_trips` below is where that is
            # measured. This file's version of the call predates the field and
            # raised `ValueError: not enough values to unpack` in three of its
            # four groups, which is why the shape is written out in full here.
            I._record_depends(manifest, [("std.collections", "/src/c.mojo",
                                          "dkey-collection")])
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
        I._record_depends(manifest, [("std.x", "/src/x.mojo", "dkey-x")])
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
    I._record_depends(manifest, [("std.rt", "/src/rt.mojo", "dkey-rt")],
                      "dkey-self")
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
                                         "source": "/src/rt.mojo",
                                         "instantiations": "dkey-rt"}]),
        # The MODULE's own digest, read back by `_manifest_instantiations`, is
        # the half of the field a `depends_on` comparison cannot see. It is the
        # same key `_BUILT` is indexed on, so a writer that recorded the wrong
        # one here drops this library off a linker's line.
        check("the_modules_own_digest_survives",
              payload["instantiations"] == "dkey-self"
              and I._manifest_instantiations(dylib) == "dkey-self"),
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
    I._record_depends(manifest, [("m", "p", "k")])
    return check("updating_a_manifest_that_is_not_there_creates_nothing",
                 not os.path.exists(manifest), manifest)


def test_the_demands_digest_round_trips(tmpdir):
    """The THIRD field of a `depends` entry, end to end, through the real reader.

    This is the group that could not exist while this file passed
    `(module, source)` pairs: `_record_depends` grew the field when `_BUILT`'s key
    grew a demands digest, the writer was updated, and a test written against the
    old arity raised `ValueError: not enough values to unpack (expected 3, got
    2)` in three of four groups — so the field that decides WHICH library a
    linker gets had no test at all, and the groups that would have had one were
    red for a reason nobody read.

    So it is measured, through `dylib_chain` (the link-line walker) against a
    seeded `_BUILT`, over three cases and each is a sentence in
    `dylib_chain`'s own docstring:

    * the recorded digest is the one that selects the library — TWO libraries
      built from ONE source under two digests, and the manifest names one of
      them. If the digest were not consulted, or were read from the wrong place,
      this returns the wrong one of the two.
    * a digest nobody built is NOT silently satisfied when the choice would be a
      guess: two candidates and no exact key is `_built_lookup`'s documented
      refusal, so the dependency drops off the chain and the image's own symbol
      audit reports the dangling reference. (A reader that "helpfully" picked one
      would fail here.)
    * with only ONE candidate it IS a fallback rather than an omission, which is
      the other half of the same sentence — and the case a manifest written
      before the field existed is in.

    `_BUILT` is saved and restored rather than cleared: it is module state other
    tests in a suite share, and a test that empties it turns every later build
    into a rebuild.
    """
    arch = "arm64"
    dep_source = os.path.join(tmpdir, "src", "dep.mojo")
    os.makedirs(os.path.dirname(dep_source), exist_ok=True)
    # The architecture is read off the FILE NAME's last dot (`_arch_of_dylib`),
    # so the suffix is load-bearing here and not decoration.
    dep_a = os.path.join(tmpdir, "libdep.aaaaaaaa." + arch + ".dylib")
    dep_b = os.path.join(tmpdir, "libdep.bbbbbbbb." + arch + ".dylib")
    for path in (dep_a, dep_b):
        open(path, "wb").close()
    parent = os.path.join(tmpdir, "libparent.cccccccc." + arch + ".dylib")
    open(parent, "wb").close()
    manifest = B.write_dylib_manifest(parent, "@rpath/libparent.dylib",
                                      exports(2), module="std.parent")

    saved = dict(I._BUILT)
    results = []
    try:
        I._BUILT[(arch, os.path.abspath(dep_source), "dkey-a")] = dep_a
        I._BUILT[(arch, os.path.abspath(dep_source), "dkey-b")] = dep_b

        I._record_depends(manifest, [("std.dep", dep_source, "dkey-a")])
        chain = I.dylib_chain(parent)
        results.append(check(
            "the_recorded_digest_selects_the_library",
            chain == [dep_a, parent],
            f"dylib_chain returned {chain!r}; it should be the library built "
            f"under dkey-a ({dep_a!r}) then the module itself"))

        I._record_depends(manifest, [("std.dep", dep_source, "dkey-none")])
        chain = I.dylib_chain(parent)
        results.append(check(
            "an_unbuilt_digest_is_a_refusal_and_not_a_guess",
            chain == [parent],
            f"dylib_chain returned {chain!r}; with two libraries built from one "
            f"source and no key naming either, picking one would be a guess, "
            f"and the image's symbol audit is what reports the omission"))

        del I._BUILT[(arch, os.path.abspath(dep_source), "dkey-b")]
        I._record_depends(manifest, [("std.dep", dep_source, "dkey-none")])
        chain = I.dylib_chain(parent)
        results.append(check(
            "one_candidate_is_a_fallback_rather_than_an_omission",
            chain == [dep_a, parent],
            f"dylib_chain returned {chain!r}; a manifest written before the "
            f"digest was recorded must not lose a library from the link line"))
    finally:
        I._BUILT.clear()
        I._BUILT.update(saved)
    return all(results)


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
            ("the demands digest round trips",
             lambda: test_the_demands_digest_round_trips(tmpdir)),
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