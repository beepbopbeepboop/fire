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

  * `platform()`, and it is ONE call away. It needs `architecture()`, which
    asks `file(1)` what the executable is, and everything else it composes is
    here. Answering it by hardcoding `('64bit', 'Mach-O')` would be right on
    this target and wrong on every other, which is the wrong `time.time()`
    shape `formal/hostmods/time.mojo`'s docstring refuses.
  * `architecture()`, `libc_ver()`, `processor()` — `file(1)`, the executable's
    own bytes, and `uname -p`. Three subprocesses or a readable file. (Its own
    `_default_architecture` table would answer Darwin without them, but only
    after `file` has failed, and reaching for it would be guessing the answer
    the subprocess exists to find.)
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
    machine)`) are absent here anyway, so the question does not arise twice.

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
`formal/hostmods/os/_syscalls.mojo`'s docstring says a module dylib that calls
into the C library "is arm64-only on this backend", and this module inherits
`uname`, `sysctlbyname` and `strcmp` from there — so it was written expecting
to inherit that too. It does not: measured on this tree, `machine()` builds AND
RUNS under `--backend=x86_64` and under `--backend=arm64`, and on each it
reports the architecture of the image it is running in, which is the whole
point of the name. (`os.getcwd()`, measured the same way on the same tree,
also builds and runs on x86_64, so that claim in `_syscalls.mojo` is stale for
whatever `os` too — not this claim's file to correct, and recorded here only so
nobody reads this paragraph as the opposite finding.)

A Rosetta-emulated x86-64 process on an Apple Silicon host sees
`hw.machine == "x86_64"`, so the x86-64 image's answer is `x86_64` and not this
process's `arm64`. That is correct behaviour rather than a discrepancy, and
`test_formal_platform.py`'s `arch` group is written to expect it.
"""


from os._syscalls import uts_str, kern_str, str_cmp
from os._syscalls import str_len, str_at, str_alloc, str_copy, str_build
from os._syscalls import fs_free


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

    BY NUMERIC COMPARISON, not by a character set in a string literal, and the
    reason is the value model: a Mojo string literal is copied byte for byte
    and escapes are NOT interpreted (`bugs/FORMAL_string_value_model.md`), so
    `"\t"` in a source is two characters — a backslash and a `t` — and a
    whitespace SET written that way would match backslashes and letters. The
    six bytes are named at each arm: SP, HT, LF, VT, FF, CR.
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