#!/usr/bin/env python3
"""The symbol an unbound C callee binds to on THIS target, measured three ways.

    python3 test_formal_libc_symbol.py [-v] [group ...]

Groups: `table`, `retkind`, `builtin_abi`, `binding`, `dirent`, `stat`, `retvalue`. With no argument, all of them.

WHAT THIS IS ABOUT. `readdir` is one function in a C header and TWO in macOS's
C library: `_readdir` fills a `struct dirent` with a 32-bit `ino_t` (4-byte
`d_ino`, `d_reclen` at 4, `d_name` at 8) and `_readdir$INODE64` fills one with
a 64-bit `ino_t` (8-byte `d_ino`, `d_seekoff`, `d_reclen` at 16, `d_namlen` at
18, `d_name` at 21). `<sys/dirent.h>` chooses between them with
`#if __DARWIN_64_BIT_INO_T`, so a C program compiled for a 64-bit target — every
program clang builds for arm64 AND for x86_64 — calls the `$INODE64` one. A
Mojo source spells the bare name and there is no header to redirect it, so the
BACKEND has to know which of the two the target means
(`formal/model.py`'s `target_libc_symbol`), and `stat`, `lstat`, `fstat`,
`opendir` and the rest of that family are the same question.

Why it is worth a file of its own: BOTH symbols exist on x86-64, so the wrong
one is not a link error. The image builds, loads, runs and answers. It answered
`os.listdir("…")` as `cc.txt` where CPython says `ccc.txt`, with a count one
too high; it answered `os.path.isfile(…)` as 0, `getsize` as 0 and `st_mode` as
41572, none of which is a number any program should have believed
(`FORMAL_x86_64_byte_read_of_a_libc_returned_pointer_reads_the_wrong_bytes`,
whose three candidate causes — the byte read, the element read, the copy — were
each measured and each wrong).

WHY arm64 IS NOT TOUCHED, and why that is measured rather than assumed: arm64
has no 32-bit `ino_t`, libsystem_c exports no `$INODE64` twin for
`arm64-macos` (the linker says `Undefined symbols for architecture arm64` when
a C program asks for it), and the bare name there IS the 64-bit-inode function —
which is why every arm64 case in the tree agreed with CPython all along.
Emitting the `$INODE64` spelling on arm64 would trade a silent wrong answer for
a link failure, so `target_libc_symbol` is asked with the target and answers per
target.

THE GROUPS, and why there are several. `table` asks the DECISION as a
function, which is cheap and pins the two halves that could drift (the table and
the suffix; the Mach-O-only, x86_64-only gate). `builtin_abi` is the same kind of
question with the opposite answer — the three builtins whose C NAMESAKE EXISTS,
so the bind audit's provider check waves them through and an image calling one
links into a function of a different signature (`double pow(double, double)`,
`int abs(int)`); `formal/model.py::FOREIGN_ABI_BUILTINS` refuses them at the call
and this group is what says that refusal is load-bearing rather than redundant.
`binding` reads the built image's own dyld bind stream, so what is asserted
is the symbol the LOADER will look up rather than what a function returned — the two were the same decision
until they were not. `dirent` and `stat` then BUILD and EXECUTE, and compare
against CPython in this process: 32 bytes of each of the first `readdir`
entries against `ctypes`' own `readdir`, and six `struct stat` fields read at the
offsets this target declares against `os.stat`. A group that only inspected the
symbol name would still be green if the struct at the other end were the wrong
one; these two are not.

BOTH ARCHITECTURES, and x86-64 runs under Rosetta 2 on Apple Silicon and is
SKIPPED (not failed) on a host with no x86-64 support at all, with the reason
printed. Where a case has an answer on both, the two must AGREE as well as match
CPython — the two backends are separate implementations of one lowering, so their
agreement is evidence and CPython is the arbiter of whether the agreement is
right.
"""
import argparse
import os
import platform
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
# The per-child budgets are `exec_budget`'s, for the reason its docstring gives:
# a wall clock sized for "much more than a tiny program needs" fires on a loaded
# machine, and a timeout inside a test file is reported as an ordinary FAIL of
# the COMPILER. This file used to spell its own (300 and 60), which is the same
# number in a place no reader can check against the others.
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

# The record terminator, for the reason every other formal test file gives
# (`test_formal_dylib.py` states it): a separator this suite can read back
# without asking whether the image decoded a literal, `@@` being two bytes a
# real newline cannot collide with.
REC = "@@"

# How many bytes of each `struct dirent` the `dirent` group dumps. 32 is
# `d_reclen` for every entry macOS returns for a short name, so one dump covers
# the whole record INCLUDING the first bytes of the next one — which is how the
# two layouts tell themselves apart at a glance.
DIRENT_BYTES = 32

# The `struct stat` fields the `stat` group reads, as `(label, reader, offset,
# os.stat attribute)`. The offsets are the ones
# `formal/hostmods/os/_syscalls.mojo` documents, checked here against the
# layout ctypes reports for THIS host's `struct stat` (0 dev, 4 mode, 6 nlink,
# 8 ino, 16 uid, 20 gid, 24 rdev, 96 size, 104 blocks, 112 blksize) — and they
# are read through THAT module's own `le16`/`le32`/`le64` rather than through a
# fresh copy of the reading, so this group is about the BINDING and not about a
# second implementation of a byte read. `st_ino` at 8 and `st_size` at 96 are
# the two a 32-bit-inode `stat` moves, and `st_blksize` at 112 is past
# everything the other layout fills.
STAT_FIELDS = [
    ("mode", "le16", 4, "st_mode"),
    ("nlink", "le16", 6, "st_nlink"),
    ("ino", "le64", 8, "st_ino"),
    ("uid", "le32", 16, "st_uid"),
    ("gid", "le32", 20, "st_gid"),
    ("size", "le64", 96, "st_size"),
    ("blocks", "le64", 104, "st_blocks"),
    ("blksize", "le32", 112, "st_blksize"),
]


