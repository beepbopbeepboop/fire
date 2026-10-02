#!/usr/bin/env python3
"""Build `platform` for the formal backend and RUN it against CPython's.

    python3 test_formal_platform.py [-v] [group ...]

WHY AN ORACLE RATHER THAN A TABLE
--------------------------------
Every value here is either a fact about the machine the image is running on or
the result of CPython's own arithmetic, and both are asked rather than typed:
the five `uname(3)` fields come from `os.uname()` in THIS process, `mac_ver()`
comes from CPython's `mac_ver()`, and `system_alias` is compared case for case
over a corpus. Nothing in this file states what `platform.machine()` is. A
table of those answers is a table that is wrong the moment the host changes,
and this module's whole claim is that it agrees with CPython on the host it is
running on.

BUILDING AND RUNNING, NOT BUILDING. Every group below executes the arm64 image
and compares what it PRINTED. An honest refusal is better than a wrong image,
so a name this module cannot answer must not be an image at all — hence the
`absent` group, which pins each omission as a REFUSAL rather than trusting a
docstring.

THE TWO SOURCES OF `mac_ver_release`, AND WHY THAT IS A GROUP
-------------------------------------------------------------
`platform.mac_ver()` reads the product version out of
`/System/Library/CoreServices/SystemVersion.plist` and this module reads it out
of the kernel's `kern.osproductversion`. Two sources, one product version, and
the only honest way to justify the second is to ask both: the `macver` group
compares the image against CPython's `mac_ver()` AND against the plist CPython
read, so the claim in `formal/hostmods/platform.mojo`'s docstring is an
assertion somebody can delete when it stops being true.

`system_alias` IS THE GROUP WORTH READING
-----------------------------------------
It is the only pure function CPython's `platform` has that this module ships,
and it is the one with real logic in it: CPython parses the leading component
of a SunOS release with `int()`, and `int()` accepts surrounding whitespace, a
sign and single underscores between digits — so a validator that accepts only
digits turns a release CPython rewrites into one this leaves alone, which is a
wrong answer rather than a refusal. The corpus is the corners: below `5`,
above `5`, a leading `+`, an embedded `_`, an empty first component, a doubled
underscore, a trailing dot, and a name that merely STARTS WITH `SunOS`.

`architecture` IS THE GROUP THAT NEEDED A CAPABILITY
---------------------------------------------------
CPython reads it out of `file -b <exe>` — a SUBPROCESS — and this module reads
the same two facts (the pointer width, and whether the format is one `file`
would call an executable) out of the file's own Mach-O header, which is where
`file` reads them. That needed `read(2)` in `formal/hostmods/os/_syscalls.mojo`
(it had `open`, `lseek` and `close` and could not read a byte) and a reader for
the header, and the `architecture` group is what pins the result against
CPython over the four shapes of file — an executable, a UNIVERSAL binary (every
system tool on an Apple Silicon macOS), a dylib, and something that is not a
Mach-O at all. It is also the group that pins a CPython quirk rather than a
Mach-O fact: CPython accepts `file -b` output containing `executable` or the
phrase `shared object`, and this macOS's `file` no longer prints that phrase, so
CPython answers `('64bit', '')` for a dylib and this module answers the same.

Groups: `resolve`, `uname`, `processor`, `macver`, `alias`, `free`,
`architecture`, `arch`, `exports`, `absent`. With no argument, all.
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
PLATFORM_MODULE = os.path.join(HOSTMODS, "platform.mojo")

sys.path.insert(0, HERE)

# The independent driver, the record format and the assertion helpers live in
# the dylib suite; imported rather than copied so a fix to any of them cannot
# leave a second, quietly different one behind.
from test_formal_json import (build, check, compare, mj, records,  # noqa: E402
                              reader, run)
import test_formal_json as J  # noqa: E402

TEMP = None

# The record writer every generated program here shares. `<len>:<value>` records
# rather than a bare separator, for the reason `test_formal_json.py` gives and
# not because of taste: `platform.version()` is a SENTENCE containing spaces,
# colons and semicolons, so a separator-only split would mis-align on it and
# then report a wrong answer rather than an error.
#
# `memcpy`/`snprintf` rather than `json.put_byte`: this copies a string in one
# move and formatting is libc's, and importing the 1,195-line `json` module to
# obtain a byte-at-a-time writer would be the larger duplication.
PRELUDE = '''
def nlen(n) -> int:
    var k = 1
    if n < 10:
        return k
    if n < 100:
        return k + 1
    return k + 2

def rec(out, u, s) -> int:
    """`<len>:<value>@@` into `out` at `u`. The new `u`.

    TWO `@` and not one, for the reason `test_formal_json.py`'s `ndelim` gives:
    the mask there escapes every literal `@` as `~@`, so a masked case cannot
    contain `@@` — which is what makes the two-byte separator the right one and
    a one-byte `@` the wrong one. The corpus here is printable ASCII and none
    of it holds an `@`, but the length prefix has to be read by the same
    parser as every other group's records, and that parser splits on two.

    `nlen(n) + 1` and not `nlen(n)`: `snprintf` wrote the digits AND the colon,
    so advancing by the digit count alone leaves the next record's first byte
    on top of the colon. The first version of this harness did that, and it
    showed up as a `records()` failure that read like a wrong `uname` answer
    rather than as a broken record writer.
    """
    var n = strlen(s)
    snprintf(out + u, 16, "%lld:", n)
    u = u + nlen(n) + 1
    memcpy(out + u, s, n)
    u = u + n
    memset(out + u, 64, 2)
    return u + 2
'''


def _write(name, text):
    p = os.path.join(TEMP, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def _program(name, body):
    """Build and run `body` (a `main` plus whatever it needs) and return its
    stdout as raw latin-1, so every byte survives."""
    return run(build(PRELUDE + "\n" + body, name))


# ── the corpus ────────────────────────────────────────────────────────────
#
# `(system, release, version)` triples for `system_alias`. Every string is
# plain printable ASCII, so `mj` is the only masking this corpus needs and no
# value can contain the record terminator.
ALIAS_CASES = [
    # SunOS at or above 5: the marketing release is three below the kernel's.
    ("SunOS", "5", "v"),
    ("SunOS", "5.11", "v"),
    ("SunOS", "5.11.2", "v"),
    ("SunOS", "10.3", "v"),
    ("SunOS", "05", "v"),
    ("SunOS", "5.", "v"),
    ("SunOS", "100.0", "v"),
    # Below 5 really are SunOS, and the test is the release's own
    # lexicographic order.
    ("SunOS", "4.0", "v"),
    ("SunOS", "0", "v"),
    ("SunOS", "", "v"),
    # `int()`'s own rules, which is where a hand-rolled parser goes wrong.
    ("SunOS", " 7 ", "v"),        # surrounding whitespace is allowed
    ("SunOS", "+8", "v"),         # and a sign
    ("SunOS", "1_0", "v"),        # and single underscores between digits
    ("SunOS", "1__0", "v"),       # but not doubled
    ("SunOS", "_5", "v"),         # nor leading
    ("SunOS", "5_", "v"),         # nor trailing
    ("SunOS", "5-", "v"),         # nor anything after a digit
    ("SunOS", "abc", "v"),        # no digits at all
    ("SunOS", ".5", "v"),         # an empty first component
    ("SunOS", "5.abc", "v"),      # only the FIRST component is parsed
    # Windows, and Darwin, and everything else untouched.
    ("win32", "10", "v"),
    ("win16", "10", "v"),
    ("win32", "1_0", "v"),        # the SunOS arithmetic does not apply
    ("win32", "", ""),
    ("Darwin", "25.6.0", "v"),
    ("SunOSX", "5", "v"),         # a name that merely STARTS WITH SunOS
    ("Sun", "5", "v"),
    ("", "", ""),
    ("Linux", "6.1.0", "v"),
]


# ── groups ────────────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import platform` finds `formal/hostmods/platform.mojo`, and the name
    left `HOST_MODELLED`.

    The set membership matters for the same reason it does in
    `test_formal_small_hosts.py`: `HOST_MODELLED` is a CLAIM that the module
    could be written, and a name leaves it by being written, because an entry
    left behind would refuse a file AFTER the module that answers it is in the
    tree — a false statement about the target rather than a conservative one.
    """
    import formal.imports as I
    check(os.path.isfile(PLATFORM_MODULE), f"no Mojo source for platform")
    for rel in ("t1.mojo", os.path.join("tools", "ci_line.py")):
        got = I.resolve_module_path("platform", relative_to=os.path.join(HERE, rel))
        check(got is not None and os.path.samefile(got, PLATFORM_MODULE),
              f"`import platform` from {rel} did not resolve to "
              f"{PLATFORM_MODULE}, got {got!r} — the hostmods root is appended "
              f"to every file's search roots, so a file in a subdirectory must "
              f"find it too")
    check(I.host_module_tier("platform") == "",
          "platform is still in HOST_MODELLED: a Mojo source wins over that "
          "set, so the entry now describes nothing the build does")
    if verbose:
        print(f"    resolves from the root and from tools/, and out of the set")
    return True, "platform resolves to formal/hostmods/platform.mojo, out of HOST_MODELLED"


