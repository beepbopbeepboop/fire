#!/usr/bin/env python3
"""Mach-O64 binary builder for macOS (arm64 and x86-64).

Mach-O is the native executable format for macOS. It's simpler than ELF:
- 32-byte header
- LOAD_COMMAND entries for segments
- __TEXT segment for code (executable)
- __DATA segment for data (read-only for our purposes)
- LC_MAIN for entry point

Unlike ELF, Mach-O doesn't require a separate loader for arm64 on macOS.
The OS kernel loads and executes Mach-O binaries directly. The x86-64
variant is the same image with a different cpu type and stub geometry (see
formal/macho_linker.py's `arch` parameter); on Apple Silicon it runs under
Rosetta 2, transparently, the same way a clang `-arch x86_64` binary does.
"""

import struct


# Mach-O constants
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
MH_MAGIC = 0xFEEDFACE
MH_CIGAM = 0xCEFAEDFE

MH_EXECUTE = 2
MH_DYLIB = 6

CPU_TYPE_ARM64 = 0x0100000C
CPU_SUBTYPE_ARM64_ALL = 0x00000003

LC_SEGMENT_64 = 0x19
LC_MAIN = 0x80000028
LC_LOAD_DYLIB = 0x0C
LC_SYMTAB = 0x02
LC_UUID = 0x1B
LC_SOURCE_VERSION = 0x2A
LC_UNIXTHREAD = 0x05

ARM_THREAD_STATE64 = 4
ARM_THREAD_STATE64_COUNT = 32

MH_TWOLEVEL = 0x00800000
MH_NOUNDEFS = 0x00000001
MH_BIND_AT_LOAD = 0x00000002
MH_DEAD_STRIPPABLE_DYLIB = 0x00002000


def _build_segment_64(
    segname: str,
    vmaddr: int,
    vmsize: int,
    fileoff: int,
    filesize: int,
    maxprot: int,
    initprot: int,
    nsects: int = 0,
    flags: int = 0,
) -> bytes:
    """Build a LC_SEGMENT_64 load command.
    
    Layout:
    - cmd (4 bytes)
    - cmdsize (4 bytes)
    - segname (16 bytes, null-padded)
    - vmaddr (8 bytes)
    - vmsize (8 bytes)
    - fileoff (8 bytes)
    - filesize (8 bytes)
    - maxprot (4 bytes)
    - initprot (4 bytes)
    - nsects (4 bytes)
    - flags (4 bytes)
    """
    # cmdsize = cmd + cmdsize + segname + vmaddr + vmsize + fileoff + filesize + maxprot + initprot + nsects + flags
    # Plus nsects * 80 bytes for section_64 records (each is exactly 80 bytes).
    if nsects:
        raise ValueError(
            "section_64 records are not implemented here; "
            "use formal.macho_linker (emits full section headers)")
    section_data_size = nsects * 80
    cmdsize = 4 + 4 + 16 + 8 + 8 + 8 + 8 + 4 + 4 + 4 + 4 + section_data_size
    segname_bytes = segname.encode('ascii')[:16].ljust(16, b'\x00')

    buf = bytearray()
    buf.extend(struct.pack('<I', LC_SEGMENT_64))  # cmd
    buf.extend(struct.pack('<I', cmdsize))  # cmdsize
    buf.extend(segname_bytes)  # segname
    buf.extend(struct.pack('<Q', vmaddr))  # vmaddr
    buf.extend(struct.pack('<Q', vmsize))  # vmsize
    buf.extend(struct.pack('<Q', fileoff))  # fileoff
    buf.extend(struct.pack('<Q', filesize))  # filesize
    buf.extend(struct.pack('<I', maxprot))  # maxprot
    buf.extend(struct.pack('<I', initprot))  # initprot
    buf.extend(struct.pack('<I', nsects))  # nsects
    buf.extend(struct.pack('<I', flags))  # flags
    return bytes(buf)


