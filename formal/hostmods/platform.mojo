"""
platform.mojo - the `platform` module for the formal backend.

`formal/imports.py` resolves an import in four passes, and the FIRST is "a
Mojo source `<name>.mojo` or `<name>/__init__.mojo` in a search root WINS
OUTRIGHT, even over the host-module list". This file is that source for the
name `platform`, so the refusal thirty swept files were getting —

    imports 'platform', which is a host module (CPython standard library),
    which has no Mojo source for this backend to compile

— is gone. It is the largest single host-import row in
`tools/formal_sweep.py`'s "not-answerable/host-import" line that is reachable
at all, and every one of those thirty files asks for one name, `machine()`.

WHY IT LIVES HERE AND NOT IN ITS OWN DIRECTORY is `sys.mojo`'s story and is
not repeated: `formal/hostmods/` is a search root of `formal/imports.py` and
of nothing else in the tree, so a Mojo `platform` here captures `import
platform` for the formal backend without capturing it for the compiler's own
sources. See `formal/imports.py`'s `_HOSTMODS_ROOT`.

THE TWO CALLS THIS MODULE MAKES, AND NOTHING ELSE
------------------------------------------------
`uname(3)` and `sysctlbyname(3)`, both in libSystem, both wrapped in
`formal/hostmods/os/_syscalls.mojo` rather than here — that file holds every
libSystem call this backend makes, once, and `platform` needs its string
primitives anyway (a kernel string lives in a buffer the C library fills and
the caller cannot keep), so a second `str_alloc` here would be a second
implementation of a routine whose whole value is being the same one everywhere.

WHAT THIS TARGET CAN ANSWER, AND WHY EACH NAME IS HERE
-----------------------------------------------------
Everything CPython's `platform` can answer without a second process, a Python
interpreter, or a file it can read. Concretely:

  * the five `uname(3)` fields — `system`, `node`, `release`, `version`,
    `machine` — which is all of CPython's `os.uname()` is, in CPython's order,
    measured (see `_syscalls.mojo`'s `uts_str`);
  * `mac_ver()`'s release and machine, the product version from the kernel's
    `kern.osproductversion` and the machine from `uname`;
  * `system_alias`, which is pure string arithmetic over three strings and
    whose SunOS half is the part that has to be RIGHT for this to be CPython's
    `system_alias` and not a macOS-shaped function with the same name.

WHAT IS ABSENT, AND WHAT EACH ABSENCE NEEDS
-------------------------------------------
Every absence below needs an object a freestanding arm64 image that links
libSystem and nothing else does not have. None of them is a missing line of
code, and `test_formal_platform.py`'s `absent` group pins each one as a
REFUSAL so an omission cannot read as an implementation.

  * `sys.executable`, and `platform()` is the one absence it costs rather than
    one this module can hide. Everything `platform()` composes answers —
    `uname`, `mac_ver`, `system_alias`, `architecture` — and the string join is
    `platform_string` below. What is left is the path `platform()` passes to
    `architecture`, and there is NO WAY to discover it here: libSystem's
    `_NSGetExecutablePath` FAULTS on this target (measured four ways — `clang
    -O0`, `clang -O1`, a 64 KiB static buffer, and `ctypes` from CPython — all
    SIGSEGV) and `getprogname()` returns a basename, not a path. So
    `platform(exe, aliased, terse)` takes the path as a PARAMETER, which is why
    it has three parameters where CPython's has two, and why the caller passes
    `(0, 0)` for the two flags CPython defaults. The second difference is NOT
    ours to fix and is CPython's own subprocess: `uname -p`, which is
    `processor`. Both are at `platform`'s own docstring, with the measurements.
  * `libc_ver()`, `processor()` — `uname -p` and a readable C library, i.e. two
    subprocesses or a file. (CPython's own `_default_architecture` table would
    answer Darwin for `architecture` without `file(1)`, but only after `file` has
    failed, and reaching for it would be guessing the answer the subprocess
    exists to find — which is why `architecture` reads the header instead and
    agrees with CPython on every file shape, `/bin/ls`'s universal binary
    included.)
  * `python_version()`, `python_implementation()`, `python_build()`,
    `python_branch()`, `python_compiler()`, `python_revision()`,
    `python_version_tuple()` — there is no Python on this image. This module
    is compiled BY this project; `sys.version()` in `formal/hostmods/sys.mojo`
    answers for the COMPILER's target language, and that is a different
    question from "which Python am I running under".
  * `java_ver()`, `win32_ver()`, `win32_edition()`, `win32_is_iot()`,
    `ios_ver()`, `android_ver()`, `freedesktop_os_release()` — a JVM, the
    Windows API, an embedded iOS/Android property API, and `/etc/os-release`
    read as a file.
  * `invalidate_caches()` — there is no cache. There is no module storage on
    this path (`formal/hostmods/sys.mojo`), so every call here re-reads the
    kernel, and a CPython answer that would be FALSE here: CPython's
    `_uname_cache` holds the first answer forever, so a `machine()` that
    changed under a running program would be a bug in CPython and a feature
    here.
  * the CLASSES `uname_result`, `AndroidVer`, `IOSVersionInfo` — a type is not
    a value on this path, which is the same limit
    `bugs/FORMAL_module_state_no_storage.md` records.
  * the TUPLE-SHAPED three: `uname()`, `mac_ver()`, `system_alias()`,
    `java_ver()`, `win32_ver()`, `android_ver()`, `ios_ver()`. A tuple is a
    frame blob carved out of the callee's frame and cannot be returned across a
    dylib boundary at all, so each of these is spelled here as one function per
    component and every function says which component it is.

  `mac_ver()`'s MIDDLE component is the one place a tuple is not spelled out:
  CPython sets `versioninfo` to the literal `('', '', '')` on macOS and never
  computes it, so there is nothing to answer and inventing three empty-string
  functions would be three names with no computation behind them.

THE TWO SPELLING RULES EVERY FUNCTION HERE FOLLOWS
--------------------------------------------------
  * `-> str` or `-> int` on EVERY export, which is not documentation: the
    annotation is what puts `char *` in the module dylib's manifest signature,
    and without it a call result is a word of unknown provenance and `f() == g()`
    on two of those is an ADDRESS comparison
    (`bugs/FORMAL_string_equality_of_two_unclassified_words.md`).
  * NO DEFAULT ARGUMENT ANYWHERE. `system_alias` is the only function here that
    takes arguments and CPython's own signature for it has none to default, so
    there was never a spelling to drop; the measurement that a default is not
    applied across a dylib boundary at all is
    `bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`, and the
    functions CPython DOES give defaults to (`platform(aliased, terse)`,
    `architecture(executable, bits, linkage)`, `mac_ver(release, versioninfo,
    machine)`) are absent here or take their argument, so the question does not
    arise twice: `architecture_bits`/`architecture_linkage` both take the path
    and neither takes a preset, which is the one part of CPython's `architecture`
    signature this module cannot honour and each docstring says so.

MEMORY, AND WHO OWNS A STRING
-----------------------------
There is no module storage here, so there is nowhere to keep a `uname`
answer — which means `system()`, `machine()` and their four siblings each
make their own `uname(3)` call and each return a FRESH `malloc`'d buffer the
CALLER OWNS. `platform_free` gives it back. The alternative, one buffer filled
once and returned as an interior pointer, is the shape `formal/hostmods/
sys.mojo`'s `sys.stdout` refusal is about, and it is also what would make two
successive calls alias each other.

The functions that return an argument unchanged say so, and the string they
hand back is the CALLER'S and must not be passed to `platform_free`. Which is
which is stated at each definition, because `os.path` has the same split and a
caller who gets it wrong gets a double free.

BOTH BACKENDS, and that is worth saying because the module this one takes its
C library calls from says otherwise
----------------------------------------------------
`formal/hostmods/os/_syscalls.mojo`'s docstring used to say a module dylib
that calls into the C library "is arm64-only on this backend", and this module
inherits `uname`, `sysctlbyname` and `strcmp` from there — so it was written
expecting to inherit that too. It does not: measured on this tree, `machine()`
builds AND RUNS under `--backend=x86_64` and under `--backend=arm64`, and on
each it reports the architecture of the image it is running in, which is the
whole point of the name. That claim in `_syscalls.mojo` has since been
corrected in place, along with the five other modules that repeated it; what
the x86-64 backend does need is the right symbol per call, which is
`formal/model.py`'s `target_libc_symbol`.

A Rosetta-emulated x86-64 process on an Apple Silicon host sees
`hw.machine == "x86_64"`, so the x86-64 image's answer is `x86_64` and not this
process's `arm64`. That is correct behaviour rather than a discrepancy, and
`test_formal_platform.py`'s `arch` group is written to expect it.
"""