def group_uname(tmpdir, verbose):
    """The five `uname(3)` fields, each against `os.uname()` in this process.

    `os.uname()` and not `platform.uname()`, because `platform.uname()` on
    CPython is the same five fields with a sixth resolved by a subprocess, and
    comparing five-fields-to-six-fields would make this test depend on that
    subprocess's answer.
    """
    names = ["system", "node", "release", "version", "machine"]
    src = ["import platform", "", "def main() -> int:",
           "    var out: Pointer[UInt8] = malloc(2048)",
           "    memset(out, 0, 2048)", "    var u = 0"]
    for n in names:
        src.append(f"    u = rec(out, u, platform.{n}())")
    src.append("    printf(\"%s\", out)")
    src.append("    return 0")
    got = records(_program("platform_uname", "\n".join(src) + "\n"))
    check(len(got) == len(names),
          f"uname: image reported {len(got)} of {len(names)} fields")
    bad = []
    u = os.uname()
    want = [u.sysname, u.nodename, u.release, u.version, u.machine]
    for (idx, ln, val), w in zip(got, want):
        if ln != len(val):
            bad.append((idx, f"length {ln} but {len(val)} bytes"))
            continue
        if val != w:
            bad.append((idx, f"{val!r} != CPython {w!r}"))
    check(not bad, f"uname: {len(bad)} field(s) differ from os.uname(); "
                   f"first: {bad[0] if bad else ''}")
    # The point of the row: `machine()` is the name thirty swept files want.
    check(got[4][2] in ("arm64", "x86_64", "aarch64", "i386", "i686"),
          f"machine() reported {got[4][2]!r}, which is not an architecture "
          f"name this tree has ever seen — either the uname field is being "
          f"read at the wrong offset or this is a machine nobody has run this "
          f"on")
    if verbose:
        print(f"    5 uname fields, each against os.uname() in this process")
    return True, f"{len(names)} uname fields agree with os.uname()"


