import collections
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time

# Dependency order: X86 needs ProofLib, and work.lean re-exports it so the
# generated proof files (which import ProofLib + work + Refine) get the x86-64
# model without naming a fourth module.
# Order is build order: `Contracts` imports `ProofLib` and `Refine`, so it
# must come after them.
LIBRARY_MODULES = ("ProofLib", "X86", "work", "Refine", "Contracts")
VERDICT_EXT = ".leanverdict"
# Where a library module's own hole census is stored, beside the .olean it was
# measured from and under the same key — so a cas HIT on the .olean is a hit on
# its census, and a tree whose .oleans predate the census is the only case that
# has to be measured (see `library_census`).
CENSUS_EXT = ".libcensus"
_OLEAN_DIGESTS: dict = {}
# stem -> (n_sorries, (names...)), filled by ensure_library for this process and
# read by library_census so the common case is a dict lookup, not a cas probe.
_LIB_CENSUS: dict = {}


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


def _olean_key(stem: str, source: str, lean: str, source_digest: str = "") -> str:
    """CAS key for a library .olean: the source bytes, the module name and the
    toolchain. Lean's output for a given (source, version) pair is
    deterministic, so this is a hit on every machine and every rebuild after
    the first — ProofLib.olean alone is 27MB and takes ~90s to produce.

    `source_digest` is the EFFECTIVE digest (`_effective_digest`), not this
    module's own bytes, and that is load-bearing: `work.lean` imports `X86`,
    so an edit to `X86.lean` changes what `work.olean` MEANS while leaving
    `work.lean` byte-identical. Keyed on its own bytes alone, the cas would
    serve the `work.olean` elaborated against the previous X86 — the exact
    "wrong artifact served from cache, silently" failure the self-host
    fingerprint rules exist to prevent, one module down. It defaults to this
    module's own digest so a caller that has not computed the effective one
    gets the old key rather than a key with a hole in it."""
    import cas
    with open(source, "rb") as f:
        return "leanlib/" + cas.hash_parts(
            b"lean-olean-v2", stem.encode(), lean_version(lean).encode(),
            (source_digest or _sha256_file(source)).encode(), f.read())

def _library_is_current(source: str, olean: str, stamp: str,
                        source_digest: str) -> bool:
    """Is this .olean built from exactly this source AND the imports it names?

    Purely content-based, with no mtime in the decision: `touch
    lib/ProofLib.lean` (or a git checkout, or an editor that rewrites mtimes)
    must not cost a 27MB Lean rebuild, and an mtime rule cannot tell "touched"
    from "edited" — which is why a bare mtime check makes the whole formal
    suite mysteriously slow again after anything touches lib/. The stamp
    records the source digest the .olean was built from *and* a digest of the
    .olean itself, so an edit invalidates, a touch does not, and an .olean
    swapped out from under the stamp invalidates too.

    `source_digest` is the EFFECTIVE digest — this module's own bytes AND every
    library module it imports, transitively — and that is the second half of
    the rule. The stamp used to record this module's own bytes alone, so
    editing `X86.lean` left `work.olean` (built from `work.lean`, which
    `import X86`) in place: every later `lean` run then recompiled the stale
    import inside the checker, with no error anywhere and a memory bill an
    order of magnitude over the honest one. See `_effective_digest`."""
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


def _write_stamp(stamp: str, source: str, olean: str,
                 source_digest: str = "") -> None:
    """Record which source a .olean was built from, so a later run is a stat.

    `source_digest` is the EFFECTIVE digest the currency check compares
    against, for the reason `_effective_digest` gives; the default is this
    module's own bytes, which is what a tree with no imports has."""
    tmp = f"{stamp}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(f"{source_digest or _sha256_file(source)} "
                f"{_digest(olean).hex()}\n")
    os.replace(tmp, stamp)


def _module_imports(source: str) -> set:
    """The `LIBRARY_MODULES` names this library source's `import` lines name.

    Read from the source rather than hard-coded, because the import graph is
    the thing that has to stay right and a table beside it is a second copy of
    it to forget. `import Lean` and anything outside `LIBRARY_MODULES` are not
    this mechanism's business — those are pinned by the toolchain half of the
    key instead."""
    names = set()
    try:
        with open(source, "r", errors="replace") as f:
            for line in f:
                if not line.startswith("import "):
                    continue
                name = line[len("import "):].strip().split()
                if name:
                    names.add(name[0])
    except OSError:
        return names
    return names & set(LIBRARY_MODULES)


def _effective_digest(stem: str, lib_dir: str, _seen=None) -> str:
    """A digest over `stem`'s own source AND every library module it imports.

    **The staleness this closes.** A Lean `.olean` embeds its imports'
    definitions, so `work.olean` — built from `work.lean`, which is
    `import ProofLib` + `import X86` and about 700KB of code — MEANS something
    different after an edit to `X86.lean`. The currency check compared only the
    module's own bytes, so such an edit left `work.olean` in place and every
    later `lean` run silently recompiled the stale import inside the checker:
    measured, `python3 test_formal.py` went from 1.2 GB across 31 processes to a
    32 GB kill, with no error anywhere, because nothing was wrong with any
    single file — the artifact the checker read was simply not the artifact its
    source now describes. And the CAS key had the same hole, which is worse: a
    hit would have served that stale `.olean` to every machine.

    Transitive, and cycle-safe (`_seen`): `Contracts` imports `ProofLib` and
    `Refine`, `Refine` imports `ProofLib`, and a future cycle must not hang
    the build. One hash per module per run, so the whole library is a handful
    of 27MB reads rather than one per dependent."""
    import hashlib
    seen = set() if _seen is None else _seen
    if stem in seen:
        return ""
    seen.add(stem)
    path = os.path.join(lib_dir, stem + ".lean")
    if not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    deps = sorted(_module_imports(path))
    for dep in deps:
        h.update(dep.encode())
        h.update(_effective_digest(dep, lib_dir, seen).encode())
    return h.hexdigest()