from os._syscalls import uts_str, kern_str, str_cmp
from os._syscalls import str_len, str_at, str_alloc, str_copy, str_build
from os._syscalls import str_dup, str_trunc, str_strip, str_replace_all
from os._syscalls import fs_free

# Which fact `os._syscalls.fs_macho_field` is asked for, as the two NUMBERS it
# takes. Numbers here rather than `os._syscalls`'s own names because a
# module-level constant is not exported as a word across a dylib boundary
# (`bugs/FORMAL_module_state_no_storage.md`) — which is why `_syscalls.mojo`
# spells the same two constants as `MACHO_WIDTH`/`MACHO_EXECUTABLE` for its own
# callers and this module repeats the numbers it passes. 0 is the pointer width
# in bits and 1 is "the kind of file `file -b` would call an executable"; both
# are documented at `fs_macho_field`.
MACHO_WIDTH = 0
MACHO_EXECUTABLE = 1
from os._syscalls import fs_macho_field


# The five fields of `uname(3)`, in the order `os.uname()` returns them, so a
# field number here means what it means in `uts_str`. Module-level names are
# not exported as a word across a dylib boundary — they are for THIS unit, and
# only this unit reads them.
U_SYSNAME = 0
U_NODENAME = 1
U_RELEASE = 2
U_VERSION = 3
U_MACHINE = 4

