"""Mach-O executable (a.out) generator: constructs an MH_EXECUTE binary from scratch.

Three builders:
- build_macho_executable: minimal executable, no external symbols.
- build_macho_executable_extern: executable linking /usr/lib/libSystem.B.dylib
  via a __TEXT,__stubs section + __DATA_CONST,__got slot and classic dyld bind
  opcodes (LC_DYLD_INFO). dyld resolves the GOT slot at load time.
- build_macho_dylib: MH_DYLIB with an export trie.

Two architectures: `arch="arm64"` (the original target) and `arch="x86_64"`
(the formal x86-64 codegen's target, which runs under Rosetta on Apple
Silicon). The segment/load-command layout, the bind opcode stream and the
entry-offset arithmetic are identical between them; only three things vary —
the Mach-O cpu type/subtype, the per-symbol stub instruction sequence, and
its size (12 bytes of ADRP/LDR/BR on arm64, 6 bytes of `jmpq *disp(%rip)` on
x86-64). Each is a parameter here rather than a second copy of the builder,
so the two architectures cannot drift apart on the parts that must match.
"""

import struct


PAGEZERO_CMD = 0x1
SEGMENT_64_CMD = 0x19
LOAD_DYLINKER_CMD = 0x0E
LOAD_DYLIB_CMD = 0x0C
UUID_CMD = 0x1B
BUILD_VERSION_CMD = 0x32
MAIN_CMD = 0x80000028
DYLD_INFO_ONLY_CMD = 0x80000022

MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
# Subtypes come from <mach/machine.h>: CPU_SUBTYPE_ARM64_ALL is 0 and
# CPU_SUBTYPE_X86_64_ALL is 3. They are NOT interchangeable — stamping the
# arm64 image with 3 (the x86_64 value) still builds, still passes
# `codesign -v`, and still disassembles under `otool`, but execve rejects it
# with EBADARCH ("Bad CPU type in executable"), so only a test that actually
# RUNS the binary can see it. test_x86_64_encoders.py asserts both pairs.
CPU_SUBTYPE_ARM64_ALL = 0x00000000
CPU_TYPE_X86_64 = 0x01000007
CPU_SUBTYPE_X86_64_ALL = 0x00000003
MH_EXECUTE = 2

# The section TYPE dyld reads a load-time initializer list from, and it is NOT
# the pointer-array type (`S_MOD_INIT_FUNC_POINTERS`, 0x9) that the name
# `__mod_init_func` suggests. Measured on this platform (macOS 26.6.2, dyld as
# shipped): a `__DATA,__mod_init_func` section carrying a correct 8-byte pointer
# to a module body is parsed, loads, links and is NEVER CALLED — the importing
# program ran and printed only its own output — while `clang -dynamiclib`'s own
# initializer, in a `__TEXT,__init_offsets` section of type 0x16, runs. So this
# writer emits the form the toolchain emits and the loader honours:
#
#   * `S_INIT_FUNC_OFFSETS` (0x16) as the section TYPE. `clang` uses it for every
#     `__attribute__((constructor))`, which is what makes it present in every
#     image the platform's own build system produces.
#   * 32-bit values, and they are OFFSETS FROM THE START OF THE IMAGE (its
#     mach_header), not addresses and not offsets from the section. Measured both
#     ways: `clang -dynamiclib` at `__TEXT` `0x0` stores the initializer's
#     address verbatim, and the same file linked at `__TEXT 0x100000000` stores
#     `address - 0x100000000`. A 32-bit field cannot hold an address in an image
#     whose `__TEXT` is at `TEXT_BASE`, so this is also the only form that works
#     for an image linked where this one is.
#
# The name is a convention; the type is the mechanism, and `_write_text_segment`
# is told the type.
S_INIT_FUNC_OFFSETS = 0x16


def _init_offsets_blob(addrs) -> bytes:
    """The `__init_offsets` payload: one 32-bit image-relative offset per address.

    `TEXT_BASE` is subtracted because it is this file's mach_header address for
    every image it writes (`__TEXT` is the lowest segment of both an executable
    and a dylib, and the mach_header lives at its start), and because that is
    what the offset is measured from — see `S_INIT_FUNC_OFFSETS`.

    Refused rather than truncated, for a value that will not fit: `struct.pack`
    raises on an address 4 GB or more past `TEXT_BASE`, and a silently dropped
    initializer is the exact failure this mechanism exists to prevent.
    """
    out = bytearray()
    for addr in (addrs or []):
        try:
            out += struct.pack("<I", int(addr) - TEXT_BASE)
        except (struct.error, TypeError, ValueError) as e:
            raise ValueError(
                f"a load-time initializer at {addr!r} is not an address in an "
                f"image whose mach_header is at {TEXT_BASE:#x}: the offset form "
                f"this platform's dyld reads is 32 bits wide ({e})") from None
    return bytes(out)

# Per-architecture Mach-O identity and stub geometry.
ARCHES = {
    "arm64": {
        "cputype": CPU_TYPE_ARM64,
        "cpusubtype": CPU_SUBTYPE_ARM64_ALL,
        "stub_size": 12,
    },
    "x86_64": {
        "cputype": CPU_TYPE_X86_64,
        "cpusubtype": CPU_SUBTYPE_X86_64_ALL,
        "stub_size": 6,
    },
}


def arch_spec(arch: str) -> dict:
    """Mach-O identity and stub geometry for `arch`, or a clear error."""
    spec = ARCHES.get(arch)
    if spec is None:
        raise ValueError(
            f"unknown arch {arch!r} (expected one of {sorted(ARCHES)})")
    return spec


def stub_size(arch: str = "arm64") -> int:
    """Bytes each __TEXT,__stubs entry occupies for `arch`."""
    return arch_spec(arch)["stub_size"]


# dyld bind opcodes (classic LC_DYLD_INFO binding)
BIND_DONE = 0x00
BIND_SET_DYLIB_ORDINAL_IMM = 0x10
BIND_SET_SYMBOL_TRAILING_FLAGS_IMM = 0x40
BIND_SET_TYPE_IMM = 0x50
# The segment index is the low nibble OF THE OPCODE: ld emits a literal 0x72
# (0x70 | segment 2) followed by the ULEB offset. Writing 0x70 and then the
# segment as a separate byte — as this used to — makes dyld read the segment
# byte as the offset, so it bound at __DATA_CONST+2 and left the real GOT slot
# at zero for the stub to branch through.
BIND_SET_SEGMENT_AND_OFFSET_ULEB = 0x70
BIND_DO_BIND = 0x90
BIND_TYPE_POINTER = 0x1
# Flag byte ld emits for a function symbol (verified against the lazy-bind
# stream of an ld-linked C program calling printf: `40 5f "_printf\0" 90 00`).
BIND_SYMBOL_FLAGS_FUNCTION = 0x5F
GOT_SEGMENT_INDEX = 2      # segment ordinal of __DATA_CONST (0=__PAGEZERO, 1=__TEXT)

LIBSYSTEM_PATH = b"/usr/lib/libSystem.B.dylib\0"

PAGEZERO_SIZE = 0x100000000
# __TEXT's mapped address for every image this module emits.
#
# Exactly 4 GB, i.e. the first address ABOVE the range __PAGEZERO reserves, and
# that is a hard requirement rather than a convention: __PAGEZERO claims all of
# [0, 4 GB) with nothing mapped, and the kernel will not map any other segment
# into it for an executable. Measured: moving __TEXT down to 3 GB — leaving a
# full gigabyte of headroom, apparently the obvious way to keep an x86-64 image
# clear of the 4 GB boundary — produced a binary that AMFI rejected outright and
# the kernel SIGKILLed before its first instruction, with nothing on stderr.
#
# Everything else in an image (the GOT, the stubs, __DATA_CONST and __LINKEDIT)
# is placed relative to this constant, so the whole image moves with it and no
# call site has to know which architecture it is building for.
TEXT_BASE = 0x100000000
DATA_BASE = TEXT_BASE + 0x4000
LINKEDIT_BASE = TEXT_BASE + 0x8000
PAGE_SIZE = 0x4000

def _dylinker_cmd() -> bytes:
    """LC_LOAD_DYLINKER pointing at /usr/lib/dyld, in the form ld emits.

    dylinker_command is {cmd, cmdsize, {name, timestamp}} — 16 bytes of fixed
    part — so `name` must be an offset *past* that, and `timestamp` is a real
    field. Writing the path at offset 12 (over the timestamp) is what this
    builder used to do; ld puts it at 24 with a 40-byte command.
    """
    name = b"/usr/lib/dyld\0"
    cmdsize = (24 + len(name) + 7) & ~7
    buf = bytearray(cmdsize)
    struct.pack_into("<III", buf, 0, LOAD_DYLINKER_CMD, cmdsize, 24)
    struct.pack_into("<I", buf, 12, 0)          # timestamp
    buf[24:24 + len(name)] = name
    return bytes(buf)


DYLINKER_CMDSIZE = len(_dylinker_cmd())