def _acquire_build_lock(olean: str, timeout: float) -> int:
    """Exclusive, crash-safe lock for the build of ONE .olean.

    `flock`, not an O_EXCL lock file: the kernel drops the lock when the
    holder dies, so a process killed mid-build (a cancelled suite run, an
    OOM kill, Ctrl-C) cannot leave a lock file behind that wedges every
    later run forever. An O_EXCL marker would need a staleness heuristic to
    recover from exactly that, and a wrong staleness heuristic either hangs
    forever or lets two builds through.

    Returns the open fd; the caller releases with `_release_build_lock`.
    """
    import fcntl
    fd = os.open(olean + ".buildlock", os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() > deadline:
                os.close(fd)
                raise RuntimeError(
                    f"timed out after {timeout:.0f}s waiting for another "
                    f"process to build {os.path.basename(olean)}")
            time.sleep(0.25)


def _release_build_lock(fd: int) -> None:
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ── Vacuity: declarations whose statement asserts nothing ───────────────────
#
# The census of `sorry`s counts HOLES, and a hole is not the only way a proof
# can carry no information. `extern_<sym>_step : True := by trivial` — the step
# theorem at every extern call site, which is what the arm64 and x86-64
# generators emit for a `mojo_*` or libc call — is admitted by a complete proof
# and proves nothing whatsoever: `True` is inhabited, so the declaration is
# true whatever the machine model says about the call. It reports ZERO sorries
# and is exactly as uninformative as a `sorry`, and that is why a proof with a
# thousand of them and a proof with none of them are indistinguishable in the
# output.
#
# Why this is a TEXT scan and the sorry census is not — the asymmetry is the
# whole reason both exist, so it is worth stating exactly. Whether a `sorry`
# was ADMITTED depends on which tactic branch ran, which is elaboration; a grep
# counts the `all_goals first | … | sorry` alternatives that lost, so it is a
# count of hypothetical holes that never goes down (see `_run_lean`). Whether a
# declaration is VACUOUS is a property of its type ascription, and a type is a
# closed term: `theorem foo : True` is vacuous, is vacuous on every Lean
# version, and cannot be made non-vacuous by a tactic. So the same scan that is
# unsound for holes is the soundest possible instrument for this.
#
# Two shapes, and only two, because a count of everything that looks weak would
# be its own kind of untrustworthy number:
#
#   * the statement is literally `True` (parenthesised or not);
#   * the statement is `∀ …, … → True` — an implication to `True` under any
#     binder, which is inhabited for every argument, so a theorem of that shape
#     says nothing about the arguments either. `DylibExport.Semantics` in
#     lib/ProofLib.lean is this one, and it is what the dylib proofs'
#     `<export>_semantics` theorems are stated with.
#
# Both are reported with the declaration's NAME, because "3 vacuous" does not
# tell a reader where to look and "3 vacuous: extern_mojo_print_step,
# extern_malloc_step, …" does.
_VACUOUS_TRUE = "states `True`"
_VACUOUS_GOAL = "states `∀ …, … → True`"

# `(theorem|lemma|def) NAME` at the start of a line. The name is Lean's own
# component name, so dots and primes are part of it, and the leading `private`
# / `@[simp]` attributes are simply not matched — a declaration behind an
# attribute is still a declaration.
_DECL_RE = re.compile(r"^\s*(?:private\s+|protected\s+|noncomputable\s+)*"
                      r"(theorem|lemma|def)\s+([A-Za-z_][\w'.]*)")
# Lean 4 spells the dependent arrow `→` and `forall` as `∀`; ASCII `->` and
# `forall` are accepted so the scanner does not depend on a spelling choice.
# `\b` is wrong after `∀`: `∀` is not a word character in python's `re`, so
# `\b` there asks for a boundary between two non-word characters and never
# matches. The lookahead is the actual intent — a binder list follows.
_FORALL_RE = re.compile(r"^(?:∀|forall)(?=[\s(]).*(?:→|->)\s*True$", re.S)
_TRUE_RE = re.compile(r"^True$")


_OPEN = "([{"
_CLOSE = ")]}"


def _depth_delta(line: str) -> int:
    return sum(line.count(c) for c in _OPEN) - sum(line.count(c) for c in _CLOSE)


def _split_at_assignment(text: str):
    """(before, after) at the first `:=` at bracket depth 0, or (None, None).

    Lean cannot spell `:=` inside a type ascription, so bracket depth is the
    whole test. `None` means the header is not closed by anything on the text
    handed in — the caller's cue to read more lines or to give up, never to
    guess.
    """
    depth = 0
    for i, ch in enumerate(text):
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        elif ch == ":" and i + 1 < len(text) and text[i + 1] == "=" and depth == 0:
            return text[:i], text[i + 2:]
    return None, None


def _after_binders(text: str) -> str:
    """`text` with its leading binder groups removed, whitespace collapsed.

    A declaration's binders are `(x : Nat)`, `{α : Type}` and `[ι : Type]` groups
    in an unbroken run after the name, and everything after them is the return
    type (and, after the `:=`, the body). Consuming exactly that run is what
    keeps the parentheses in a RETURN type out of it: `theorem foo (x : Nat) :
    (P ∧ Q)` must be read as `P ∧ Q`, and a "last top-level `)`" rule reads it
    as empty instead.
    """
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1            # a binder RUN is separated by spaces or a newline
        if i >= n or text[i] not in _OPEN:
            break
        depth = 0
        while i < n:
            if text[i] in _OPEN:
                depth += 1
            elif text[i] in _CLOSE:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
    return " ".join(text[i:].split())


def _unannotated(rest: str) -> str:
    """`rest` with the leading `:` that introduces the return type removed."""
    rest = rest.strip()
    return rest[1:].strip() if rest.startswith(":") else rest


def vacuous_declarations(text: str, body_lines: int = 8) -> list:
    """[(name, shape, line)] for declarations that assert nothing.

    `shape` is `_VACUOUS_TRUE` or `_VACUOUS_GOAL`, and is carried rather than
    counted because the two are different claims about a file: a `True`
    statement is a placeholder that was never filled in, while a `∀ …, … → True`
    is a TYPE somebody chose — a definition whose every inhabitant carries no
    information, which no proof of that definition can repair.

    A `def` is judged on its BODY and only when its declared return type is
    `Prop` (`DylibExport.Semantics … : Prop := ∀ observable, … → True` is the
    shape in this project). A `def` with no declared return type is skipped
    rather than inferred: Lean's inference is elaboration, and an inferred type
    is exactly the kind of judgement a text scanner has no business making.

    Every miss here is a miss, never a wrong answer, and that is the direction
    that matters — a scanner that reports a finding nobody can act on is the
    same defect as one that misses them.
    """
    lines = text.splitlines()
    out, head, head_line, kind, name, depth = [], None, 0, None, None, 0
    for lineno, raw in enumerate(lines, 1):
        if head is None:
            m = _DECL_RE.match(raw)
            if not m:
                continue
            kind, name, head, head_line, depth = m.group(1), m.group(2), [raw], lineno, 0
        else:
            head.append(raw)
        depth += _depth_delta(raw)
        before, after = _split_at_assignment("\n".join(head))
        if before is None:
            # The header has not closed. Read more — a statement is at most a
            # few lines and a BODY can be thousands, so this never scans one —
            # but do not read forever, and give up by starting afresh.
            if lineno - head_line > 12:
                head = None
            continue
        head = None
        # `before` still starts with `def NAME` / `theorem NAME`; the binder
        # skipper has to begin after the name or it stops on the first
        # character and returns the whole header as the statement.
        typed = _DECL_RE.sub("", before, count=1)
        if kind == "def":
            if _unannotated(_after_binders(typed)) != "Prop":
                continue                    # returns a value, not a proposition
            # A definition's proposition is its BODY, which continues onto the
            # following lines. It is bounded three ways — a blank line, a line
            # that starts another declaration, and the line cap — because
            # running on into the next declaration would leave `True` in the
            # middle of the text and make the whole match fail, which is how a
            # real finding goes missing to a sloppy terminator.
            stmt = " ".join(after.split())
            for extra in lines[lineno:lineno + body_lines]:
                if not extra.strip() or _DECL_RE.match(extra):
                    break
                stmt += " " + " ".join(extra.split())
        else:
            stmt = _unannotated(_after_binders(typed))
        # `after` is whatever followed the `:=` ON ITS OWN LINE, which is often
        # nothing at all with the body starting on the next line; the trim is
        # what keeps the whitespace a `" ".join` leaves behind from making
        # `^`-anchored patterns miss a real finding.
        stmt = stmt.strip()
        stmt = stmt.strip("()").strip() if stmt.startswith("(") else stmt
        if _TRUE_RE.match(stmt):
            out.append((name, _VACUOUS_TRUE, head_line))
        elif _FORALL_RE.match(stmt):
            out.append((name, _VACUOUS_GOAL, head_line))
    return out


# Lean's own hole report, which arrives on **STDOUT** (measured; see `_run_lean`).
# Two shapes, because the toolchain's wording is not something to depend on: the
# pinned 4.32.2 emits
#
#   lib/ProofLib.lean:4624:8: warning: declaration uses `sorry`
#
# — a LOCATION and no name — while some versions name the declaration. Both are
# matched, and a name that is absent is recovered from the line, which is
# strictly better than the location because it is what a reader has to open.
#
# This is also the measurement that was wrong the first time. Asking Lean to
# elaborate a module whose `.olean` was already current prints NOTHING — the
# artifact is a recovery cache, and a cached elaboration does not look at the
# holes — so a census taken that way reports a library with two `sorry`s in it
# as clean. That is why the real measurement copies the sources somewhere with
# no `.olean` beside them (see `library_census`), and why the record carries a
# tag saying which measurement produced it.
_SORRY_LOC_RE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*warning:\s*"
    r"declaration uses\s+[`'\u2018]?sorry", re.M)