# CPython's `mac_ver()` reads the product version from
# `/System/Library/CoreServices/SystemVersion.plist` and falls back to `''`.
# The same product version is in the kernel's `kern.osproductversion`, which is
# one `sysctlbyname` away and needs no file to be read at all. Measured equal
# on this host by `test_formal_platform.py`, which asks CPython for the plist's
# value and this image for the sysctl's and compares them.
MACVER_MIB = "kern.osproductversion"


# ── what the kernel says the machine is ───────────────────────────────────

def system() -> str:
    """`platform.system()`: the operating system's name as the kernel spells
    it — `"Darwin"` on macOS, not `"macOS"`.

    `os.uname()[0]`, which is where CPython reads it. A `malloc`'d string the
    caller owns; see the module docstring.
    """
    return uts_str(U_SYSNAME)


def node() -> str:
    """`platform.node()`: the network name of this machine, as `gethostname`
    reports it.

    `os.uname()[1]`. Not a name this module can look up in a directory: there
    is no name service on this target and no DNS, so this is whatever the
    kernel was told at boot, which is exactly what CPython's own answer is.
    """
    return uts_str(U_NODENAME)


def release() -> str:
    """`platform.release()`: the kernel's own release string.

    `os.uname()[2]`, so on macOS this is the DARWIN release (what
    `platform.platform()` reports under the marketing name) and NOT the macOS
    product version — which is `mac_ver_release()` below, and the two
    differing is not a defect in either answer.
    """
    return uts_str(U_RELEASE)


def version() -> str:
    """`platform.version()`: the kernel's build string, in full.

    `os.uname()[3]`. It is long and contains spaces, `:` and `;` — it is a
    sentence, not a version number — and nothing here formats it: it is
    returned byte for byte as the kernel wrote it, because there is no float
    and no float arithmetic on this path to compute a version out of it.
    """
    return uts_str(U_VERSION)


def machine() -> str:
    """`platform.machine()`: the hardware name — `"arm64"` on this target.

    `os.uname()[4]`. This is the name thirty swept files import this module
    for, and it is a fact about the image the program is running IN, so a
    formal image can answer it exactly: it is the one question `platform` asks
    that a freestanding image has every reason to know.

    A `malloc`'d string the caller owns; see the module docstring.
    """
    return uts_str(U_MACHINE)


def uname_processor() -> str:
    """`platform.uname().processor`: `""` — always, and that is the answer.

    CPython's `uname()` resolves this one field LAZILY and, on any platform
    without a dedicated reader for it, by running `uname -p` as a subprocess.
    There is no subprocess here (FORMAL.md §1: libSystem and nothing else), so
    `""` is not an approximation of `"arm"`: it is CPython's own spelling of
    "cannot be determined", which is what its `_unknown_as_blank` produces and
    what its `processor()` returns on a host where the subprocess fails.

    The name says which part of CPython's `uname()` it is, because the tuple
    cannot be returned — see the module docstring.
    """
    return ""


# ── what macOS calls itself, as against what the kernel calls itself ───────

def mac_ver_release() -> str:
    """`platform.mac_ver()[0]`: the macOS PRODUCT version, e.g. `"26.6.2"`.

    Read from the kernel (`kern.osproductversion`) where CPython reads it from
    `/System/Library/CoreServices/SystemVersion.plist`. Two sources, one
    product version, and `test_formal_platform.py` asserts they agree rather
    than asserting a number — that assertion is the whole justification for the
    second source.

    `""` when the kernel has no such name, which is a macOS older than 10.13.4
    and is also CPython's own answer when the plist cannot be read: the name
    has a default of `''` and the fallback returns it unchanged. Not a name
    this target has any other way to spell.
    """
    return kern_str(MACVER_MIB)


def mac_ver_machine() -> str:
    """`platform.mac_ver()[2]`: the hardware name, with CPython's one rewrite.

    CPython takes `os.uname().machine` and maps `ppc` and `Power Macintosh` to
    the canonical `PowerPC`; everything else is returned unchanged. That is
    reproduced here rather than skipped, because "the canonical spelling" is
    part of the name's contract and this image could be asked about it: the
    rewrite is two comparisons and costs nothing.

    OWNERSHIP DIFFERS BETWEEN THE TWO BRANCHES, which is the one thing a caller
    has to be told twice. `uname`'s machine is a `malloc`'d buffer the caller
    owns, and on this target (`arm64`) that is what comes back; `"PowerPC"` is a
    string literal in this module's own text, in the read-only section of a
    dylib that outlives the call, and must NOT be passed to `platform_free`.
    So `platform_free` the result only when it is not the literal — which a
    caller cannot test, and does not have to: on any machine this backend can
    produce the literal branch is dead, so the honest rule is the one
    `platform_free`'s own docstring gives, and this function is called out here
    as the second place where the two answers differ.
    """
    var m = uts_str(U_MACHINE)
    if str_cmp(m, "ppc") == 0:
        return "PowerPC"
    if str_cmp(m, "Power Macintosh") == 0:
        return "PowerPC"
    return m