# sizeofcmds of each executable layout (see the two builders below).
NOEXTERN_SIZEOFCMDS = 72 + 152 + 72 + 48 + DYLINKER_CMDSIZE + 24 + 24 + 24
EXTERN_SIZEOFCMDS = (72 + 232 + 152 + 72 + 48 + DYLINKER_CMDSIZE + 24
                     + 24 + 56 + 24)

# The `__DATA` segment a module-global slot table needs: its segment command
# (72) plus one section header (80). A PARAMETER of the two layouts above
# rather than a constant folded into them, because whether an image HAS module
# state is a property of the source, and a program with no `global NAME` in it
# must keep the layout it had — the entry offset moves with sizeofcmds, so
# folding this in unconditionally would move every image on the tree for a
# segment most of them do not have.
DATA_SIZEOFCMDS = 72 + 80

# Where `__DATA` is MAPPED for every image this module emits, Mach-O and dylib
# alike. A fixed address rather than "the page after __TEXT", and that is the
# whole design decision behind this capability:
#
# __TEXT's size is a function of the CODE, and the code needs to know where
# __DATA is (every access is an ADRP to it), so deriving __DATA from __TEXT makes
# each depend on the other. Placing it at a fixed address a few MB past the text
# breaks the cycle: the codegen reads this constant before it emits anything,
# the linker writes the segment here, and neither needs the other's output.
#
# ABOVE the text, because a Mach-O's segments must ascend in virtual address and
# nothing can go below __TEXT — __PAGEZERO covers all of [0, 4 GB) and the kernel
# will not map a segment into it. See the note on `TEXT_BASE` for the
# measurements behind that, which is that a `__DATA` above 4 GB killed every
# x86-64 image under Rosetta while the same source ran fine on arm64.
#
# The distance is chosen for ADRP's ±4 GB page range, not for tidiness: a page
# delta is (target - pc) >> 12, so anything within 4 GB works and this is three
# orders of magnitude inside it. It is also far enough past TEXT_BASE that no
# realistic formal image's __TEXT reaches it — and a `__DATA` that OVERLAPPED
# __TEXT would be a mapping failure at launch, which is why the builders below
# raise rather than emit one.
GLOBALS_VM = TEXT_BASE + 0x400000

# sizeofcmd of LC_CODE_SIGNATURE, and the alignment the entry offset needs.
#
# Every image this module emits is signed after the fact by `codesign -s -`,
# and codesign ADDS an LC_CODE_SIGNATURE (16 bytes) to the load-command list.
# It can only do that where there is slack between the end of the load commands
# and the first byte of code; with the code starting flush against sizeofcmds,
# those 16 bytes land ON the first instructions instead. The image still signs
# and dyld still maps it, but LC_MAIN's entry offset now points at a load
# command, so the process dies of SIGILL/SIGKILL at launch with nothing on
# stderr — which is exactly what this reserve exists to prevent. (The dylib
# builder has always had this slack; see dylib_code_offset.)
CODE_SIGNATURE_CMDSIZE = 16





def executable_entry_offset(sizeofcmds: int) -> int:
    """File offset of the entry point for a layout with this sizeofcmds.

    32-byte aligned and leaving CODE_SIGNATURE_CMDSIZE bytes of slack after the
    load commands, so post-hoc codesigning has somewhere to put
    LC_CODE_SIGNATURE. 32-byte alignment is what makes the slack guaranteed
    rather than a coin flip: rounding to 16 instead can leave 0-15 bytes, i.e.
    sometimes not enough room for the command codesign adds.
    """
    return ((32 + sizeofcmds + CODE_SIGNATURE_CMDSIZE) + 31) & ~31


NOEXTERN_ENTRYOFF = executable_entry_offset(NOEXTERN_SIZEOFCMDS)
EXTERN_ENTRYOFF = executable_entry_offset(EXTERN_SIZEOFCMDS)

# Entry offsets for an image that carries module-global storage. Separate
# constants rather than arguments to the two above because the CODEGEN reads
# them before it has compiled anything (`_codegen_and_link` picks the base
# address to emit for), and the choice of which one is the same decision twice:
# has_externs decides between NOEXTERN/EXTERN, has_globals adds to whichever.
NOEXTERN_GLOBALS_ENTRYOFF = executable_entry_offset(
    NOEXTERN_SIZEOFCMDS + DATA_SIZEOFCMDS)
EXTERN_GLOBALS_ENTRYOFF = executable_entry_offset(
    EXTERN_SIZEOFCMDS + DATA_SIZEOFCMDS)


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _text_filesize(body_end: int) -> int:
    """filesize/vmsize of __TEXT for content ending at file offset `body_end`.

    Every image in this module puts the load commands, the code and (extern
    path) the stubs in __TEXT, then puts each following segment on the next
    page boundary. __TEXT is therefore sized from its CONTENT, not pinned to
    one page: with a fixed 0x4000 __TEXT, any program whose code runs past the
    end of the first page — i.e. anything real, ~45KB of arm64 code and up —
    writes beyond a segment that never declared the bytes, bytearray silently
    *extends* the image, and the result is a binary longer than every segment
    claims (which `_assert_no_unclaimed_bytes` exists to catch, and which
    `codesign` rejects outright). Growing __TEXT keeps vmaddr == TEXT_BASE +
    fileoff for every segment, so nothing the codegen computed off the entry
    base or a stub address moves.
    """
    return _align_up(body_end, PAGE_SIZE)


def _write_text_segment(file: bytearray, o: int, filesize: int,
                        sections: list) -> int:
    """Write the __TEXT segment command and its section headers at `o`.

    One section is a (name, vmaddr, size, fileoff, flags, reserved1) tuple —
    reserved1 is what carries a stub section's stub size. Returns the offset
    just past the command.
    """
    def patch(off, fmt, *vals):
        struct.pack_into(fmt, file, off, *vals)

    cmdsize = 72 + 80 * len(sections)
    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", cmdsize)
    file[o + 8 : o + 24] = b"__TEXT".ljust(16, b"\0")
    patch(o + 24, "<Q", TEXT_BASE)
    patch(o + 32, "<Q", filesize)   # vmsize
    patch(o + 40, "<Q", 0)          # fileoff 0: __TEXT starts the file
    patch(o + 48, "<Q", filesize)   # filesize
    patch(o + 56, "<I", 5)          # maxprot r-x
    patch(o + 60, "<I", 5)          # initprot r-x
    patch(o + 64, "<I", len(sections))
    patch(o + 68, "<I", 0)
    s = o + 72
    for name, vmaddr, size, fileoff, flags, reserved1 in sections:
        file[s : s + 16] = name.ljust(16, b"\0")
        file[s + 16 : s + 32] = b"__TEXT".ljust(16, b"\0")
        patch(s + 32, "<Q", vmaddr)
        patch(s + 40, "<Q", size)
        patch(s + 48, "<I", fileoff)
        patch(s + 52, "<I", 2)      # align: 2**2 = 4-byte
        patch(s + 56, "<I", 0)      # reloff
        patch(s + 60, "<I", 0)      # nreloc
        patch(s + 64, "<I", flags)
        patch(s + 68, "<I", reserved1)
        patch(s + 72, "<I", 0)      # reserved2
        s += 80
    return o + cmdsize

# MH_NOUNDEFS | MH_DYLDLINK | MH_TWOLEVEL | MH_PIE. The last two are not
# cosmetic: a main executable without MH_DYLDLINK and MH_PIE is killed by
# dyld before it reaches its entry point (verified by bisecting the load
# commands of a hand-built image — the same image runs with these flags set).
MH_EXECUTE_FLAGS = 0x1 | 0x4 | 0x80 | 0x200000