_SORRY_NAMED_RE = re.compile(r"declaration ['\u2018]([^'\u2019]+)['\u2019] uses")
_DECL_NAME_RE = re.compile(r"^\s*(?:private\s+|protected\s+|noncomputable\s+)*"
                           r"(?:theorem|lemma|def)\s+([A-Za-z_][\w'.]*)")


def _declaration_at(lines, lineno: int) -> str:
    """The declaration a warning at `lineno` belongs to, or `line N`.

    Lean reports a hole's position inside the declaration, so the name is the
    nearest `theorem`/`lemma`/`def` header at or above that line. Falling back to
    the LINE is deliberate: an unnamed entry is still a location a reader can
    act on, whereas a wrong name is worse than none.

    A line outside the source is the case that makes the fallback necessary
    rather than cosmetic. Clamping the index instead — which is what the first
    version did — silently attributes every out-of-range hole to the LAST
    declaration in the file, and two holes then de-duplicate to one and the
    count comes back short. A count that is short because a name collided is
    indistinguishable, in the output, from a count that is right.
    """
    if lineno < 1 or lineno > len(lines):
        return f"line {lineno}"
    for i in range(lineno - 1, -1, -1):
        m = _DECL_NAME_RE.match(lines[i])
        if m:
            return m.group(1)
    return f"line {lineno}"