# ── running an image ───────────────────────────────────────────────────────

def rosetta():
    """Can this host run an x86-64 image at all? True / False / None (not Darwin).

    None means "this is not a macOS host", which is a different answer from
    False and gets its own message: the x86-64 image is a Mach-O and there is
    nothing to run it with anywhere else.
    """
    if sys.platform != "darwin":
        return None
    try:
        # A host probe, not compiled code: `arch` running `/usr/bin/true`, whose
        # answer is whether this host can run an x86-64 image at all. The RUN
        # budget because it is the cheapest child in this file, and a comment
        # because the same number as an image run would otherwise be ambiguous.
        p = subprocess.run(["arch", "-x86_64", "/usr/bin/true"],
                           capture_output=True, timeout=RUN_TIMEOUT_S)
        return p.returncode == 0
    except Exception:
        return False


def build(src, out, arch):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           "--backend=" + arch, "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=COMPILE_TIMEOUT_S, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(out, arch):
    """`(rc, stdout, stderr)`, and a HANG reported rather than raised.

    A formal image that never terminates is one of the wrong answers these
    groups exist to catch — `os.listdir` on the wrong `readdir` loops forever,
    because `d_name` at the wrong offset never finds its NUL — and the way that
    showed up before was a `TimeoutExpired` escaping the runner. 124 is the
    shell's convention for a timeout and the message says which case it was.
    """
    argv = [out]
    if arch == "x86_64" and sys.platform == "darwin":
        argv = ["arch", "-x86_64", out]        # Rosetta 2
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return 124, "", f"the image did not finish within {RUN_TIMEOUT_S}s"
    return p.returncode, p.stdout, p.stderr


def records(text):
    """`{label: value}` from `label=value@@` records."""
    out = {}
    for chunk in text.split(REC):
        chunk = chunk.strip()
        if not chunk:
            continue
        label, _, value = chunk.partition("=")
        out[label] = value
    return out


def linked_dylibs(image_path):
    """The install names in `image_path`'s LC_LOAD_DYLIB commands.

    Needed because the image that makes the C call is not always the
    executable: `from os._syscalls import readdir` puts the call inside that
    MODULE's dylib, and the executable binds only `printf` and the module's
    mangled exports. Reading the wrong image's bind stream would assert nothing
    about `readdir` at all.
    """
    with open(image_path, "rb") as f:
        data = f.read()
    if struct.unpack_from("<I", data, 0)[0] != 0xFEEDFACF:
        raise ValueError(f"{image_path} is not a 64-bit Mach-O")
    ncmds = struct.unpack_from("<I", data, 16)[0]
    off, names = 32, []
    for _ in range(ncmds):
        cmd, cmdsize, nameoff = struct.unpack_from("<III", data, off)
        if cmd == 0x0C:                        # LC_LOAD_DYLIB
            stop = data.index(b"\0", off + nameoff)
            names.append(data[off + nameoff:stop].decode())
        off += cmdsize
    return names


# ── the dyld bind stream, read back out of a built image ───────────────────

BIND_OPCODE_MASK = 0xF0
BIND_IMMEDIATE_MASK = 0x0F
BIND_OPCODE_DONE = 0x00
BIND_OPCODE_SET_DYLIB_ORDINAL_IMM = 0x10
BIND_OPCODE_SET_DYLIB_SPECIAL_IMM = 0x30
BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM = 0x40
BIND_OPCODE_SET_TYPE_IMM = 0x50
BIND_OPCODE_SET_ADDEND_SLEB = 0x60
BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB = 0x70
BIND_OPCODE_ADD_ADDR_ULEB = 0x80
BIND_OPCODE_DO_BIND = 0x90
BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB = 0xA0
BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED = 0xB0
BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB = 0xC0


def bind_symbols(image_path):
    """The C symbol names in `image_path`'s classic dyld bind stream.

    Read out of the IMAGE rather than asked of the codegen, because the claim
    under test is about what the loader will look up: `formal/macho_linker.py`
    writes the names into the `LC_DYLD_INFO_ONLY` bind stream and dyld prepends
    the Mach-O underscore when it resolves them, so this list is one step from
    the `dlsym` that decides whether the image runs at all.

    A `ValueError` on an opcode this decoder does not implement, rather than a
    skip: a linker that grew a new opcode would otherwise make this group
    silently check less than it says it checks.
    """
    with open(image_path, "rb") as f:
        data = f.read()
    if struct.unpack_from("<I", data, 0)[0] != 0xFEEDFACF:
        raise ValueError(f"{image_path} is not a 64-bit Mach-O")
    ncmds = struct.unpack_from("<I", data, 16)[0]
    off, bind_off, bind_size = 32, None, None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == 0x80000022:                  # LC_DYLD_INFO_ONLY
            bind_off, bind_size = struct.unpack_from("<II", data, off + 16)
            break
        off += cmdsize
    if bind_off is None:
        raise ValueError(f"{image_path} carries no LC_DYLD_INFO_ONLY, so it "
                         f"binds nothing by a bind stream")
    names = []
    i, end = bind_off, bind_off + bind_size
    while i < end:
        op = data[i]
        i += 1
        opcode, imm = op & BIND_OPCODE_MASK, op & BIND_IMMEDIATE_MASK
        if opcode in (BIND_OPCODE_SET_DYLIB_ORDINAL_IMM,
                      BIND_OPCODE_SET_DYLIB_SPECIAL_IMM,
                      BIND_OPCODE_SET_TYPE_IMM):
            continue                            # one byte, already consumed
        if opcode == BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM:
            i += 1                              # the trailing FLAGS byte
            stop = data.index(b"\0", i)
            names.append(data[i:stop].decode())
            i = stop + 1
            continue
        if opcode in (BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB,
                      BIND_OPCODE_ADD_ADDR_ULEB,
                      BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB):
            i = _uleb_end(data, i)
            continue
        if opcode == BIND_OPCODE_SET_ADDEND_SLEB:
            i = _sleb_end(data, i)
            continue
        if opcode in (BIND_OPCODE_DO_BIND, BIND_OPCODE_DONE):
            continue
        if opcode == BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED:
            i += 2
            continue
        if opcode == BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB:
            i = _uleb_end(data, i)
            i = _uleb_end(data, i)
            continue
        raise ValueError(f"{image_path}: bind opcode 0x{op:02x} at "
                         f"{i - 1} is not one this decoder implements")
    return names