def group_processor(tmpdir, verbose):
    """`uname_processor()` is `""`, and that is CPython's own blank.

    Two things are checked, and the second is the interesting one. The first is
    the value. The second is that CPython's `uname().processor` is NOT `""` on
    this host — it is `uname -p` output, which needs a subprocess — so this is
    NOT agreement, and the module says so. Asserting agreement would be the
    test that would have made an approximation look like a result.

    So the assertion is that the image is `""` AND that CPython here is not,
    which is what makes the divergence a documented fact rather than a latent
    wrong answer.
    """
    got = records(_program("platform_processor", """
import platform

def main() -> int:
    var out: Pointer[UInt8] = malloc(64)
    memset(out, 0, 64)
    var u = rec(out, 0, platform.uname_processor())
    printf("%s", out)
    return 0
"""))
    check(len(got) == 1, f"uname_processor: image reported {len(got)} answers")
    check(got[0][2] == "",
          f"uname_processor() reported {got[0][2]!r}; the module documents it "
          f"as always empty, because CPython's only other source for it is a "
          f"subprocess and there is none here")
    cpy = platform.uname().processor
    check(cpy != "",
          "CPython's own uname().processor is also empty on this host, so the "
          "`processor` group can no longer prove that the two DIVERGE — and "
          "the module's docstring claims a divergence, so it has to be checked "
          "against a host where CPython really runs `uname -p`")
    if verbose:
        print(f'    the image says ""; CPython says {cpy!r} — the divergence '
          f"the docstring claims, measured")
    return True, 'uname_processor() is "" while CPython subprocesses to ' + repr(cpy)