def _census_from_output(text: str, source_lines=None) -> tuple:
    """(n, (names...)) from one `lean` run's output, de-duplicated in order.

    `source_lines` is the module's lines, and it is what turns Lean's anonymous
    "declaration uses sorry" into a name — see `_declaration_at`. Without it
    the names are the locations, which is still actionable and never wrong.
    """
    text = text or ""
    hits = list(_SORRY_LOC_RE.finditer(text))
    named = _SORRY_NAMED_RE.findall(text)
    names, seen = [], set()
    for i, m in enumerate(hits):
        if i < len(named):
            name = named[i]
        elif source_lines is not None:
            name = _declaration_at(source_lines, int(m.group("line")))
        else:
            name = f"{m.group('file')}:{m.group('line')}"
        if name not in seen:
            seen.add(name)
            names.append(name)
    if not hits and named:
        # A wording that names the declaration without the `warning:` prefix the
        # pinned toolchain uses. Counted, because a hole is a hole.
        for name in named:
            if name not in seen:
                seen.add(name)
                names.append(name)
    return len(names), tuple(names)


# The census record is VERSIONED inside its own value, not only in its key.
# That is not belt-and-braces: the first version of this measurement asked Lean
# to elaborate a module whose `.olean` was already current, Lean served it from
# that cache and printed nothing, and the result was published as "0 holes" for
# every module in `lib/`. A wrong number in a content-addressed store is
# permanent — every later reader gets it — and it is exactly the number this
# exists to make trustworthy, so the record has to be able to say which
# measurement produced it. A body without this tag is a MISS, which is the only
# safe reading of a value written by a version that measured nothing.
_CENSUS_TAG = "lean-lib-census-v3"


def _census_lookup(key: str):
    """The census recorded beside a library .olean, or None if never measured."""
    import cas
    hit = cas.lookup(key, CENSUS_EXT)
    if not hit:
        return None
    try:
        with open(hit, "rb") as f:
            body = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    tag, _, rest = body.partition("\n")
    if tag != _CENSUS_TAG:
        return None
    head, _, names = rest.partition("\n")
    try:
        count = int(head)
    except ValueError:
        return None
    return count, tuple(n for n in names.split("\t") if n)


def _census_publish(key: str, census: tuple) -> None:
    import cas
    try:
        cas.publish(key, CENSUS_EXT,
                    (_CENSUS_TAG + "\n" + str(census[0]) + "\n"
                     + "\t".join(census[1])).encode())
    except OSError:
        pass          # a census that cannot be stored must not fail a build


def library_census(lean: str, lib_dir: str, timeout: int = 1200,
                   measure: bool = True) -> dict:
    """stem -> (n_sorries, (names...)) for every library module MEASURED.

    The hole census of a generated proof is not the whole story, and the gap
    was silent: a proof file is elaborated by `lean`, and Lean warns about
    every `sorry` it admits IN THAT FILE — but `lib/ProofLib.lean` and
    `lib/Refine.lean` are consumed as pre-built `.olean`s, so a `sorry` in
    them produces no warning at all when the proof imports them. That is not
    a small hole: `Refine.dylib_export_contract_stub` is a bare `sorry` and is
    what every `dylib --formal` proof's contract theorem rests on, and
    `test_formal_dylib.py`'s "the generated proof contains no sorry" check
    greps the GENERATED file, so it is green.

    So the census has to reach the library too, and the only sound way to count
    a hole is to elaborate the module and read what Lean says.

    **And here is the part that was hiding them, measured rather than guessed.
    Elaborating a module whose `.olean` is already present and current prints
    NOTHING**: Lean uses the existing artifact as a recovery cache and skips
    elaboration entirely, so the run that "measures" `lib/ProofLib.lean` on a
    tree that has been built once reports zero holes for a file with two. That
    was the mechanism, and it is the same mechanism that made the holes
    invisible to every consumer: the `.olean` is a cache, and a cached
    elaboration is precisely the one that does not look at the holes. The first
    version of this function got it wrong in exactly that way and reported all
    four library modules clean.

    So the measurement is made where no cache can hide: the sources are copied
    into a private temp directory, which therefore has no `.olean` beside them,
    and elaborated there with `LEAN_PATH` pointing at the copy FIRST and the
    real `lib/` second — so a module's own dependencies come from the copy as
    they are produced, and a module that is only in `lib/` still resolves.
    Nothing in `lib/` is written, and nothing here is published as a `.olean`,
    because an artifact built from a copied source is not the artifact
    `ensure_library` would produce and must not be served as one.

    The cost is one full elaboration per module — the same ~90s that building
    the `.olean` costs, paid once, then cached in the CAS under the `.olean`'s
    own key so a cas hit on the artifact is a hit on its census. The per-`.olean`
    flock is taken, and the CAS re-checked inside it, so concurrent callers
    still produce one measurement between them.

    **A module that cannot be measured is ABSENT from the returned dict, never
    present with a zero.** Those are different facts and conflating them is how
    "the library has no holes" gets reported by a tool that never looked. The
    report says which of the two it is printing.
    """
    out, missing = {}, []
    for stem in LIBRARY_MODULES:
        source = os.path.join(lib_dir, stem + ".lean")
        if not os.path.isfile(source):
            continue
        if stem in _LIB_CENSUS:
            out[stem] = _LIB_CENSUS[stem]
            continue
        try:
            key = _olean_key(stem, source, lean, _effective_digest(stem,
                                                                   lib_dir))
        except Exception:
            # An unreadable source or a broken store means UNMEASURED, which
            # the caller reports as such. It must not be an exception: this is
            # a report about a proof, not a gate on one.
            missing.append(stem)
            continue
        got = _census_lookup(key)
        if got is None:
            missing.append(stem)
        else:
            out[stem] = got
    if not missing or not measure:
        return out
    import tempfile
    olean = os.path.join(lib_dir, missing[0] + ".olean")
    fd = _acquire_build_lock(olean, timeout)
    try:
        still = {}
        for stem in missing:
            source = os.path.join(lib_dir, stem + ".lean")
            try:
                got = _census_lookup(_olean_key(
                    stem, source, lean, _effective_digest(stem, lib_dir)))
            except Exception:
                got = None
            if got is not None:
                still[stem] = got          # a peer may have measured it
        out.update(still)
        todo = [s for s in missing if s not in still]
        if not todo:
            return out
        with tempfile.TemporaryDirectory(prefix="lean_census_") as td:
            for stem in LIBRARY_MODULES:
                src = os.path.join(lib_dir, stem + ".lean")
                if os.path.isfile(src):
                    shutil.copyfile(src, os.path.join(td, stem + ".lean"))
            env = os.environ.copy()
            # The COPY FIRST, so a dependency that is itself being measured is
            # found as the `.olean` this run just produced rather than as the
            # cached one it was supposed to be standing in for.
            #
            # ABSOLUTE, and that is not tidiness: `LEAN_PATH` is resolved
            # against the elaborating process's own cwd, which is the temp
            # directory, so a relative `lib` handed in by a caller points at
            # `<tempdir>/lib` and every import of another library module fails.
            # The first version of this took `lib_dir` as given, measured
            # ProofLib from the CAS, then reported X86/work/Refine as
            # UNMEASURED — a third silent way for the census to shrink to
            # whatever happened to be cached.
            env["LEAN_PATH"] = os.pathsep.join((td, os.path.abspath(lib_dir)))
            for stem in todo:
                src = os.path.join(td, stem + ".lean")
                if not os.path.isfile(src):
                    continue
                got = _measure_one(lean, src, td, env, timeout,
                                   _read_lines(src))
                if got is None:
                    continue               # unmeasured, and said as such
                _LIB_CENSUS[stem] = got
                out[stem] = got
                try:
                    _census_publish(_olean_key(
                        stem, os.path.join(lib_dir, stem + ".lean"), lean,
                        _effective_digest(stem, lib_dir)), got)
                except Exception:
                    pass
    finally:
        _release_build_lock(fd)
    return out