def _uleb_end(data, i):
    while True:
        byte = data[i]
        i += 1
        if not byte & 0x80:
            return i


def _sleb_end(data, i):
    while True:
        byte = data[i]
        i += 1
        if not byte & 0x80:
            return i


# ── 1. `table`: the decision, as a function ────────────────────────────────

def group_table(verbose):
    """`target_libc_symbol` per target, and `libc_source_name` back again."""
    from formal.model import (INODE64_DUAL_LIBC, INODE64_SUFFIX,
                              libc_source_name, target_libc_symbol)
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
        elif verbose:
            print(f"      ok: {msg}")

    # The two names this whole file is about, on each of the three targets the
    # backend can emit. `("x86_64", "elf")` is glibc, which has one `readdir`
    # and one `stat` and both are 64-bit-ino; it is in the table because a
    # `sys.platform` probe instead of a `fmt` parameter would have applied a
    # macOS fix to a Linux image.
    for name in ("readdir", "stat", "opendir", "lstat"):
        check(target_libc_symbol(name, "x86_64", "macho") == name + INODE64_SUFFIX,
              f"x86_64 macho binds {name} as {name}{INODE64_SUFFIX}")
        check(target_libc_symbol(name, "arm64", "macho") == name,
              f"arm64 macho binds {name} unchanged (no $INODE64 twin exists "
              f"for arm64-macos)")
        check(target_libc_symbol(name, "x86_64", "elf") == name,
              f"x86_64 elf binds {name} unchanged (glibc has one of each)")

    # Names with no second spelling are returned untouched on every target,
    # which is the answer for the whole C library outside the table — including
    # the ones the host modules call on every path.
    for name in ("printf", "malloc", "free", "getcwd", "memcmp", "open",
                 "read", "write", "close", "lseek", "uname"):
        for arch, fmt in (("x86_64", "macho"), ("arm64", "macho"),
                          ("x86_64", "elf")):
            check(target_libc_symbol(name, arch, fmt) == name,
                  f"{arch}/{fmt} binds {name} unchanged")

    # The table and the suffix are two halves of one fact: every name in the
    # table has to be one the suffix can be appended to, or a name added to the
    # table without the suffix would be emitted as the bare name again.
    check(all(not n.endswith(INODE64_SUFFIX) for n in INODE64_DUAL_LIBC),
          f"no name in INODE64_DUAL_LIBC already carries {INODE64_SUFFIX}")
    check(all(target_libc_symbol(n, "x86_64", "macho").endswith(INODE64_SUFFIX)
              for n in INODE64_DUAL_LIBC),
          f"all {len(INODE64_DUAL_LIBC)} names in the table are re-spelled on "
          f"x86_64 macho")

    # The inverse, which the link audit depends on: it asks a HOST dlsym
    # whether the C library provides a symbol, and that dlsym runs in this
    # python3 — so on an arm64 host `readdir$INODE64` cannot be found and
    # asking about it would refuse a correct x86-64 image.
    # A C IDENTIFIER MAY BEGIN WITH AN UNDERSCORE, and this table used to
    # assert the opposite in three of its seven rows -- `_readdir` → `readdir`,
    # `_printf` → `printf`, `_os_syscalls_readdir_9f63a2` →
    # `os_syscalls_readdir_9f63a2`.  All three were the same wrong inverse:
    # `libc_source_name` is asked "what did the SOURCE spell?", and the only
    # thing this pipeline re-spells is the `$INODE64` suffix
    # (`target_libc_symbol`), so a leading underscore is part of the name and
    # stripping it asks `dlsym` about a DIFFERENT function.  libSystem's
    # `_NSGetExecutablePath` is the one that bites: the audit reported a symbol
    # libSystem exports as one nothing provides.
    #
    # The suffix cases are unchanged and are the only ones the strip is for.
    # `_readdir$INODE64` still arrives with an underscore because a Mach-O
    # spelling reaches here together with the suffix `target_libc_symbol` added.
    for spelled, want in (("readdir$INODE64", "readdir"),
                          ("_readdir$INODE64", "readdir"),
                          ("_readdir", "_readdir"),
                          ("readdir", "readdir"),
                          ("printf", "printf"),
                          ("_printf", "_printf"),
                          ("_NSGetExecutablePath", "_NSGetExecutablePath"),
                          ("_os_syscalls_readdir_9f63a2",
                           "_os_syscalls_readdir_9f63a2")):
        check(libc_source_name(spelled) == want,
              f"libc_source_name({spelled!r}) is {want!r}")
    # …and a name with NO underscore in it is unaffected, which is the other half
    # of "the strip exists for the suffix": every ordinary libc name this tree
    # emits goes through unchanged.
    check(all(libc_source_name(n) == n for n in
              ("printf", "malloc", "getcwd", "arc4random_buf", "CC_SHA256")),
          "an ordinary C name is its own source name")
    return fails


# ── 2. `binding`: what the built image asks the loader for ─────────────────