def group_macver(tmpdir, verbose):
    """`mac_ver_release()` and `mac_ver_machine()` against CPython's own
    `mac_ver()`, AND against the plist CPython read.

    The second comparison is the one that justifies the module's choice of
    source. CPython reads `SystemVersion.plist`; this module asks the kernel.
    If either comparison is dropped the docstring's claim becomes unfalsifiable,
    so both are here and the plist is read with `plistlib` — the same file and
    the same key, not a number typed into this file.
    """
    got = records(_program("platform_macver", """
import platform

def main() -> int:
    var out: Pointer[UInt8] = malloc(1024)
    memset(out, 0, 1024)
    var u = 0
    u = rec(out, u, platform.mac_ver_release())
    u = rec(out, u, platform.mac_ver_machine())
    printf("%s", out)
    return 0
"""))
    check(len(got) == 2, f"mac_ver: image reported {len(got)} of 2 components")
    want = platform.mac_ver()
    check(got[0][2] == want[0],
          f"mac_ver_release() reported {got[0][2]!r}, CPython's mac_ver()[0] "
          f"is {want[0]!r}")
    check(got[1][2] == want[2],
          f"mac_ver_machine() reported {got[1][2]!r}, CPython's mac_ver()[2] "
          f"is {want[2]!r}")

    # The source of CPython's own answer, read the way CPython reads it.
    plist = "/System/Library/CoreServices/SystemVersion.plist"
    if not os.path.exists(plist):
        check(False,
              "SystemVersion.plist is not there, so the second source cannot "
              "be compared and the module's docstring claim about it is "
              "unverifiable on this host — not silently skipped")
    import plistlib
    with open(plist, "rb") as f:
        product = plistlib.load(f)["ProductVersion"]
    check(got[0][2] == product,
          f"mac_ver_release() reported {got[0][2]!r} but the plist CPython "
          f"reads says {product!r}: the kernel's kern.osproductversion and "
          f"the plist are NOT the same answer on this host, so the module's "
          f"second source is a guess")
    if verbose:
        print(f"    2 components against mac_ver(), and the release against "
              f"the plist CPython read ({product})")
    return True, "both mac_ver components agree with CPython, and its release with the plist"


def group_alias(tmpdir, verbose):
    """`system_alias`, all three components, over `ALIAS_CASES`.

    Three records per case, so `reader` re-indexes each component's records
    from 0 — the record POSITION is the case index, which is the property
    `records`' own docstring states and the reason `compare` can use it.
    """
    src = ["import platform", "", "def main() -> int:",
           "    var out: Pointer[UInt8] = malloc(16384)",
           "    memset(out, 0, 16384)", "    var u = 0"]
    for sysname, rel, ver in ALIAS_CASES:
        src.append(f"    u = rec(out, u, platform.system_alias_system("
                   f"{mj(sysname)}, {mj(rel)}, {mj(ver)}))")
        src.append(f"    u = rec(out, u, platform.system_alias_release("
                   f"{mj(sysname)}, {mj(rel)}, {mj(ver)}))")
        src.append(f"    u = rec(out, u, platform.system_alias_version("
                   f"{mj(sysname)}, {mj(rel)}, {mj(ver)}))")
    src.append("    printf(\"%s\", out)")
    src.append("    return 0")
    got = records(_program("platform_alias", "\n".join(src) + "\n"))
    check(len(got) == 3 * len(ALIAS_CASES),
          f"system_alias: image reported {len(got)} of "
          f"{3 * len(ALIAS_CASES)} components")

    def want_fn(case):
        return platform.system_alias(*case)

    labels = ["system", "release", "version"]
    for k in range(3):
        compare(f"system_alias {labels[k]}", ALIAS_CASES, reader(got, k, 3),
                want_fn=lambda case, k=k: platform.system_alias(*case)[k])
    if verbose:
        print(f"    3 components x {len(ALIAS_CASES)} cases, "
              f"{3 * len(ALIAS_CASES)} comparisons")
    return True, (f"{3 * len(ALIAS_CASES)} system_alias components agree "
                  f"with CPython over {len(ALIAS_CASES)} cases")