def build_macho_executable(code: bytes, arch: str = "arm64",
                           globals_image=None) -> bytes:
    """Minimal MH_EXECUTE: no external symbols, no stubs, no GOT.

    The entry offset is derived from this layout (see executable_entry_offset)
    rather than passed in, so the code, LC_MAIN and the __text section offset
    cannot drift apart the way a caller-supplied constant allowed.

    `globals_image` is a `model.GlobalDataImage` or None. Non-None adds a
    writable `__DATA` segment for the module-global slot table. Its
    presence changes `sizeofcmds`, so it changes the entry offset — which is why
    `NOEXTERN_ENTRYOFF` has a globals-carrying twin and the codegen picks
    between them before it emits."""
    spec = arch_spec(arch)
    gblob = _globals_blob(globals_image)
    has_globals = bool(gblob)
    entryoff = (NOEXTERN_GLOBALS_ENTRYOFF if has_globals
                else NOEXTERN_ENTRYOFF)
    body_end = entryoff + len(code)
    text_size = _text_filesize(body_end)
    g_file = text_size if has_globals else 0
    g_size = _align_up(len(gblob), PAGE_SIZE) if has_globals else 0
    g_vm = GLOBALS_VM if has_globals else 0
    _check_globals_do_not_overlap_text(text_size, has_globals)
    linkedit_file = g_file + g_size if has_globals else text_size
    linkedit_size = PAGE_SIZE
    file = bytearray(linkedit_file + linkedit_size)

    def patch(off: int, fmt: str, *vals) -> None:
        struct.pack_into(fmt, file, off, *vals)

    sizeofcmds = NOEXTERN_SIZEOFCMDS + (DATA_SIZEOFCMDS if has_globals else 0)

    patch(0, "<I", MAGIC_64)
    patch(4, "<I", spec["cputype"])
    patch(8, "<I", spec["cpusubtype"])

    patch(12, "<I", MH_EXECUTE)
    patch(16, "<I", 8 + (1 if has_globals else 0))
    patch(20, "<I", sizeofcmds)
    patch(24, "<I", MH_EXECUTE_FLAGS)

    o = 32

    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72)
    file[o + 8 : o + 24] = b"__PAGEZERO".ljust(16, b"\0")
    patch(o + 24, "<Q", 0)
    patch(o + 32, "<Q", 0x100000000)
    o += 72

    o = _write_text_segment(file, o, text_size, [
        (b"__text", TEXT_BASE + entryoff, len(code), entryoff,
         0x80000400, 0),
    ])

    # __DATA (module-global slots). Its ORDINAL is 2: an executable spends 0 on
    # __PAGEZERO and 1 on __TEXT, and this layout has no __DATA_CONST — the
    # ordinal 2, and the segment is emitted immediately after it.
    if has_globals:
        o = _write_data_segment(file, o, g_vm, g_file, g_size, gblob)

    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72)
    file[o + 8 : o + 24] = b"__LINKEDIT".ljust(16, b"\0")
    patch(o + 24, "<Q", TEXT_BASE + linkedit_file)
    patch(o + 32, "<Q", linkedit_size)
    patch(o + 40, "<Q", linkedit_file)
    patch(o + 48, "<Q", linkedit_size)
    patch(o + 56, "<I", 1)   # maxprot r--: __LINKEDIT holds the code signature
    patch(o + 60, "<I", 1)   # initprot r-- (dyld maps it read-only)
    o += 72

    patch(o + 0, "<I", DYLD_INFO_ONLY_CMD)
    patch(o + 4, "<I", 48)
    # No rebase stream. The address-valued module globals are filled by CODE in
    # the startup stub rather than by the loader; see
    # `arm64_codegen._emit_global_init` for the measurement behind that choice,
    # which is that a classic LC_DYLD_INFO_ONLY rebase stream is parsed and then
    # silently ignored on the macOS this backend runs on.
    patch(o + 8, "<I", 0)
    patch(o + 12, "<I", 0)
    o += 48

    file[o : o + DYLINKER_CMDSIZE] = _dylinker_cmd()
    o += DYLINKER_CMDSIZE

    patch(o + 0, "<I", UUID_CMD)
    patch(o + 4, "<I", 24)
    o += 24

    patch(o + 0, "<I", BUILD_VERSION_CMD)
    patch(o + 4, "<I", 24)
    patch(o + 8, "<I", 1)        # platform: macOS
    patch(o + 12, "<I", 0x000B0000)  # minos 11.0
    patch(o + 16, "<I", 0x000B0000)  # sdk 11.0
    patch(o + 20, "<I", 0)       # ntools
    o += 24

    patch(o + 0, "<I", MAIN_CMD)
    patch(o + 4, "<I", 24)
    patch(o + 8, "<Q", entryoff)
    patch(o + 16, "<Q", 0)
    o += 24

    assert o <= entryoff, (o, entryoff)
    file[entryoff : entryoff + len(code)] = code
    if has_globals:
        file[g_file : g_file + len(gblob)] = gblob
    _assert_no_unclaimed_bytes(file, [(0, text_size)]
                               + ([(g_file, g_size)] if has_globals else [])
                               + [(linkedit_file, linkedit_size)])
    return bytes(file)


def dylib_command_size(install_name: str) -> int:
    """sizeofcmds of an LC_LOAD_DYLIB naming `install_name`.

    dylib_command is {cmd, cmdsize, name-offset, timestamp, current_version,
    compatibility_version} — 24 bytes of fixed part, then the NUL-terminated
    path, padded to 8. Needed UP FRONT by the executable build, because each
    dependency adds a load command and the load-command list's size is what
    sets the entry offset (see `extern_entry_offset`)."""
    return (24 + len(install_name.encode("utf-8")) + 1 + 7) & ~7


def extern_entry_offset(dylib_install_names=(), has_globals: bool = False) -> int:
    """File offset of the entry point for the extern executable layout.

    The no-dependency case is the historical constant; each linked dylib adds
    one LC_LOAD_DYLIB to the load-command list, which pushes the entry point
    down (the code has to start after the whole list, with room for the
    LC_CODE_SIGNATURE codesign appends). The codegen needs this BEFORE it
    emits, because the entry offset decides the base address every ADRP and
    relative branch is computed against — hence a function rather than a
    constant.

    `has_globals` adds the `__DATA` segment's load command, for the same reason
    and with the same consequence: it moves the entry point, so the codegen has
    to know it before emitting and the linker has to use the same value."""
    extra = sum(dylib_command_size(n) for n in dylib_install_names)
    return executable_entry_offset(EXTERN_SIZEOFCMDS + extra
                                   + (DATA_SIZEOFCMDS if has_globals else 0))


def _bind_info(external_syms: list[str], dylib_of: dict = None,
               got_segment: int = GOT_SEGMENT_INDEX) -> bytes:
    """Classic dyld bind opcodes pointing each __got slot at its symbol.

    A __got slot is a S_NON_LAZY_SYMBOL_POINTERS entry in __DATA_CONST (segment
    ordinal 2). The bind cursor starts at (segment base + offset); SET_SEGMENT_
    AND_OFFSET_ULEB places it at the slot, then DO_BIND writes the resolved
    pointer (8 bytes) and advances it by 8, naturally walking down the slots.

    `dylib_of` maps a symbol name to the 1-based dylib ordinal that provides
    it; ordinal 1 is libSystem (the default, and what every symbol gets when
    this is None). Ordinals follow LC_LOAD_DYLIB order, so the caller must
    pass them in the same order the load commands are emitted.

    `got_segment` is the SEGMENT ORDINAL of the __DATA_CONST holding the GOT,
    which is a per-image fact and NOT a constant: segment ordinals count the
    image's segments from 0 and a Mach-O *executable* spends ordinal 0 on
    __PAGEZERO, putting __DATA_CONST at 2 — but a MH_DYLIB has no __PAGEZERO,
    so its __DATA_CONST is ordinal 1. Passing the executable's 2 to a dylib
    points the bind at __LINKEDIT, and dyld faults writing the fixup into a
    read-only page (an EXC_BAD_ACCESS inside dyld's own applyFixups).
    """
    out = bytearray()
    for i, sym in enumerate(external_syms):
        ordinal = (dylib_of or {}).get(sym, 1)
        out += bytes((BIND_SET_DYLIB_ORDINAL_IMM | ordinal,))
        out += bytes((BIND_SET_SYMBOL_TRAILING_FLAGS_IMM,))
        # BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM is *trailing*: the symbol
        # flags are a separate byte after the opcode, before the name. Folding
        # them into the opcode byte (or omitting them) desynchronises the whole
        # stream — the first character of every symbol is eaten as the flags
        # byte, and every later opcode is read from the wrong offset, which is
        # what made dyld (and `codesign`, which runs the same validator) reject
        # the image outright.
        out += bytes((BIND_SYMBOL_FLAGS_FUNCTION,))
        # The stream carries the name the SOURCE spelled; dyld prepends the
        # Mach-O underscore when it forms the symbol it looks up. Both spellings
        # were measured against a real dyld: "printf" binds and calls through,
        # while "_printf" gets "Symbol not found: __printf" — the underscore in
        # the message is dyld's own, on top of ours. The codegen hands us the
        # name as the source spelled it, so it is written out unchanged.
        #
        # **It used to drop one leading underscore here**, on the reading that
        # the name arriving is the assembler's spelling — and that is false of
        # every name this link line produces, which are source spellings
        # (measured: a program calling a hostmod function binds
        # `['os_path_join_2dbb98', 'printf']`, and neither begins with `_`). So
        # for a C function that legitimately begins with one the stream carried
        # a DIFFERENT function's name: `external_call["_exit", Int32](3)` bound
        # `exit`, which flushes stdio, where `_exit` does not (C99 7.20.4.4 /
        # POSIX — `_exit` terminates without flushing open streams). Measured on
        # both architectures, before this line changed: the image printed what
        # `exit` flushes and one that calls the real `_exit` prints nothing.
        # The paragraph above this one recorded the same reasoning error and is
        # why the line is worth reading twice.
        out += sym.encode()
        out += b"\0"
        out += bytes((BIND_SET_TYPE_IMM | BIND_TYPE_POINTER,))
        out += bytes((BIND_SET_SEGMENT_AND_OFFSET_ULEB | got_segment,))
        _uleb(out, i * 8)           # offset within __DATA_CONST
        out += bytes((BIND_DO_BIND,))
    out += bytes((BIND_DONE,))
    return bytes(out)


def _assert_no_unclaimed_bytes(image: bytes, segments: list) -> None:
    """Every byte of the file must be claimed by some segment.

    A slice assignment whose value is longer than its slice makes bytearray
    *insert* the extra bytes and shift the tail, which leaves the finished image
    longer than the last segment's declared filesize. Nothing else notices: the
    image still parses, still assembles, and `codesign` refuses it with the
    famously unhelpful "main executable failed strict validation" (that one
    unclaimed byte was the whole reason the extern path could not be built).
    """
    end = 0
    for fileoff, filesize in segments:
        end = max(end, fileoff + filesize)
    if end != len(image):
        raise ValueError(
            f"image is {len(image)} bytes but its segments claim only {end}: "
            f"a byte was inserted past the end of the last segment")