BINDING_PROGRAM = """\
from os._syscalls import fs_opendir, fs_readdir, fs_stat, str_alloc
import glob

def main(n):
    var d = fs_opendir("@@DIR@@")
    var e: Pointer[UInt8] = fs_readdir(d)
    printf("dirent=%d@@", e != 0)
    var buf: Pointer[UInt8] = str_alloc(256)
    printf("stat=%d@@", fs_stat("formal/model.py", buf) == 0)
    var p = glob.glob("*.mojo", 0, 0)
    printf("glob=%d@@", p != 0)
    return 0
"""

# What each target's image must name, and why. Both spellings are EXPORTED by
# macOS on x86-64 — that is what makes the mistake a silent answer rather than
# a link error — and only one of them is the function a 64-bit C program's
# `readdir` is.
BINDING_EXPECTED = {
    "x86_64": {"readdir": "readdir$INODE64", "opendir": "opendir$INODE64",
               "stat": "stat$INODE64"},
    "arm64": {"readdir": "readdir", "opendir": "opendir", "stat": "stat"},
}

# The host module's own exports the `glob` dylib must bind, by PREFIX, because
# the hash suffix is a function of the module's path and identity and is not the
# claim. `glob.mojo` calls `basename`/`dirname` without importing them, which is
# what put them in the `retkind` census's unclassified list; which library
# answers them is a whole-image fact, so it is read here out of the bind stream
# rather than argued in a comment — see `HOSTMOD_NON_C_CALLEES`. libc's
# `basename(3)`/`dirname(3)` are the wrong answer and a plausible one: both
# names resolve in this very process (`ctypes.CDLL(None)`), so nothing about the
# spelling separates them, and libc's `dirname` strips trailing slashes where
# CPython's does not.
HOSTMOD_EXPORT_BINDS = ("os_path_basename", "os_path_dirname")
# …and the C-library spellings that must NOT appear, for the same reason the
# `$INODE64` check above is two-sided: a bind of the bare name would be the
# wrong library answering, and nothing else in this file would notice.
HOSTMOD_C_SPELLINGS = ("basename", "dirname")


def group_binding(tmpdir, arch, verbose):
    """The image's bind stream names the function this target means."""
    src = os.path.join(tmpdir, "binding.mojo")
    d = os.path.join(tmpdir, "dir")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "a"), "w") as f:
        f.write("x")
    with open(src, "w") as f:
        f.write(BINDING_PROGRAM.replace("@@DIR@@", d))
    out = os.path.join(tmpdir, "binding." + arch)
    rc, text = build(src, out, arch)
    if rc != 0:
        return [f"build failed: {text.strip()[-400:]}"]
    # The module dylib, not the executable: that is where a call to
    # `os._syscalls`' `readdir` is emitted, and the executable's own stream
    # names `printf` and the module's mangled exports.
    libs = [n for n in linked_dylibs(out)
            if "__syscalls" in os.path.basename(n)]
    if len(libs) != 1:
        return [f"expected exactly one os._syscalls dylib on the link line, "
                f"got {[os.path.basename(n) for n in linked_dylibs(out)]}"]
    try:
        names = bind_symbols(libs[0])
    except ValueError as e:
        return [str(e)]
    if verbose:
        print(f"      {os.path.basename(libs[0])} binds: {sorted(names)}")
    fails = []
    for source_name, want in sorted(BINDING_EXPECTED[arch].items()):
        # The other function of the same NAME: the bare spelling where this
        # target wants the suffixed one, and the suffixed one where it wants
        # the bare spelling. Both are exported on x86-64, so an image that
        # bound the wrong one would load and run.
        other = (source_name + "$INODE64" if want == source_name
                 else source_name)
        if want not in names:
            fails.append(f"the {arch} module does not bind {want} (the "
                         f"{source_name} this target means); it binds "
                         f"{sorted(names)}")
        if other in names:
            fails.append(f"the {arch} module ALSO binds {other}, the other "
                         f"function of that name — both exist on x86-64, so "
                         f"nothing but this check would notice")

    # The same build, read a second time: the `glob` dylib's stream, for the two
    # names `retkind`'s census could not classify until somebody asked which
    # library answers them. One build per architecture serves both, because both
    # questions are about bind streams and a second build would buy a second
    # chance for the same linker to disagree with itself.
    glob_libs = [n for n in linked_dylibs(out)
                 if os.path.basename(n).startswith("glob.")]
    if len(glob_libs) != 1:
        fails.append(f"expected exactly one glob dylib on the {arch} link "
                     f"line, got {[os.path.basename(n)
                                  for n in linked_dylibs(out)]}")
        return fails
    try:
        gnames = bind_symbols(glob_libs[0])
    except ValueError as e:
        fails.append(str(e))
        return fails
    if verbose:
        print(f"      {os.path.basename(glob_libs[0])} binds: {sorted(gnames)}")
    for prefix in HOSTMOD_EXPORT_BINDS:
        if not any(n.startswith(prefix) for n in gnames):
            fails.append(f"the {arch} glob module binds no {prefix}_<hash> "
                         f"export, so `basename`/`dirname` in "
                         f"HOSTMOD_NON_C_CALLEES is a claim about a binding "
                         f"that is not there; it binds {sorted(gnames)}")
    for spelling in HOSTMOD_C_SPELLINGS:
        if spelling in gnames:
            fails.append(f"the {arch} glob module binds libc's `{spelling}`, "
                         f"which strips trailing slashes where CPython's "
                         f"`os.path.{spelling}` does not — and "
                         f"`HOSTMOD_NON_C_CALLEES` says this call reaches "
                         f"os.path's own")
    return fails


# ── 3. `dirent`: 32 bytes of each entry, against ctypes' own readdir ───────

