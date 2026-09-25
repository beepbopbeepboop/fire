#!/usr/bin/env python3
"""Sweep every *.py / *.mojo under the repo through `build --formal` (arm64 Mach-O
by default; `--arch x86_64` sweeps the x86-64 machine subset instead).

Mojo is a Python superset, so .py files are valid inputs. Prints one
FAIL: line per failure; PASS lines are counted but not printed.
Summary (1-3 lines) at the end. Exit 1 if any FAIL.

Built with --no-prove, so what this measures is the arm64 CODEGEN's language
coverage: which source constructs the model can lower. Proof generation and
Lean typechecking are a separate, much narrower capability with their own
coverage (and their own failures, several of them about function *shapes*
rather than about anything the code generator could not lower) — they are
exercised by test_formal.py / `make check-formal`, not by this sweep. With
proofs on, a single unmodellable shape anywhere in a file fails the whole
file and masks which codegen gaps are real.

Verdicts are cached in the CAS (cas.formal_build_key: source bytes + the
formal backend's own sources + the interpreter + the build flags), so a
re-run with nothing changed reads a file per file instead of recompiling.
Editing anything under formal/, the parser, or mojo/middle/ invalidates it.

The default scope is this repo (the stdlib tree is excluded by name — it
lives outside the repo and is far larger); pass it explicitly to sweep it:

  python3 tools/formal_sweep.py -t 300 /path/to/mojo/stdlib

The architecture is a cache-key input, not a global: `--arch` adds
`--backend=<arch>` to the build flags, and those flags are what
cas.formal_build_key folds in, so an arm64 verdict is never served for an
x86_64 sweep (or the reverse).

Usage:
  python3 tools/formal_sweep.py [-j N] [-t SECONDS] [--arch x86_64] [paths...]
"""
import argparse
import concurrent.futures
import ctypes
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cas
from formal import macho_linker as ML

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE = os.path.join(REPO, "fire.py")

# Every build flag that changes the artifact, and therefore the cache key
# (cas.formal_build_key folds them in). The arch is one of them: the two
# backends lower the same AST to different code, so a verdict from one says
# nothing about the other, and folding `--backend=` in here is what keeps the
# two sweeps' verdicts in separate cache entries. The same tuple drives both
# the cache key and the argv below, so the two cannot drift apart.
def build_flags(arch: str) -> tuple:
    return ("--formal", "--no-prove", f"--backend={arch}")


def _criteria_id() -> str:
    """This tool's own content, as a cache-key input.

    A cached entry is a verdict, and a verdict is a function of the source AND
    the rules this tool applies to it. Without this in the key, tightening a
    check (e.g. also requiring the image's imports to be dyld-resolvable)
    silently keeps serving every verdict the OLD rules produced — which is how
    a file with 31 unresolvable imports stayed scored PASS after the check
    that would have caught it was added."""
    with open(os.path.abspath(__file__), "rb") as f:
        return cas.hash_parts(f.read())

SKIP_DIRS = {
    ".git", ".pixi", "output", "build", "__pycache__", ".mypy_cache",
    ".pytest_cache", "node_modules", "stdlib",  # external stdlib tree
}
# Mojo is a Python superset, so both extensions are valid inputs to the
# compiler; the stdlib tree is almost entirely .mojo.
SUFFIXES = (".py", ".mojo")
DEFAULT_JOBS = max(4, min(os.cpu_count() or 8, 20))
DEFAULT_TIMEOUT = 30


def find_source_files(roots):
    if roots:
        files = []
        for root in roots:
            root = os.path.abspath(root)
            if os.path.isfile(root) and root.endswith(SUFFIXES):
                files.append(root)
            elif os.path.isdir(root):
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [
                        d for d in dirnames
                        if d not in SKIP_DIRS and not d.startswith(".")
                    ]
                    for fn in filenames:
                        if fn.endswith(SUFFIXES):
                            files.append(os.path.join(dirpath, fn))
        return sorted(set(files))

    files = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for fn in filenames:
            if fn.endswith(SUFFIXES):
                files.append(os.path.join(dirpath, fn))
    return sorted(files)


def rel(path):
    return os.path.relpath(path, REPO)