def _uleb_bytes(value: int) -> bytes:
    out = bytearray()
    _uleb(out, value)
    return bytes(out)


def _uleb(out: bytearray, value: int) -> None:
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return


def _write_data_segment(file: bytearray, o: int, data_vm: int, data_file: int,
                        data_size: int, blob: bytes) -> int:
    """Write the `__DATA` segment command + its `__globals` section header.

    One section, `__globals`, holding the module-global slot table and the blobs
    and string bytes the address-valued slots point at. `initprot` is rw- (3)
    because a `global NAME` store WRITES here — a read-only data segment would
    fault on the first write, which is the one operation the segment exists for.

    The load-time initializer is NOT here: it is a `__TEXT,__init_offsets`
    section, beside the code it points at and in the form this platform's
    `clang` emits (`_init_offsets_blob` and `build_macho_dylib`).

    Returns the offset just past the command."""
    def patch(off, fmt, *vals):
        struct.pack_into(fmt, file, off, *vals)

    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72 + 80)
    file[o + 8 : o + 24] = b"__DATA".ljust(16, b"\0")
    patch(o + 24, "<Q", data_vm)
    patch(o + 32, "<Q", data_size)
    patch(o + 40, "<Q", data_file)
    patch(o + 48, "<Q", data_size)
    patch(o + 56, "<I", 0x3)
    patch(o + 60, "<I", 0x3)
    patch(o + 64, "<I", 1)
    patch(o + 68, "<I", 0)
    s = o + 72
    file[s : s + 16] = b"__globals".ljust(16, b"\0")
    file[s + 16 : s + 32] = b"__DATA".ljust(16, b"\0")
    patch(s + 32, "<Q", data_vm)
    patch(s + 40, "<Q", len(blob))
    patch(s + 48, "<I", data_file)
    patch(s + 52, "<I", 3)
    patch(s + 56, "<I", 0)
    patch(s + 60, "<I", 0)
    patch(s + 64, "<I", 0x3)          # S_... : initialized data
    patch(s + 68, "<I", 0)
    patch(s + 72, "<I", 0)
    return o + 72 + 80


def data_segment_ordinal(segments_before_data: int) -> int:
    """The segment ordinal of `__DATA` in a given image.

    An executable spends ordinal 0 on __PAGEZERO, so its __DATA is 2 with no
    GOT segment and 3 with one; a dylib has no __PAGEZERO, so it is 1 and 2.
    Passed in as a count rather than derived here because the two builders
    already know their own segment list — the bug this shape exists to prevent is
    a hardcoded ordinal pointing the fixups at the wrong segment, which dyld
    reports as a fault inside its own applyFixups and not as anything about this
    module."""
    return segments_before_data


def _globals_blob(globals_image) -> bytes:
    """The data blob for a `model.GlobalDataImage`, or b"" for None.

    The one reader of that object for the Mach-O path, so the three builders
    cannot each spell the blob differently. Accepting None is the NORMAL case — a
    module with no `global NAME` in it has no slots — so every builder takes the
    same argument and decides for itself whether it emits a segment."""
    if globals_image is None:
        return b""
    return bytes(globals_image.blob)


def _check_globals_do_not_overlap_text(text_size: int, has_globals: bool) -> None:
    """Refuse a Mach-O image whose `__DATA` would collide with its `__TEXT`.

    `GLOBALS_VM` is ABOVE `TEXT_BASE`, and both facts about that are forced:

      * ABOVE, because a Mach-O's segments must ASCEND in virtual address — dyld
        refuses an image otherwise ("segment '__DATA' vm address out of order",
        measured) — and nothing can go BELOW `__TEXT` either, since
        __PAGEZERO covers all of [0, 4 GB) and the kernel will not map a segment
        into it. Above the text is the only ascending arrangement.
      * FIXED, because __TEXT's size is a function of the CODE and every access
        to a slot is an address the codegen must compute BEFORE the image
        exists. Deriving one from the other makes each depend on the other;
        there is no ordering of the two passes that resolves it, because the
        number of instructions emitted does not depend on the addresses in them.

    So the price is a ceiling on how large an image with module globals can be,
    and this is where that price is collected rather than discovered at launch.
    A program whose __TEXT would reach `GLOBALS_VM` gets two load commands
    describing overlapping mappings; dyld resolves that by refusing the image,
    with nothing in the output naming the segment that collided — so the check
    says which segment and by how much instead.

    The margin is not a guess: the largest formal image measured on this tree
    (`fire.py` plus its whole stdlib dylib set) is an order of magnitude inside
    it, and this raises only on a program the repository does not contain."""
    if not has_globals:
        return
    room = GLOBALS_VM - TEXT_BASE
    if text_size > room:
        raise ValueError(
            f"__TEXT is {text_size} bytes but the fixed module-global __DATA "
            f"is mapped at {GLOBALS_VM:#x}, only {room} bytes past the text "
            f"base {TEXT_BASE:#x}. A __TEXT that reached it would give two "
            f"load commands describing overlapping mappings, and dyld refuses "
            f"such an image at launch without naming the segment that "
            f"collided. A program with module-global state has to fit under "
            f"that ceiling; one without it has no limit.")


def _stub_bytes(got_vm: int, stub_vm: int, arch: str = "arm64") -> bytes:
    """One __TEXT,__stubs entry: jump through the GOT slot at `got_vm`.

    arm64: ADRP X16, page / LDR X16, [X16, #off] / BR X16 — 12 bytes.
    x86-64: JMPQ *disp(%rip), a single 6-byte RIP-relative indirect jump whose
    displacement runs from the END of the instruction."""
    if arch == "x86_64":
        from formal.x86_64 import encode_jmp_rm64
        return encode_jmp_rm64(got_vm - (stub_vm + 6))
    from formal.arm64 import encode_adrp, encode_ldr_xt_xn_imm, encode_br_xn
    page_off = (got_vm & ~0xFFF) - (stub_vm & ~0xFFF)
    got_off = got_vm & 0xFFF
    return (
        encode_adrp(16, page_off)
        + encode_ldr_xt_xn_imm(16, 16, got_off)
        + encode_br_xn(16)
    )


def externer_layout(code_len: int, external_syms: list,
                    arch: str = "arm64", entryoff: int = None) -> dict:
    """Stub/GOT layout for the extern executable.

    Returns the file offset of __text,__stubs and the stub vmaddr for each
    symbol (sorted so both call-site patching and binary emission agree on
    slot ordering).

    `entryoff` is where the code starts, and it is a PARAMETER because a
    linked dylib adds a load command and so moves it (`extern_entry_offset`).
    Falling back to the no-dependency constant is what made a dylib-linked
    image branch into its own epilogue padding: every stub address came out
    low by the load commands' size, so each cross-module BL landed in the
    middle of the caller instead of on a stub. The caller and this function
    must agree on the offset for the SAME dylib set."""
    syms = sorted(external_syms)
    ssize = stub_size(arch)
    if entryoff is None:
        entryoff = EXTERN_ENTRYOFF
    stub_file = (entryoff + code_len + 3) & ~3
    stub_base_vm = TEXT_BASE + stub_file
    return {
        "stub_file": stub_file,
        "stub_addrs": {sym: stub_base_vm + i * ssize for i, sym in enumerate(syms)},
    }