DIRENT_PROGRAM = """\
from os._syscalls import fs_opendir, fs_readdir

def main(n):
    var d = fs_opendir("@@DIR@@")
    var e: Pointer[UInt8] = fs_readdir(d)
    var k = 0
    while e != 0 and k < 3:
        printf("k%d=", k)
        var i = 0
        while i < @@N@@:
            var q: Pointer[UInt8] = e + i
            printf("%02x", q.value())
            i = i + 1
        printf("@@")
        e = fs_readdir(d)
        k = k + 1
    return 0
"""


def _ctypes_dirent_bytes(path, count):
    """The first `count` `struct dirent`s, as ctypes' own `readdir` fills them.

    `ctypes` binds the C library's plain `readdir`, which is the same symbol a
    C program on THIS host gets — so on an arm64 host it is the 64-bit-inode
    one, which is the layout the x86-64 image must produce too. That is the
    whole oracle: two processes, one directory, one `readdir` order.
    """
    import ctypes
    libc = ctypes.CDLL("libSystem.B.dylib", use_errno=True)
    libc.opendir.restype = ctypes.c_void_p
    libc.opendir.argtypes = [ctypes.c_char_p]
    libc.readdir.restype = ctypes.c_void_p
    libc.readdir.argtypes = [ctypes.c_void_p]
    handle = libc.opendir(path.encode())
    if not handle:
        raise OSError(f"ctypes opendir({path!r}) failed")
    out = []
    try:
        while len(out) < count:
            entry = libc.readdir(handle)
            if not entry:
                break
            out.append(ctypes.string_at(entry, DIRENT_BYTES).hex())
    finally:
        libc.closedir(ctypes.c_void_p(handle))
    return out


def group_dirent(tmpdir, arch, verbose):
    """`readdir`'s bytes, from the image and from `ctypes`, must be equal."""
    d = os.path.join(tmpdir, "dirent")
    os.makedirs(d, exist_ok=True)
    for name in ("aaa.txt", "bbb.txt", "ccc.txt"):
        with open(os.path.join(d, name), "w") as f:
            f.write(name)
    src = os.path.join(tmpdir, "dirent.mojo")
    with open(src, "w") as f:
        f.write(DIRENT_PROGRAM.replace("@@DIR@@", d).replace("@@N@@",
                                                             str(DIRENT_BYTES)))
    out = os.path.join(tmpdir, "dirent." + arch)
    rc, text = build(src, out, arch)
    if rc != 0:
        return [f"build failed: {text.strip()[-400:]}"]
    rc, stdout, stderr = run(out, arch)
    if rc != 0:
        return [f"exit {rc}, stderr {stderr.strip()[:200]!r}"]
    got = records(stdout)
    want = _ctypes_dirent_bytes(d, 3)
    if verbose:
        print(f"      ctypes: {want}")
    fails = []
    if len(got) != 3:
        fails.append(f"the image printed {len(got)} entries, ctypes read "
                     f"{len(want)}")
    for k, expect in enumerate(want):
        if got.get(f"k{k}") != expect:
            fails.append(f"entry {k}: the image says {got.get(f'k{k}')!r}, "
                         f"ctypes' readdir says {expect!r}")
    return fails


# ── 4. `stat`: six fields at declared offsets, against `os.stat` ───────────

STAT_PROGRAM = """\
from os._syscalls import fs_stat, str_alloc, le16, le32, le64

def main(n):
    var buf: Pointer[UInt8] = str_alloc(256)
    var r = fs_stat("@@PATH@@", buf)
    printf("r=%d@@", r)
@@READS@@
    return 0
"""


def group_stat(tmpdir, arch, verbose):
    """`stat`'s fields, read at the offsets this target declares, vs CPython."""
    fixture = os.path.join(tmpdir, "statfile")
    with open(fixture, "w") as f:
        f.write("0123456789" * 40)
    reads = "\n".join(
        '    printf("%s=%%d@@", %s(buf, %d))' % (label, reader, off)
        for label, reader, off, _ in STAT_FIELDS)
    src = os.path.join(tmpdir, "stat.mojo")
    with open(src, "w") as f:
        f.write(STAT_PROGRAM.replace("@@PATH@@", fixture)
                .replace("@@READS@@", reads))
    out = os.path.join(tmpdir, "stat." + arch)
    rc, text = build(src, out, arch)
    if rc != 0:
        return [f"build failed: {text.strip()[-400:]}"]
    rc, stdout, stderr = run(out, arch)
    if rc != 0:
        return [f"exit {rc}, stderr {stderr.strip()[:200]!r}"]
    got = records(stdout)
    st = os.stat(fixture)
    if verbose:
        print(f"      os.stat: mode={st.st_mode} ino={st.st_ino} "
              f"size={st.st_size}")
    fails = []
    if got.get("r") != "0":
        fails.append(f"stat of an existing file returned {got.get('r')!r}, "
                     f"not 0")
    for label, _, _, attr in STAT_FIELDS:
        want = str(getattr(st, attr))
        if got.get(label) != want:
            fails.append(f"{attr}: the image says {got.get(label)!r}, "
                         f"os.stat says {want} (read at byte "
                         f"{dict((l, o) for l, _, o, _ in STAT_FIELDS)[label]}"
                         f" of the struct this target fills in)")
    return fails


# ── 5. `retkind`: what a BARE C call's return register means ────────────────
#
# A C function that returns `int` puts the low 32 bits in the return register
# and leaves the rest UNSPECIFIED (AAPCS64 §6.9, SysV AMD64 §3.2.3), so whether
# a `-1` arrives as 0xFFFFFFFF_FFFFFFFF or as 0x00000000_FFFFFFFF is a property
# of the host library's syscall sequence and not of the source. Measured on both
# architectures before `model.BARE_C_RETURN_KINDS` existed: `mkstemps(b, 0) == -1`
# answered 0 while `access(p, 2) == -1` — the identical signature — answered 1,
# and `== 4294967295` answered 1 for the first.
#
# So the table is asked three ways here, and the third is the one that keeps it
# honest:
#
#   * the ANSWER is pinned by the `retvalue` group below, which builds and runs;
#   * the DECISION is pinned here, including the part that could silently
#     corrupt a program instead — a callee a linked Mojo library publishes is
#     this project's own function whatever it is spelled, and `read`, `stat`,
#     `remove` and `walk` all reach this line as either;
#   * the table is checked for TOTALITY over the host modules, so a new bare C
#     call cannot arrive unnormalised with nothing saying so.

