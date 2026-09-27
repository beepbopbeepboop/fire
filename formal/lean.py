import hashlib
import os
import shutil
import subprocess

# Dependency order: X86 needs ProofLib, and work.lean re-exports it so the
# generated proof files (which import ProofLib + work + Refine) get the x86-64
# model without naming a fourth module.
LIBRARY_MODULES = ("ProofLib", "X86", "work", "Refine")
VERDICT_EXT = ".leanverdict"
_OLEAN_DIGESTS: dict = {}


def _default_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pinned_toolchain(root: str) -> str | None:
    """The toolchain named by <root>/lean-toolchain, e.g. leanprover/lean4:v4.32.2."""
    try:
        with open(os.path.join(root, "lean-toolchain")) as f:
            spec = f.read().strip()
    except OSError:
        return None
    return spec or None


def elan_toolchain_binary(spec: str) -> str | None:
    """Concrete <elan>/toolchains/<mangled>/bin/lean for a lean-toolchain spec.

    elan's on-disk directory name escapes the spec separators by repeating the
    dash: '/' becomes '--' and ':' becomes '---'. Resolving the pinned
    toolchain directly (instead of running the elan shim) is what keeps
    proof checking from silently using - or downloading - whatever toolchain
    the shim's default happens to be, which is what a shim invoked with a cwd
    outside the repo does.
    """
    elan_home = os.environ.get("ELAN_HOME") or os.path.expanduser("~/.elan")
    mangled = spec.replace("/", "--").replace(":", "---").replace("@", "---")
    candidate = os.path.join(elan_home, "toolchains", mangled, "bin", "lean")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return None


