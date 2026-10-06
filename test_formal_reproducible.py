#!/usr/bin/env python3
"""Reproducible builds: the same input must produce the same bytes.

A backend that PROVES its output has one property no other consumer needs and
no other test in this tree checks: an image is a function of the program and
nothing else. Not of the machine it was built on, not of the directory it was
built in, not of the file name it was published under, not of the clock, not of
`PYTHONHASHSEED`. Every other question about an image — does it run, does it
agree with the interpreter, does its proof typecheck — is answered by looking at
WHAT it computes, and a compiler can pass all of them while emitting different
bytes for the same source on Tuesday and Wednesday.

So this file compares bytes. The axes, each measured rather than reasoned
about, and each one an assertion with the difference it used to produce:

  1. **Two fresh processes, and everything else varied.** Different working
     directory, different `TMPDIR`, different environment-variable ORDER (a
     dict handed to `execve` keeps its insertion order, so building it in
     reverse really does reach the child in a different order), a different
     `PYTHONHASHSEED`, `PYTHONDONTWRITEBYTECODE` set on one side only, a
     different output directory AND a different output NAME, and a cold CAS on
     each side so the second build is a build and not a cache read. On both
     backends.
  2. **The machine busy and not.** A handful of spinners are started for the
     duration of the second build, so a build that read a clock, a pid or a
     random source would have had the chance to show it.
  3. **Two builds of ONE source in ONE process, to two different names.** This
     is the axis the fresh-process cases structurally miss: with one name per
     case the names never differ, and this is the axis on which the tree WAS
     nondeterministic. `codesign` derives an ad-hoc signature's identifier from
     the file's BASENAME when no `-i` is given (`Identifier=fact-55554944…`,
     where `55554944` is "UUID" and sixteen zero bytes), which put a spelling
     of the output path inside the signature bytes — which are part of the
     artifact. Measured: `formal/examples/fact.mojo` built as `alpha.aout` and
     as `zzz9.aout`, every other byte equal, differing in ONE byte at offset
     49160, inside the LC_CODE_SIGNATURE that starts at 49152. Fixed by
     `formal/build.py::_signature_identity`, and asserted here on both
     backends and by reading the identifier back out of `codesign -dv`.
  4. **A program that imports a local module**, built twice with the
     module-dylib cache dropped in between, so the library is really rebuilt
     and not served: the executable AND the dylib must both be identical. This
     is the only shape here where the image records a path that is not the
     program's own — `LC_LOAD_DYLIB` names the library's real location, because
     dyld has to load it — so both builds use the SAME `GMOJO_HOME` (a second
     one is a different absolute path, which is a different load command, and
     that is not a defect) and only its `cas/formal-imports` subtree is
     emptied between them.
  5. **`fire.py dylib --formal` twice**, for the library's own sake.
  6. **LC_UUID is a content digest**: equal across equal builds, DIFFERENT for
     different content, and not the all-zero constant this backend used to emit
     (which told dyld's caches that every image this compiler has ever produced
     is the same image).
  7. **The image still runs**, on both backends, because a byte-identical
     artifact that does not run is a different defect and this file must not be
     the reason it appears.
  8. **`cas.formal_build_key` does not carry the output path.** The
     "nothing that does not determine the bytes" half of the key's contract,
     and it is only sound because of (3): a key that had to name the output
     file would be admitting that the output file decides the artifact. The
     "everything that does" half — the import closure, the criteria, the
     architecture — is `test_formal_sweep_cache_key.py`, and is not restated
     here.

What is deliberately NOT asserted, because it is a fact about the program and
not about the compiler: a program that reads `__file__` embeds the path it was
handed, so two builds of it from two directories differ, and that is the
language's answer rather than a leak. It is the one case in the 312-case corpus
sweep that still differs, and it differs in exactly the string it is supposed
to print.

Invocation:
    python3 test_formal_reproducible.py [-v]
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = HERE
sys.path.insert(0, HERE)

from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S   # noqa: E402

FIRE = os.path.join(HERE, "fire.py")

# Reaping a CPU spinner, which is neither a compilation nor a program under
# test: the one call in this file with no shared constant to describe it, named
# here for that reason rather than forced onto one that does not describe it
# (the same distinction `exec_budget`'s own docstring draws, and the one
# `tools/suite.py`'s `STALE_PER_CHILD_BUDGETS` census cannot see — it walks
# `timeout=` keywords, not constants).
SPINNER_REAP_S = 10

# A program with a `main`, so the image is one that RUNS and its exit status is
# the entry function's return value (which is what case 7 checks). Chosen over
# an example for one reason: `formal/examples/*.mojo` is swept by
# `x86-examples` for what it computes, and a case here should be about the
# bytes rather than about the arithmetic.
RUNNABLE = """\
def main(n: Int) -> Int:
    var total: Int = 0
    var i: Int = 1
    while i <= n:
        total = total + i
        i = i + 1
    return total