# ── CPython's `int()`, for one number in `system_alias` ───────────────────
#
# `system_alias` does exactly one arithmetic thing: it parses the leading
# component of a release string with `int()` and subtracts three. Reproducing
# `int()` is the whole difficulty, because `int()` accepts more than digits —
# surrounding whitespace, a sign, and single underscores BETWEEN digits — and
# a validator that accepts less turns a release string CPython rewrites into
# one this leaves alone, which is a wrong answer rather than a refusal.
#
# `int("5abc")` is a ValueError and CPython's `except ValueError: pass` LEAVES
# the release alone in that case, so the two functions below have to agree
# about validity exactly, not approximately. That is why they are two passes
# over the same walk rather than one function with a side channel: a value that
# is 0 is a value `int()` produces (`int("0")`), so there is no sentinel to
# return and no way to tell "0" from "did not parse" through one word.

def _int_is_space(b) -> int:
    """1 if the byte `b` is ASCII whitespace.

    BY NUMERIC COMPARISON, not by membership in a string literal, and the reason
    is the ARGUMENT rather than the escapes: `b` is a byte VALUE read out of `s`
    by `_int_at`, and a set is a POINTER, so asking one means allocating a
    one-byte string per call — inside the loop `_int_bounds` runs twice over
    every byte of every release string `system_alias` parses. The six bytes are
    named at each arm: SP, HT, LF, VT, FF, CR.

    The reason this function used to give was false and had stopped being true
    at `9023031b`: it said a literal's escapes are NOT interpreted on this path,
    so `"\\t"` here would be a backslash and a `t`. A literal IS decoded, inside a
    module as well as inside a program, on both architectures —
    `fire_compiler.py`'s `decode_c_escapes`, the decoder every engine shares,
    pinned by `test_formal_sys.py::test_a_literal_inside_a_module_is_decoded_too`.
    It no longer decides anything here, and the comparison above would be the
    right shape either way; `formal/hostmods/argparse.mojo` above its `_ws_set`
    and `formal/hostmods/textwrap.mojo`'s module docstring record the same
    correction for the `memset` sets that DO have the pointer to hand.
    """
    if b == 32:
        return 1
    if b == 9:
        return 1
    if b == 10:
        return 1
    if b == 11:
        return 1
    if b == 12:
        return 1
    if b == 13:
        return 1
    return 0


def _int_is_digit(b) -> int:
    """1 if the byte `b` is an ASCII decimal digit."""
    if b < 48:
        return 0
    if b > 57:
        return 0
    return 1


def _int_bounds(s) -> int:
    """The index one past the last non-whitespace byte of `s`.

    `s` is NUL-terminated, so this stops there; a NUL is not whitespace and
    not a digit, so it is excluded by both walks.
    """
    var i = 0
    var n = str_len(s)
    while i < n:
        if _int_is_space(_int_at(s, i)) == 0:
            break
        i = i + 1
    while n > i:
        if _int_is_space(_int_at(s, n - 1)) == 0:
            break
        n = n - 1
    return n


def _int_at(s, i) -> int:
    """The byte at `i` of `s`, through a declared pointee.

    A one-byte load is spelled `var q: Pointer[UInt8] = s + i` then
    `q.value()`: an EXPRESSION cannot be asked for a pointee it does not
    declare, which is the fact `formal/hostmods/json.mojo`'s `byte_at` is
    written around.
    """
    var q: Pointer[UInt8] = s + i
    return q.value()


def _int_ok(s) -> int:
    """1 if CPython's `int(s)` would succeed, 0 if it raises `ValueError`.

    The rule, in the order `int()` applies it: optional surrounding ASCII
    whitespace, an optional `+`/`-`, then one or more decimal digits with any
    number of single underscores BETWEEN them — never leading, never trailing
    and never doubled. Empty is 0, a lone sign is 0, and an underscore with no
    digit on one side of it is 0.
    """
    var n = _int_bounds(s)
    if n == 0:
        return 0
    var i = 0
    while i < n:
        if _int_is_space(_int_at(s, i)) == 1:
            i = i + 1
            continue
        break
    if i < n:
        var c = _int_at(s, i)
        if c == 43 or c == 45:
            i = i + 1
    var digits = 0
    while i < n:
        var c = _int_at(s, i)
        if _int_is_digit(c) == 1:
            digits = digits + 1
            i = i + 1
            continue
        if c == 95 and digits > 0 and i + 1 < n:
            if _int_is_digit(_int_at(s, i + 1)) == 1:
                i = i + 1
                continue
        return 0
    if digits == 0:
        return 0
    return 1


