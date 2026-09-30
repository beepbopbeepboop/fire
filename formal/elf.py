#!/usr/bin/env python3
"""ELF64 executable builder for Linux (x86-64).

Ported from /Users/mrs/net/chatgpt/claude/formal/compiler/elf.py, the toy
formal compiler's x86-64 output format, with the two things that were
hard-coded for macOS turned into parameters:

- the shared library the extern symbols bind to (`libSystem.B.dylib` there,
  `libc.so.6` here), and
- the base address (0x400000, the conventional ET_EXEC text base on Linux).

The extern mechanism is the ELF counterpart of the Mach-O stubs: the image
carries a `.got` of 8-byte slots and one R_X86_64_GLOB_DAT relocation per
symbol, and the codegen's call sites are `call [rip+disp32]` through those
slots (`Assembler.emit_extern_call_got` / `resolve_extern`). The dynamic
loader fills each slot at process startup, so no trampoline code is needed —
which is why the ELF image has no equivalent of __TEXT,__stubs.

Layout, all after a single PT_LOAD that starts at the code:
    .text | .dynstr | .dynsym | .dynamic | .got | .rela.dyn
with a second PT_DYNAMIC program header when there are externs to bind.
"""

import struct
from typing import Optional


ELF_MAGIC = b"\x7fELF"
ELFCLASS64 = 2
ELFDATA2LSB = 1
ET_EXEC = 2
EM_X86_64 = 0x3E
PT_LOAD = 1
PT_DYNAMIC = 2
PF_X = 1
PF_W = 2
PF_R = 4
DT_NULL = 0
DT_NEEDED = 1
DT_STRTAB = 5
DT_SYMTAB = 6
DT_RELA = 7
DT_RELASZ = 8
DT_STRSZ = 10
STB_GLOBAL = 1
R_X86_64_GLOB_DAT = 6

# Default virtual address of .text. Fixed rather than derived from the image
# so `compute_got_addrs` (called before the image exists, to patch call sites)
# and `build_elf` (called with the finished code) agree by construction.
DEFAULT_BASE = 0x400000

# The C library the extern symbols resolve against. macOS has everything in
# libSystem; on Linux the symbols formal needs (exit, printf) live in libc.
DEFAULT_LIBC = "libc.so.6"

# sizeofcmds equivalent: one PT_LOAD with no externs, two with.
_PHDR_SIZE = 56
_EHDR_SIZE = 64
_PHNUM_NOEXTERN = 1
_PHNUM_EXTERN = 2
# .dynamic holds 7 entries: DT_NEEDED, DT_SYMTAB, DT_STRTAB, DT_STRSZ,
# DT_RELA, DT_RELASZ, DT_NULL.
_DYNAMIC_ENTRIES = 7
_DYNAMIC_SIZE = _DYNAMIC_ENTRIES * 16
_SYMSZ = 24
_RELASZ = 24
_GOTSLOT = 8


def _ident() -> bytes:
    """The 16-byte e_ident: magic, class, endianness, version, OS ABI, ABI
    version, pad — then the 5 bytes of padding EI_NIDENT leaves."""
    return struct.pack(
        "<4sBBBBBBB5x",
        ELF_MAGIC,
        ELFCLASS64,
        ELFDATA2LSB,
        1,          # EI_VERSION
        0,          # EI_OSABI: ELFOSABI_NONE / System V
        0,          # EI_ABIVERSION
        0,          # EI_PAD
        0,          # padding
    )


def _sym_name_offsets(names: list[str]) -> tuple[bytes, dict[str, int]]:
    buf = bytearray()
    offsets: dict[str, int] = {}
    for n in names:
        offsets[n] = len(buf)
        buf.extend(n.encode())
        buf.append(0)
    return bytes(buf), offsets


def _build_dynsym(sym_names: list[str], str_offsets: dict[str, int]) -> bytes:
    """One STB_GLOBAL, SHN_UNDEF symbol per name, after the empty STN_UNDEF."""
    buf = bytearray()
    buf.extend(b"\x00" * _SYMSZ)
    for name in sym_names:
        buf.extend(struct.pack(
            "<IBBHQQ",
            str_offsets[name],       # st_name
            STB_GLOBAL << 4,         # st_info
            0,                       # st_other
            0,                       # st_shndx: undefined, bound at load
            0,                       # st_value
            0,                       # st_size
        ))
    return bytes(buf)


def _build_dynamic(str_offsets: dict[str, int], lib_name: str,
                   dynsym_vaddr: int, dynstr_vaddr: int, dynstr_size: int,
                   rela_vaddr: int, rela_size: int) -> bytes:
    entries = [
        struct.pack("<QQ", DT_NEEDED, str_offsets[lib_name]),
        struct.pack("<QQ", DT_SYMTAB, dynsym_vaddr),
        struct.pack("<QQ", DT_STRTAB, dynstr_vaddr),
        struct.pack("<QQ", DT_STRSZ, dynstr_size),
        struct.pack("<QQ", DT_RELA, rela_vaddr),
        struct.pack("<QQ", DT_RELASZ, rela_size),
        struct.pack("<QQ", DT_NULL, 0),
    ]
    return b"".join(entries)


def _build_rela_dyn(got_slots: list[tuple[str, int]],
                    sym_index_map: dict[str, int]) -> bytes:
    """One R_X86_64_GLOB_DAT per GOT slot: fill the slot with the symbol."""
    buf = bytearray()
    for sym_name, got_vaddr in got_slots:
        r_info = (sym_index_map.get(sym_name, 0) << 32) | R_X86_64_GLOB_DAT
        buf.extend(struct.pack("<QQq", got_vaddr, r_info, 0))
    return bytes(buf)