def _bind_symbols(binary: bytes) -> list:
    """The external symbol names a Mach-O image binds, read from its bind stream.

    The images carry no LC_SYMTAB (the linker never emits one), so neither
    `nm -u` nor `dyld_info -imports` can list what they need — the names live
    only in the classic dyld bind opcodes, which this project writes itself
    (macho_linker._bind_info), so walking them here is exact rather than a
    heuristic. Opcode constants come from the linker, so the two cannot drift.
    """
    # LC_DYLD_INFO_ONLY gives the bind stream's file offset and size.
    ncmds = struct.unpack_from("<I", binary, 16)[0]
    off = 32
    bind_off = bind_size = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", binary, off)
        if cmd == ML.DYLD_INFO_ONLY_CMD:
            # dyld_info_command: cmd, cmdsize, rebase_off, rebase_size,
            # bind_off, bind_size, … — bind_off is the FIFTH field.
            (_c, _cs, _ro, _rs, bind_off,
             bind_size) = struct.unpack_from("<IIIIII", binary, off)
            break
        off += cmdsize
    if not bind_size:
        return []
    # Walk the opcodes. This emitter's own layout (macho_linker._bind_info),
    # per bound symbol:
    #     BIND_SET_DYLIB_ORDINAL_IMM|n, BIND_SET_SYMBOL_TRAILING_FLAGS_IMM,
    #     <flags byte>, <name>\0, BIND_SET_TYPE_IMM|…, BIND_SET_SEGMENT_AND_
    #     OFFSET_ULEB|seg, <ULEB offset>, BIND_DO_BIND
    # and a trailing BIND_DONE. The flags byte is what a walker that assumes
    # the plain SET_SYMBOL form gets wrong: it reads it as the first
    # character of the name.
    stream = memoryview(binary)[bind_off:bind_off + bind_size]
    i, out = 0, []
    while i < len(stream):
        byte = stream[i]
        i += 1
        if byte == ML.BIND_SET_SYMBOL_TRAILING_FLAGS_IMM:
            i += 1                       # the trailing-flags byte
            start = i
            while i < len(stream) and stream[i] != 0:
                i += 1
            if i > start:
                out.append(bytes(stream[start:i]).decode("utf-8", "replace"))
            i += 1                       # the NUL
        elif (byte & 0xF0) == ML.BIND_SET_SEGMENT_AND_OFFSET_ULEB:
            while i < len(stream) and stream[i] & 0x80:      # ULEB offset
                i += 1
            i += 1
        # every other opcode this emitter writes carries no operand
    return out


# One dyld-resolved libSystem binding in this process answers "can dyld
# resolve this name at load time" exactly, without executing the image.
_LIB = None
_RESOLVABLE: dict = {}


def _resolvable(name: str) -> bool:
    """Whether this process's libSystem has `name`.

    The probe is the host's own (arm64) libSystem, which is also what an
    x86_64 image's dyld resolves against under Rosetta 2 — same library, same
    exports, different slice. The bind stream itself is read from the image
    under test, so which symbols it NEEDS is exact either way; only the
    answer to "could dyld find it" is approximated, and the two slices do not
    differ in any name the formal backends emit."""
    global _LIB
    if name not in _RESOLVABLE:
        if _LIB is None:
            _LIB = ctypes.CDLL(None)
        _RESOLVABLE[name] = hasattr(_LIB, name)
    return _RESOLVABLE[name]


def _unresolved_imports(binary: bytes) -> list:
    """Externs the image needs that dyld cannot resolve — i.e. it cannot load.

    This backend compiles ONE file and resolves no imports, so a call into
    another module lowers to a BL against a symbol nothing defines. That is a
    real limit of the path, not a codegen failure, but it must not be counted
    as coverage: the binary builds and then dies in dyld at launch."""
    return [s for s in _bind_symbols(binary) if not _resolvable(s.lstrip("_"))]


def _verdict_bytes(ok, detail):
    return b"ok\n" if ok else b"fail\n" + detail.encode("utf-8", "replace")


def _verdict_from_bytes(raw):
    ok, _, detail = raw.decode("utf-8", "replace").partition("\n")
    return (ok == "ok"), detail.strip()