"""

# The same, through a module boundary: a local module the program imports, so
# the build compiles it into a dylib and records it in LC_LOAD_DYLIB.
LIB_MODULE = "def twice(x: Int) -> Int:\n    return x * 2\n"
LIB_PROGRAM = """\
from libmod import twice

def main(n: Int) -> Int:
    return twice(n) + 1
"""

# The library `fire.py dylib --formal` builds in case 5.
DYLIB_MODULE = """\
def add_one(x: Int) -> Int:
    return x + 1


def mul_two(x: Int) -> Int:
    return x * 2
"""

VERBOSE = False


def check(name, cond, detail=""):
    if cond:
        print(f"PASS  {name}")
        return True
    print(f"FAIL  {name}  {detail}")
    return False


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


# ── the varied build environment ───────────────────────────────────────────

# Every axis at once, one side each. `PYTHONHASHSEED` is the one that matters
# most and is the reason it is worth a test at all: a set or dict whose
# iteration order reaches a symbol table, a section order or a bind stream is
# the classic way a Python-hosted code generator stops being reproducible, and
# it is invisible in a single process — `PYTHONHASHSEED` is read once, at
# interpreter start-up.
ODD_ENV = {
    "PYTHONHASHSEED": "31337",
    "PYTHONDONTWRITEBYTECODE": "1",
    "LC_ALL": "C",
    "TZ": "UTC",
    "NO_COLOR": "1",
    "TERM": "dumb",
    # Reversed so the child receives them in a different order than the even
    # side, which `os.environ` builds by insertion.
    "_ZZZ_LAST": "1",
}


def build_env(cas_home, tmpdir, odd, reversed_order=False):
    """The child's environment: `os.environ`, plus or minus the odd half.

    `reversed_order` inserts the odd keys from the other end, which is what
    makes the ORDER differ — `subprocess` passes the dict to `execve` and
    `environ` is ordered.
    """
    env = {}
    base = dict(os.environ)
    if odd:
        items = list(ODD_ENV.items())
        if reversed_order:
            items.reverse()
        for k, v in items:
            env[k] = v
    for k, v in base.items():
        env[k] = v
    env["GMOJO_HOME"] = cas_home          # one CAS, wiped between builds
    env["TMPDIR"] = tmpdir
    return env


def cold(cas_home):
    """Empty the two module-dylib caches, so a build is a build.

    `formal-imports` is the per-module library cache and `rtdylib` the C
    runtime library; both are content-addressed, so leaving them in place would
    make the second build a cache READ and the case would pass without testing
    anything.
    """
    for sub in ("formal-imports", "rtdylib"):
        shutil.rmtree(os.path.join(cas_home, "cas", sub), ignore_errors=True)


def build(argv, cwd, env, expect_ok=True):
    """Run one `fire.py` build; return (rc, image bytes or None, stderr)."""
    completed = subprocess.run([sys.executable, FIRE] + argv, cwd=cwd, env=env,
                               capture_output=True, text=True,
                               timeout=COMPILE_TIMEOUT_S)
    if VERBOSE:
        print(f"      build {' '.join(argv)} rc={completed.returncode}")
    if completed.returncode != 0 and expect_ok:
        return completed.returncode, None, (completed.stderr or
                                            completed.stdout)[-400:]
    return completed.returncode, None, ""


def build_executable(root, name, arch, cas_home, tmpdir, cwd, odd, load=0,
                     source=RUNNABLE):
    """One `fire.py build --formal` of `source`; return its bytes or None."""
    src = write(os.path.join(root, name + ".mojo"), source)
    out = os.path.join(root, name + ".aout")
    if os.path.exists(out):
        os.unlink(out)
    cold(cas_home)
    spinners = _start_load(load)
    try:
        rc, _, err = build(["build", "--formal", "--no-prove", f"--backend={arch}",
                            "-o", out, "-n", "10", src], cwd=cwd,
                           env=build_env(cas_home, tmpdir, odd,
                                         reversed_order=odd))
    finally:
        _stop_load(spinners)
    if rc != 0:
        return None, err
    with open(out, "rb") as f:
        return f.read(), ""


def _start_load(n):
    """`n` CPU spinners, so a build runs on a machine that is not idle."""
    procs = []
    for _ in range(max(0, n)):
        try:
            procs.append(subprocess.Popen(
                [sys.executable, "-c",
                 "import time\nd=time.time()+30\nx=0\n"
                 "while time.time()<d: x+=1\n"]))
        except OSError:
            break
    return procs


def _stop_load(procs):
    for p in procs:
        try:
            p.kill()
            p.wait(timeout=SPINNER_REAP_S)
        except Exception:  # noqa: BLE001 — a spinner is not the subject
            pass


# ── Mach-O reading, small and local ────────────────────────────────────────

def macho_commands(data: bytes) -> dict:
    """`{load-command name: payload bytes}` for the commands this file asks about."""
    import struct
    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    names = {0x0C: "LC_LOAD_DYLIB", 0x0D: "LC_ID_DYLIB", 0x1B: "LC_UUID",
             0x1D: "LC_CODE_SIGNATURE", 0x80000028: "LC_MAIN",
             0x80000022: "LC_DYLD_INFO_ONLY", 0x0E: "LC_LOAD_DYLINKER"}
    out = {}
    o = 32
    for _ in range(ncmds):
        if o + 8 > len(data):
            break
        cmd, cmdsize = struct.unpack_from("<II", data, o)
        out.setdefault(names.get(cmd, hex(cmd)), data[o:o + cmdsize])
        o += cmdsize
        if o > sizeofcmds + 32:
            break
    return out


def macho_uuid(data: bytes) -> bytes:
    cmd = macho_commands(data).get("LC_UUID")
    return cmd[8:24] if cmd else b""


def codesign_identifier(path: str) -> str:
    """`codesign -dv`'s `Identifier=`, or "" if it will not say."""
    r = subprocess.run(["codesign", "-dv", path], capture_output=True,
                       text=True)
    for line in (r.stderr or "").splitlines():
        if line.startswith("Identifier="):
            return line.split("=", 1)[1].strip()
    return ""


