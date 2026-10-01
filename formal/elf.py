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

# Where the module-global `.globals` section is MAPPED, for the same reason
# `macho_linker.GLOBALS_VM` is fixed rather than derived: __TEXT's size is a
# function of the code, and every access to a slot needs this address BEFORE the
# code is emitted, so deriving one from the other makes each depend on the other.
# A fixed base 4 MB past the code leaves every RIP-relative displacement (whose
# range is ±2 GB) comfortably inside, and it is a constant both the codegen and
# this builder read — so the address a backend computes and the one this
# segment declares are the same number rather than two that have to agree.
GLOBALS_VM = DEFAULT_BASE + 0x400000

# The `__DATA`-equivalent program header an image with module-global slots
# carries. `PT_LOAD` is 56 bytes and its flags are the PF_W bit, which the
# code segment does not have: a slot is WRITTEN by a `global NAME` store, and a
# read-only mapping faults on the first one.
GLOBALS_PF = PF_R | PF_W

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
    """The .dynamic array: DT_NEEDED, DT_SYMTAB, DT_STRTAB, DT_STRSZ,
    DT_RELA, DT_RELASZ, DT_NULL."""
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


def _layout(code_size: int, external_syms: list[str], lib_name: str,
            globals_size: int = 0) -> dict:
    """Every size and virtual address the image needs, in one place.

    `compute_got_addrs` runs BEFORE the image exists (it back-patches the call
    sites) while `build_elf` runs after, so the two must not each compute the
    .got address: they share this."""
    phnum = _PHNUM_EXTERN if external_syms else _PHNUM_NOEXTERN
    # A `.globals` section adds a second PT_LOAD: the code segment is PF_X and a
    # slot is WRITTEN, and a program header's flags are per-segment, so the two
    # cannot be one mapping.
    if globals_size:
        phnum += 1
    text_file_offset = _EHDR_SIZE + _PHDR_SIZE * phnum

    names = list(external_syms) + ([lib_name] if external_syms else [])
    dynstr_size = sum(len(n) + 1 for n in names)
    dynsym_size = (1 + len(external_syms)) * _SYMSZ
    dynamic_size = _DYNAMIC_SIZE if external_syms else 0
    got_size = _GOTSLOT * len(external_syms)
    # NO relocation entries for the globals: their address-valued slots are
    # filled by CODE in the startup stub (`x86_64_codegen._emit_global_init`),
    # not by the loader. That is the same mechanism the Mach-O side uses and
    # for the same reason — it needs no cooperation from the dynamic linker, and
    # it is the one already proven against a real loader on this target.
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
    # The .globals CONTENT sits at the end of the image but is MAPPED at
    # GLOBALS_VM, so `globals_off` (a file offset) and `GLOBALS_VM` (an address)
    # are deliberately different numbers — see GLOBALS_VM's note.
    #
    # The offset follows the SAME convention as the code segment's, which is
    # `text_file_offset` — "the next byte after the headers" — rather than
    # page-aligning it. Page-aligning only THIS segment would make the two
    # disagree about how a PT_LOAD's offset relates to its address, which is a
    # stranger image than either convention alone. Making both congruent with
    # p_align is a change to the existing `_layout` arithmetic and to every ELF
    # image the tree already builds; it is not this change's, and it is recorded
    # as an observation in `bugs/FORMAL_elf_globals_segment.md` rather than
    # half-applied here.
    globals_off = off
    off += globals_size
    rela_off = off
    off += rela_size
    return {
        "phnum": phnum,
        "text_file_offset": text_file_offset,
        "dynstr_off": dynstr_off, "dynstr_size": dynstr_size,
        "dynsym_off": dynsym_off, "dynsym_size": dynsym_size,
        "dynamic_off": dynamic_off, "dynamic_size": dynamic_size,
        "got_off": got_off, "got_size": got_size,
        "globals_off": globals_off, "globals_size": globals_size,
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
              lib_name: str = DEFAULT_LIBC,
              globals_image=None) -> bytes:
    """Build an x86-64 ET_EXEC image around `code`.

    `entry` is the process entry (the startup stub's address), which is `vaddr`
    here because the code is the first thing in the image. PT_LOAD maps the
    code at `vaddr` by starting its file offset at the end of the headers, so
    every address the codegen computed off `vaddr` is the address the loader
    gives it.

    `globals_image` is a `formal.model.GlobalDataImage` or None; non-None adds
    the module-global slot table as a second, WRITABLE PT_LOAD mapped at
    `GLOBALS_VM`. Its address-valued words are filled by the startup stub's
    initializer rather than by a relocation — see
    `x86_64_codegen._emit_global_init`."""
    if external_syms is None:
        external_syms = []
    gblob = b"" if globals_image is None else bytes(globals_image.blob)

    lay = _layout(len(code), external_syms, lib_name, len(gblob))
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
    # headers so the code lands exactly at vaddr. Its p_filesz stops at the
    # globals so the second PT_LOAD owns those bytes — a byte claimed by two
    # program headers is a mapping the loader resolves by refusing to load.
    p_flags = PF_R | PF_X
    if external_syms:
        p_flags |= PF_W        # the loader writes the .got slots
    code_and_dyn_size = lay["globals_off"]
    buf.extend(struct.pack("<IIQQQQQQ",
        PT_LOAD, p_flags, text_file_offset, vaddr, vaddr,
        code_and_dyn_size, code_and_dyn_size, code_align,
    ))

    if gblob:
        # The slot table's own mapping: writable, at the FIXED address the
        # codegen computed every access against (GLOBALS_VM), covering a file
        # range at the end of the image. `p_filesz == p_memsz` because the
        # blob is fully present in the file — this is initialized data, not
        # .bss.
        buf.extend(struct.pack("<IIQQQQQQ",
            PT_LOAD, GLOBALS_PF,
            text_file_offset + lay["globals_off"], GLOBALS_VM, GLOBALS_VM,
            lay["globals_size"], lay["globals_size"], code_align,
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
    buf.extend(gblob)                     # .globals, the module-global slots
    buf.extend(rela_data)                 # .rela.dyn

    buf.extend(b"\x00" * (total_size_padded - total_size))
    return bytes(buf)