def _layout(code_size: int, external_syms: list[str], lib_name: str) -> dict:
    """Every size and virtual address the image needs, in one place.

    `compute_got_addrs` runs BEFORE the image exists (it back-patches the call
    sites) while `build_elf` runs after, so the two must not each compute the
    .got address: they share this."""
    phnum = _PHNUM_EXTERN if external_syms else _PHNUM_NOEXTERN
    text_file_offset = _EHDR_SIZE + _PHDR_SIZE * phnum

    names = list(external_syms) + ([lib_name] if external_syms else [])
    dynstr_size = sum(len(n) + 1 for n in names)
    dynsym_size = (1 + len(external_syms)) * _SYMSZ
    dynamic_size = _DYNAMIC_SIZE if external_syms else 0
    got_size = _GOTSLOT * len(external_syms)
    rela_size = _RELASZ * len(external_syms)

    off = code_size
    dynstr_off = off
    off += dynstr_size
    dynsym_off = off
    off += dynsym_size
    dynamic_off = off
    off += dynamic_size
    got_off = off
    off += got_size
    rela_off = off
    off += rela_size
    return {
        "phnum": phnum,
        "text_file_offset": text_file_offset,
        "dynstr_off": dynstr_off, "dynstr_size": dynstr_size,
        "dynsym_off": dynsym_off, "dynsym_size": dynsym_size,
        "dynamic_off": dynamic_off, "dynamic_size": dynamic_size,
        "got_off": got_off, "got_size": got_size,
        "rela_off": rela_off, "rela_size": rela_size,
        "body_size": off,
    }


def compute_got_addrs(code_size: int, external_syms: list[str],
                      vaddr: int = DEFAULT_BASE,
                      lib_name: str = DEFAULT_LIBC) -> dict[str, int]:
    """Absolute virtual address of each symbol's .got slot.

    Must agree with `build_elf`'s layout — both go through `_layout`."""
    if not external_syms:
        return {}
    lay = _layout(code_size, external_syms, lib_name)
    base = vaddr + lay["got_off"]
    return {sym: base + i * _GOTSLOT
            for i, sym in enumerate(external_syms)}


def build_elf(code: bytes, entry: int = DEFAULT_BASE,
              vaddr: int = DEFAULT_BASE,
              external_syms: Optional[list[str]] = None,
              lib_name: str = DEFAULT_LIBC) -> bytes:
    """Build an x86-64 ET_EXEC image around `code`.

    `entry` is the process entry (the startup stub's address), which is `vaddr`
    here because the code is the first thing in the image. PT_LOAD maps the
    code at `vaddr` by starting its file offset at the end of the headers, so
    every address the codegen computed off `vaddr` is the address the loader
    gives it."""
    if external_syms is None:
        external_syms = []

    lay = _layout(len(code), external_syms, lib_name)
    phnum = lay["phnum"]
    text_file_offset = lay["text_file_offset"]
    code_align = 0x1000

    dynstr_names = list(external_syms)
    if external_syms:
        dynstr_names.append(lib_name)
    dynstr_data, str_offsets = _sym_name_offsets(dynstr_names)
    dynsym_data = _build_dynsym(external_syms, str_offsets)
    sym_index = {s: i + 1 for i, s in enumerate(external_syms)}
    got_slots = [(sym, vaddr + lay["got_off"] + i * _GOTSLOT)
                 for i, sym in enumerate(external_syms)]
    rela_data = _build_rela_dyn(got_slots, sym_index)
    dynamic_data = (_build_dynamic(
        str_offsets, lib_name,
        vaddr + lay["dynsym_off"], vaddr + lay["dynstr_off"], lay["dynstr_size"],
        vaddr + lay["rela_off"], lay["rela_size"]) if external_syms else b"")

    total_size = text_file_offset + lay["body_size"]
    total_size_padded = (total_size + code_align - 1) // code_align * code_align

    buf = bytearray()

    # ELF header
    buf.extend(_ident())
    buf.extend(struct.pack("<HHIQQQI",
        ET_EXEC,          # e_type
        EM_X86_64,        # e_machine
        1,                # e_version
        entry,            # e_entry
        _EHDR_SIZE,       # e_phoff
        0,                # e_shoff
        0,                # e_flags
    ))
    buf.extend(struct.pack("<HHHHHH",
        _EHDR_SIZE,       # e_ehsize
        _PHDR_SIZE,       # e_phentsize
        phnum,            # e_phnum
        0, 0, 0,          # e_shentsize, e_shnum, e_shstrndx
    ))

    # PT_LOAD covering code + the dynamic sections. p_offset is the end of the
    # headers so the code lands exactly at vaddr.
    p_flags = PF_R | PF_X
    if external_syms:
        p_flags |= PF_W        # the loader writes the .got slots
    segment_file_size = lay["body_size"]
    buf.extend(struct.pack("<IIQQQQQQ",
        PT_LOAD, p_flags, text_file_offset, vaddr, vaddr,
        segment_file_size, segment_file_size, code_align,
    ))

    if external_syms:
        buf.extend(struct.pack("<IIQQQQQQ",
            PT_DYNAMIC, PF_R | PF_W,
            text_file_offset + lay["dynamic_off"],
            vaddr + lay["dynamic_off"], vaddr + lay["dynamic_off"],
            lay["dynamic_size"], lay["dynamic_size"], 8,
        ))

    buf.extend(code)                      # .text
    buf.extend(dynstr_data)               # .dynstr
    buf.extend(dynsym_data)               # .dynsym
    buf.extend(dynamic_data)              # .dynamic
    buf.extend(b"\x00" * lay["got_size"])  # .got, filled by the loader
    buf.extend(rela_data)                 # .rela.dyn

    buf.extend(b"\x00" * (total_size_padded - total_size))
    return bytes(buf)