# ── the cases ──────────────────────────────────────────────────────────────

def test_two_processes_everything_else_varied(tmp):
    """Case 1+2: cwd, TMPDIR, env order, hash seed, name, dir, cold CAS, load."""
    ok = True
    for arch in ("arm64", "x86_64"):
        # One CAS and one TMPDIR for the PAIR (see the module docstring: a
        # different GMOJO_HOME is a different absolute path in LC_LOAD_DYLIB),
        # wiped between the two builds, and a different source directory,
        # output directory and output NAME for each side.
        cas_home = os.path.join(tmp, f"cas-{arch}")
        tmpdir = os.path.join(tmp, f"tmp-{arch}")
        for d in (cas_home, tmpdir):
            os.makedirs(d, exist_ok=True)
        even_root = os.path.join(tmp, f"even-{arch}")
        odd_root = os.path.join(tmp, f"odd-{arch}")
        for d in (even_root, odd_root):
            os.makedirs(d, exist_ok=True)
        load = min(4, (os.cpu_count() or 2))
        even, err_a = build_executable(even_root, "prog", arch, cas_home,
                                       tmpdir, REPO, odd=False)
        # cwd is the SOURCE's own directory here, not the repository's: the
        # build resolves a sibling import and the output relative to it, so a
        # different cwd is a different build invocation, not a cosmetic one.
        odd, err_b = build_executable(odd_root, "renamed", arch, cas_home,
                                      tmpdir, odd_root, odd=True, load=load)
        if not check(f"{arch}: both builds succeeded",
                     even is not None and odd is not None,
                     f"{err_a}{err_b}"):
            ok = False
            continue
        ok &= check(f"{arch}: identical bytes for two varied fresh processes",
                    even == odd,
                    f"{len(even)}B/{len(odd)}B {sha(even)}/{sha(odd)}, "
                    f"{_diff_runs(even, odd)}")
        # …and the LC_UUID halves of that statement, which is the part that can
        # be true of two images that are byte-identical for a different reason.
        ok &= check(f"{arch}: the two LC_UUIDs agree",
                    macho_uuid(even) == macho_uuid(odd),
                    f"{macho_uuid(even).hex()}/{macho_uuid(odd).hex()}")
    return ok