def _build_main_entry(entryoff: int, stacksize: int = 0) -> bytes:
    """Build a LC_MAIN load command.
    
    Layout:
    - cmd (4 bytes)
    - cmdsize (4 bytes)
    - entryoff (8 bytes)
    - stacksize (8 bytes)
    """
    cmdsize = 4 + 4 + 8 + 8  # 24 bytes
    buf = bytearray()
    buf.extend(struct.pack('<I', LC_MAIN))  # cmd
    buf.extend(struct.pack('<I', cmdsize))  # cmdsize
    buf.extend(struct.pack('<Q', entryoff))  # entryoff
    buf.extend(struct.pack('<Q', stacksize))  # stacksize
    return bytes(buf)


def _build_load_dylib(path: str, timestamp: int = 0, current_version: int = 0, compatibility_version: int = 0) -> bytes:
    """Build a LC_LOAD_DYLIB load command.
    
    Layout:
    - cmd (4 bytes)
    - cmdsize (4 bytes)
    - name (offset, 4 bytes)
    - timestamp (4 bytes)
    - current_version (4 bytes)
    - compatibility_version (4 bytes)
    """
    name_offset = 4 + 4 + 4 + 4 + 4 + 4  # cmd + cmdsize + name + timestamp + current_version + compat_version
    cmdsize = name_offset + len(path.encode('ascii')) + 1  # +1 for null terminator
    cmdsize = (cmdsize + 7) & ~7  # align to 8 bytes
    
    buf = bytearray()
    buf.extend(struct.pack('<I', LC_LOAD_DYLIB))  # cmd
    buf.extend(struct.pack('<I', cmdsize))  # cmdsize
    buf.extend(struct.pack('<I', name_offset))  # name (offset)
    buf.extend(struct.pack('<I', timestamp))  # timestamp
    buf.extend(struct.pack('<I', current_version))  # current_version
    buf.extend(struct.pack('<I', compatibility_version))  # compatibility_version
    buf.extend(path.encode('ascii'))
    buf.extend(b'\x00')  # null terminator
    # Pad to alignment
    while len(buf) % 8 != 0:
        buf.extend(b'\x00')
    return bytes(buf)


def build_macho(
    code: bytes,
    external_syms: list[str] | None = None,
    arch: str = "arm64",
    dylibs: list | None = None,
) -> bytes:
    """Build a Mach-O-64 executable for `arch` from scratch.

    This builds the Mach-O binary from scratch without templates. The entry
    offset comes from formal.macho_linker's layout constants (see
    executable_entry_offset), not from a literal here, so `code` must have been
    compiled for the matching base address.
    """
    if external_syms is None:
        external_syms = []

    if external_syms:
        # External symbols: build __stubs + __got + LC_LOAD_DYLIB + bind.
        # The call instructions in `code` must already point at the real stub
        # vmaddrs (see compute_macho_got_addrs + asm.resolve_extern).
        from formal.macho_linker import build_macho_executable_extern
        return build_macho_executable_extern(code, external_syms, arch,
                                             dylibs=dylibs)

    from formal.macho_linker import build_macho_executable

    # The entry offset is the linker's to decide (it is derived from the load
    # command list plus the slack post-hoc codesigning needs) — the caller only
    # has to have emitted `code` for that same offset, which it learns from
    # NOEXTERN_ENTRYOFF / EXTERN_ENTRYOFF before compiling.
    return build_macho_executable(code, arch)


def compute_macho_got_addrs(code_size: int, external_syms: list[str],
                            vaddr: int = 0x100000000,
                            arch: str = "arm64",
                            entryoff: int = None) -> dict[str, int]:
    """Compute the absolute vmaddr of each symbol's __TEXT,__stubs stub.

    The extern executable links libSystem; each call site branches to a stub
    that jumps through a __DATA_CONST,__got slot. Returns a
    {symbol: stub_vmaddr} map for the assembler's resolve_extern to backpatch.
    """
    if not external_syms:
        return {}
    from formal.macho_linker import externer_layout
    return externer_layout(code_size, external_syms, arch,
                           entryoff)["stub_addrs"]