# The bare callees in `formal/hostmods/` that are NOT C library entry points,
# and why each is not one. An exact list rather than a filter, so a new one has
# to be classified here instead of being quietly skipped: the census below is
# only meaningful if the exceptions are a list somebody maintains on purpose.
# `str_copy` is the row that makes the export gate in
# `bare_c_return_kind` load-bearing — it is this project's own, reached by
# `os/__init__.mojo` WITHOUT an import statement, and it spells a name a C
# library has no business exporting.
#
# `basename` and `dirname` are the same shape and were found by the census when
# `formal/hostmods/glob.mojo` grew calls to them without importing them. They
# are NOT the POSIX `basename(3)`/`dirname(3)`, which is the reading the spelling
# invites and the one this list would have carried had nobody measured: MEASURED,
# the `glob` dylib binds `os_path_basename_<hash>` and `os_path_dirname_<hash>`
# from the `os.path` dylib — ordinal 3 on its link line, next to the
# `os_path_isdir`/`os_path_join` it imports explicitly — and binds no bare
# `basename` or `dirname` at all. `formal/hostmods/os/path/__init__.mojo` is
# where both are defined, and they answer CPython's rules (an ALIAS into the
# input for a non-empty basename), which libc's `dirname(3)` does not: it strips
# trailing slashes, so `basename("a/b/")` would be `"b"` where CPython says `""`.
# That is also why the row cannot go in `BARE_C_RETURN_KINDS` even though both
# names exist in libSystem — and they do, measured with `ctypes.CDLL(None)`, so
# the "every table entry names a symbol this host's C library defines" check
# below would NOT have caught the mistake. The `binding` group asserts the bind
# stream itself, on both architectures, so the classification is pinned by the
# image rather than by this comment.
#
# `str_alloc` WAS here and stopped being a bare callee: `os/__init__.mojo` now
# writes `from ._syscalls import str_alloc, …`, so the census — which skips
# imported names — no longer finds it, and the anti-rot check below requires the
# entry to go. `str_copy` is still bare there, and the two are called side by
# side, which is what makes the pair worth naming.
HOSTMOD_NON_C_CALLEES = {
    "admitted": "`@admitted` is a contract decorator "
                "(formal/admitted.py::ADMITTED_DECORATOR), not a call",
    "basename": "`os.path`'s own, reached by `glob.mojo` with no import "
                "statement — it binds `os_path_basename_<hash>` from the "
                "os.path dylib, measured in the `binding` group",
    "dirname": "`os.path`'s own, the same shape and the same measurement as "
               "`basename`",
    "str_copy": "`os._syscalls`' own byte copy, called from os/__init__.mojo "
                "the same way",
}


def hostmod_bare_callees():
    """`{name: {files}}` for every bare callee in the host modules.

    A bare callee is an `IdentExpr` call target that the file neither defines
    nor imports, which is `formal/arm64_codegen.py::_emit_call`'s `is_extern`
    read on one file. Deliberately NOT narrowed by "some other host module
    defines this name too": `mkdir`, `chdir` and `getcwd` are libc's AND the
    `os` API's, and the call in `_syscalls.mojo` is the C library's while the
    call in `os/__init__.mojo`'s callers is this project's. Which one a call
    site reaches is a whole-image fact the export tables answer, so a file-level
    census has to report both and let `HOSTMOD_NON_C_CALLEES` say which are not
    C.
    """
    import fire_compiler as F
    from formal.model import builtin_function, iter_nodes, \
        type_constructor_kind

    root = os.path.join(HERE, "formal", "hostmods")
    paths = []
    for dirpath, _dirs, names in os.walk(root):
        for n in sorted(names):
            if n.endswith(".mojo"):
                paths.append(os.path.join(dirpath, n))
    out = {}
    for p in paths:
        with open(p) as f:
            tree = F.Parser(F.py_tokenize_named(f.read(), p)) \
                           .with_filename(p).parse_module()
        defined, imported = set(), set()
        for node in iter_nodes(tree):
            if isinstance(node, (F.FunctionDef, F.StructDef)):
                defined.add(node.name)
            elif isinstance(node, F.FromImportStmt):
                for nm, alias in (node.names or []):
                    imported.add(alias or nm)
            elif isinstance(node, F.ImportStmt):
                imported.add(node.alias or node.module.split(".")[-1])
        for node in iter_nodes(tree):
            if not isinstance(node, F.CallExpr) \
                    or not isinstance(node.func, F.IdentExpr):
                continue
            name = node.func.name
            if name in defined or name in imported:
                continue
            if builtin_function(name) or type_constructor_kind(name):
                continue
            out.setdefault(name, set()).add(os.path.relpath(p, HERE))
    return out