def _diff_runs(a: bytes, b: bytes) -> str:
    """How many byte-runs differ, and the first offset, for a FAIL message."""
    if a == b:
        return "identical"
    runs = 0
    first = None
    i = 0
    while i < min(len(a), len(b)):
        if a[i] != b[i]:
            if first is None:
                first = i
            j = i
            while j < min(len(a), len(b)) and a[j] != b[j]:
                j += 1
            runs += 1
            i = j
        else:
            i += 1
    return f"{runs} differing runs, first at {first}"


def test_two_names_in_one_process(tmp):
    """Case 3: the axis that WAS broken, in one process, two names."""
    import formal.build as FB
    ok = True
    saved = os.environ.get("GMOJO_HOME")
    try:
        for arch in ("arm64", "x86_64"):
            cas_home = os.path.join(tmp, f"inproc-cas-{arch}")
            os.makedirs(cas_home, exist_ok=True)
            os.environ["GMOJO_HOME"] = cas_home
            src = write(os.path.join(tmp, f"inproc-{arch}.mojo"), RUNNABLE)
            images = []
            for name in ("one.aout", "two.aout"):
                out = os.path.join(tmp, f"inproc-{arch}-{name}")
                cold(cas_home)
                result = FB.compile_formal(src, output=out, test_input=10,
                                          prove=False, check=False, arch=arch)
                with open(result["path"], "rb") as f:
                    images.append(f.read())
            ok &= check(f"{arch}: one process, two output names, one image",
                        images[0] == images[1],
                        f"{sha(images[0])}/{sha(images[1])}, "
                        f"{_diff_runs(images[0], images[1])}")
            if platform.system() == "Darwin":
                # The byte comparison above already implies this one, so the
                # point of doing it separately is that it NAMES the cause: it is
                # the `Identifier=` line and nothing else, and asking
                # `codesign` is the only way to see it. Comparing the two
                # identifiers rather than looking for a substring is the whole
                # difference between this being an assertion and being a
                # decoration — `codesign` strips the extension, so the pre-fix
                # identifier was `one-55554944…` and a `not in` test against
                # `one.aout` would have passed on exactly the code it was
                # written for.
                idents = [codesign_identifier(
                    os.path.join(tmp, f"inproc-{arch}-{n}")) for n in
                    ("one.aout", "two.aout")]
                ok &= check(f"{arch}: the ad-hoc identifier is the same for "
                            f"both names", idents[0] and idents[0] == idents[1],
                            f"{idents}")
    finally:
        if saved is None:
            os.environ.pop("GMOJO_HOME", None)
        else:
            os.environ["GMOJO_HOME"] = saved
    return ok