def run_one(path, timeout, flags):
    """Return (ok, detail). detail empty on success.

    `flags` is the build flag tuple (see build_flags) — required, not defaulted,
    because it is simultaneously the cache key's input and the argv: a wrong
    default would publish one architecture's verdict under the other's key.

    Cached in the CAS under cas.formal_build_key (source bytes + the formal
    backend's sources + the interpreter + BUILD_FLAGS), so a re-run with
    nothing changed is a file read per file instead of a compile. A timeout is
    a property of this machine's load, not of the source, so it is never
    published — it would otherwise pin a file at "timeout" until the key
    changed.
    """
    try:
        with open(path, "rb") as f:
            source = f.read().decode("utf-8", "replace")
    except OSError as e:
        return False, str(e)[:200]
    key = cas.formal_build_key(source, path, flags, _criteria_id())
    hit = cas.lookup(key, ".result")
    if hit is not None:
        cas.stats["hits"] += 1
        try:
            with open(hit, "rb") as f:
                return _verdict_from_bytes(f.read())
        except OSError:
            pass    # unreadable cache entry: fall through and rebuild
    cas.stats["misses"] += 1
    try:
        # -o into a temp dir so we don't scatter .aout across the tree
        with tempfile.TemporaryDirectory(prefix="formal_sweep_") as td:
            out = os.path.join(td, "a.out")
            proc = subprocess.run(
                [sys.executable, FIRE, "build", *flags, "-o", out, path],
                capture_output=True, text=True, timeout=timeout, cwd=REPO,
            )
            if proc.returncode == 0:
                with open(out, "rb") as f:
                    binary = f.read()
        if proc.returncode == 0:
            missing = _unresolved_imports(binary)
            if missing:
                ok, detail = False, (
                    f"builds, but {len(missing)} import(s) dyld cannot "
                    f"resolve (one file compiled, no import resolution): "
                    f"{', '.join(sorted(set(missing))[:3])}"
                    + (" ..." if len(set(missing)) > 3 else ""))
            else:
                ok, detail = True, ""
        else:
            err = (proc.stderr or proc.stdout or "").strip()
            # keep the last non-empty line — that's the formal build's message
            lines = [ln for ln in err.splitlines() if ln.strip()]
            detail = lines[-1] if lines else f"exit {proc.returncode}"
            ok = False
        cas.publish(key, ".result", _verdict_bytes(ok, detail))
        return ok, detail
    except subprocess.TimeoutExpired:
        return False, f"timeout (> {timeout}s)"
    except Exception as e:
        return False, str(e)[:200]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"parallel workers (default {DEFAULT_JOBS})")
    ap.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="per-file build timeout in seconds "
                         f"(default {DEFAULT_TIMEOUT}; raise it for the "
                         "much larger stdlib modules)")
    ap.add_argument("--arch", default="arm64",
                    choices=("arm64", "x86_64", "x86-64", "amd64"),
                    help="machine subset to sweep (default arm64; the "
                         "x86-64 spellings are accepted as aliases)")
    ap.add_argument("paths", nargs="*",
                    help="files or dirs (default: all *.py/*.mojo under repo)")
    args = ap.parse_args()
    arch = "x86_64" if args.arch in ("x86-64", "amd64") else args.arch
    flags = build_flags(arch)

    files = find_source_files(args.paths or None)
    if not files:
        print("no .py/.mojo files found", file=sys.stderr)
        sys.exit(2)

    jobs = max(1, args.jobs)
    print(f"Sweeping {len(files)} files through build --formal "
          f"[{arch}] ({jobs} workers, {args.timeout}s timeout)...",
          file=sys.stderr)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(run_one, p, args.timeout, flags): p
                for p in files}
        for fut in concurrent.futures.as_completed(futs):
            path = futs[fut]
            results[path] = fut.result()

    passed = failed = 0
    fails = []
    for path in files:  # deterministic order
        ok, detail = results[path]
        if ok:
            passed += 1
        else:
            failed += 1
            fails.append((rel(path), detail))

    # FAIL lines only (PASS counted, not printed)
    for r, detail in fails:
        print(f"FAIL: {r}  ({detail})")

    total = passed + failed
    pct = (100.0 * passed / total) if total else 0.0
    print(f"[{arch}] PASS={passed} FAIL={failed} total={total} "
          f"({pct:.1f}% pass)")
    print(f"cas: {cas.stats['hits']} hit / {cas.stats['misses']} miss")
    if failed:
        print(f"first failure: {fails[0][0]}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