def build_macho_executable_extern(
    code: bytes, external_syms: list, arch: str = "arm64",
    dylibs: list = None, globals_image=None,
) -> bytes:
    """Executable with __TEXT,__stubs + __DATA_CONST,__got + LC_LOAD_DYLIB
    libSystem + classic bind. `code` already contains call instructions whose
    targets (stub addresses) end in immediate zero placeholders; the caller
    patches them to the real stub vmaddrs via resolve_extern before calling.

    Like build_macho_executable, the entry offset comes from this layout
    (executable_entry_offset) rather than from the caller.

    `dylibs` is an optional list of `{"install_name": str, "symbols": set}`
    — formal libraries this executable links against, in the order the caller
    wants their LC_LOAD_DYLIB commands emitted. Dylib ordinals are 1-based
    over that list *after* libSystem, so a symbol in `dylibs[k]["symbols"]`
    binds with ordinal k+2; everything else binds from libSystem (ordinal 1).
    Each one adds a load command, which moves the entry point, so the caller
    must have compiled `code` for the offset `extern_entry_offset` reports for
    the SAME dylib list.

    `globals_image` is a `model.GlobalDataImage` (or None): the module-global
    slot table this image needs in `__DATA`. Its presence adds a segment, which
    moves the entry point, so `has_globals` has to be threaded through the same
    `extern_entry_offset` the caller computed the base address from."""
    spec = arch_spec(arch)
    ssize = spec["stub_size"]
    dylibs = list(dylibs or [])
    gblob = _globals_blob(globals_image)
    has_globals = bool(gblob)
    entryoff = extern_entry_offset([d["install_name"] for d in dylibs],
                                   has_globals=has_globals)
    external_syms = sorted(external_syms)
    n = len(external_syms)
    stub_file = (entryoff + len(code) + 3) & ~3
    stub_base_vm = TEXT_BASE + stub_file
    dylib_of = {}
    for k, d in enumerate(dylibs):
        for sym in d.get("symbols") or ():
            dylib_of[sym] = k + 2          # ordinal 1 is libSystem
    bind = _bind_info(external_syms, dylib_of)
    bind_len = len(bind)

    # Everything in __TEXT, then one page per `8 * n` of GOT, then __LINKEDIT
    # — all sized from the content, so a program past the first page gets more
    # __TEXT pages instead of running off the end of the segment (see
    # _text_filesize and _assert_no_unclaimed_bytes).
    text_size = _text_filesize(stub_file + ssize * n)
    data_file = text_size
    data_size = _align_up(8 * n, PAGE_SIZE) or PAGE_SIZE
    # __DATA (module-global slots) goes after __DATA_CONST, so its ordinal is
    # one past the GOT's: __PAGEZERO 0, __TEXT 1, __DATA_CONST 2, __DATA 3.
    g_file = data_file + data_size if has_globals else 0
    g_size = _align_up(len(gblob), PAGE_SIZE) if has_globals else 0
    g_vm = GLOBALS_VM if has_globals else 0
    _check_globals_do_not_overlap_text(text_size, has_globals)
    bind_file = g_file + g_size if has_globals else data_file + data_size
    got_base_vm = TEXT_BASE + data_file
    sizeofcmds = (EXTERN_SIZEOFCMDS + sum(
        dylib_command_size(d["install_name"]) for d in dylibs)
        + (DATA_SIZEOFCMDS if has_globals else 0))
    # The extern layout emits 10 load commands (…LC_LOAD_DYLIB libSystem,
    # LC_BUILD_VERSION, LC_MAIN); each linked dylib adds one more, and the
    # __DATA segment one more still.
    ncmds = 10 + len(dylibs) + (1 if has_globals else 0)
    file = bytearray(bind_file + bind_len)

    def patch(off: int, fmt: str, *vals) -> None:
        struct.pack_into(fmt, file, off, *vals)

    patch(0, "<I", MAGIC_64)
    patch(4, "<I", spec["cputype"])
    patch(8, "<I", spec["cpusubtype"])

    patch(12, "<I", MH_EXECUTE)
    patch(16, "<I", ncmds)
    patch(20, "<I", sizeofcmds)
    patch(24, "<I", MH_EXECUTE_FLAGS)

    o = 32

    # __PAGEZERO
    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72)
    file[o + 8 : o + 24] = b"__PAGEZERO".ljust(16, b"\0")
    patch(o + 24, "<Q", 0)
    patch(o + 32, "<Q", PAGEZERO_SIZE)
    patch(o + 40, "<Q", 0)
    patch(o + 48, "<Q", 0)
    patch(o + 56, "<I", 0)
    patch(o + 60, "<I", 0)
    patch(o + 64, "<I", 0)
    patch(o + 68, "<I", 0)
    o += 72

    # __TEXT (vmaddr TEXT_BASE, fileoff 0) with __text + __stubs
    o = _write_text_segment(file, o, text_size, [
        (b"__text", TEXT_BASE + entryoff, len(code), entryoff,
         0x80000400, 0),
        (b"__stubs", stub_base_vm, ssize * n, stub_file, 0x80000408, ssize),
    ])

    # __DATA_CONST (fileoff data_file, one page per 8 * n of GOT) with __got
    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72 + 80)
    file[o + 8 : o + 24] = b"__DATA_CONST".ljust(16, b"\0")
    patch(o + 24, "<Q", got_base_vm)
    patch(o + 32, "<Q", data_size)  # vmsize
    patch(o + 40, "<Q", data_file)  # fileoff
    patch(o + 48, "<Q", data_size)  # filesize
    patch(o + 56, "<I", 0x3)  # rw- : dyld writes the GOT slot at load time
    patch(o + 60, "<I", 0x3)
    patch(o + 64, "<I", 1)  # nsects: __got
    patch(o + 68, "<I", 0)
    s = o + 72
    file[s : s + 16] = b"__got".ljust(16, b"\0")
    file[s + 16 : s + 32] = b"__DATA_CONST".ljust(16, b"\0")
    patch(s + 32, "<Q", got_base_vm)
    patch(s + 40, "<Q", 8 * n)
    patch(s + 48, "<I", data_file)
    patch(s + 52, "<I", 3)
    patch(s + 56, "<I", 0)
    patch(s + 60, "<I", 0)
    patch(s + 64, "<I", 0x6)
    patch(s + 68, "<I", 0)
    patch(s + 72, "<I", 0)
    o += 72 + 80

    if has_globals:
        o = _write_data_segment(file, o, g_vm, g_file, g_size, gblob)

    # __LINKEDIT
    linkedit_len = bind_len
    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72)
    file[o + 8 : o + 24] = b"__LINKEDIT".ljust(16, b"\0")
    patch(o + 24, "<Q", TEXT_BASE + bind_file)
    patch(o + 32, "<Q", _align_up(linkedit_len, PAGE_SIZE))
    patch(o + 40, "<Q", bind_file)
    patch(o + 48, "<Q", linkedit_len)
    patch(o + 56, "<I", 1)   # maxprot r--: __LINKEDIT holds the code signature
    patch(o + 60, "<I", 1)   # initprot r--; dyld only reads the bind opcodes
    o += 72

    # LC_DYLD_INFO_ONLY -> bind_off/bind_size = bind data in __LINKEDIT;
    # rebase_off/rebase_size stay zero (see the noextern builder for why).
    # NOTE: dyld_info_command fields are uint32_t, not uint64_t.
    patch(o + 0, "<I", DYLD_INFO_ONLY_CMD)
    patch(o + 4, "<I", 48)
    patch(o + 8, "<I", 0)
    patch(o + 12, "<I", 0)
    patch(o + 16, "<I", bind_file)            # bind_off
    patch(o + 20, "<I", bind_len)             # bind_size
    patch(o + 24, "<I", 0)         # weak_bind_off/size/...
    patch(o + 28, "<I", 0)
    patch(o + 32, "<I", 0)
    patch(o + 36, "<I", 0)
    patch(o + 40, "<I", 0)
    patch(o + 44, "<I", 0)
    o += 48

    # LC_LOAD_DYLINKER
    file[o : o + DYLINKER_CMDSIZE] = _dylinker_cmd()
    o += DYLINKER_CMDSIZE

    # LC_UUID
    patch(o + 0, "<I", UUID_CMD)
    patch(o + 4, "<I", 24)
    o += 24

    # LC_LOAD_DYLIB (libSystem)
    #
    # The name slice must be exactly as wide as the name. Writing 27 bytes
    # ("/usr/lib/libSystem.B.dylib\0") into a 26-byte slice makes bytearray
    # *insert* the extra byte and shift everything after it right by one, which
    # left the finished image a byte longer than __LINKEDIT's declared
    # filesize — one unclaimed trailing byte, which is all it takes for
    # `codesign` to refuse the whole executable with "main executable failed
    # strict validation" and for the extern path to be unbuildable.
    patch(o + 0, "<I", LOAD_DYLIB_CMD)
    patch(o + 4, "<I", 56)
    patch(o + 8, "<I", 24)
    patch(o + 12, "<I", 0)          # timestamp
    patch(o + 16, "<I", 0x10000)    # current version
    patch(o + 20, "<I", 0x10000)    # compatibility version
    file[o + 24 : o + 24 + len(LIBSYSTEM_PATH)] = LIBSYSTEM_PATH
    o += 56

    # One LC_LOAD_DYLIB per linked formal library, in the order the caller
    # listed them — which is what fixes the dylib ordinals the bind stream
    # uses (ordinal 1 is libSystem, so these are 2, 3, …). A dependency the
    # loader cannot satisfy makes dyld refuse the image at launch, so the
    # path recorded is the dylib's real location rather than its `@rpath`
    # install name (which would additionally need an LC_RPATH here).
    for d in dylibs:
        name = d["install_name"].encode("utf-8") + b"\0"
        dsize = dylib_command_size(d["install_name"])
        patch(o + 0, "<I", LOAD_DYLIB_CMD)
        patch(o + 4, "<I", dsize)
        patch(o + 8, "<I", 24)
        patch(o + 12, "<I", 0)          # timestamp
        patch(o + 16, "<I", 0x10000)    # current version
        patch(o + 20, "<I", 0x10000)    # compatibility version
        file[o + 24 : o + 24 + len(name)] = name
        o += dsize

    # LC_BUILD_VERSION — not optional decoration. Without it this image is
    # rejected by `codesign` with "main executable failed strict validation"
    # (dyld has no declared platform/minimum OS to validate the load commands
    # against), which is why the extern path could not be signed at all. Every
    # other layout here has always carried one.
    patch(o + 0, "<I", BUILD_VERSION_CMD)
    patch(o + 4, "<I", 24)
    patch(o + 8, "<I", 1)             # platform: macOS
    patch(o + 12, "<I", 0x000B0000)   # minos 11.0
    patch(o + 16, "<I", 0x000B0000)   # sdk 11.0
    patch(o + 20, "<I", 0)            # ntools
    o += 24

    # LC_MAIN
    patch(o + 0, "<I", MAIN_CMD)
    patch(o + 4, "<I", 24)
    patch(o + 8, "<Q", entryoff)
    patch(o + 16, "<Q", 0)
    o += 24

    # The code starts after the load commands with CODE_SIGNATURE_CMDSIZE bytes
    # of slack in between (executable_entry_offset), which is what
    # `codesign -s -` needs to add LC_CODE_SIGNATURE without landing it on the
    # first instructions.
    assert o + CODE_SIGNATURE_CMDSIZE <= entryoff, (o, entryoff)
    file[entryoff : entryoff + len(code)] = code
    for i in range(n):
        got_vm = got_base_vm + i * 8
        stub_vm = stub_base_vm + i * ssize
        f = stub_file + i * ssize
        file[f : f + ssize] = _stub_bytes(got_vm, stub_vm, arch)
    file[bind_file : bind_file + bind_len] = bind
    if has_globals:
        file[g_file : g_file + len(gblob)] = gblob
    _assert_no_unclaimed_bytes(file, [(0, text_size), (data_file, data_size)]
                               + ([(g_file, g_size)] if has_globals else [])
                               + [(bind_file, bind_len)])
    return bytes(file)