def _measure_one(lean: str, source: str, workdir: str, env: dict,
                 timeout: int, source_lines=None):
    """The hole census of one module, or None if it could not be measured.

    None and `(0, ())` are kept apart all the way to the report. Lean exits
    non-zero on a module with an ERROR, and a module with errors also has no
    trustworthy census, so a non-zero exit is unmeasured rather than a count —
    the only thing a failed elaboration can honestly report about holes is
    nothing.
    """
    # The `.olean` is LEFT in place. It is the artifact a later module in the
    # same run imports, and deleting it after each measurement (the first
    # version did) means every module after the first is elaborated against the
    # cached library instead of the copy — which is a weaker claim than "this
    # measurement stands on nothing but the sources", and silently so. The
    # caller's TemporaryDirectory removes the whole set.
    out = os.path.join(workdir, os.path.basename(source)[:-5] + ".olean")
    try:
        res = subprocess.run([lean, "-o", out, source], capture_output=True,
                             text=True, timeout=timeout, env=env, cwd=workdir)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return _census_from_output((res.stderr or "") + (res.stdout or ""),
                               source_lines)


def _read_lines(path: str):
    """A file's lines, or None if it cannot be read.

    None is not an empty list on purpose: it means "cannot resolve a hole's
    line to a declaration", which downgrades the census to locations. An empty
    list would make every line resolve to `line 1`.
    """
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return None


def ensure_library(lean: str, lib_dir: str, timeout: int = 1200) -> None:
    """Make every library .olean current, building at most ONE of each.

    The check-build step is a check-then-act on a shared filesystem, and the
    proof suite runs ~16 of these concurrently, so without the lock below
    every one of them misses the stamp at the same instant, misses the cas
    on a cold store, and starts its own `lean -o <same path>` — N
    simultaneous ~80s builds of a 27MB artifact, all writing the SAME output
    file. Measured on a cold cas with 3 concurrent callers: 3 builds, peak 3
    concurrent `lean`, all finishing at ~81s. That is a correctness hazard
    as much as a waste — concurrent unsynchronised writes to one output path
    can interleave into a truncated or mixed .olean, and every later
    typecheck then reads it.

    Two things fix it, and both are here: the build happens under an
    exclusive lock with the currency check REPEATED inside it (a peer may
    have built it while we queued), and the build writes to a private temp
    path that is `os.replace`d into place, so even a lock that did not hold
    could not leave a partial file where a valid one belongs.

    This makes concurrent callers cheap but does not make them FREE: the
    lock is per-.olean and serialised, so 16 processes still queue. The
    suite therefore also registers the library build as its own test
    (`prooflib` in tools/suite.py) and every proof-checking test depends on
    it, so the one build happens once, alone, before the fan-out starts and
    the other 15 find the stamp valid and return immediately.
    """
    import cas
    env = os.environ.copy()
    env["LEAN_PATH"] = lib_dir
    for stem in LIBRARY_MODULES:
        source = os.path.join(lib_dir, stem + ".lean")
        olean = os.path.join(lib_dir, stem + ".olean")
        stamp = olean + ".srcsha256"
        if not os.path.isfile(source):
            continue
        digest = _effective_digest(stem, lib_dir)
        if _library_is_current(source, olean, stamp, digest):
            continue
        # Pre-stamp trees (fresh clone, or an olean built by the Makefile):
        # accept it if it is newer than the source, then record its digests so
        # later touches are free. Stamp-only, so no lock needed — and
        # _write_stamp is itself atomic.
        if (not os.path.isfile(stamp) and os.path.isfile(olean)
                and os.path.getmtime(olean) >= os.path.getmtime(source)):
            _write_stamp(stamp, source, olean, digest)
            continue
        key = _olean_key(stem, source, lean, digest)
        fd = _acquire_build_lock(olean, timeout)
        try:
            # DOUBLE-CHECK under the lock. Everyone else in the fan-out is
            # doing the same thing, and the whole point of the lock is that
            # exactly one of them proceeds past here.
            if _library_is_current(source, olean, stamp, digest):
                continue
            hit = cas.lookup(key, ".olean")
            if hit:
                shutil.copyfile(hit, olean)
            else:
                tmp = f"{olean}.tmp.{os.getpid()}"
                try:
                    result = subprocess.run(
                        [lean, "-o", tmp, source],
                        capture_output=True, text=True, timeout=timeout,
                        env=env,
                    )
                    if result.returncode != 0:
                        raise RuntimeError((result.stderr or result.stdout
                                            or "lean failed").strip())
                    os.replace(tmp, olean)
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                with open(olean, "rb") as f:
                    cas.publish(key, ".olean", f.read())
                # The run that just elaborated this module is the only place
                # Lean ever reports the holes IN it — a later proof consumes
                # the .olean and is told nothing. Captured here it costs
                # nothing, because the elaboration was going to happen anyway;
                # `library_census` is the reader, and a pre-built .olean has no
                # such moment, which is the one case it measures for itself.
                got = _census_from_output(
                    (result.stderr or "") + (result.stdout or ""),
                    _read_lines(source))
                _LIB_CENSUS[stem] = got
                _census_publish(key, got)
            _write_stamp(stamp, source, olean, digest)
        finally:
            _release_build_lock(fd)


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