def _int_value(s) -> int:
    """The value CPython's `int(s)` would return. Only call it when
    `_int_ok(s)` is 1.

    Sign and underscores are consumed rather than accumulated: a sign flips the
    result at the end and an underscore contributes nothing, so one pass over
    the digits is enough and there is no second parse whose disagreement would
    be a wrong answer.

    `%lld` and not `%d` in the digit-to-string spelling in `system_alias`: a
    `%d` conversion is 32 bits wide on this path
    (`bugs/FORMAL_string_value_model.md` §2), and this value is small enough
    that it would not have shown — which is why it is spelled correctly rather
    than left to be discovered by a large release number later.
    """
    var n = _int_bounds(s)
    var i = 0
    var neg = 0
    while i < n:
        var c = _int_at(s, i)
        if c == 43 or c == 45:
            if c == 45:
                neg = 1
            i = i + 1
            continue
        break
    var v = 0
    while i < n:
        var c = _int_at(s, i)
        if _int_is_digit(c) == 1:
            v = v * 10 + (c - 48)
            i = i + 1
            continue
        i = i + 1
    if neg == 1:
        return 0 - v
    return v


# ── CPython's `system_alias` ──────────────────────────────────────────────
#
# `system_alias(system, release, version)` returns three strings, so it is
# three functions here; `_alias_part` is the one computation behind all three,
# because three copies of a SunOS rewrite is three things to keep in step and
# the sweep's "what does this backend ask of the operating system" is a
# question with a short answer precisely because it is not answered three
# times.
#
# `which` is 0 for the system, 1 for the release and 2 for the version, and
# the arguments are named `sysname`/`rel`/`ver` rather than CPython's
# `system`/`release`/`version` because `system` and `release` are FUNCTIONS in
# this module and a parameter of the same name would shadow them inside this
# body.

def _alias_part(which, sysname, rel, ver) -> str:
    """One component of CPython's `system_alias(sysname, rel, ver)`."""
    # bpo-35516, and it is the whole reason `Darwin` is not rewritten to
    # `macOS` here: CPython takes a `system`/`release` that may be a kernel's
    # rather than the running system's, and a Darwin release must not become a
    # macOS product version behind the caller's back. `platform()` does that
    # substitution itself, on purpose, where it can see both.
    if str_cmp(sysname, "SunOS") != 0:
        if which == 0 and (str_cmp(sysname, "win32") == 0
                           or str_cmp(sysname, "win16") == 0):
            return "Windows"
        return _alias_pick(which, sysname, rel, ver)

    # "SunOS releases below 5 really are SunOS", and the test is the release's
    # own lexicographic order, exactly as CPython writes it.
    if str_cmp(rel, "5") < 0:
        return _alias_pick(which, sysname, rel, ver)

    # The system and the version do not depend on the arithmetic below, so
    # both are answered without allocating anything. That is not an
    # optimisation: `system_alias_system` therefore never mallocs at all, which
    # is what lets its docstring say the answer is always an alias or a
    # literal, and what makes "which of the three owns this buffer" a
    # property of the ARGUMENTS rather than of the function.
    if which == 0:
        return "Solaris"
    if which == 2:
        return ver

    # The release rewrite: CPython splits on `.`, parses `l[0]` with `int()`,
    # and puts `int(l[0]) - 3` back in its place. So only the part BEFORE the
    # first dot is ever touched, and only the whole-string case needs a copy.
    var d = _alias_dot_at(rel)
    var head = rel
    var owned = 0
    if d >= 0:
        head = str_copy(str_alloc(d), rel, d)
        owned = 1
    if _int_ok(head) == 0:
        # CPython's `except ValueError: pass`: the release keeps the component
        # it came with.
        if owned == 1:
            fs_free(head)
        return rel
    var ns = _int_to_str(_int_value(head) - 3)
    if owned == 1:
        fs_free(head)
    if d < 0:
        return ns
    var out = str_build(ns, ".", rel + d + 1)
    fs_free(ns)
    return out


def _alias_pick(which, a, b, c) -> str:
    """The `which`th of three values, by index. A tuple in everything but the
    name, and a function because a value that is a blob of three words cannot
    be returned across a dylib boundary."""
    if which == 0:
        return a
    if which == 1:
        return b
    return c


def _alias_dot_at(rel) -> int:
    """The index of the first `.` in `rel`, or -1."""
    var n = str_len(rel)
    var i = 0
    while i < n:
        if str_at(rel, i, ".") == 1:
            return i
        i = i + 1
    return 0 - 1


def _int_to_str(v) -> str:
    """CPython's `str(v)` for an integer, in a buffer the CALLER OWNS.

    `%lld` for the reason `_int_value` names. `snprintf` and not a hand-rolled
    digit loop: this is a formatting question the C library already answers,
    and `formal/hostmods/os/_syscalls.mojo` has said twice that a second
    implementation of a libc routine is worse than the call.
    """
    var d = str_alloc(24)
    snprintf(d, 24, "%lld", v)
    return d