MH_DYLIB = 6
ID_DYLIB_CMD = 0x0D
DYLD_EXPORTS_TRIE_CMD = 0x80000033


def _trie_insert(root: dict, name: bytes, terminal: bytes) -> None:
    """Add `name` -> `terminal` to a radix trie, splitting edges as needed.

    A node is `{"term": bytes | None, "kids": {edge: node}}`, and `edge` is
    the BYTES that follow the parent, so a shared prefix is stored once and
    the symbols that share it become siblings one level down. That is the
    whole reason this function exists — see `_export_trie`.

    One pass per level and an explicit `break` out of the edge scan rather
    than a `continue`: a `continue` restarts the scan over the node it was
    written for, and the split case has already moved `node`, so the rescan
    would insert the new symbol's (now empty) remainder into the WRONG node —
    an empty edge, and a trie dyld walks off the end of. Written as three
    explicit cases because the third one is the bug.
    """
    node = root
    rest = name
    while True:
        if not rest:
            node["term"] = terminal
            return
        for edge in list(node["kids"]):
            if rest.startswith(edge):
                # The whole edge is consumed: descend.
                node = node["kids"][edge]
                rest = rest[len(edge):]
                break
            if edge.startswith(rest):
                # `rest` is a PREFIX of an existing edge: split the edge at the
                # divergence, keep what is left of the old edge under the
                # split, and the new symbol IS the split.
                child = node["kids"].pop(edge)
                split = {"term": terminal,
                         "kids": {edge[len(rest):]: child}}
                node["kids"][rest] = split
                return
        else:
            node["kids"][rest] = {"term": terminal, "kids": {}}
            return


def _trie_preorder(root: dict) -> list:
    """Every node, a parent before its children, edges in sorted order.

    The order the layout walk uses, and the sort is part of the format rather
    than taste: a trie is emitted with each node's edges in ascending byte
    order, and dyld's lookup narrows with that ordering.
    """
    out = [root]
    for edge in sorted(root["kids"]):
        out.extend(_trie_preorder(root["kids"][edge]))
    return out


def _trie_node_size(node: dict, widths: dict) -> int:
    """Bytes `_trie_emit` will write for `node`, given each offset's width.

    The width is a parameter rather than a measurement because it is the only
    circularity in the layout: an edge's encoded size includes the ULEB of its
    child's offset, and that offset is not known until the sizes are. The
    widths converge — they only ever grow, and are bounded by the trie's own
    size — which is what `_export_trie`'s loop waits for.
    """
    term = node["term"] or b""
    size = 2 + len(term)              # terminalSize + childCount + the
    #                                # terminal, in _trie_emit's order
    for edge, kid in node["kids"].items():
        size += len(edge) + 1 + widths[id(kid)]
    return size


def _trie_emit(node: dict, offsets: dict) -> bytes:
    """One node: `terminalSize`, the terminal, `childCount`, then the edges.

    **The terminal comes BEFORE the child count, and both are single bytes.**
    That is the order, and it is worth stating because the prose in Apple's
    own header puts the child count second, and following the prose produces a
    file dyld misreads. Ground truth, from a dylib this machine's `cc` linked
    (`cc -dynamiclib`, two functions `_foo` and `_foobar`), decoded with the
    order below:

        trie = 00 01 5f 66 6f 6f 00 11 | 00 00 00 00 03 00 e8 05
               00 03 00 d0 05 01 62 61 72 00 0c 00 00 00 00 00
                    ^^^^^^^^^^^^^^^^^^^^^^^^^ root: 0 children-of-size,
                                      one edge `_foo` -> node at 0x11
               node@0x0c: 03 | 00 e8 05 | 00
                            tsz   flags=0   nkids=0
                                  addr=0x2E8          <- `_foobar`
               node@0x11: 03 | 00 d0 05 | 01 | 62 61 72 00 0c
                            tsz   flags=0   nkids=1
                                  addr=0x2D0          <- `_foo`
                                  edge `bar` -> node at 0x0c

    and `dyld_info -exports` on that same file agrees: `_foo` at 0x2D0,
    `_foobar` at 0x2E8. With the child count read second instead, the same
    bytes decode as one root child `_foo` whose terminal is `d0 05 01` — flags
    720, address 1 — and `_foobar` is not in the trie at all. Both readings
    are self-consistent on the bytes; only one of them is the format, and the
    test is which one `dyld_info` reproduces.
    """
    term = node["term"] or b""
    if len(term) > 255:
        raise ValueError(
            f"export trie terminal is {len(term)} bytes; the format's "
            f"terminalSize is one byte")
    if len(node["kids"]) > 255:
        raise ValueError(
            f"export trie node has {len(node['kids'])} children; the format's "
            f"childCount is one byte")
    out = bytearray()
    out.append(len(term))
    out += term
    out.append(len(node["kids"]))
    for edge in sorted(node["kids"]):
        out += edge + b"\0"
        _uleb(out, offsets[id(node["kids"][edge])])
    for edge in sorted(node["kids"]):
        out += _trie_emit(node["kids"][edge], offsets)
    return bytes(out)


def _export_trie(exports: list) -> bytes:
    """The module's export trie, as a real radix trie.

    The terminal's flags word is 0, i.e. EXPORT_SYMBOL_FLAGS_KIND_REGULAR.
    The low two bits of that word are the symbol *kind* (0 = regular,
    1 = thread-local, 2 = absolute), so a nonzero value here does not merely
    look odd: dyld reports every such symbol as "[per-thread]" in
    `dyld_info -exports`, and any consumer that honours the kind (a TLS-aware
    caller, or dyld's own validation) would treat an ordinary function as a
    thread-local one.

    **Shared prefixes are split, and that is not an optimisation — it is the
    format.** This used to be a FLAT trie: every symbol one whole edge off the
    root, which is shorter to write and is wrong as soon as one symbol is a
    prefix of another. dyld narrows a lookup by walking edges, and a flat trie
    puts `_m_version` and `_m_version_info_major` SIBLINGS; dyld matches the
    first against the second's leading bytes, descends into a node with no
    children, and does not go back to try the next edge. The longer symbol is
    then in the file, in the manifest, and unbindable.

    Measured, on the smallest module that shows it (three functions, `version`
    / `version_info_major` / `other`):

        print(m.other())            -> 3
        print(m.version())          -> 1
        print(m.version_info_major())
          dyld: Symbol not found: _m_version_info_major
            Referenced from: .../p.aout
            Expected in:     .../m.<digest>.arm64.dylib

    The image built, passed every static check, and died in the loader for a
    function that is right there in the trie. Nothing reported it: the module
    built, the manifest listed the symbol, this tree's own trie reader read
    it back correctly, and only dyld — the one reader that implements the
    format — disagreed. So the trie is a proper radix trie now, with a
    shared prefix stored once and the two symbols siblings one level down,
    which is what the format has always meant.
    """
    root = {"term": None, "kids": {}}
    for export in sorted(exports, key=lambda e: e["symbol"]):
        # The export table holds Mach-O names; `symbol` is the C identifier
        # the ABI spells (what an importer's bind stream carries, and what
        # dyld prepends its underscore to). Prepending it here keeps the two
        # conventions from drifting: a trie written with the bare C name
        # exports a symbol nothing can bind, and the program dies in dyld with
        # "Symbol not found" for a function that is right there.
        raw = (export["symbol"] if export["symbol"].startswith("_")
               else "_" + export["symbol"]).encode("utf-8")
        addr = bytearray()
        _uleb(addr, export["entry"] - TEXT_BASE)
        flags = bytearray()
        _uleb(flags, 0)
        _trie_insert(root, raw, bytes(flags) + bytes(addr))
    order = _trie_preorder(root)
    widths = {id(node): 1 for node in order}
    offsets = {id(node): 0 for node in order}
    cursor = 0
    for _ in range(8):
        sizes = {id(node): _trie_node_size(node, widths) for node in order}
        cursor = 0
        for node in order:                     # a parent before its children
            offsets[id(node)] = cursor
            cursor += sizes[id(node)]
        measured = {id(node): len(_uleb_bytes(offsets[id(node)]))
                    for node in order}
        if measured == widths:
            break
        widths = measured
    else:
        # Not a "should not happen": a layout whose encoded sizes never settle
        # is a trie whose edge offsets would be written for the wrong widths,
        # and the file would be a plausible-looking wrong one. Say so.
        raise ValueError("export trie layout did not converge")
    trie = _trie_emit(root, offsets)
    if len(trie) != cursor:
        raise ValueError(
            f"export trie is {len(trie)} bytes but the layout reserved "
            f"{cursor}: the emitted offsets do not match the layout")
    return trie