def group_builtin_abi(verbose):
    """`FOREIGN_ABI_BUILTINS`: three builtins the C library DEFINES, so the
    bind audit cannot be what refuses them.

    This file is about "the symbol an unbound C callee binds to on THIS target",
    and the three names in `formal/model.py`'s `FOREIGN_ABI_BUILTINS` are the
    case where that question has a SURPRISING answer: the provider check asks the
    C library (`dlsym`) and the C library has all three, so an image calling
    `pow`, `round` or `abs` links, loads and runs — into a function of a
    different signature.  Measured, both architectures, 2026-10-04, with CPython
    as the arbiter: `pow(10, 2)` answered 0 where CPython answers 100,
    `round(7)` answered 7 on arm64 and 0 here, and `abs(2**40+5)` answered 5 on
    both where CPython answers 1099511627781 — libSystem's `abs` is
    `int abs(int)`, so it sees the low half of the 64-bit word this path passes.

    So the refusal has to happen at the CALL (`model.builtin_binding_refusal`,
    asked by both emitters beside the intercepts that DO lower a name), and this
    group is what makes that refusal load-bearing rather than redundant: it asks
    the host's own C library whether these symbols exist, which is the fact that
    says the bind audit would wave them through.  The differential half — the
    wrong answers, and the refusal that replaced them — is
    `test_formal_value_model.py`'s `BUILTIN_REFUSALS`, which builds and runs;
    this group is the host fact and costs no build.
    """
    import formal.model as M
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
        elif verbose:
            print(f"      ok: {msg}")

    names = sorted(M.FOREIGN_ABI_BUILTINS)
    check(names == ["abs", "pow", "round"],
          f"the three names whose C namesake is a different function: {names}")
    # NOTHING lowers them, so the refusal at the call site is not shadowed by a
    # lowering that arrived later — the intercepts the emitters consult come
    # first, so a name in any of those tables would never reach
    # `builtin_binding_refusal` and this table would be dead code.
    for name in names:
        check(name not in M.EMITTER_BUILTINS
              and M.builtin_function(name) is None
              and name not in M.INT_TYPE_CTORS
              and name not in M.IDENTITY_TYPE_CTORS,
              f"{name} is lowered by nothing, so the refusal is reached")
    # …and the C library HAS them, which is the whole reason the bind audit does
    # not catch them.  Darwin-only for the same reason `group_retkind`'s ctypes
    # check is: the provider check the build performs is a `dlsym` against this
    # host's library, so the fact worth asserting is the fact about THIS one.
    if sys.platform == "darwin":
        import ctypes
        lib = ctypes.CDLL(None)
        for name in names:
            try:
                getattr(lib, name)
                check(True, f"libSystem defines `{name}`, so a call to it "
                            f"would bind rather than dangle")
            except AttributeError:
                check(False,
                      f"libSystem does NOT define `{name}` here, so the bind "
                      f"audit would have refused it and the emitter refusal is "
                      f"redundant on this host — and the measured wrong answers "
                      f"this table records could not have happened")
    elif verbose:
        print("NOTE: not Darwin, so the provider check's own question cannot "
              "be asked of this host's C library here")
    return fails


def group_retkind(verbose):
    """`bare_c_return_kind`: the prototype, the export exception, totality."""
    from formal.model import (BARE_C_RETURN_KINDS, EXTERN_RETURN_VOID,
                              EXTERN_RETURN_WORD, bare_c_return_kind)
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
        elif verbose:
            print(f"      ok: {msg}")

    def kind_of(name, exports=None, aliases=None):
        """`bare_c_return_kind` with no Mojo library on the link line."""
        return bare_c_return_kind(name, exports or {}, {}, {}, aliases or {},
                                  exports or {})

    # The three widths, one name each, and the reason they are three: a `size_t`
    # or a `uint64_t` return has bit 31 set in ordinary use, so the `int` row's
    # conversion applied to it would fabricate a negative number.
    check(kind_of("mkstemps") == (32, True),
          f"mkstemps returns C's int: {kind_of('mkstemps')!r}")
    check(kind_of("mkdtemp") == EXTERN_RETURN_WORD,
          f"mkdtemp returns char *: a whole register, no conversion")
    check(kind_of("clock_gettime_nsec_np") == EXTERN_RETURN_WORD,
          "clock_gettime_nsec_np returns uint64_t — 1.7e18 has bit 31 set, so "
          "this is the name that says the fix is not sign-extend everything")
    check(kind_of("free") == EXTERN_RETURN_VOID, "free returns void")
    check(kind_of("no_such_c_function") is None,
          "a C symbol with no prototype entry is passed through as it arrived")

    # The EXPORT exception, which is what stops this from corrupting a call into
    # another host module. `read` is the name that makes it necessary: it is
    # libc's `read` and this tree's own wrapper for it, and only the export
    # tables can say which one a given call reached.
    exports = {"read": {"symbol": "_hostmod_read", "nargs": 3}}
    check(bare_c_return_kind("read", exports, {}, {}, {}, exports) is None,
          "a callee a linked library PUBLISHES is a Mojo value whatever it is "
          "spelled — no conversion, though libc's read is in the table")
    aliased = {"as_read": {"symbol": "_hostmod_read", "nargs": 3}}
    check(bare_c_return_kind("as_read", {}, {}, {}, aliased, {}) is None,
          "…and the same holds through an import alias, which is how "
          "`from m import f as g` binds")
    check(kind_of("mkdir") == (32, True),
          "with no library on the link line, mkdir is libc's and is normalized")

    # TOTALITY, forward: every bare callee the host modules make must be a name
    # this table has an opinion about, or a call can reach a C library entry
    # point whose -1 the host returns 0x00000000_FFFFFFFF and nothing says so.
    census = hostmod_bare_callees()
    unknown = {n: fs for n, fs in census.items()
               if n not in BARE_C_RETURN_KINDS
               and n not in HOSTMOD_NON_C_CALLEES}
    check(not unknown,
          f"all {len(census)} bare callees in formal/hostmods are either in "
          "BARE_C_RETURN_KINDS or in HOSTMOD_NON_C_CALLEES"
          + ("" if not unknown else "; unclassified: "
             + ", ".join(f"{n} ({sorted(fs)[0]})"
                         for n, fs in sorted(unknown.items()))))
    # …and every name the exceptions claim IS a bare callee, so the exception
    # list cannot grow a name that was never there to excuse.
    check(not (set(HOSTMOD_NON_C_CALLEES) - set(census)),
          "every HOSTMOD_NON_C_CALLEES entry is a name the census found"
          + ("" if set(HOSTMOD_NON_C_CALLEES) <= set(census) else
             "; stale: " + ", ".join(sorted(set(HOSTMOD_NON_C_CALLEES)
                                            - set(census)))))

    # TOTALITY, backward: a table entry is a claim about a real function, so ask
    # the C library whether it has one. A typo or an invented name would
    # otherwise be a prototype nothing can be held to.
    if sys.platform == "darwin":
        import ctypes
        lib = ctypes.CDLL(None)
        absent = []
        for name in sorted(BARE_C_RETURN_KINDS):
            try:
                getattr(lib, name)
            except AttributeError:
                absent.append(name)
        check(not absent,
              f"all {len(BARE_C_RETURN_KINDS)} prototypes in the table name a "
              "symbol this host's C library defines"
              + ("" if not absent else "; not defined here: "
                 + ", ".join(absent)))
    elif verbose:
        print("NOTE: not Darwin, so the prototype table's symbols cannot be "
              "asked of a C library here")
    return fails