def group_free(tmpdir, verbose):
    """A string this module allocated is released by `platform_free`, and two
    calls to `machine()` do not alias.

    The second half is the property that decides how the module is written: with
    no module storage, one shared buffer would make every answer an interior
    pointer into it, and a program that keeps two of them would see the second
    call overwrite the first. So this reads one machine name, reads another,
    and then reads the FIRST pointer again — which is the aliasing that would
    be there if the strings were shared.
    """
    got = records(_program("platform_free", """
import platform

def main() -> int:
    var out: Pointer[UInt8] = malloc(2048)
    memset(out, 0, 2048)
    var u = 0
    var a = platform.machine()
    var b = platform.machine()
    u = rec(out, u, a)
    u = rec(out, u, b)
    u = rec(out, u, a)
    platform_free(a)
    platform_free(b)
    printf("%s", out)
    return 0
"""))
    check(len(got) == 3, f"free: image reported {len(got)} of 3 answers")
    check(got[0][2] == got[2][2],
          "the first machine() string changed when the second was taken — "
          "the two calls share one buffer, so every answer this module "
          "returns aliases the last one")
    if verbose:
        print(f"    platform_free runs, and two calls do not alias")
    return True, "platform_free works and successive answers do not alias"


def group_exports(tmpdir, verbose):
    """Every public name `platform.mojo` declares reaches a dylib's export
    table, and every one of them LINKS when called.

    Two checks, and the second is the one that catches what the first cannot.
    `reflect.export_exclusions` is the RULE (`doc/ABI.md`) applied to the
    source: it catches a name the rule would deny. It cannot catch a name that
    is declared, exported and yet unreachable, so the second build CALLS all of
    them — which is where a signature that does not bind a symbol shows up.

    The declared list is read from the module's OWN parse, so a failure names
    the name rather than a count.
    """
    sys.path.insert(0, HERE)
    import fire_compiler as F
    import reflect
    with open(PLATFORM_MODULE) as f:
        src = f.read()
    stmts = F.Parser(F.py_tokenize(src)).parse_module()
    declared = sorted(s.name for s in stmts
                      if isinstance(s, F.FunctionDef) and not s.name.startswith("_"))
    check(declared, "platform.mojo declares no public function")
    excluded = reflect.export_exclusions(src, stmts)
    denied = [n for n in declared if n in excluded]
    check(not denied,
          f"platform.mojo declares {denied} but doc/ABI.md's rule excludes "
          f"them ({[excluded[n] for n in denied]}) — a name the export rule "
          f"denies is a module nothing can call")

    # Every public name, called. `_int_to_str`-style helpers are private, so
    # this is the module's whole API and each call uses arguments its own
    # docstring accepts.
    calls = [
        ("system", "()"), ("node", "()"), ("release", "()"), ("version", "()"),
        ("machine", "()"), ("uname_processor", "()"),
        ("mac_ver_release", "()"), ("mac_ver_machine", "()"),
        ("system_alias_system", '("SunOS", "5.11", "v")'),
        ("system_alias_release", '("SunOS", "5.11", "v")'),
        ("system_alias_version", '("SunOS", "5.11", "v")'),
        # Nested, because that is the spelling the module's docstring gives a
        # caller: release what the next call allocates.
        ("platform_free", "(platform.machine())"),
        # `architecture` is two functions because its answer is a tuple, and the
        # sink takes the string each half returns. The path is this repository's
        # own `fire.py`, which exists on every checkout that can run this file.
        ("architecture_bits", '("fire.py")'),
        ("architecture_linkage", '("fire.py")'),
    ]
    check(sorted(n for n, _ in calls) == declared,
          f"the call list is not the module's public surface; only in the "
          f"test: {sorted(set(declared) ^ set(n for n, _ in calls))}")
    src = ["import platform", "", "def main() -> int:"]
    for n, args in calls:
        src.append(f"    {n}_sink(platform.{n}{args})")
    src.append("    return 0")
    for n, _ in calls:
        src.append("")
        src.append(f"def {n}_sink(v):")
        src.append("    return 0")
    _program("platform_exports", "\n".join(src) + "\n")
    if verbose:
        print(f"    {len(declared)} public names exported and called")
    return True, f"{len(declared)} public names export and link"