# v3 added the library census (`lib_sorries`, `lib_detail`) to the stored body,
# so the key changes rather than a v2 entry being read as "the library has no
# holes" — which is exactly the claim v2 could not make and did not check.
_VERDICT_VERSION = b"formal-proof-verdict-v3"
# -1 in the `lib_sorries` field, distinct from 0: "not measured" and "measured,
# no holes" are different facts and the report prints them differently.
_LIB_UNMEASURED = -1


def proof_verdict_key(proof_path: str, lib_dir: str, lean: str) -> str:
    import cas
    parts = [_VERDICT_VERSION, lean_version(lean).encode()]
    for stem in LIBRARY_MODULES:
        parts.append(stem.encode())
        olean = os.path.join(lib_dir, stem + ".olean")
        parts.append(_digest(olean) if os.path.isfile(olean) else b"\0missing")
    with open(proof_path, "rb") as f:
        parts.append(f.read())
    return "proof/" + cas.hash_parts(*parts)


# What a proof check actually established. `ok` is the verdict every existing
# caller reads and the only one that gates anything; the rest is the census,
# and it exists because `ok` on its own is a claim this project has made and
# cannot support. A proof that admits a thousand `sorry`s passes; so does one
# whose only step theorems are `True := by trivial`; so does one that rests on a
# `sorry` in a `.olean` Lean never re-reports. `lines` is the human-readable
# form, and `check_proof_cached` writes it to stderr on every call, so the
# figure cannot be computed and then dropped on the floor again — which is
# precisely what it was for a year.
Census = collections.namedtuple(
    "Census", "ok detail cached n_sorries lib_sorries lib_detail lines")


def proof_census(proof_path: str, repo_root: str | None = None,
                 timeout: int = 1200) -> Census:
    """`(ok, detail, cached, n_sorries, lib_sorries, lib_detail, lines)`.

    `check_proof_cached` is this with the census rendered; it exists separately
    so a caller that wants to REPORT the census (fire.py's `Proof:` line, this
    repository's own test) does not have to re-derive it, and so the four
    elements the older signature returns keep meaning exactly what they meant.

    **Report, not gate.** Nothing in here changes `ok`, and nothing here raises:
    a census that cannot be measured is printed as unmeasured, never as zero.
    That is deliberate and it is the reason this can land in the middle of four
    other agents' work without changing a verdict anyone is relying on.
    """
    root = repo_root or _default_root()
    lib_dir = os.path.join(root, "lib")
    lean = find_lean(root)

    def census(ok, detail, cached, n_sorries, lib):
        lines = _census_lines(proof_path, lib_dir, n_sorries, lib)
        lib_sorries, lib_detail = _lib_totals(lib)
        return Census(ok, detail, cached, n_sorries, lib_sorries, lib_detail,
                      lines)

    if not lean:
        return census(False, "lean not found", False, 0, {})
    try:
        ensure_library(lean, lib_dir, timeout)
    except Exception as e:
        return census(False, f"proof library build failed: {e}", False, 0, {})
    try:
        key = proof_verdict_key(proof_path, lib_dir, lean)
    except OSError as e:
        return census(False, f"proof file unreadable: {e}", False, 0, {})
    # Measured AFTER the library is current and BEFORE the verdict is read, so
    # the stored body and this run's figures cannot disagree. A failure here is
    # swallowed on purpose: the census is a report, and a report that cannot be
    # produced must not turn a passing proof into a failing one.
    try:
        lib = library_census(lean, lib_dir, timeout)
    except Exception:
        lib = {}
    stored = cas_lookup_verdict(key)
    if stored is not None:
        ok, n_sorries, lib_sorries, lib_detail, detail = stored
        lib = _lib_from_record(lib, lib_sorries, lib_detail)
        return census(ok, detail, True, n_sorries, lib)
    ok, detail, n_sorries = _run_lean(proof_path, lib_dir, lean, timeout)
    lib_sorries, lib_detail = _lib_totals(lib)
    _publish_verdict(key, ok, n_sorries, lib_sorries, lib_detail, detail)
    return census(ok, detail, False, n_sorries, lib)