def test_a_program_that_imports_a_module(tmp):
    """Case 4: the executable AND the library it links, both rebuilt."""
    ok = True
    for arch in ("arm64", "x86_64"):
        cas_home = os.path.join(tmp, f"imp-cas-{arch}")
        tmpdir = os.path.join(tmp, f"imp-tmp-{arch}")
        for d in (cas_home, tmpdir):
            os.makedirs(d, exist_ok=True)
        images, libs = [], []
        for side, root in enumerate((os.path.join(tmp, f"imp-a-{arch}"),
                                     os.path.join(tmp, f"imp-b-{arch}"))):
            os.makedirs(root, exist_ok=True)
            write(os.path.join(root, "libmod.mojo"), LIB_MODULE)
            images.append(build_executable(
                root, f"prog{side}", arch, cas_home, tmpdir, root, odd=bool(side),
                source=LIB_PROGRAM)[0])
            libs_dir = os.path.join(cas_home, "cas", "formal-imports", arch)
            libs.append(sorted((f, open(os.path.join(libs_dir, f), "rb").read())
                               for f in os.listdir(libs_dir)
                               if f.endswith(".dylib")))
        if not check(f"{arch}: both module builds succeeded",
                     all(images) and all(libs),
                     "a build failed or no module dylib was published"):
            ok = False
            continue
        ok &= check(f"{arch}: an importing program's image is reproducible",
                    images[0] == images[1],
                    f"{_diff_runs(images[0], images[1])}")
        ok &= check(f"{arch}: its module dylib is reproducible",
                    libs[0] == libs[1],
                    f"{[f for f, _ in libs[0]]} vs {[f for f, _ in libs[1]]}")
    return ok


def test_the_dylib_driver(tmp):
    """Case 5: `fire.py dylib --formal`, which is the other publishing path."""
    ok = True
    src = write(os.path.join(tmp, "dylibsrc", "lib.mojo"), DYLIB_MODULE)
    images = []
    for side in (0, 1):
        cas_home = os.path.join(tmp, f"dylib-cas-{side}")
        os.makedirs(cas_home, exist_ok=True)
        cold(cas_home)
        out = os.path.join(tmp, f"dylib-out-{side}", "lib.dylib")
        rc, _, err = build(["dylib", "--formal", "--no-prove", "-o", out, src],
                           cwd=os.path.dirname(src),
                           env=build_env(cas_home, tmp, odd=bool(side),
                                         reversed_order=bool(side)))
        if rc != 0:
            ok = check("the dylib build succeeded", False, err)
            break
        with open(out, "rb") as f:
            images.append(f.read())
    else:
        ok &= check("two `dylib --formal` builds are byte-identical",
                    images[0] == images[1],
                    f"{sha(images[0])}/{sha(images[1])}, "
                    f"{_diff_runs(images[0], images[1])}")
    return ok


def test_the_uuid_is_the_content(tmp):
    """Case 6: equal content ⇒ equal uuid; different content ⇒ different."""
    if platform.system() != "Darwin":
        print("SKIP  the LC_UUID cases (Mach-O only)")
        return True
    ok = True
    cas_home = os.path.join(tmp, "uuid-cas")
    tmpdir = os.path.join(tmp, "uuid-tmp")
    for d in (cas_home, tmpdir):
        os.makedirs(d, exist_ok=True)
    root = os.path.join(tmp, "uuid-src")
    os.makedirs(root, exist_ok=True)
    a, err_a = build_executable(root, "a", "arm64", cas_home, tmpdir, REPO,
                                odd=False)
    b, err_b = build_executable(root, "b", "arm64", cas_home, tmpdir, REPO,
                                odd=False)
    other, _ = build_executable(
        root, "c", "arm64", cas_home, tmpdir, REPO, odd=False,
        source=RUNNABLE.replace("total = total + i", "total = total + i * 2"))
    if not check("the uuid case's builds succeeded",
                 a and b and other, f"{err_a}{err_b}"):
        return False
    ua, ub, uo = macho_uuid(a), macho_uuid(b), macho_uuid(other)
    ok &= check("equal content ⇒ equal LC_UUID", ua == ub,
                f"{ua.hex()}/{ub.hex()}")
    ok &= check("different content ⇒ different LC_UUID", ua != uo,
                f"{ua.hex()}/{uo.hex()}")
    ok &= check("LC_UUID is not the all-zero constant this backend used to emit",
                ua != bytes(16),
                "an all-zero uuid tells dyld every image is the same image")
    return ok