# ── 6. `retvalue`: the same thing, measured on a built image ────────────────
#
# What is asserted is the ANSWER, never the instruction: `mkstemps` on a path
# that does not exist returns -1, and a C `int` return is a sign-extended word,
# so `== -1` and `< 0` are true and `== 4294967295` is false. `truncate` is the
# control — the identical prototype, which libSystem happened to arrive
# sign-extended even before the table — and `clock_gettime_nsec_np` is the one
# that says the conversion did not become a blanket `sxtw`: its value is
# 1.7e18, bit 31 long since set, and a blanket sign-extension would make every
# `time.time_ns()` negative.

RET_PROGRAM = """\
from os._syscalls import str_dup

def main(n):
    var b = str_dup("@@DIR@@/nodirXXXX/z")
    printf("mk_eq_m1=%d@@", mkstemps(b, 0) == -1)
    printf("mk_lt_0=%d@@", mkstemps(b, 0) < 0)
    printf("mk_eq_32=%d@@", mkstemps(b, 0) == 4294967295)
    printf("mk_ne_0=%d@@", mkstemps(b, 0) != 0)
    printf("tr_eq_m1=%d@@", truncate("@@DIR@@/nodirXXXX/z", 0) == -1)
    printf("ns_pos=%d@@", clock_gettime_nsec_np(0) > 0)
    printf("ns_gt_2p31=%d@@", clock_gettime_nsec_np(0) > 2147483648)
    printf("len_ok=%d@@", strlen("abcd") == 4)
    return 0
"""

# label -> what the C library's own answer is, as CPython/ctypes in this
# process establish it. `mk_eq_m1` and `tr_eq_m1` are the -1 rows; `mk_eq_32`
# is the one that was true before the fix and must be false after it, which is
# what makes this a test of the conversion rather than of a comparison.
RET_EXPECTED = {
    "mk_eq_m1": "1",
    "mk_lt_0": "1",
    "mk_eq_32": "0",
    "mk_ne_0": "1",
    "tr_eq_m1": "1",
    "ns_pos": "1",
    "ns_gt_2p31": "1",
    "len_ok": "1",
}


def group_retvalue(tmpdir, arch, verbose):
    """A C `int` return is a sign-extended word; a `uint64_t` one is not."""
    d = os.path.join(tmpdir, "retdir")
    os.makedirs(d, exist_ok=True)
    src = os.path.join(tmpdir, "ret.mojo")
    with open(src, "w") as f:
        f.write(RET_PROGRAM.replace("@@DIR@@", d))
    out = os.path.join(tmpdir, "ret." + arch)
    rc, text = build(src, out, arch)
    if rc != 0:
        return [f"build failed: {text.strip()[-400:]}"]
    rc, stdout, stderr = run(out, arch)
    if rc != 0:
        return [f"exit {rc}, stderr {stderr.strip()[:200]!r}"]
    got = records(stdout)
    if verbose:
        print(f"      image said: {got}")
    fails = []
    for label, want in RET_EXPECTED.items():
        if got.get(label) != want:
            fails.append(f"{label}: the image says {got.get(label)!r}, the C "
                         f"answer is {want!r}")
    return fails


GROUPS = {
    # `table` is a function of the target alone, so it is not per-architecture:
    # it is listed with the others because it is one of the things that can be
    # wrong, and a check that is not run is not a check.
    "table": (lambda tmpdir, arch, verbose: group_table(verbose), False),
    "retkind": (lambda tmpdir, arch, verbose: group_retkind(verbose), False),
    "builtin_abi": (lambda tmpdir, arch, verbose: group_builtin_abi(verbose),
                    False),
    "binding": (group_binding, True),
    "dirent": (group_dirent, True),
    "stat": (group_stat, True),
    "retvalue": (group_retvalue, True),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2

    archs = ["arm64"]
    r = rosetta()
    if r is True:
        archs.append("x86_64")
    elif r is None and args.verbose:
        print("NOTE: not Darwin, so the x86-64 image cannot be executed here; "
              "arm64 only")

    failed = []
    total = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for n in names:
            fn, per_arch = GROUPS[n]
            for arch in (archs if per_arch else [None]):
                total += 1
                fails = fn(tmpdir, arch, args.verbose)
                label = n if arch is None else f"{n} [{arch}]"
                detail = "" if not fails else (
                    "  " + "\n      ".join([fails[0]] + fails[1:]))
                print(("PASS " if not fails else "FAIL ") + label + detail)
                if fails:
                    failed.append(label)
    print(f"\n{total - len(failed)}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())