def system_alias_system(sysname, rel, ver) -> str:
    """`platform.system_alias(system, release, version)[0]`.

    CPython's `system_alias` in full, not the macOS-shaped identity this target
    would get by accident: `SunOS` becomes `Solaris`, `win32`/`win16` become
    `Windows`, and everything else — including `Darwin` — is returned
    unchanged, deliberately (bpo-35516; see `_alias_part`).

    An ALIAS of `sysname` unless the name is one of the three above, in which
    case it is a literal in this module's own text. So: do not pass the result
    to `platform_free`.
    """
    return _alias_part(0, sysname, rel, ver)


def system_alias_release(sysname, rel, ver) -> str:
    """`platform.system_alias(system, release, version)[1]`.

    CPython's rewrite: for a `SunOS` release at or above `5`, the leading
    component is decremented by three — the marketing release is three lower
    than the kernel's — and the rest of the string is kept. `""`, `"4.0"`,
    `"5"` and `"10.3"` come back as themselves, `"5"`, `"5.11"` and `"10.3"`
    as `"2"`, `"2.11"` and `"7.3"`.

    A `malloc`'d string the caller OWNS only in the SunOS branch, and an alias
    of `rel` otherwise, so `platform_free` applies to the result only when
    `sysname` is `"SunOS"`. Each component function says so because a caller
    that frees the wrong one of the three has a double free, and which of the
    three allocates depends on the ARGUMENTS rather than on the function.
    """
    return _alias_part(1, sysname, rel, ver)


def system_alias_version(sysname, rel, ver) -> str:
    """`platform.system_alias(system, release, version)[2]`.

    ALWAYS `ver`, unchanged. CPython rewrites the system name and the release
    and never touches the version, so this is the identity — shipped anyway,
    because a caller porting `system_alias` needs three answers and two of them
    existing would make the third look like a gap.

    An ALIAS of `ver`. Do not pass it to `platform_free`.
    """
    return _alias_part(2, sysname, rel, ver)


# ── what the executable IS ─────────────────────────────────────────────────

def architecture_bits(exe) -> str:
    """`platform.architecture(exe)[0]`: `"64bit"`, `"32bit"`, or `"64bit"`.

    THE FIRST HALF of CPython's `architecture`, whose answer is a TUPLE and a
    tuple on this path is a frame blob that cannot cross a boundary — hence the
    two functions. `architecture_bits` and `architecture_linkage` are one
    question asked twice, and `architecture_linkage`'s docstring says which one
    to believe when they seem to disagree.

    CPython reads the answer out of `file -b <exe>` and looks for `32-bit` or
    `64-bit` in it. This reads the same fact out of the file's own Mach-O header
    (`os._syscalls.fs_macho_field`, `MACHO_WIDTH`), which is where `file` reads
    it, so the two agree by construction rather than by coincidence — and no
    subprocess is involved, which is the whole reason the question was open for
    as long as it was.

    A path that is not a Mach-O answers CPython's DEFAULT, which is
    `sizeof(void *) * 8` — and on this target a value IS a 64-bit word, so that
    is `"64bit"` whether or not the file was readable. That is CPython's own
    behaviour (`platform.architecture('fire.py')` is `('64bit', '')` here, and
    so is `platform.architecture('/no/such/file')`), and it is stated here
    because it is the one place this function answers without having read
    anything.

    NOT ANSWERABLE: the `bits` PRESET parameter. CPython's signature is
    `architecture(executable, bits='', linkage='')` and a caller may pass
    `bits='32bit'` to be told `('32bit', …)` for a file it cannot read; a
    default argument is not applied across a dylib boundary
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`), so there is
    no spelling of "the default, or this" here, and a caller that needs one
    has to compare the two answers itself.
    """
    var b = fs_macho_field(exe, MACHO_WIDTH)
    if b == 32:
        return "32bit"
    return "64bit"