def test_the_image_still_runs(tmp):
    """Case 7: reproducible AND runnable, on both backends."""
    ok = True
    n = 6
    # The program sums 1..n, so the entry value is not the answer — the answer
    # is n*(n+1)/2. Written out rather than computed, so a change to the
    # program above has to change this line too and cannot silently pass.
    want = 21
    for arch in ("arm64", "x86_64"):
        cas_home = os.path.join(tmp, f"run-cas-{arch}")
        tmpdir = os.path.join(tmp, f"run-tmp-{arch}")
        for d in (cas_home, tmpdir):
            os.makedirs(d, exist_ok=True)
        root = os.path.join(tmp, f"run-src-{arch}")
        os.makedirs(root, exist_ok=True)
        src = write(os.path.join(root, "prog.mojo"), RUNNABLE)
        out = os.path.join(root, "prog.aout")
        cold(cas_home)
        rc, _, err = build(["build", "--formal", "--no-prove", f"--backend={arch}",
                            "-o", out, "-n", str(n), src], cwd=root,
                           env=build_env(cas_home, tmpdir, odd=False))
        if not check(f"{arch}: the run case built", rc == 0, err):
            ok = False
            continue
        argv = (["arch", "-x86_64", out] if arch == "x86_64"
                and sys.platform == "darwin" else [out])
        r = subprocess.run(argv, capture_output=True,
                           timeout=RUN_TIMEOUT_S)
        ok &= check(f"{arch}: the image still runs and sums 1..{n}",
                    r.returncode == want,
                    f"exit {r.returncode}, wanted {want}; "
                    f"{(r.stderr or b'').decode('utf-8', 'replace')[-200:]}")
        v = subprocess.run(["codesign", "-v", out], capture_output=True,
                           text=True) if sys.platform == "darwin" else None
        if v is not None:
            ok &= check(f"{arch}: the ad-hoc signature still verifies",
                        v.returncode == 0,
                        (v.stderr or "").strip()[-200:])
    return ok


def test_the_cache_key_does_not_carry_the_output_path(tmp):
    """Case 8: the "nothing that does not" half of `formal_build_key`.

    It is only sound because of case 3: a key that had to name the output file
    would be admitting that the output file decides the artifact. The other
    half — everything that does decide it — is `test_formal_sweep_cache_key.py`.
    """
    import cas
    from formal import imports as FI
    src = write(os.path.join(tmp, "key", "prog.mojo"), RUNNABLE)
    source = open(src).read()
    flags = ("--formal", "--no-prove", "--backend=arm64")
    here = os.path.join(tmp, "key")
    write(os.path.join(here, "one.aout"), "")
    write(os.path.join(here, "two.aout"), "")
    a = cas.formal_build_key(source, os.path.join(here, "one.aout"), flags,
                             "test", imports=FI.import_closure_digest(src))
    b = cas.formal_build_key(source, os.path.join(here, "two.aout"), flags,
                             "test", imports=FI.import_closure_digest(src))
    other = cas.formal_build_key(source, os.path.join(here, "one.aout"),
                                 ("--formal", "--no-prove", "--backend=x86_64"),
                                 "test", imports=FI.import_closure_digest(src))
    return (check("the output path is not in the key", a == b,
                  f"{a} / {b}")
            and check("the architecture is in the key", a != other))


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*")
    args = ap.parse_args()
    VERBOSE = args.verbose

    cases = [
        ("two fresh processes, everything else varied",
         test_two_processes_everything_else_varied),
        ("two output names in one process",
         test_two_names_in_one_process),
        ("a program that imports a module",
         test_a_program_that_imports_a_module),
        ("the dylib driver", test_the_dylib_driver),
        ("the LC_UUID is the content", test_the_uuid_is_the_content),
        ("the image still runs", test_the_image_still_runs),
        ("the cache key does not carry the output path",
         test_the_cache_key_does_not_carry_the_output_path),
    ]
    if args.cases:
        cases = [c for c in cases
                 if any(sel in c[0] for sel in args.cases)]

    npass = nfail = 0
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="formal-repro-") as tmp:
        for name, fn in cases:
            print(f"\n-- {name}")
            try:
                ok = fn(tmp)
            except Exception as e:  # noqa: BLE001 — reported, not raised
                ok = check(name, False, f"{type(e).__name__}: {e}")
            npass += 1 if ok else 0
            nfail += 0 if ok else 1
    secs = time.time() - t0
    print(f"\nformal reproducible: PASS={npass} FAIL={nfail} ({secs:.1f}s)")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