def dylib_load_commands(install_name: str, has_externs: bool,
                        deps: list = None, has_globals: bool = False,
                        has_mod_init: bool = False) -> tuple:
    """(sizeofcmds, ncmds) of a dylib's load-command list.

    One function, because the code offset is DERIVED from this and the two
    must agree: a dylib that calls out carries a __DATA_CONST segment and an
    LC_LOAD_DYLIB for libSystem on top of the plain layout, which pushes the
    code down, and every MODULE it depends on adds another LC_LOAD_DYLIB that
    pushes it down further. Computing the offset from a separate copy of the
    formula is what produced "dylib load commands overlap code" the moment
    externs existed — the same drift the executable's entry offset had.

    `deps` are the install names of the libraries this one links, in the order
    their LC_LOAD_DYLIB commands are emitted. That order IS the bind stream's
    ordinal space (1 = libSystem when present, then deps), so it is passed in
    rather than sorted here: reordering it would silently rebind every symbol.

    `has_globals` adds the module-global `__DATA` segment, and `has_mod_init`
    a THIRD SECTION in `__TEXT` (the `__init_offsets` list a library with a
    module body runs at load, beside the code it points at — `S_INIT_FUNC_OFFSETS`
    for the form). Either is 80 more bytes of load command and so pushes the
    code down by as much as the segment or section it describes. Both effects
    have to be visible here, where the code offset is decided, rather than
    discovered later by the builder — and the builder's own check that the base
    it was handed matches this layout is what turns a caller that forgot to pass
    the flag into a refusal instead of a mis-mapped image."""
    deps = list(deps or [])
    name = install_name.encode("utf-8") + b"\0"
    id_cmdsize = (24 + len(name) + 7) & ~7
    # __TEXT carries __text, plus __stubs when the library calls out, plus
    # __init_offsets when it has a module body, so its command is 72 + 80 per
    # section.
    text_sections = (2 if has_externs else 1) + (1 if has_mod_init else 0)
    text_cmdsize = 72 + 80 * text_sections
    dep_cmds = sum(dylib_command_size(d) for d in deps)
    sizeofcmds = (text_cmdsize + 72 + id_cmdsize + 24 + 24 + 48 + 16 + dep_cmds
                  + (dylib_command_size(LIBSYSTEM_PATH.decode()) + 152
                     if has_externs else 0)
                  + (DATA_SIZEOFCMDS if has_globals else 0))
    return sizeofcmds, (7 + (2 if has_externs else 0) + len(deps)
                        + (1 if has_globals else 0))


def dylib_code_offset(install_name: str, has_externs: bool = False,
                      deps: list = None, has_globals: bool = False,
                      has_mod_init: bool = False) -> int:
    """File offset of a dylib's code.

    `has_externs`, `deps`, `has_globals` and `has_mod_init` must match what the
    library is actually built with — the caller needs them BEFORE compiling,
    because they decide the base address the code is emitted for.
    """
    sizeofcmds, _n = dylib_load_commands(install_name, has_externs, deps,
                                         has_globals, has_mod_init)
    return ((32 + sizeofcmds + 31) & ~15)


def _write_load_dylib(file, o: int, install_name: str) -> int:
    """Emit one LC_LOAD_DYLIB at `o`; return the offset just past it."""
    raw = install_name.encode("utf-8") + b"\0"
    cmdsize = dylib_command_size(install_name)
    struct.pack_into("<I", file, o, LOAD_DYLIB_CMD)
    struct.pack_into("<I", file, o + 4, cmdsize)
    struct.pack_into("<I", file, o + 8, 24)
    struct.pack_into("<I", file, o + 12, 0)
    struct.pack_into("<I", file, o + 16, 0x10000)
    struct.pack_into("<I", file, o + 20, 0x10000)
    file[o + 24 : o + 24 + len(raw)] = raw
    return o + cmdsize


