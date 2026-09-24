"""Mach-O executable (a.out) generator: constructs an MH_EXECUTE binary from scratch.

Two builders:
- build_macho_executable: minimal executable, no external symbols.
- build_macho_executable_extern: executable linking /usr/lib/libSystem.B.dylib
  via a __TEXT,__stubs section + __DATA_CONST,__got slot and classic dyld bind
  opcodes (LC_DYLD_INFO). dyld resolves the GOT slot at load time.
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
MH_EXECUTE = 2

# dyld bind opcodes (classic LC_DYLD_INFO binding)
BIND_DONE = 0x00
BIND_SET_DYLIB_ORDINAL_IMM = 0x10
BIND_SET_SYMBOL_TRAILING_FLAGS_IMM = 0x40
BIND_SET_TYPE_IMM = 0x50
BIND_SET_SEGMENT_AND_OFFSET_ULEB = 0x70
BIND_DO_BIND = 0x90
BIND_TYPE_POINTER = 0x1

LIBSYSTEM_PATH = b"/usr/lib/libSystem.B.dylib\0"

EXTERN_ENTRYOFF = 744  # 32 (header) + 712 (sizeofcmds), fixed for extern layout
PAGEZERO_SIZE = 0x100000000
TEXT_BASE = 0x100000000
DATA_BASE = 0x100004000
LINKEDIT_BASE = 0x100008000
PAGE_SIZE = 0x4000


def build_macho_executable(code: bytes, entryoff: int) -> bytes:
    file = bytearray(0x8000)

    def patch(off: int, fmt: str, *vals) -> None:
        struct.pack_into(fmt, file, off, *vals)

    sizeofcmds = 72 + 152 + 72 + 48 + 32 + 24 + 24 + 24

    patch(0, "<I", MAGIC_64)
    patch(4, "<I", CPU_TYPE_ARM64)
    patch(8, "<I", 0)
    patch(12, "<I", MH_EXECUTE)
    patch(16, "<I", 8)
    patch(20, "<I", sizeofcmds)
    patch(24, "<I", 0)

    o = 32

    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72)
    file[o + 8 : o + 24] = b"__PAGEZERO".ljust(16, b"\0")
    patch(o + 24, "<Q", 0)
    patch(o + 32, "<Q", 0x100000000)
    o += 72

    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 152)
    file[o + 8 : o + 24] = b"__TEXT".ljust(16, b"\0")
    patch(o + 24, "<Q", 0x100000000)
    patch(o + 32, "<Q", 0x4000)
    patch(o + 40, "<Q", 0)
    patch(o + 48, "<Q", 0x4000)
    patch(o + 56, "<I", 5)
    patch(o + 60, "<I", 5)
    patch(o + 64, "<I", 1)
    patch(o + 68, "<I", 0)
    s = o + 72
    file[s : s + 16] = b"__text".ljust(16, b"\0")
    file[s + 16 : s + 32] = b"__TEXT".ljust(16, b"\0")
    patch(s + 32, "<Q", 0x100000000 + entryoff)
    patch(s + 40, "<Q", len(code))
    patch(s + 48, "<I", entryoff)
    patch(s + 52, "<I", 2)
    patch(s + 56, "<I", 0)
    patch(s + 60, "<I", 0)
    patch(s + 64, "<I", 0x80000400)
    patch(s + 68, "<I", 0)
    patch(s + 72, "<I", 0)
    o += 152

    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72)
    file[o + 8 : o + 24] = b"__LINKEDIT".ljust(16, b"\0")
    patch(o + 24, "<Q", 0x100004000)
    patch(o + 32, "<Q", 0x4000)
    patch(o + 40, "<Q", 0x4000)
    patch(o + 48, "<Q", 0x4000)
    patch(o + 56, "<I", 5)
    patch(o + 60, "<I", 5)
    o += 72

    patch(o + 0, "<I", DYLD_INFO_ONLY_CMD)
    patch(o + 4, "<I", 48)
    o += 48

    patch(o + 0, "<I", LOAD_DYLINKER_CMD)
    patch(o + 4, "<I", 32)
    patch(o + 8, "<I", 12)
    file[o + 12 : o + 26] = b"/usr/lib/dyld\0"
    o += 32

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
    return bytes(file)


def _bind_info(external_syms: list[str]) -> bytes:
    """Classic dyld bind opcodes pointing each __got slot at its symbol.

    A __got slot is a S_NON_LAZY_SYMBOL_POINTERS entry in __DATA_CONST (segment
    ordinal 2). The bind cursor starts at (segment base + offset); SET_SEGMENT_
    AND_OFFSET_ULEB places it at the slot, then DO_BIND writes the resolved
    pointer (8 bytes) and advances it by 8, naturally walking down the slots.
    """
    out = bytearray()
    for i, sym in enumerate(external_syms):
        out += bytes((BIND_SET_DYLIB_ORDINAL_IMM | 0x1,))
        out += bytes((BIND_SET_SYMBOL_TRAILING_FLAGS_IMM | 0x0,))
        out += sym.encode()
        out += b"\0"
        out += bytes((BIND_SET_TYPE_IMM | BIND_TYPE_POINTER,))
        out += bytes((BIND_SET_SEGMENT_AND_OFFSET_ULEB,))
        out += bytes((2,))          # segment ordinal: __DATA_CONST
        _uleb(out, i * 8)           # offset within __DATA_CONST
        out += bytes((BIND_DO_BIND,))
    out += bytes((BIND_DONE,))
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


def _stub_bytes(got_vm: int, stub_vm: int) -> bytes:
    from formal.arm64 import encode_adrp, encode_ldr_xt_xn_imm, encode_br_xn

    page_off = (got_vm & ~0xFFF) - (stub_vm & ~0xFFF)
    got_off = got_vm & 0xFFF
    return (
        encode_adrp(16, page_off)
        + encode_ldr_xt_xn_imm(16, 16, got_off)
        + encode_br_xn(16)
    )


def externer_layout(code_len: int, external_syms: list[str]) -> dict:
    """Stub/GOT layout for the extern executable.

    Returns the entry offset, the file offset of __text,__stubs, and the stub
    vmaddr for each symbol (sorted so both BL patching and binary emission
    agree on slot ordering)."""
    syms = sorted(external_syms)
    entryoff = EXTERN_ENTRYOFF
    stub_file = (entryoff + code_len + 3) & ~3
    stub_base_vm = TEXT_BASE + stub_file
    return {
        "entryoff": entryoff,
        "stub_file": stub_file,
        "stub_addrs": {sym: stub_base_vm + i * 12 for i, sym in enumerate(syms)},
    }


def build_macho_executable_extern(
    code: bytes, entryoff: int, external_syms: list[str]
) -> bytes:
    """Executable with __TEXT,__stubs + __DATA_CONST,__got + LC_LOAD_DYLIB
    libSystem + classic bind. `code` already contains BL instructions whose
    targets (stub addresses) end in immediate zero placeholders; the caller
    patches them to the real stub vmaddrs via resolve_extern before calling."""
    external_syms = sorted(external_syms)
    n = len(external_syms)
    stub_file = (entryoff + len(code) + 3) & ~3
    stub_base_vm = TEXT_BASE + stub_file
    got_base_vm = DATA_BASE
    bind = _bind_info(external_syms)
    bind_file = PAGE_SIZE * 2
    bind_len = len(bind)

    sizeofcmds = 72 + 232 + 152 + 72 + 48 + 32 + 24 + 56 + 24
    assert entryoff == 32 + sizeofcmds, entryoff
    total = bind_file + bind_len
    file = bytearray(total)

    def patch(off: int, fmt: str, *vals) -> None:
        struct.pack_into(fmt, file, off, *vals)

    patch(0, "<I", MAGIC_64)
    patch(4, "<I", CPU_TYPE_ARM64)
    patch(8, "<I", 0)
    patch(12, "<I", MH_EXECUTE)
    patch(16, "<I", 9)
    patch(20, "<I", sizeofcmds)
    patch(24, "<I", 0)

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
    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72 + 2 * 80)
    file[o + 8 : o + 24] = b"__TEXT".ljust(16, b"\0")
    patch(o + 24, "<Q", TEXT_BASE)
    patch(o + 32, "<Q", 0x4000)
    patch(o + 40, "<Q", 0)
    patch(o + 48, "<Q", 0x4000)
    patch(o + 56, "<I", 5)
    patch(o + 60, "<I", 5)
    patch(o + 64, "<I", 2)  # nsects: __text + __stubs
    patch(o + 68, "<I", 0)
    s = o + 72
    file[s : s + 16] = b"__text".ljust(16, b"\0")
    file[s + 16 : s + 32] = b"__TEXT".ljust(16, b"\0")
    patch(s + 32, "<Q", TEXT_BASE + entryoff)
    patch(s + 40, "<Q", len(code))
    patch(s + 48, "<I", entryoff)
    patch(s + 52, "<I", 2)
    patch(s + 56, "<I", 0)
    patch(s + 60, "<I", 0)
    patch(s + 64, "<I", 0x80000400)
    patch(s + 68, "<I", 0)
    patch(s + 72, "<I", 0)
    s += 80
    file[s : s + 16] = b"__stubs".ljust(16, b"\0")
    file[s + 16 : s + 32] = b"__TEXT".ljust(16, b"\0")
    patch(s + 32, "<Q", stub_base_vm)
    patch(s + 40, "<Q", 12 * n)
    patch(s + 48, "<I", stub_file)
    patch(s + 52, "<I", 2)
    patch(s + 56, "<I", 0)
    patch(s + 60, "<I", 0)
    patch(s + 64, "<I", 0x80000408)
    patch(s + 68, "<I", 12)
    patch(s + 72, "<I", 0)
    o += 72 + 2 * 80

    # __DATA_CONST (vmaddr DATA_BASE, fileoff 0x4000) with __got
    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72 + 80)
    file[o + 8 : o + 24] = b"__DATA_CONST".ljust(16, b"\0")
    patch(o + 24, "<Q", DATA_BASE)
    patch(o + 32, "<Q", 0x4000)
    patch(o + 40, "<Q", PAGE_SIZE)
    patch(o + 48, "<Q", PAGE_SIZE)
    patch(o + 56, "<I", 0x3)  # rw- : dyld writes the GOT slot at load time
    patch(o + 60, "<I", 0x3)
    patch(o + 64, "<I", 1)  # nsects: __got
    patch(o + 68, "<I", 0)
    s = o + 72
    file[s : s + 16] = b"__got".ljust(16, b"\0")
    file[s + 16 : s + 32] = b"__DATA_CONST".ljust(16, b"\0")
    patch(s + 32, "<Q", got_base_vm)
    patch(s + 40, "<Q", 8 * n)
    patch(s + 48, "<I", PAGE_SIZE)
    patch(s + 52, "<I", 3)
    patch(s + 56, "<I", 0)
    patch(s + 60, "<I", 0)
    patch(s + 64, "<I", 0x6)
    patch(s + 68, "<I", 0)
    patch(s + 72, "<I", 0)
    o += 72 + 80

    # __LINKEDIT
    patch(o + 0, "<I", SEGMENT_64_CMD)
    patch(o + 4, "<I", 72)
    file[o + 8 : o + 24] = b"__LINKEDIT".ljust(16, b"\0")
    patch(o + 24, "<Q", LINKEDIT_BASE)
    patch(o + 32, "<Q", 0x4000)
    patch(o + 40, "<Q", PAGE_SIZE * 2)
    patch(o + 48, "<Q", bind_len)
    patch(o + 56, "<I", 5)
    patch(o + 60, "<I", 5)
    o += 72

    # LC_DYLD_INFO_ONLY -> bind_off/bind_size = bind data in __LINKEDIT.
    # NOTE: dyld_info_command fields are uint32_t, not uint64_t.
    patch(o + 0, "<I", DYLD_INFO_ONLY_CMD)
    patch(o + 4, "<I", 48)
    patch(o + 8, "<I", 0)          # rebase_off
    patch(o + 12, "<I", 0)         # rebase_size
    patch(o + 16, "<I", bind_file) # bind_off
    patch(o + 20, "<I", bind_len)  # bind_size
    patch(o + 24, "<I", 0)         # weak_bind_off/size/...
    patch(o + 28, "<I", 0)
    patch(o + 32, "<I", 0)
    patch(o + 36, "<I", 0)
    patch(o + 40, "<I", 0)
    patch(o + 44, "<I", 0)
    o += 48

    # LC_LOAD_DYLINKER
    patch(o + 0, "<I", LOAD_DYLINKER_CMD)
    patch(o + 4, "<I", 32)
    patch(o + 8, "<I", 12)
    file[o + 12 : o + 26] = b"/usr/lib/dyld\0"
    o += 32

    # LC_UUID
    patch(o + 0, "<I", UUID_CMD)
    patch(o + 4, "<I", 24)
    o += 24

    # LC_LOAD_DYLIB (libSystem)
    patch(o + 0, "<I", LOAD_DYLIB_CMD)
    patch(o + 4, "<I", 56)
    patch(o + 8, "<I", 24)
    patch(o + 12, "<I", 2)
    patch(o + 16, "<I", 0x10000)
    patch(o + 20, "<I", 0x10000)
    file[o + 24 : o + 24 + 26] = LIBSYSTEM_PATH
    o += 56

    # LC_MAIN
    patch(o + 0, "<I", MAIN_CMD)
    patch(o + 4, "<I", 24)
    patch(o + 8, "<Q", entryoff)
    patch(o + 16, "<Q", 0)
    o += 24

    assert o == entryoff, (o, entryoff)
    file[entryoff : entryoff + len(code)] = code
    for i in range(n):
        got_vm = got_base_vm + i * 8
        stub_vm = stub_base_vm + i * 12
        f = stub_file + i * 12
        file[f : f + 12] = _stub_bytes(got_vm, stub_vm)
    file[bind_file : bind_file + bind_len] = bind
    return bytes(file)


if __name__ == "__main__":
    main_code = bytes([0x00, 0x00, 0x80, 0x52, 0xC0, 0x03, 0x5F, 0xD6])
    with open("/tmp/a.out", "wb") as f:
        f.write(build_macho_executable(main_code, 480))
    print("wrote /tmp/a.out")