def find_lean(repo_root: str | None = None) -> str | None:
    root = repo_root or _default_root()
    spec = pinned_toolchain(root)
    candidates = [os.environ.get("LEAN"),
                  os.path.join(root, ".pixi", "envs", "default", "bin", "lean")]
    if spec:
        pinned = elan_toolchain_binary(spec)
        if pinned:
            candidates.append(pinned)
    candidates.append(shutil.which("lean"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _olean_key(stem: str, source: str, lean: str) -> str:
    """CAS key for a library .olean: the source bytes, the module name and the
    toolchain. Lean's output for a given (source, version) pair is
    deterministic, so this is a hit on every machine and every rebuild after
    the first — ProofLib.olean alone is 27MB and takes ~90s to produce."""
    import cas
    with open(source, "rb") as f:
        return "leanlib/" + cas.hash_parts(
            b"lean-olean-v1", stem.encode(), lean_version(lean).encode(), f.read())


def _library_is_current(source: str, olean: str, stamp: str,
                        source_digest: str) -> bool:
    """Is this .olean built from exactly these source bytes?

    Purely content-based, with no mtime in the decision: `touch
    lib/ProofLib.lean` (or a git checkout, or an editor that rewrites mtimes)
    must not cost a 27MB Lean rebuild, and an mtime rule cannot tell "touched"
    from "edited" — which is why a bare mtime check makes the whole formal
    suite mysteriously slow again after anything touches lib/. The stamp
    records the source digest the .olean was built from *and* a digest of the
    .olean itself, so an edit invalidates, a touch does not, and an .olean
    swapped out from under the stamp invalidates too.
    """
    if not (os.path.isfile(olean) and os.path.isfile(stamp)):
        return False
    try:
        with open(stamp) as f:
            recorded_source, recorded_olean = f.read().split()[:2]
    except (OSError, ValueError):
        return False
    if recorded_source != source_digest:
        return False
    return _digest(olean).hex() == recorded_olean


def _write_stamp(stamp: str, source: str, olean: str) -> None:
    tmp = f"{stamp}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(f"{_sha256_file(source)} {_digest(olean).hex()}\n")
    os.replace(tmp, stamp)


def _build_lock(olean: str):
    """Exclusive, cross-process, released on exit: an flock on a side file.

    The stamp check above is not a lock. Every process that arrives while the
    library is stale sees it stale, misses the CAS (nobody has published yet),
    and runs `lean -o <the same .olean>` — forty of them at once, which is
    exactly what a `-j18` suite plus a few concurrent `make check-formal`
    shells produces. They overwrite each other's output file, so the winner is
    whichever finished last, and a reader can observe a half-written `.olean`.

    The lock is on a SIDE file (`<olean>.lock`), never on the `.olean` itself:
    lean truncates and rewrites the `.olean`, so locking it would let a second
    process in as soon as the first one created it. A side file is never
    rewritten, so the lock actually spans the whole build.

    `flock` is advisory and per-open-file-description, so it releases when the
    process dies — a crashed build cannot wedge the tree. It is also per-host:
    this coordinates the processes on one machine, which is the case that
    happens (one repo, one lib/ directory). It does not coordinate a network
    filesystem, and nothing here assumes it does.
    """
    import contextlib
    import fcntl

    @contextlib.contextmanager
    def _locked():
        path = olean + ".lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)       # closing releases the lock, even if we raised
    return _locked()


def _ensure_one(lean: str, lib_dir: str, stem: str, env: dict,
                timeout: int) -> None:
    """Build one library module if it is not already current. Caller holds the
    lock for this stem, and must have re-checked currency after taking it."""
    import cas
    source = os.path.join(lib_dir, stem + ".lean")
    olean = os.path.join(lib_dir, stem + ".olean")
    stamp = olean + ".srcsha256"
    key = _olean_key(stem, source, lean)
    hit = cas.lookup(key, ".olean")
    if hit:
        shutil.copyfile(hit, olean)
    else:
        # lean writes the .olean in place, so build beside it and move it into
        # place: a concurrent reader either sees the old file or the new one.
        tmp_olean = f"{olean}.tmp.{os.getpid()}"
        try:
            result = subprocess.run(
                [lean, "-o", tmp_olean, source],
                capture_output=True, text=True, timeout=timeout, env=env,
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout
                                    or "lean failed").strip())
            os.replace(tmp_olean, olean)
        finally:
            if os.path.exists(tmp_olean):
                os.unlink(tmp_olean)
        with open(olean, "rb") as f:
            cas.publish(key, ".olean", f.read())
    _write_stamp(stamp, source, olean)


def ensure_library(lean: str, lib_dir: str, timeout: int = 1200) -> None:
    env = os.environ.copy()
    env["LEAN_PATH"] = lib_dir
    for stem in LIBRARY_MODULES:
        source = os.path.join(lib_dir, stem + ".lean")
        olean = os.path.join(lib_dir, stem + ".olean")
        stamp = olean + ".srcsha256"
        if not os.path.isfile(source):
            continue
        digest = _sha256_file(source)
        if _library_is_current(source, olean, stamp, digest):
            continue
        # Pre-stamp trees (fresh clone, or an olean built by the Makefile):
        # accept it if it is newer than the source, then record its digests so
        # later touches are free.
        if (not os.path.isfile(stamp) and os.path.isfile(olean)
                and os.path.getmtime(olean) >= os.path.getmtime(source)):
            _write_stamp(stamp, source, olean)
            continue
        # Serialise the build, then RE-CHECK under the lock: the process we
        # waited for has very probably just built exactly what we were about
        # to, and this is the line that makes the lock cheap instead of merely
        # correct.
        with _build_lock(olean):
            if _library_is_current(source, olean, stamp, _sha256_file(source)):
                continue
            _ensure_one(lean, lib_dir, stem, env, timeout)



# ── verdict cache ───────────────────────────────────────────────────────────
#
# Typechecking a generated proof is the dominant cost of the whole formal
# pipeline: these proofs are ~700KB of `native_decide` goals and take tens of
# seconds of wall time and *more* system time than user time (the 27MB
# ProofLib.olean is mapped and the native_decide shared objects are loaded per
# goal). The verdict, though, is a pure function of its inputs, so it caches
# like any other compile artifact — in cas.py's content-addressed store, which
# is exactly the tier-1 "instantiate once, ever" mechanism
# (MODULE_CACHE_DESIGN.md). Re-running `make check-formal`, or rebuilding the
# same dylib twice, then costs a hash instead of a Lean run.
#
# The key folds in everything that can change the verdict, and nothing else:
#   * the proof file's exact bytes — the complete source lean reads;
#   * every .olean reachable through LEAN_PATH (ProofLib/work/Refine), by
#     content: rebuilding an .olean from unchanged source can still change its
#     bytes, and a changed import is exactly what a stale verdict must not
#     survive;
#   * the lean binary's `--version`, so a toolchain bump (or switching from
#     the pinned toolchain to another one) invalidates every verdict.
# The proof's own directory is deliberately NOT in the key: the generator only
# ever emits `import ProofLib/work/Refine`, so the verdict does not depend on
# where the file happens to sit, and keying on the path would make a cache
# that misses for a file merely copied somewhere else.

def _digest(path: str) -> bytes:
    """sha256 of a file's bytes, memoised on (size, mtime_ns) so a suite of
    concurrent runs hashes ProofLib.olean (27MB) once, not once per proof."""
    st = os.stat(path)
    memo_key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    hit = _OLEAN_DIGESTS.get(memo_key)
    if hit is not None:
        return hit
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    value = h.digest()
    _OLEAN_DIGESTS[memo_key] = value
    return value


def lean_version(lean: str, timeout: int = 120) -> str:
    try:
        result = subprocess.run([lean, "--version"], capture_output=True,
                                text=True, timeout=timeout)
        return (result.stdout or result.stderr or "").strip()
    except Exception:
        return "unknown"


def proof_verdict_key(proof_path: str, lib_dir: str, lean: str) -> str:
    import cas
    parts = [b"formal-proof-verdict-v1", lean_version(lean).encode()]
    for stem in LIBRARY_MODULES:
        parts.append(stem.encode())
        olean = os.path.join(lib_dir, stem + ".olean")
        parts.append(_digest(olean) if os.path.isfile(olean) else b"\0missing")
    with open(proof_path, "rb") as f:
        parts.append(f.read())
    return "proof/" + cas.hash_parts(*parts)


def check_proof_cached(proof_path: str, repo_root: str | None = None,
                       timeout: int = 1200) -> tuple[bool, str, bool]:
    """check_proof, memoised on the exact inputs. Third element is True on a
    cache hit (nothing was run). Both verdicts are cached: a known-failing
    example is just as deterministic as a passing one, and re-deriving it with
    a multi-minute Lean run is what made iterating on the suite painful."""
    import cas
    root = repo_root or _default_root()
    lib_dir = os.path.join(root, "lib")
    lean = find_lean(root)
    if not lean:
        return False, "lean not found", False
    try:
        ensure_library(lean, lib_dir, timeout)
    except Exception as e:
        return False, f"proof library build failed: {e}", False
    try:
        key = proof_verdict_key(proof_path, lib_dir, lean)
    except OSError as e:
        return False, f"proof file unreadable: {e}", False
    stored = cas.lookup(key, VERDICT_EXT)
    if stored:
        with open(stored, "rb") as f:
            body = f.read().decode("utf-8", "replace")
        ok, _, detail = body.partition("\n")
        return ok == "ok", detail.strip("\n"), True
    ok, detail = _run_lean(proof_path, lib_dir, lean, timeout)
    try:
        cas.publish(key, VERDICT_EXT,
                    (("ok\n" if ok else "fail\n") + detail + "\n").encode())
    except OSError:
        pass  # a cache that cannot be written must not fail the check
    return ok, detail, False


def check_proof(proof_path: str, repo_root: str | None = None,
                timeout: int = 1200) -> tuple[bool, str]:
    ok, detail, _ = check_proof_cached(proof_path, repo_root, timeout)
    return ok, detail


def _run_lean(proof_path: str, lib_dir: str, lean: str,
              timeout: int) -> tuple[bool, str]:
    env = os.environ.copy()
    env["LEAN_PATH"] = os.pathsep.join(
        (os.path.dirname(os.path.abspath(proof_path)), lib_dir))
    try:
        result = subprocess.run(
            [lean, os.path.basename(proof_path)],
            capture_output=True, text=True, timeout=timeout, env=env,
            cwd=os.path.dirname(os.path.abspath(proof_path)),
        )
    except subprocess.TimeoutExpired:
        return False, "lean timed out"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "lean failed").strip()
    return True, ""
