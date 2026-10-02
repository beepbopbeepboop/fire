#!/usr/bin/env python3
"""The symbol an unbound C callee binds to on THIS target, measured three ways.

    python3 test_formal_libc_symbol.py [-v] [group ...]

Groups: `table`, `binding`, `dirent`, `stat`. With no argument, all of them.

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
(`bugs/FORMAL_x86_64_byte_read_of_a_libc_returned_pointer_reads_the_wrong_bytes.md`,
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

THE THREE GROUPS, and why there are three. `table` asks the DECISION as a
function, which is cheap and pins the two halves that could drift (the table and
the suffix; the Mach-O-only, x86_64-only gate). `binding` reads the built
image's own dyld bind stream, so what is asserted is the symbol the LOADER will
look up rather than what a function returned — the two were the same decision
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
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60

# The record terminator, for the reason every other formal test file gives: a
# Mojo string literal's `\n` is not unescaped on this path, so a formal image
# prints the two characters backslash and `n` and a record-structured program
# has to choose its own terminator.
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
        p = subprocess.run(["arch", "-x86_64", "/usr/bin/true"],
                           capture_output=True, timeout=60)
        return p.returncode == 0
    except Exception:
        return False


def build(src, out, arch):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           "--backend=" + arch, "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
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
                           timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "", f"the image did not finish within {RUN_TIMEOUT}s"
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
    for spelled, want in (("readdir$INODE64", "readdir"),
                          ("_readdir$INODE64", "readdir"),
                          ("_readdir", "readdir"),
                          ("readdir", "readdir"),
                          ("printf", "printf"),
                          ("_printf", "printf"),
                          ("_os_syscalls_readdir_9f63a2",
                           "os_syscalls_readdir_9f63a2")):
        check(libc_source_name(spelled) == want,
              f"libc_source_name({spelled!r}) is {want!r}")
    return fails


# ── 2. `binding`: what the built image asks the loader for ─────────────────

BINDING_PROGRAM = """\
from os._syscalls import fs_opendir, fs_readdir, fs_stat, str_alloc

def main(n):
    var d = fs_opendir("@@DIR@@")
    var e: Pointer[UInt8] = fs_readdir(d)
    printf("dirent=%d@@", e != 0)
    var buf: Pointer[UInt8] = str_alloc(256)
    printf("stat=%d@@", fs_stat("formal/model.py", buf) == 0)
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


GROUPS = {
    # `table` is a function of the target alone, so it is not per-architecture:
    # it is listed with the others because it is one of the things that can be
    # wrong, and a check that is not run is not a check.
    "table": (lambda tmpdir, arch, verbose: group_table(verbose), False),
    "binding": (group_binding, True),
    "dirent": (group_dirent, True),
    "stat": (group_stat, True),
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