def build_macho_dylib(code: bytes, base_addr: int, exports: list,
                      install_name: str, arch: str = "arm64",
                      external_syms: list = None,
                      entryoff: int = None, deps: list = None,
                      dep_syms: dict = None, globals_image=None,
                      mod_init_addrs: list = None) -> bytes:
    """MH_DYLIB with an export trie, and — when `external_syms` is given —
    the same extern machinery an executable has: __TEXT,__stubs, a
    __DATA_CONST,__got, an LC_LOAD_DYLIB for libSystem, and a bind stream.

    A dylib that calls out is the normal case, not an exotic one: the stdlib
    calls printf and malloc everywhere, so refusing externs here is what stops
    a formal stdlib dylib from existing at all. The layout mirrors
    `build_macho_executable_extern` deliberately — a caller reaching a symbol
    goes through a stub and a GOT slot dyld fills at load time — so a program
    and the library it links behave the same way.

    `entryoff` is where the code starts (it moves with the load-command list,
    which now includes the libSystem dependency), so the stub addresses the
    caller patched its call sites to must be computed for the same value.

    `deps` are install names of MODULE libraries this dylib links (a package
    that calls its sibling's functions), and `dep_syms` maps each such
    library's exported symbol to it. Without the load commands, a call to a
    sibling binds against nothing: the image builds, and then dies in dyld
    with "Symbol not found" for a function that exists in the sibling. Bind
    ordinals are assigned in this order — libSystem is 1, then deps in the
    order given — so the same list drives both the commands and the stream.

    `globals_image` gives the library its own `__DATA` slot table, which is the
    same treatment an executable gets and for the same reason: a `global NAME`
    inside a library function writes a word that a LATER call has to read, and
    a word in that library's frames would be gone by then. It is deliberately
    NOT exported in the trie — see `bugs/FORMAL_module_state_no_storage.md` for
    why a cross-module global is a separate capability and not this one: an
    exporting module's slot would need the importing module's GOT to carry a
    POINTER-TO-DATA symbol, and this backend's export/bind machinery is
    function-shaped.

    `mod_init_addrs` are the ADDRESSES of the functions the LOADER must run when
    it loads this image — the module body's wrapper, one per source file that
    had one, in that order — and they become the `__TEXT,__init_offsets` list
    dyld calls (`_init_offsets_blob` for the form, which is offsets rather than
    pointers and is the reason the section is in `__TEXT`). Addresses in,
    because `Assembler.label` already records `org + len(text)`: a label is the
    address the image maps.

    This is the library's entry point, and the reason a module with top-level
    statements can be a library at all: an initializer runs after the image's
    dependencies are loaded and before the program's `main`, which is the
    position CPython gives a module body's statements at import. A library with a
    body and no initializer compiles the body to a function nothing runs, which
    is the silent no-op the list removes — and which cost 16 files of this
    repository before it existed (`tools/formal_sweep.py`'s
    CODEGEN/DEPENDENCY rows, all sixteen of which were this one message).

    Empty — the ordinary case, every module whose top level is declarations and
    constants — writes no section and does not move the code, so every image the
    tree built before this argument existed is byte-for-byte the image it builds
    now."""
    spec = arch_spec(arch)
    trie = _export_trie(exports)
    name = install_name.encode("utf-8") + b"\0"
    id_cmdsize = (24 + len(name) + 7) & ~7
    ssize = spec["stub_size"]
    external_syms = sorted(external_syms or [])
    n = len(external_syms)
    # One LC_LOAD_DYLIB for libSystem, and the DYLD_INFO_ONLY now carries a
    # real bind stream, so both add to the load-command list — which is what
    # moves the code (and so the stubs).
    deps = list(deps or [])
    gblob = _globals_blob(globals_image)
    has_globals = bool(gblob)
    # One entry per load-time initializer, in the order the addresses were
    # given, as the 32-bit IMAGE-RELATIVE OFFSETS this platform's dyld reads —
    # `_init_offsets_blob` for why that is the form and not a pointer array.
    init_blob = _init_offsets_blob(mod_init_addrs)
    has_mod_init = bool(init_blob)
    sizeofcmds, ncmds = dylib_load_commands(install_name, bool(n), deps,
                                             has_globals, has_mod_init)
    code_file = dylib_code_offset(install_name, bool(n), deps, has_globals,
                                  has_mod_init)
    if base_addr != TEXT_BASE + code_file:
        raise ValueError("dylib base address does not match Mach-O layout")
    # Stubs follow the code exactly as in the executable, so a call site's
    # patched target and the stub the image emits cannot drift apart.
    stub_file = (code_file + len(code) + 3) & ~3 if n else 0
    stub_base_vm = base_addr + (stub_file - code_file)
    # The initializer list follows the stubs (or the code, in a library that
    # calls nothing out) and is INSIDE __TEXT, at a 4-byte-aligned file offset
    # because its entries are 4 bytes. Beside the code rather than in `__DATA`
    # for the reason the offsets are relative: the values are offsets from the
    # mach_header, and `__TEXT` is the segment the mach_header lives in.
    init_file = _align_up((stub_file + ssize * n) if n else code_file + len(code), 4) \
        if has_mod_init else 0
    text_size = _text_filesize(init_file + len(init_blob) if has_mod_init
                               else (stub_file + ssize * n) if n
                               else code_file + len(code))
    data_file = text_size if n else 0
    data_size = _align_up(8 * n, PAGE_SIZE) if n else 0
    got_base_vm = TEXT_BASE + data_file if n else 0
    # __DATA (module-global slots) after __DATA_CONST, so its ORDINAL is 1 with
    # no GOT segment and 2 with one. That is the executable's numbering less
    # one, because a dylib has no __PAGEZERO — the same off-by-one the GOT
    # ordinal already has to get right, and the reason this is computed from
    # `n` rather than written down.
    g_file = (data_file + data_size) if (n and has_globals) else (
        text_size if has_globals else 0)
    g_size = _align_up(len(gblob), PAGE_SIZE) if has_globals else 0
    g_vm = GLOBALS_VM if has_globals else 0
    _check_globals_do_not_overlap_text(text_size, has_globals)
    # A dylib has no __PAGEZERO, so its segments are 0=__TEXT,
    # 1=__DATA_CONST, 2=__LINKEDIT — the GOT is ordinal 1 here, not the
    # executable's 2 (see _bind_info).
    # libSystem takes ordinal 1 (it is emitted first); each dep follows, in
    # `deps` order, so a symbol must be attributed to the library that
    # actually defines it or dyld binds it against the wrong image.
    dylib_of = {}
    for i, dep in enumerate(deps):
        for sym in (dep_syms or {}).get(dep) or []:
            dylib_of[sym] = (2 if n else 1) + i
    bind = _bind_info(external_syms, dylib_of=dylib_of, got_segment=1) if n else b""
    # __LINKEDIT starts after whatever content precedes it, and the order is
    # fixed: __TEXT, then __DATA_CONST (the GOT) when there are externs, then
    # __DATA (the module-global slots) when there are any. Written as the sum of
    # the pieces that are actually present rather than as a chain of cases,
    # because the chain had a branch that returned 0 for the most ordinary
    # dylib there is — one with externs and no globals — and produced an image
    # whose load commands ran off the end of a 31-byte file.
    linkedit_file = text_size + (data_size if n else 0) + g_size
    file = bytearray(linkedit_file + len(trie) + len(bind))

    def patch(off, fmt, *vals):
        struct.pack_into(fmt, file, off, *vals)

    patch(0, "<I", MAGIC_64)
    patch(4, "<I", spec["cputype"])
    patch(8, "<I", spec["cpusubtype"])
    patch(12, "<I", MH_DYLIB)
    patch(16, "<I", ncmds)
    patch(20, "<I", sizeofcmds)
    patch(24, "<I", 0x800005)
    o = 32

    text_sections = [(b"__text", base_addr, len(code), code_file, 0x80000400, 0)]
    if n:
        text_sections.append(
            (b"__stubs", stub_base_vm, ssize * n, stub_file, 0x80000408, ssize))
    if has_mod_init:
        # `S_INIT_FUNC_OFFSETS`, and `__TEXT` — the two things `_init_offsets_blob`
        # says dyld reads and where. An initializer this image declares but dyld
        # does not call is the module body compiled and never run: the file
        # builds, links, and does nothing at load time.
        text_sections.append(
            (b"__init_offsets", TEXT_BASE + init_file, len(init_blob),
             init_file, S_INIT_FUNC_OFFSETS, 0))
    o = _write_text_segment(file, o, text_size, text_sections)
    if n:
        # __DATA_CONST,__got — rw- because dyld writes the resolved pointer.
        patch(o, "<I", SEGMENT_64_CMD)
        patch(o + 4, "<I", 152)
        file[o + 8 : o + 24] = b"__DATA_CONST".ljust(16, b"\0")
        patch(o + 24, "<Q", got_base_vm)
        patch(o + 32, "<Q", data_size)     # vmsize
        patch(o + 40, "<Q", data_file)     # fileoff
        patch(o + 48, "<Q", data_size)     # filesize
        patch(o + 56, "<I", 0x3)
        patch(o + 60, "<I", 0x3)
        patch(o + 64, "<I", 1)             # nsects: __got
        patch(o + 68, "<I", 0)
        s2 = o + 72
        file[s2 : s2 + 16] = b"__got".ljust(16, b"\0")
        file[s2 + 16 : s2 + 32] = b"__DATA_CONST".ljust(16, b"\0")
        patch(s2 + 32, "<Q", got_base_vm)
        patch(s2 + 40, "<Q", 8 * n)
        patch(s2 + 48, "<I", data_file)
        patch(s2 + 52, "<I", 3)
        patch(s2 + 56, "<I", 0)
        patch(s2 + 60, "<I", 0)
        patch(s2 + 64, "<I", 0x6)
        patch(s2 + 68, "<I", 0)
        patch(s2 + 72, "<I", 0)
        o += 152

    if has_globals:
        o = _write_data_segment(file, o, g_vm, g_file, g_size, gblob)

    patch(o, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72)
    file[o + 8 : o + 24] = b"__LINKEDIT".ljust(16, b"\0")
    patch(o + 24, "<Q", TEXT_BASE + linkedit_file)
    linkedit_len = len(trie) + len(bind)
    patch(o + 32, "<Q", ((linkedit_len + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE)
    patch(o + 40, "<Q", linkedit_file)
    patch(o + 48, "<Q", linkedit_len)
    patch(o + 56, "<I", 1)
    patch(o + 60, "<I", 1)
    o += 72

    patch(o, "<I", ID_DYLIB_CMD)
    patch(o + 4, "<I", id_cmdsize)
    patch(o + 8, "<I", 24)
    patch(o + 12, "<I", 0)
    patch(o + 16, "<I", 0x10000)
    patch(o + 20, "<I", 0x10000)
    file[o + 24 : o + 24 + len(name)] = name
    o += id_cmdsize

    if n:
        # The library's own dependency. Without it the bind stream's ordinal
        # 1 has nothing to refer to and every extern is unresolvable at load.
        o = _write_load_dylib(file, o, LIBSYSTEM_PATH.decode())

    # Module libraries, in the same order the bind ordinals above assume.
    for dep in deps:
        o = _write_load_dylib(file, o, dep)

    patch(o, "<I", BUILD_VERSION_CMD)
    patch(o + 4, "<I", 24)
    patch(o + 8, "<I", 1)
    patch(o + 12, "<I", 0x000B0000)
    patch(o + 16, "<I", 0x000B0000)
    patch(o + 20, "<I", 0)
    o += 24

    patch(o, "<I", UUID_CMD)
    patch(o + 4, "<I", 24)
    o += 24

    patch(o, "<I", DYLD_INFO_ONLY_CMD)
    patch(o + 4, "<I", 48)
    # bind_off/bind_size in that field order, so dyld has GOT slots to fill;
    # rebase_off/rebase_size stay zero (see the noextern builder).
    patch(o + 8, "<I", 0)
    patch(o + 12, "<I", 0)
    patch(o + 16, "<I", linkedit_file + len(trie) if n else 0)
    patch(o + 20, "<I", len(bind))
    o += 48

    patch(o, "<I", DYLD_EXPORTS_TRIE_CMD)
    patch(o + 4, "<I", 16)
    patch(o + 8, "<I", linkedit_file)
    patch(o + 12, "<I", len(trie))
    o += 16

    if o > code_file:
        raise ValueError("dylib load commands overlap code")
    file[code_file : code_file + len(code)] = code
    if n:
        for i in range(n):
            f = stub_file + i * ssize
            got_vm = got_base_vm + i * 8
            file[f : f + ssize] = _stub_bytes(got_vm, stub_base_vm + i * ssize,
                                               arch)
    if has_globals:
        file[g_file : g_file + len(gblob)] = gblob
    if init_blob:
        file[init_file : init_file + len(init_blob)] = init_blob
    file[linkedit_file : linkedit_file + len(trie)] = trie
    file[linkedit_file + len(trie) : linkedit_file + linkedit_len] = bind
    _assert_no_unclaimed_bytes(
        file,
        [(0, text_size)]
        + ([(data_file, data_size)] if n else [])
        + [(linkedit_file, linkedit_len)])
    return bytes(file)


if __name__ == "__main__":
    main_code = bytes([0x00, 0x00, 0x80, 0x52, 0xC0, 0x03, 0x5F, 0xD6])
    with open("/tmp/a.out", "wb") as f:
        f.write(build_macho_executable(main_code))
    print("wrote /tmp/a.out")
