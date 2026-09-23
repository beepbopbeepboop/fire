#!/usr/bin/env python3
"""Mach-O64 binary builder for macOS ARM64.

Mach-O is the native executable format for macOS. It's simpler than ELF:
- 32-byte header
- LOAD_COMMAND entries for segments
- __TEXT segment for code (executable)
- __DATA segment for data (read-only for our purposes)
- LC_MAIN for entry point

Unlike ELF, Mach-O doesn't require a separate loader for arm64 on macOS.
The OS kernel loads and executes Mach-O binaries directly.
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
    # Plus nsects * 68 bytes for section data
    section_data_size = nsects * 68
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
    # No section data when nsects=0
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
    entry: int = 0x100000000,
    external_syms: list[str] | None = None,
    vaddr: int = 0x100000000,
) -> bytes:
    """Build a Mach-O64 executable for ARM64 from scratch.
    
    This builds the Mach-O binary from scratch without templates.
    """
    if external_syms is None:
        external_syms = []
    
    if external_syms:
        # External symbols: build __stubs + __got + LC_LOAD_DYLIB + bind.
        # BL instructions in `code` must already point at the real stub
        # vmaddrs (see compute_macho_got_addrs + asm.resolve_extern).
        from formal.macho_linker import build_macho_executable_extern, externer_layout
        layout = externer_layout(len(code), external_syms)
        return build_macho_executable_extern(code, layout["entryoff"], external_syms)

    from formal.macho_linker import build_macho_executable

    # Entry point sits after the header + load commands. sizeofcmds for this
    # layout is 448 (72+152+72+48+32+24+24+24), so code starts at 32+448=480.
    # (The upstream formal tree passed 456 here, which overlaps LC_MAIN —
    # its no-extern Mach-O path asserts/fails; fixed for this port.)
    return build_macho_executable(code, entryoff=480)


def compute_macho_got_addrs(code_size: int, external_syms: list[str], vaddr: int = 0x100000000) -> dict[str, int]:
    """Compute the absolute vmaddr of each symbol's __TEXT,__stubs stub.

    The extern executable links libSystem; each call site is a BL to a 12-byte
    stub that does ADRP/LDR/BR through a __DATA_CONST,__got slot. Returns a
    {symbol: stub_vmaddr} map for the assembler's resolve_extern to backpatch.
    """
    if not external_syms:
        return {}
    from formal.macho_linker import externer_layout
    return externer_layout(code_size, external_syms)["stub_addrs"]