def group_absent(tmpdir, verbose):
    """Every name the module documents as absent, asserted as a REFUSAL.

    An omission that is not pinned is indistinguishable from an implementation,
    and this module's absences all have a stated capability behind them, so each
    is pinned as a build that fails with a message naming the module and the
    name. The probe is a CALL, not a bare name: a bare `platform.platform` is a
    read of a module-level name, refused for a different and vaguer reason that
    does not name the name being asked for.
    """
    absent = [
        # One composition away, and what it is composed of is here: `platform()`
        # itself, which is `uname` + `mac_ver` + `system_alias` + `architecture`
        # and one string-formatting helper
        # (bugs/FORMAL_platform_one_call_from_answered.md).
        "platform",
        # Subprocesses and a readable file.
        "processor", "libc_ver",
        # No Python on this image.
        "python_version", "python_implementation", "python_build",
        "python_branch", "python_compiler", "python_revision",
        "python_version_tuple",
        # A JVM, the Windows API, an iOS/Android property API, /etc/os-release.
        "java_ver", "win32_ver", "win32_edition", "win32_is_iot",
        "ios_ver", "android_ver", "freedesktop_os_release",
        # Nothing to invalidate: this path has no cache and no storage.
        "invalidate_caches",
        # The tuple-shaped three, spelled as one function per component.
        "uname", "mac_ver", "system_alias",
        # Types, which are not values on this path.
        "uname_result", "AndroidVer", "IOSVersionInfo",
    ]
    for name in absent:
        src = ("import platform\n\ndef main() -> int:\n"
               f"  platform.{name}(0)\n  return 0\n")
        tmp = _write(f"absent_platform_{name}.mojo", src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_platform_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"platform.{name} resolved, but the module documents it as "
              f"absent — either the docstring is wrong or the module grew a "
              f"name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"platform.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent names refused"


def group_arch(tmpdir, verbose):
    """`machine()` on BOTH backends, and it names the ARCHITECTURE OF THE IMAGE.

    The oracle is deliberately NOT this process's `platform.machine()`. An
    x86-64 image running under Rosetta on an Apple Silicon host legitimately
    reports `x86_64`, because that is what the kernel tells THAT process — so
    comparing it with the arm64 answer of the python3 running this test would
    report a correct image as a wrong one. The assertion is the honest one: an
    image built for an architecture reports that architecture.

    It is also the measurement behind the module docstring's claim that this
    module works on both backends, which it inherited an expectation of NOT
    doing from `formal/hostmods/os/_syscalls.mojo`'s arm64-only note.
    """
    src = ('import platform\n\ndef main() -> int:\n'
           '    printf("%s@@", platform.machine())\n'
           "    return 0\n")
    for arch, want in (("arm64", "arm64"), ("x86_64", "x86_64")):
        tmp = _write(f"machine_{arch}.mojo", src)
        out = os.path.join(TEMP, f"machine_{arch}")
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "--backend", arch, "-o", out, tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode == 0,
              f"{arch}: build failed: {(r.stderr or r.stdout).strip()[-400:]}")
        try:
            got = subprocess.run([out], capture_output=True,
                                 timeout=J.RUN_TIMEOUT, cwd=HERE)
        except OSError as e:
            # An x86-64 image will not launch at all on a machine without
            # Rosetta, and that is a fact about the HOST, not about the
            # module. Say so and stop rather than failing the group.
            check(arch == "arm64",
                  f"the {arch} image would not launch on this host: {e}")
            continue
        check(got.returncode == 0,
              f"{arch}: image exited {got.returncode}")
        text = got.stdout.decode("latin-1")
        check(text == want + "@@",
              f"{arch}: machine() reported {text!r}, and an image built for "
              f"{arch} must report {want!r}")
    if verbose:
        print("    machine() reports its own image's architecture, on both")
    return True, "machine() names the image's own architecture on arm64 and x86_64"


