#!/usr/bin/env python3
"""JSON result cache for the large-scale Python-3.14.6 stdlib test harness.

Same idea as cas.py's content-addressed artifact store, but a different shape:
we're not caching compiled objects, we're caching a *test outcome* (category +
stderr) for "does mojo.py build accept this .py file", so a single flat JSON
file keyed by hash is the right fit rather than a splayed content store.

The key reuses cas.py's compiler_fingerprint()/toolchain_fingerprint() so the
cache is automatically invalidated the moment mojo_compiler.py, gimple_codegen.py,
myinterpreter.py, or any other codegen source changes (including uncommitted
edits) - a cache hit is only ever served for "this exact source, against this
exact compiler+toolchain", never a stale answer from before a fix landed.
"""
import hashlib
import json
import os
import threading

import cas

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, "py314_build_cache.json")

_lock = threading.Lock()
_cache = None
_dirty = False


def _load():
    global _cache
    if _cache is None:
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH) as f:
                    _cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                _cache = {}
        else:
            _cache = {}
    return _cache


def build_key(filepath: str, gcc: str, flags: tuple = ()) -> str:
    """Cache key for 'run mojo.py build on this file' - folds in the compiler
    fingerprint, the toolchain fingerprint, and the file's own content, so any
    change to any of the three (fix a codegen bug, switch gcc, edit the test
    file) is a guaranteed miss rather than a stale hit."""
    with open(filepath, "rb") as f:
        src = f.read()
    h = hashlib.blake2b(digest_size=20)
    for part in (
        "mojo-py314-test-v1",
        cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(gcc, flags),
    ):
        h.update(part.encode())
    h.update(src)
    return h.hexdigest()


def get(key):
    with _lock:
        return _load().get(key)


def put(key, value):
    global _dirty
    with _lock:
        _load()[key] = value
        _dirty = True


def save():
    """Atomic write - safe to call from multiple threads/processes; last
    writer wins on the whole file, matching cas.py's temp-write + os.replace."""
    global _dirty
    with _lock:
        if not _dirty:
            return
        tmp = CACHE_PATH + f".tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(_cache, f)
        os.replace(tmp, CACHE_PATH)
        _dirty = False


def stats():
    with _lock:
        return {"entries": len(_load())}