def architecture_linkage(exe) -> str:
    """`platform.architecture(exe)[1]`: `"Mach-O"`, or `""`.

    CPython's second half is "which of the formats `file` named is in the
    output" — `Mach-O` here, `ELF` on Linux, `PE`/`WindowsPE` on Windows. Only
    the first is a format this target has: both architectures `formal` emits
    are Mach-O and the ELF image it also emits is the Linux one, where CPython
    would answer `'ELF'`, and saying so would be a claim about a machine this
    image does not run on.

    `"Mach-O"` for an EXECUTABLE and `""` for everything else, and the second
    half of that is CPython's parser being older than `file(1)` rather than a
    fact about Mach-O: CPython accepts a file whose `file -b` output contains
    the word `executable` or the phrase `shared object`, and this macOS's `file`
    prints "Mach-O 64-bit dynamically linked shared library" for a dylib — never
    that phrase — so CPython answers `architecture(any_dylib)` as
    `('64bit', '')` here. MEASURED on this host, and emulated deliberately: this
    module is a mirror of CPython, so a right answer that disagrees with the
    thing being mirrored is still a wrong answer for a caller. The reading is
    the header's `filetype` (`os._syscalls.fs_macho_field`'s `MACHO_EXECUTABLE`),
    which is where `file` reads it too.

    `""` for anything that is not a Mach-O either, which is CPython's own answer
    for a file whose format it does not recognise (`platform.architecture
    ('fire.py')` is `('64bit', '')`), and it is the answer a caller can act on:
    CPython's `platform()` puts `linkage` in the string it builds, so `""` drops
    out.

    THE TWO HALVES CANNOT DISAGREE about the file and only disagree about the
    default: `architecture_linkage("")` says nothing about the width, while
    `architecture_bits` answers CPython's default for a file it could not read.
    Both are CPython's answers for the same file, and
    `test_formal_platform.py`'s `arch` group asks CPython for the PAIR rather
    than for one half at a time.
    """
    if fs_macho_field(exe, MACHO_EXECUTABLE) == 1:
        return "Mach-O"
    return ""


# ── the string CPython builds out of the pieces ───────────────────────────
#
# `_platform(*parts)` in CPython is a VARIADIC function over an arbitrary number
# of strings, and a variadic Mojo function is refused on this path
# (`model.variadic_call_refusal`). So the transcription here is SIX-PART, which
# is exactly the number CPython's own `platform()` passes on macOS — two when
# `terse`, six otherwise — and an absent part is the EMPTY STRING rather than a
# missing argument, because `filter(len, args)` is what makes an empty part
# disappear and it tests the length of the part BEFORE the strip. Six is also
# the widest signature `formal/hostmods/re.mojo` uses, which
# `test_formal_re_formal.py`'s ABI group still checks every signature against.
#
# Nothing is lost by fixing the arity and the two shapes a caller actually
# needs are covered: a terse call passes two parts and four empties, and a full
# call passes six.

def platform_string(p0, p1, p2, p3, p4, p5) -> str:
    """CPython's `platform._platform(*parts)`: the join, then eleven cleanups.

    **The NAME is CPython's with the leading underscore removed, and that is
    this path's export rule and nothing else.** `platform._platform` is private
    in CPython by convention and reachable, because CPython has no cross-module
    ABI to satisfy; here a name beginning with `_` is denied by
    `doc/ABI.md`'s rule (`reflect.export_exclusions`'s `EXCL_PRIVATE`, measured
    and settled in `bugs/FORMAL_known_limits.md` §1.1) with no opt-in, so a
    caller cannot import it and the corner cases below could not be tested. One
    public name rather than a private definition and a public alias, because two
    names for one function is one implementation and one place to keep it right.

    All eleven steps are transcribed, because the ones that cannot fire on this
    host are exactly the ones a macOS-only transcription would get wrong: none
    of `system()`, the product version, `machine()`, `architecture`'s two
    answers or the empty `processor` contains a space, a slash, a colon or the
    word `unknown`, so an implementation that only joined would be
    INDISTINGUISHABLE from a correct one here — and wrong the moment a node name
    or a release string carried one.

    The three decisions worth naming, in the order CPython makes them:

    * **`filter(len, …)` tests the part BEFORE the strip, and that is
      observable.** `platform_string('', 'a')` is `'a'` and `platform_string('   ', 'a')` is
      `'-a'` — measured on this host's CPython — because the second part is
      non-empty, survives the filter, strips to nothing, and contributes an
      EMPTY piece to the join. So the emptiness test and the strip are two
      questions about two different strings, which is why they are two passes
      here (the same reason `_int_ok`/`_int_value` are) rather than one.
    * **`str_replace_all(s, 'unknown', '')` removes EVERY occurrence, anywhere,
      including inside a word**, which is why this is a substring replace and
      not a test for the word: `platform_string('unknown-x')` is `'-x'`, leading dash
      and all, because only TRAILING dashes are stripped at the end.
    * **the `--` fold is a fixed point, not a counted number of passes.** A part
      that ENDS in `-` (`'5-'`) produces `'5--'`, which one pass folds to `'5-'`
      — and which, before the trailing strip, is stable. CPython's own
      `while True` with a comparison IS the loop; `str_cmp` is the comparison.

    The caller owns the result. It is a fresh buffer on every path, including
    when nothing was replaced: `str_replace_all` copies rather than returning
    its argument when there are no hits, so `platform_free` is right for it.
    """
    var parts = [p0, p1, p2, p3, p4, p5]
    var joined = ""
    var first = 1
    var i = 0
    while i < 6:
        var part = parts[i]
        if str_len(part) > 0:
            var piece = str_strip(part)
            if first == 1:
                joined = str_dup(piece)
                first = 0
            else:
                joined = str_build(joined, "-", piece)
        i = i + 1
    # CPython's eight single-character replacements, in its order. Written out
    # one per line rather than looped over a SET because they are a FIXED
    # SEQUENCE: the order is CPython's and a set would assert that no output
    # can be an input of another, which happens to be true here and is not a
    # property a reader should have to check to trust the transcription.
    var p = str_replace_all(joined, " ", "_")
    p = str_replace_all(p, "/", "-")
    p = str_replace_all(p, "\\", "-")
    p = str_replace_all(p, ":", "-")
    p = str_replace_all(p, ";", "-")
    p = str_replace_all(p, "\"", "-")
    p = str_replace_all(p, "(", "-")
    p = str_replace_all(p, ")", "-")
    p = str_replace_all(p, "unknown", "")
    while 1:
        var cleaned = str_replace_all(p, "--", "-")
        if str_cmp(cleaned, p) == 0:
            break
        p = cleaned
    var n = str_len(p)
    while n > 0 and str_at(p, n - 1, "-") == 1:
        n = n - 1
    return str_trunc(p, n)