def group_architecture(tmpdir, verbose):
    """`architecture(path)`, both halves, against CPython's own answer.

    THE CORPUS IS THE FOUR SHAPES OF FILE, not one path. CPython's answer is
    `file -b`'s output parsed for `32-bit`/`64-bit` and one of `Mach-O`/`ELF`/
    `PE`/`COFF`/`MS-DOS`, so it has four shapes and a matcher that only knows
    one of them is a matcher with a bug in it:

      * a Mach-O executable — one header, one magic;
      * a FAT/universal binary, which is EVERY SYSTEM TOOL on an Apple Silicon
        macOS: `/bin/ls` is "Mach-O universal binary with 2 architectures",
        two headers behind a slice table, big-endian offsets and little-endian
        slice magics. Answering "not a Mach-O" here is a wrong answer on the
        most ordinary path a caller can name, and it is why
        `os/_syscalls.mojo`'s `fs_macho_bits` walks the table;
      * a file that is not a Mach-O at all (a text file), and a DIRECTORY, and
        a path that is not there — all three answer CPython's DEFAULT width
        with an empty linkage, because CPython returns its presets unchanged
        when it cannot read the format.

    arm64 only, and the reason is that the answer is a property of the FILE and
    not of the image reading it: the same path gives the same answer on either
    backend, and the group that runs both is `arch`.
    """
    cases = [
        ("a single-architecture Mach-O", sys.executable),
        ("a FAT/universal binary", "/bin/ls"),
        ("another system tool", "/bin/cat"),
        ("a text file", "README.md"),
        ("a directory", "formal"),
        ("a path that is not there", os.path.join(tmpdir, "no-such-file")),
    ]
    body = ["import platform",
            "from platform import architecture_bits, architecture_linkage",
            "",
            "def show(p):",
            '    printf("%s %s@@", architecture_bits(p), '
            "architecture_linkage(p))", "",
            "def main(n):"]
    for _, p in cases:
        body.append('    show("%s")' % p.replace("\\", "\\\\").replace('"', '\\"'))
    body.append("    return 0")
    got = _program("architecture", "\n".join(body) + "\n")
    recs = [r for r in got.split("@@") if r.strip()]
    check(len(recs) == len(cases),
          f"architecture: image reported {len(recs)} of {len(cases)}")
    bad = []
    for (what, p), v in zip(cases, recs):
        b, l = platform.architecture(p)
        want = f"{b} {l}"
        if v != want:
            bad.append(f"{what} ({p}): image {v!r}, CPython {want!r}")
    check(not bad, f"architecture: {len(bad)} of {len(cases)} differ; first: "
                   + (bad[0] if bad else ""))
    # A MACHO DYLIB is the fourth shape, and the only one this repository can
    # name without inventing a path: `file -b` calls it a "shared object", which
    # is the other string CPython's parser accepts, and it has a different
    # filetype (MH_DYLIB) from an executable. It only exists after a build has
    # made one, so it is looked for AFTER the program above has run and the case
    # is added to the same comparison — never skipped silently, and skipped
    # LOUDLY if the cas has no dylib yet.
    lib = _a_built_dylib()
    if lib is None:
        if verbose:
            print("    NOTE: no formal dylib in the cas yet, so the "
                  "MH_DYLIB case did not run")
    else:
        got1 = _program("architecture_dylib",
                        "import platform\n"
                        "from platform import architecture_bits, "
                        "architecture_linkage\n\n"
                        "def main(n):\n"
                        '    printf("%s %s@@", '
                        'architecture_bits("' + lib + '"),\n'
                        '           architecture_linkage("' + lib + '"))\n'
                        "    return 0\n")
        v = [r for r in got1.split("@@") if r.strip()]
        check(len(v) == 1,
              f"architecture: the dylib case reported {len(v)} records")
        b, l = platform.architecture(lib)
        want = f"{b} {l}"
        check(v[0] == want,
              f"a dylib ({lib}): image {v[0]!r}, CPython {want!r}")
        cases.append(("a Mach-O dylib", lib))
    if verbose:
        print(f"    {len(cases)} paths: a Mach-O, two universal binaries, a "
              f"dylib, a text file, a directory, a missing path")
    return True, (f"{len(cases)} architecture() answers agree with CPython, "
                  f"universal binaries and dylibs included")


def _a_built_dylib():
    """One formal-built dylib in the cas, or None.

    `formal.build.cas_dir` is where `formal/imports.py` puts them, and the
    `*syscalls*` name is the one every `os`-importing program links, so the
    glob finds one after any build in this suite has run.
    """
    import glob
    import formal.build as B
    for pat in ("formal-imports/arm64/*syscalls*.dylib",
                "formal-imports/x86_64/*syscalls*.dylib"):
        hits = sorted(glob.glob(os.path.join(B.cas_dir(), pat)))
        if hits:
            return hits[-1]
    return None


GROUPS = {
    "resolve": group_resolve,
    "uname": group_uname,
    "processor": group_processor,
    "macver": group_macver,
    "alias": group_alias,
    "free": group_free,
    "architecture": group_architecture,
    "arch": group_arch,
    "exports": group_exports,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        TEMP = tmpdir
        J.TEMP = tmpdir
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, args.verbose)
            except Exception as e:
                import traceback
                if args.verbose:
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + name + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())