def cas_lookup_verdict(key: str):
    """`(ok, n_sorries, lib_sorries, lib_detail, detail)` from the CAS, or None.

    Four fixed header lines then the detail, which is last precisely because it
    is the only field that can be multi-line. A v1/v2 entry cannot be read here
    (it has no `lib_sorries` line), which is the intended outcome: its key
    differs anyway, and a body this cannot parse is treated as a miss rather
    than as a count of zero holes.
    """
    import cas
    hit = cas.lookup(key, VERDICT_EXT)
    if not hit:
        return None
    try:
        with open(hit, "rb") as f:
            body = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = body.split("\n")
    if len(lines) < 4:
        return None
    try:
        n_sorries = int(lines[1] or 0)
        lib_sorries = int(lines[2])
    except ValueError:
        return None
    return (lines[0] == "ok", n_sorries, lib_sorries, lines[3],
            "\n".join(lines[4:]).strip("\n"))


def _publish_verdict(key, ok, n_sorries, lib_sorries, lib_detail, detail):
    import cas
    try:
        cas.publish(key, VERDICT_EXT,
                    (("ok" if ok else "fail") + "\n" + str(n_sorries) + "\n"
                     + str(lib_sorries) + "\n" + lib_detail + "\n"
                     + detail + "\n").encode())
    except OSError:
        pass          # a cache that cannot be written must not fail the check


def _lib_totals(lib: dict) -> tuple:
    """(n_sorries, detail) over the MEASURED library modules, or (-1, "") when
    none was. The detail is `stem:name,name; stem:name`, and it is carried
    because "3" does not say which three and a reader who is deciding whether
    to trust a proof needs to open one."""
    measured = [(stem, got) for stem, got in sorted(lib.items())]
    if not measured:
        return _LIB_UNMEASURED, ""
    total = sum(got[0] for _stem, got in measured)
    # Newline between modules, TAB between names, and nothing else. The earlier
    # `"; "` / `","` spelling was a separator a Lean identifier could contain
    # (`Foo.bar, baz` is a legal name), which makes the record's own encoding
    # ambiguous for exactly the modules whose census matters most — the dylib
    # proofs' per-export theorems. TAB and NEWLINE are not in an identifier.
    detail = "\n".join(stem + "\t" + "\t".join(got[1])
                       for stem, got in measured)
    return total, detail


def _lib_from_record(lib: dict, lib_sorries: int, lib_detail: str) -> dict:
    """The measured library as `library_census` would return it, from a record.

    A verdict read from the cache carries the library's census with it, so the
    cached path needs no second measurement. The distinction that matters is
    preserved exactly: `lib_sorries == _LIB_UNMEASURED` yields `{}` — absent,
    i.e. UNMEASURED — and never a set of modules with zero holes.
    """
    if lib_sorries == _LIB_UNMEASURED:
        return {}
    out = {}
    for entry in lib_detail.split("\n"):
        stem, _, names = entry.partition("\t")
        if stem:
            named = tuple(n for n in names.split("\t") if n)
            out[stem] = (len(named), named)
    return out


def _census_lines(proof_path, lib_dir, n_sorries, lib: dict) -> list:
    """The report, as lines. Empty when there is nothing to report.

    Silence is the clean case and is the point: a proof with no admitted holes,
    no vacuous declarations and a measured clean library produces NO output, so
    a line in the log is always a fact somebody has to look at. A proof with a
    hole and a proof with a vacuous theorem produce DIFFERENT lines, which is
    the whole of what this instrument is for — they used to be the same `PASS`
    with the same empty record beside it.

    `n_sorries` is `None` when the generated file's holes were not measured —
    the read-only path, which cannot know them without elaborating. It is NOT
    then reported as zero: the vacuous count and the library's census are both
    still reported, because neither needs elaboration, and the omission of the
    one figure is visible as the absence of the clause naming it.
    """
    try:
        with open(proof_path, "r", errors="replace") as f:
            vacuous = vacuous_declarations(f.read())
    except OSError:
        vacuous = []
    lib_vacuous = []
    for stem in LIBRARY_MODULES:
        path = os.path.join(lib_dir, stem + ".lean")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", errors="replace") as f:
                for name, shape, line in vacuous_declarations(f.read()):
                    lib_vacuous.append((f"{stem}.lean", name, shape, line))
        except OSError:
            continue
    lines = []
    if n_sorries or vacuous or n_sorries is None:
        holes = (f"{n_sorries} declaration(s) admitted a `sorry`, " if n_sorries
                 is not None else "hole census not measured, ")
        lines.append(
            f"proof census: {os.path.basename(proof_path)} — "
            + holes
            + f"{len(vacuous)} vacuous (admitted by a complete proof and "
              f"asserting nothing)")
        for name, shape, line in vacuous:
            lines.append(f"  vacuous, {shape}: {name} (line {line})")
    total, detail = _lib_totals(lib)
    if total == _LIB_UNMEASURED:
        # Unconditional, and this is the point of the whole library half of the
        # census. A proof with no local holes and an unmeasured library is a
        # proof resting on holes nobody has counted, and reporting nothing is
        # the one thing this instrument must never do: silence is the clean
        # case, and "clean" is a claim.
        lines.append("  library: hole census NOT MEASURED (no lean, or no "
                     "recorded measurement of the library) — this is NOT a "
                     "report of zero, and a proof with no local `sorry` is "
                     "still resting on whatever the library admits")
    elif total:
        # One line per module. A single line carrying all four would be a
        # 200-character wrap in a terminal and a mismatch of prefix in a log,
        # and the per-module split is the readable form anyway: "Refine
        # dylib_export_contract_stub" is the whole finding.
        lines.append(f"  library: {total} declaration(s) in {len(lib)} "
                     f"module(s) admitted a `sorry`:")
        for entry in detail.split("\n"):
            stem, _, names = entry.partition("\t")
            named = [n for n in names.split("\t") if n]
            lines.append(f"    {stem}: " + (", ".join(named) if named
                                            else "none (measured, clean)"))
    for where, name, shape, line in lib_vacuous:
        lines.append(f"  library vacuous, {shape}: {name} ({where}:{line})")
    return lines