def platform(exe, aliased, terse) -> str:
    """CPython's `platform(aliased=…, terse=…)`, AND the executable path.

    **CPython's own signature is two flags and this takes three.** The third is
    `sys.executable`, which CPython reads from its own `argv[0]` and which this
    image has no way to discover: libSystem's `_NSGetExecutablePath` is the
    function that answers it and it FAULTS on this target — measured four ways,
    `clang -O0`, `clang -O1`, a 64 KiB static buffer and `ctypes` from CPython,
    all SIGSEGV, so it is the library call and not the caller — and
    `getprogname()` returns a bare basename rather than a path. So the path is a
    PARAMETER, exactly as it already is for `architecture_bits(exe)` and
    `architecture_linkage(exe)` above, and the two flags have NO DEFAULTS
    because a default argument is not applied across a dylib boundary
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`): a caller
    writes `platform(exe, 0, 0)` where CPython would write `platform()`.

    The flags are 1/0 like every flag on this path.

    What is transcribed is the whole of CPython's body on THIS system: `uname`,
    the `machine == processor` rule, `system_alias`, the Darwin branch that
    turns `Darwin` + a kernel release into `macOS` + a product version, and then
    the GENERIC handler. The Windows, Linux and Java arms are absent branches on
    a kernel that reports `Darwin`, and the three functions they need
    (`win32_ver`, `libc_ver`, `java_ver`) are absent from this module with the
    capability behind each one named at its own docstring.

    **The answer it can give is CPython's minus the `arm`.** CPython resolves
    `uname().processor` by running `uname -p` and this path has no subprocess,
    so `uname_processor()` answers `""` — which is CPython's OWN spelling of
    "cannot be determined" (`_unknown_as_blank`), and is what
    `test_formal_platform.py`'s `processor` group pins. On this host CPython's
    `platform()` is `'macOS-26.6.2-arm64-arm-64bit-Mach-O'` and this is
    `'macOS-26.6.2-arm64-64bit-Mach-O'`: the difference is exactly the one word
    a subprocess produces. A test comparing the two strings directly would be
    testing `uname -p`, so the oracle is CPython's `_platform` over this
    module's own pieces.

    The caller owns the result (`platform_free`), as it does for every string
    this module allocates.
    """
    var sysname = system()
    var rel = release()
    var ver = version()
    var mach = machine()
    var proc = uname_processor()
    if str_cmp(mach, proc) == 0:
        proc = ""
    if aliased != 0:
        sysname = system_alias_system(sysname, rel, ver)
        rel = system_alias_release(sysname, rel, ver)
        ver = system_alias_version(sysname, rel, ver)
    if str_cmp(sysname, "Darwin") == 0:
        var macos_rel = mac_ver_release()
        if str_len(macos_rel) > 0:
            sysname = "macOS"
            rel = macos_rel
    if terse != 0:
        return platform_string(sysname, rel, "", "", "", "")
    var bits = architecture_bits(exe)
    var linkage = architecture_linkage(exe)
    return platform_string(sysname, rel, mach, proc, bits, linkage)


# ── memory ────────────────────────────────────────────────────────────────

def platform_free(p) -> int:
    """Release a string one of this module's FUNCTIONS allocated. 0.

    `system`, `node`, `release`, `version`, `machine`, `mac_ver_release`,
    `mac_ver_machine` and `system_alias_release` each `malloc` their answer on
    every call, so this is what gives them back. `os.os_free` is the same
    `free` through the same wrapper, and using either on the other's strings is
    correct: one allocator, one `free`.

    A string this module RETURNED UNCHANGED from one of its arguments, or that
    it returned as one of its own string literals, is not this module's to
    release and must NOT be passed here. There are two such cases and both say
    so where they are: the three `system_alias_*` functions, and
    `mac_ver_machine`'s `"PowerPC"` branch. `os.path` has the same split for
    the same reason.
    """
    return fs_free(p)