def census_report(proof_path: str, repo_root: str | None = None) -> list:
    """The census of `proof_path` and of the library it rests on, as lines.

    No Lean run: the generated file's holes need elaboration, so they are NOT
    read here and the line that reports them is omitted rather than guessed —
    `check_proof_cached` is what supplies them, and a caller that wants the
    whole picture should call `proof_census` and use its `lines`. What this
    DOES need no elaboration, and is what a read-side display wants, is the two
    halves that were invisible before: the vacuous declarations in the
    generated file and in `lib/`, and the library's hole census as last
    measured.

    The split is deliberate. There is exactly one place in this module that can
    see everything (`proof_census`, which is also where the verdict is decided)
    and this is a second, cheaper, deliberately partial one — a read-side
    display that had to run Lean to print a figure would be a read-side display
    nobody runs.
    """
    root = repo_root or _default_root()
    lib_dir = os.path.join(root, "lib")
    lean = find_lean(root)
    lib = {}
    if lean:
        try:
            lib = library_census(lean, lib_dir, measure=False)
        except Exception:
            lib = {}
    if not os.path.isfile(proof_path):
        return [f"proof census: {proof_path} does not exist"]
    # `None`, not 0: the generated file's holes need elaboration and this path
    # does not elaborate. Reporting 0 here would be the exact conflation the
    # library half of this instrument exists to prevent, one level up.
    return _census_lines(proof_path, lib_dir, None, lib)


def _emit_census(lines: list) -> None:
    """Write the census to stderr, where a diagnostic belongs.

    stderr rather than stdout on purpose: `fire.py` owns stdout and prints
    `Proof: <path>` there, and this has to appear without a one-line change in
    a file four other agents are working in. It is also the channel every test
    harness in this repository already captures, so the figure reaches a human
    reading a failure without anyone wiring anything up.

    `FORMAL_CENSUS=off` silences it, and `always` prints it even when clean —
    for a run whose purpose is to state the figure rather than to be alarmed by
    it. The default is "print when there is something to say", which is what
    keeps the common case quiet and a line meaningful.
    """
    mode = (os.environ.get("FORMAL_CENSUS") or "").strip().lower()
    if mode == "off":
        return
    if not lines and mode != "always":
        return
    for line in lines or ["proof census: no admitted `sorry`, no vacuous "
                          "declaration, library measured clean"]:
        print(f"  [{line}]", file=sys.stderr)


def check_proof_cached(proof_path: str, repo_root: str | None = None,
                       timeout: int = 1200) -> tuple[bool, str, bool, int]:
    """check_proof, memoised on the exact inputs. Third element is True on a
    cache hit (nothing was run); fourth is the number of declarations that
    admitted a `sorry` (see `_run_lean`). Both verdicts are cached: a
    known-failing example is just as deterministic as a passing one, and
    re-deriving it with a multi-minute Lean run is what made iterating on the
    suite painful.

    Those four elements are the whole contract and they are unchanged. What is
    new is that the CENSUS IS NOW READ: `proof_census` records the library's
    holes and the vacuous declarations alongside the generated file's, and this
    writes them to stderr on every call. `n_sorries` used to be returned to
    exactly one caller, stored in a dict by `formal/build.py` and read by nobody
    — a proof with a thousand `sorry`s and a proof with none printed the same
    `PASS`, and the instrument that was supposed to prevent that was itself
    unread. See `Census` and `_emit_census`.
    """
    c = proof_census(proof_path, repo_root, timeout)
    _emit_census(c.lines)
    return c.ok, c.detail, c.cached, c.n_sorries


def check_proof(proof_path: str, repo_root: str | None = None,
                timeout: int = 1200) -> tuple[bool, str]:
    ok, detail, _, _ = check_proof_cached(proof_path, repo_root, timeout)
    return ok, detail


def _run_lean(proof_path: str, lib_dir: str, lean: str,
              timeout: int) -> tuple[bool, str, int]:
    """`(ok, detail, n_sorries)`.

    `n_sorries` is the number of declarations Lean reports as "uses `sorry`" —
    the ONLY sound way to count holes, and the reason this census is worth
    carrying.  Grepping the generated source for the word counts a
    `all_goals first | … | sorry` fallback that was never reached (a tactic
    alternative that loses is still text), so a textual count is a count of
    *hypothetical* holes and never goes down.  Worse, the doc this replaces
    counted the greps of a plain `lean` run, which reports nothing at all when
    Lean serves a cached verdict — hence a figure that was neither the
    baseline nor the current state.  Lean emits the warning during
    elaboration, once per declaration that actually admitted a hole.

    ON **STDOUT**, not stderr, and that is measured rather than assumed: this
    function is handed `stdout + stderr` for exactly that reason, and a probe
    that reads only `result.stderr` sees an empty string for a run that really
    did report two holes in `lib/ProofLib.lean` — a hole census of zero,
    confidently, from a tool that was working perfectly. Anything here that
    parses `lean` output must read both streams.

    It says nothing at all about a `sorry` in an IMPORTED module, which is the
    other half of the census and lives in `library_census`; the two are counted
    apart on purpose, because "the file Lean read" and "the proof the file
    rests on" are different things and a single total would hide which one a
    hole is in.
    """
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
        return False, "lean timed out", 0
    n_sorries = _census_from_output(
        (result.stdout or "") + (result.stderr or ""),
        _read_lines(proof_path))[0]
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "lean failed").strip(), n_sorries
    return True, "", n_sorries
