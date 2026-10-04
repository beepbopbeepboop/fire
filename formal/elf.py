#!/usr/bin/env python3
"""ELF64 builders for Linux (x86-64): an executable and a shared object.

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
which is why the ELF image has no equivalent of __TEXT,__stubs. It is also why
a MODULE's exported symbol needs no `.plt` either: `call [rip+disp32]` through
a `GLOB_DAT` slot resolves a FUNCTION symbol exactly as it resolves `printf`,
so the per-symbol work an ELF dylib shares with this executable is the whole of
the extern machinery and not a second analysis of it.

Layout, all after a single PT_LOAD that starts at the code:

    ET_EXEC   .text | .dynstr | .dynsym | .dynamic | .got | [.globals] | .rela.dyn
    ET_DYN    .text | .dynstr | .dynsym | .hash | .dynamic | .got |
              [.globals] | .rela.dyn

with a second PT_DYNAMIC program header when there is anything dynamic at all.
The shared object adds `.hash` (a 2-bucket `DT_HASH` chain), the exported
`STB_GLOBAL`/`STT_FUNC` entries its `.dynsym` needs to be found by name, and a
`DT_SONAME` carrying its own install name — the three things an `ET_EXEC` does
not have, and the three this file's `build_elf_dylib` writes.
"""

import struct
from typing import Optional


ELF_MAGIC = b"\x7fELF"
ELFCLASS64 = 2
ELFDATA2LSB = 1
ET_EXEC = 2
ET_DYN = 3
EM_X86_64 = 0x3E
PT_LOAD = 1
PT_DYNAMIC = 2
PF_X = 1
PF_W = 2
PF_R = 4
DT_NULL = 0
DT_NEEDED = 1
DT_HASH = 4
DT_STRTAB = 5
DT_SYMTAB = 6
DT_RELA = 7
DT_RELASZ = 8
DT_STRSZ = 10
DT_SONAME = 14
DT_INIT_ARRAY = 25
DT_INIT_ARRAYSZ = 27
STB_GLOBAL = 1
STB_WEAK = 2
STT_NOTYPE = 0
STT_FUNC = 2
STT_OBJECT = 1
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
# The `.dynamic` array's SIZE is not written down here: `_dynamic_tags` is the
# list of tags, `_layout` sizes the array from that list and `_dynamic_for`
# fills the values into the same list. A constant next to a list is an array one
# entry short the first time the list grows, and the loader reads past the end
# of it — which is what a shared object's own DT_SONAME and DT_HASH were, two
# entries that no count of "7 + one per dependency" mentioned.
_SYMSZ = 24
_RELASZ = 24
_GOTSLOT = 8
# A DT_HASH table is `nbucket` + `nchain` words followed by `nbucket` bucket
# heads and `nchain` chain links — the classic SysV hash the dynamic loader
# still accepts. Two buckets is what `ld -shared` emits for a library this
# size, and the loader does not care: it walks the chain from the slot the hash
# picks and stops at a zero, so the only requirement is that every symbol index
# appears in exactly one chain. (`DT_GNU_HASH` would be smaller and is what a
# modern link prefers, but it is a different table to get right and this
# emitter has one consumer — the loader — not a performance question.)
_HASH_WORD = 4
_HASH_BUCKETS = 2
_STN_UNDEF = 0
# An EXPORTED symbol's `st_shndx`. This emitter writes no section headers
# (`e_shoff` is 0, as it is for the executable here), so a defined symbol cannot
# point at a section that does not exist. `SHN_ABS` is the one index the format
# defines as meaningful with no section table behind it — and it is also what
# `nm` reports as `A` rather than `T`, so a reader can see the difference
# between "defined here" and "defined at an address" from the file alone.
_SHNDX_ABS = 0xFFF1
# One function pointer in `.init_array`. The array is a list of them and nothing
# else, so its size is a count times this — and a constant rather than a
# literal `8` at each site, because `_layout` sizes the array from it and
# `_dynamic_for` reports it as `DT_INIT_ARRAYSZ` and those two have to be the
# same number for a loader to call the right number of initializers.
_PTRSZ = 8


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


def _build_dynsym(entries: list[tuple], str_offsets: dict[str, int]) -> bytes:
    """The `.dynsym` table: the empty STN_UNDEF, then one entry per name.

    `entries` is `[(name, value, kind, shndx), …]` — the undefined symbols first
    (`shndx` 0, the loader binds them) and then a shared object's EXPORTS
    (`shndx` a real section index, `value` the address the name resolves to).
    One function for both because they are the same table: a Mach-O image needs
    only the first kind and a shared object needs both, and a second writer for
    the export half is a second place for the index arithmetic to go wrong —
    `r_info` above already packs a symbol INDEX, so an export table whose
    indices disagree with `.dynsym` is an image whose relocations point at the
    wrong name.
    """
    buf = bytearray()
    buf.extend(b"\x00" * _SYMSZ)
    for name, value, kind, shndx in entries:
        buf.extend(struct.pack(
            "<IBBHQQ",
            str_offsets[name],       # st_name
            (STB_GLOBAL << 4) | kind,  # st_info: bind, then type
            0,                       # st_other
            shndx,                   # 0 = undefined, bound at load
            value,                   # st_value
            0,                       # st_size
        ))
    return bytes(buf)


def _build_dynamic(entries: list[tuple[int, int]]) -> bytes:
    """The `.dynamic` array from `(tag, value)` pairs, DT_NULL-terminated.

    The list is the whole of it and the terminator is appended here, so a
    caller cannot forget it and a caller cannot write one that is too short: the
    loader walks this array until it finds `DT_NULL` and reads whatever follows,
    so an array one entry short is an image that reads past its own section
    header.
    """
    return b"".join(struct.pack("<QQ", tag, value)
                    for tag, value in entries) + struct.pack("<QQ", DT_NULL, 0)


def _build_hash(names: list[str]) -> bytes:
    """A `DT_HASH` table over `names`, whose `.dynsym` indices are 1..len.

    The classic SysV layout: `nbucket`, `nchain`, the bucket heads, then the
    chain links — chain `i` naming the next index after `i`, 0 for the end, and
    index 0 being the mandatory undefined symbol. Every name gets a link so the
    chain always terminates, and the bucket is the ELF hash of the name modulo
    `nbucket`, which is the function the loader will use to find it.
    """
    nchain = 1 + len(names)
    buckets = [_elf_hash(n) % _HASH_BUCKETS for n in names]
    # The chain is built BACKWARDS so each bucket head ends up naming the
    # HIGHEST index whose hash landed there, which is what makes a lookup
    # terminate on the zero at the end of the chain rather than cycling.
    heads = [0] * _HASH_BUCKETS
    links = [0] * nchain
    for i in range(len(names), 0, -1):
        slot = buckets[i - 1]
        links[i] = heads[slot]
        heads[slot] = i
    buf = bytearray(struct.pack("<II", _HASH_BUCKETS, nchain))
    for h in heads:
        buf.extend(struct.pack("<I", h))
    for link in links[1:]:
        buf.extend(struct.pack("<I", link))
    return bytes(buf)


def _elf_hash(name: str) -> int:
    """The ELF `DT_HASH` hash of `name`: `h = h*32 + c`, then `h %= 2**32`.

    Written out rather than imported because it is four characters and because
    the value has to be the loader's, not a plausible one: a `.hash` built with
    a different function produces a table that LOOKS right (the buckets are in
    range, every symbol is chained) and that a loader silently never walks, so
    every lookup misses and the library exports nothing.
    """
    h = 0
    for ch in name.encode():
        h = (h << 4) + ch
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
        h &= ~g & 0xFFFFFFFF
    return h


def _build_rela_dyn(got_slots: list[tuple[str, int]],
                    sym_index_map: dict[str, int]) -> bytes:
    """One R_X86_64_GLOB_DAT per GOT slot: fill the slot with the symbol."""
    buf = bytearray()
    for sym_name, got_vaddr in got_slots:
        r_info = (sym_index_map.get(sym_name, 0) << 32) | R_X86_64_GLOB_DAT
        buf.extend(struct.pack("<QQq", got_vaddr, r_info, 0))
    return bytes(buf)


def _layout(code_size: int, external_syms: list[str], needed: list[str],
            soname: str = None, exports: list = None,
            globals_size: int = 0, init_array_size: int = 0) -> dict:
    """Every size and virtual address the image needs, in one place.

    `compute_got_addrs` runs BEFORE the image exists (it back-patches the call
    sites) while `build_elf` runs after, so the two must not each compute the
    .got address: they share this. The same is true of a shared object's
    `.dynsym` indices — `r_info` names them — so this is also the authority for
    "symbol `i` is at `.dynsym` index `i + 1`", and of the `.init_array`, whose
    presence changes the `.dynamic` array's SIZE and therefore everything laid
    out after it. A caller that passed `init_array_size` to `build_elf_dylib` and
    not to `compute_got_addrs` would get an image whose `.dynamic` describes one
    more entry than it wrote and whose call sites branch through GOT slots a
    different distance away.

    `soname` is what makes it a shared object and its absence is what makes it
    an executable: an `ET_DYN` is defined by a `DT_SONAME` and an export table
    at least as much as by `e_type`, and `e_type` alone would let an image with
    no exports load as a library that provides nothing — which is the failure
    this file's audit exists to name.
    """
    dylib = soname is not None
    phnum = _PHNUM_NOEXTERN
    # A PT_DYNAMIC is needed whenever there IS something dynamic: an executable
    # with no externs has an empty `.dynamic` and needs no segment, while a
    # shared object always has one — its `DT_SONAME` and `DT_HASH` exist even
    # when it calls nothing out.
    if external_syms or dylib:
        phnum = _PHNUM_EXTERN
    # A `.globals` section adds a second PT_LOAD: the code segment is PF_X and a
    # slot is WRITTEN, and a program header's flags are per-segment, so the two
    # cannot be one mapping.
    if globals_size:
        phnum += 1
    text_file_offset = _EHDR_SIZE + _PHDR_SIZE * phnum

    exports = list(exports or [])
    # Whether there IS a `.dynamic` at all: an executable with no externs has
    # none (and no `DT_NEEDED`, since it binds nothing), while a shared object
    # always has one — its `DT_SONAME` and `DT_HASH` exist even when it calls
    # nothing out. Computed once and used for the array, its SIZE and the
    # `PT_DYNAMIC` header, because those three disagreeing is an image whose
    # segment describes bytes that are not there.
    dynamic = bool(external_syms) or dylib
    # `.dynstr` order: the undefined symbols, then the `DT_NEEDED` names, then
    # the SONAME, then the exported names. Every string the image references is
    # in it exactly once and in that order, which is what makes `str_offsets` a
    # function of this list rather than of four call sites.
    names = list(external_syms) + list(needed)
    if soname:
        names.append(soname)
    names.extend(e["symbol"] for e in exports)
    dynstr_size = sum(len(n) + 1 for n in names)
    n_exported = len(exports) if dylib else 0
    dynsym_size = (1 + len(external_syms) + n_exported) * _SYMSZ
    dynamic_size = ((len(_dynamic_tags(needed, soname, bool(init_array_size)))
                     + 1) * 16 if dynamic else 0)
    # nbucket + nchain words, the bucket heads, then one chain link per SYMBOL —
    # the exact shape `_build_hash` writes, and `_assemble` checks the emitted
    # length against this number before it places the table.  Counted over the
    # SYMBOLS and not over `.dynstr`: the soname and the `DT_NEEDED` names are
    # strings the image references and are not symbols, so sizing the hash from
    # the string table reserves chain links for names no lookup can ask for.
    hash_size = ((2 + _HASH_BUCKETS + len(external_syms) + n_exported)
                 * _HASH_WORD if soname else 0)
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
    hash_off = off
    off += hash_size
    dynamic_off = off
    off += dynamic_size
    got_off = off
    off += got_size
    # `.init_array` is the loader's list of functions to call while it brings
    # this object up, and it is placed BEFORE the globals because that is the
    # only place in this layout that is inside the code segment's own PT_LOAD
    # without being claimed twice: a loader reads the array, it does not write
    # it, and this image's second PT_LOAD starts at the globals.
    #
    # An ABSOLUTE address, like the `st_value` of an export and for the same
    # reason: this is an `ET_DYN` whose `p_vaddr` is `base_addr` and whose
    # relocations cover the `.got` and nothing else, so a pointer written here is
    # one the loader will not touch — and the emitters hand over addresses
    # already expressed in this image's space (`Assembler.label` records
    # `org + len(text)`), so nothing is added to them.
    init_array_off = off
    off += init_array_size
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
    # as an observation in `FORMAL_elf_globals_segment` rather than
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
        "hash_off": hash_off, "hash_size": hash_size,
        "dynamic_off": dynamic_off, "dynamic_size": dynamic_size,
        "got_off": got_off, "got_size": got_size,
        "init_array_off": init_array_off,
        "init_array_size": init_array_size,
        "globals_off": globals_off, "globals_size": globals_size,
        "rela_off": rela_off, "rela_size": rela_size,
        "body_size": off,
        "names": names,
    }


def compute_got_addrs(code_size: int, external_syms: list[str],
                      vaddr: int = DEFAULT_BASE,
                      lib_name: str = DEFAULT_LIBC,
                      soname: str = None, exports: list = None,
                      needed: list = None,
                      has_init_array: bool = False) -> dict[str, int]:
    """Absolute virtual address of each symbol's .got slot.

    Must agree with `build_elf`'s and `build_elf_dylib`'s layout — all three go
    through `_layout`, which is why the shared object's `.got` is not a second
    formula: the address a call site was PATCHED against has to be the address
    the image declares, and two layouts for one container is how a shared
    object ends up branching through a slot that is not there."""
    if not external_syms:
        return {}
    if needed is None:
        # An executable names the C library only when it has an extern to bind
        # through it; a shared object names its own soname and dependencies, and
        # `libc.so.6` is one of those dependencies rather than an implied one.
        needed = [lib_name]
    lay = _layout(code_size, external_syms, needed, soname, exports,
                  init_array_size=_PTRSZ * (1 if has_init_array else 0))
    base = vaddr + lay["got_off"]
    return {sym: base + i * _GOTSLOT
            for i, sym in enumerate(external_syms)}


def _dynamic_tags(needed: list[str], soname: str = None,
                  has_init_array: bool = False) -> list:
    """The `.dynamic` TAGS, in the order they are written.

    `_layout` sizes the array from this list and `_dynamic_for` fills the
    values into it, so the two cannot disagree about how many entries there are
    — and an array one entry short is an image whose `PT_DYNAMIC` describes
    bytes past the end of itself, which a loader reports as a corrupt file
    rather than as a bug.

    One `DT_NEEDED` per dependency, because that is the whole difference between
    an executable's single `libc.so.6` and a shared object's link line: an image
    whose `.dynstr` carries a module's exported symbol while the only `DT_NEEDED`
    is libc is a program that builds, passes every symbol audit, and dies at load
    with an unresolved symbol for a function its own source imports.

    The hash table comes FIRST among a shared object's own tags, before
    `DT_SONAME`, because that is the order `ld` writes and a loader is entitled
    to stop reading the array at the first tag it does not recognise. The
    initializer pair goes LAST, after the tables and the soname and where `ld`
    puts arrays: `DT_INIT_ARRAY` is the address of the `.init_array` this object
    wants called at load and `DT_INIT_ARRAYSZ` its size, and the pair is what
    makes a library's module body run — `elf/dl-init.c` walks every object's
    `DT_INIT_ARRAY` in dependency order, after its relocations are applied and
    before the program's own initializers, which is the position CPython gives a
    module body at import.
    """
    tags = [DT_NEEDED] * len(needed)
    tags += [DT_SYMTAB, DT_STRTAB, DT_STRSZ, DT_RELA, DT_RELASZ]
    if soname:
        tags += [DT_HASH, DT_SONAME]
    if has_init_array:
        tags += [DT_INIT_ARRAY, DT_INIT_ARRAYSZ]
    return tags


def _dynamic_for(lay: dict, str_offsets: dict, vaddr: int, needed: list[str],
                 soname: str = None) -> bytes:
    """The `.dynamic` array for a laid-out image, values resolved from `lay`.

    One function for both containers because the tags are the same list with
    different values, and the list is `_dynamic_tags` — the one `_layout` sized
    the array from.
    """
    values = {DT_SYMTAB: vaddr + lay["dynsym_off"],
              DT_STRTAB: vaddr + lay["dynstr_off"],
              DT_STRSZ: lay["dynstr_size"],
              DT_RELA: vaddr + lay["rela_off"],
              DT_RELASZ: lay["rela_size"],
              DT_HASH: vaddr + lay["hash_off"],
              DT_SONAME: str_offsets[soname] if soname else 0,
              DT_INIT_ARRAY: vaddr + lay["init_array_off"],
              DT_INIT_ARRAYSZ: lay["init_array_size"]}
    tags = _dynamic_tags(needed, soname, bool(lay["init_array_size"]))
    if tags.count(DT_NEEDED) != len(needed):
        raise ValueError("the DT_NEEDED count and the dependency list "
                         "disagree, so one of them would be written twice")
    entries = []
    it = iter(needed)
    for tag in tags:
        # One DT_NEEDED per dependency, in `needed`'s order, each naming its OWN
        # `.dynstr` entry — the tag is the same for all of them, so the value is
        # what distinguishes them and it cannot come from `values`.
        if tag == DT_NEEDED:
            entries.append((tag, str_offsets[next(it)]))
        else:
            entries.append((tag, values[tag]))
    return _build_dynamic(entries)


def build_elf(code: bytes, entry: int = DEFAULT_BASE,
              vaddr: int = DEFAULT_BASE,
              external_syms: Optional[list[str]] = None,
              lib_name: str = DEFAULT_LIBC,
              globals_image=None, deps: list = None) -> bytes:
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

    # `deps` is the module libraries on this image's link line, each one a
    # `DT_NEEDED`. `lib_name` is the C library and stays the fallback so a
    # caller that never heard of modules keeps its one entry.
    needed = elf_needed(list(deps or []) + ([lib_name] if external_syms
                                            else []),
                        bool(external_syms))
    lay = _layout(len(code), external_syms, needed, None, None, len(gblob))
    dynstr_data, str_offsets = _sym_name_offsets(lay["names"])
    lay["vaddr"] = vaddr
    dynsym_data = _build_dynsym(
        [(sym, 0, STT_NOTYPE, _STN_UNDEF) for sym in external_syms],
        str_offsets)
    sym_index = {s: i + 1 for i, s in enumerate(external_syms)}
    got_slots = [(sym, vaddr + lay["got_off"] + i * _GOTSLOT)
                 for i, sym in enumerate(external_syms)]
    rela_data = _build_rela_dyn(got_slots, sym_index)
    dynamic_data = (_dynamic_for(lay, str_offsets, vaddr, needed)
                    if external_syms else b"")
    return _assemble(lay, code, dynstr_data, dynsym_data, dynamic_data,
                     rela_data, gblob, ET_EXEC, entry)


def _assemble(lay: dict, code: bytes, dynstr_data: bytes, dynsym_data: bytes,
              dynamic_data: bytes, rela_data: bytes, gblob: bytes,
              e_type: int, entry: int, hash_data: bytes = b"",
              init_array: bytes = b"") -> bytes:
    """Headers and body for either container, from one `_layout`.

    A shared object and an executable differ in `e_type`, in the extra sections
    the layout has already sized, and in whether the segment is writable — and
    in NOTHING else about their structure. Writing that once is the point: the
    per-symbol work an ELF dylib shares with this executable is the whole of the
    extern machinery, and a second assembly loop would be the place for the two
    to disagree about which program header owns which byte.

    `init_array` is the bytes `DT_INIT_ARRAY` points at, and it is written
    between the `.got` and the `.globals` because that is where `_layout` put
    the offset the dynamic entry names; an array somewhere else would be an image
    whose `.dynamic` points at the `.got`.
    """
    phnum = lay["phnum"]
    text_file_offset = lay["text_file_offset"]
    code_align = 0x1000
    vaddr = lay["vaddr"]
    dynamic = lay["dynamic_size"] > 0

    total_size = text_file_offset + lay["body_size"]
    total_size_padded = (total_size + code_align - 1) // code_align * code_align

    buf = bytearray()

    # ELF header
    buf.extend(_ident())
    buf.extend(struct.pack("<HHIQQQI",
        e_type,             # e_type
        EM_X86_64,          # e_machine
        1,                  # e_version
        entry,              # e_entry
        _EHDR_SIZE,         # e_phoff
        0,                  # e_shoff
        0,                  # e_flags
    ))
    buf.extend(struct.pack("<HHHHHH",
        _EHDR_SIZE,         # e_ehsize
        _PHDR_SIZE,         # e_phentsize
        phnum,              # e_phnum
        0, 0, 0,            # e_shentsize, e_shnum, e_shstrndx
    ))

    # PT_LOAD covering code + the dynamic sections. p_offset is the end of the
    # headers so the code lands exactly at vaddr.
    #
    # Its p_filesz stops where the globals' own PT_LOAD begins, so no byte is
    # claimed by two program headers — a byte claimed twice is a mapping the
    # loader resolves by refusing to load. It runs to the END of the body rather
    # than stopping before `.rela.dyn`, which is what it used to do: the loader
    # reads its relocations THROUGH this mapping, so an image whose `DT_RELA`
    # names bytes no segment covers cannot be loaded at all. Measured here as
    # the image's own reader refusing to translate the `DT_RELA` address —
    # `no PT_LOAD segment maps the virtual address 0x4001e3` — which is the
    # failure in the only language a reader can use. Every byte of the image is
    # now claimed by exactly one segment, which is the same property
    # `test_formal_x86_64_dylib.py` asserts of the Mach-O library.
    p_flags = PF_R | PF_X
    if dynamic:
        p_flags |= PF_W        # the loader writes the .got slots
    code_and_dyn_size = lay["body_size"] - lay["globals_size"]
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

    if dynamic:
        buf.extend(struct.pack("<IIQQQQQQ",
            PT_DYNAMIC, PF_R | PF_W,
            text_file_offset + lay["dynamic_off"],
            vaddr + lay["dynamic_off"], vaddr + lay["dynamic_off"],
            lay["dynamic_size"], lay["dynamic_size"], 8,
        ))

    buf.extend(code)                       # .text
    buf.extend(dynstr_data)                # .dynstr
    buf.extend(dynsym_data)                # .dynsym
    if len(hash_data) != lay["hash_size"]:
        raise ValueError(f"the .hash table is {len(hash_data)} bytes and the "
                         f"layout reserved {lay['hash_size']}, so the "
                         f"DT_HASH address in .dynamic would name the wrong "
                         f"bytes")
    buf.extend(hash_data)                  # .hash
    buf.extend(dynamic_data)               # .dynamic
    buf.extend(b"\x00" * lay["got_size"])  # .got, filled by the loader
    if len(init_array) != lay["init_array_size"]:
        raise ValueError(f"the .init_array is {len(init_array)} bytes and the "
                         f"layout reserved {lay['init_array_size']}, so the "
                         f"DT_INIT_ARRAYSZ in .dynamic would name the wrong "
                         f"number of initializers")
    buf.extend(init_array)                 # .init_array, called at load
    buf.extend(gblob)                      # .globals, the module-global slots
    buf.extend(rela_data)                  # .rela.dyn

    buf.extend(b"\x00" * (total_size_padded - total_size))
    return bytes(buf)


# Where a shared object's code is mapped. An `ET_DYN` is position-independent
# and the loader chooses the base, so any p_vaddr works; it is fixed rather than
# zero so the codegen, `compute_got_addrs` and `build_elf_dylib` all read ONE
# number, exactly as `DEFAULT_BASE` is the executable's — and a library whose
# base is zero would make every absolute address in the code a relocation the
# image does not carry.
DYLIB_BASE = DEFAULT_BASE


def elf_dylib_exports(path: str) -> dict:
    """`{symbol: address}` for the DEFINED symbols in the ELF shared object at
    `path`, read back out of the FILE.

    The ELF counterpart of `formal/build.py::macho_dylib_exports`, which reads
    the Mach-O export TRIE, and it is here for the same reason: a manifest says
    what the build INTENDED to export, and this reads what a consumer of the
    artifact can actually find. `.dynstr` is located through `DT_STRTAB` and
    `.dynsym` through `DT_SYMTAB`, both of which are VIRTUAL addresses, so the
    bytes come from the PT_LOAD that maps them rather than from an offset
    remembered by the writer.
    """
    with open(path, "rb") as f:
        data = f.read()
    head = _read_header(data, path)
    if head["type"] != ET_DYN:
        raise ValueError(f"{path} is not an ELF shared object "
                         f"(e_type {head['type']}, expected {ET_DYN})")
    dyn = _dyn_entries(data, head)
    strings = _at_vaddr(data, head, dyn_tag(dyn, DT_STRTAB),
                        dyn_tag(dyn, DT_STRSZ))
    out = {}
    for st_name, st_info, st_shndx, st_value in _dynsym_entries(data, head):
        if st_shndx == _STN_UNDEF:
            continue
        if (st_info & 0xF) not in (STT_FUNC, STT_OBJECT, STT_NOTYPE):
            continue
        out[_st_name(strings, st_name)] = st_value
    return out


def _read_header(data: bytes, path: str = "<image>") -> dict:
    """The ELF header fields this file's readers need, and the one thing they
    all check first: the magic.

    Every reader here refuses a container it does not recognise rather than
    reading plausible numbers out of the wrong offset. That is the whole of the
    audit `formal/build.py::_audit_link_line_containers` performs at four bytes,
    and doing it again on the way IN is what makes a `str()` call site say what
    it found rather than returning `{}` and looking like a library that exports
    nothing.
    """
    if len(data) < _EHDR_SIZE or data[:4] != ELF_MAGIC:
        raise ValueError(f"{path} is not an ELF image (magic "
                         f"{data[:4]!r})")
    (e_type, e_machine, _ver, _entry, _phoff, _shoff, _flags) = struct.unpack_from(
        "<HHIQQQI", data, 16)
    return {"type": e_type, "machine": e_machine}


def _program_headers(data: bytes, head: dict) -> list:
    """`[(p_type, p_flags, p_offset, p_vaddr, p_filesz, p_memsz), …]`."""
    (e_phoff,) = struct.unpack_from("<Q", data, 32)
    (e_phentsize, e_phnum) = struct.unpack_from("<HH", data, 54)
    out = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        (p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz, p_memsz,
         _align) = struct.unpack_from("<IIQQQQQQ", data, off)
        out.append((p_type, p_flags, p_offset, p_vaddr, p_filesz, p_memsz))
    return out


def _dyn_entries(data: bytes, head: dict) -> list:
    """`[(tag, value), …]` — the `.dynamic` array, in file order, up to
    `DT_NULL`.

    A LIST and not a `{tag: value}` dict, and the reason is the one tag that
    repeats: `DT_NEEDED` appears once per dependency, and a dict keyed by tag
    keeps only the last of them — so a reader written that way reports an image
    linking one library when it links three, which is precisely the silent wrong
    answer this file exists to stop producing. `dyn_tag` is the accessor for
    "the value of this tag", and it refuses to guess when a tag repeats.

    Read from the PROGRAM HEADERS rather than from an offset this file
    remembered, because a `.dynamic` reachable only through a remembered offset
    is a reader that agrees with the emitter by construction and can therefore
    never notice the emitter being wrong — which is the failure this whole
    exercise exists to catch.
    """
    for p_type, _flags, p_offset, _p_vaddr, p_filesz, _memsz in \
            _program_headers(data, head):
        if p_type != PT_DYNAMIC:
            continue
        out = []
        for i in range(0, p_filesz - 15, 16):
            tag, val = struct.unpack_from("<QQ", data, p_offset + i)
            if tag == DT_NULL:
                return out
            out.append((tag, val))
        return out
    raise ValueError("the image carries no PT_DYNAMIC segment")


def dyn_tag(entries: list, tag: int) -> int:
    """The value of `tag` in a `_dyn_entries` list, refusing an ambiguous read.

    A tag that REPEATS is an error here rather than a "first" or a "last": a
    caller that asked for one dependency's name and got whichever of three
    happened to survive would be building a link line out of a coin toss.
    """
    vals = [v for t, v in entries if t == tag]
    if len(vals) > 1:
        raise ValueError(f"the image's .dynamic carries {len(vals)} entries "
                         f"for tag {tag:#x}; the caller asked for one and there "
                         f"is no right answer")
    return vals[0]


def _at_vaddr(data: bytes, head: dict, vaddr: int, size: int) -> bytes:
    """The `size` bytes at virtual address `vaddr`, through the PT_LOAD that
    maps it.

    The translation is `p_offset + (vaddr - p_vaddr)`, which is what makes this
    a reader of the IMAGE rather than of the emitter's own arithmetic: the same
    three numbers, read from the file.
    """
    for p_type, _flags, p_offset, p_vaddr, p_filesz, _memsz in \
            _program_headers(data, head):
        if p_type != PT_LOAD:
            continue
        if p_vaddr <= vaddr < p_vaddr + p_filesz:
            start = p_offset + (vaddr - p_vaddr)
            if start + size > len(data):
                break
            return data[start:start + size]
    raise ValueError(f"no PT_LOAD segment maps the virtual address {vaddr:#x}")


def _dynsym_entries(data: bytes, head: dict) -> list:
    """`[(st_name, st_info, st_shndx, st_value), …]` for every `.dynsym` entry.

    The COUNT comes from `DT_HASH`'s `nchain` — the loader's own way of learning
    how many symbols there are, since this emitter writes no section headers to
    say. A library with no hash table has no `nchain` to read, so it has no
    findable exports either, and this refuses rather than guessing a count from
    `.dynstr`'s length.
    """
    dyn = _dyn_entries(data, head)
    sym_vaddr = dyn_tag(dyn, DT_SYMTAB)
    nchain = _hash_nchain(data, head, dyn)
    sym_bytes = _at_vaddr(data, head, sym_vaddr, nchain * _SYMSZ)
    out = []
    for i in range(nchain):
        st_name, st_info, _other, st_shndx, st_value, _size = struct.unpack_from(
            "<IBBHQQ", sym_bytes, i * _SYMSZ)
        out.append((st_name, st_info, st_shndx, st_value))
    return out


def _hash_nchain(data: bytes, head: dict, dyn: dict) -> int:
    """The symbol count, from the DT_HASH table's second word."""
    raw = _at_vaddr(data, head, dyn_tag(dyn, DT_HASH), 8)
    nbucket, nchain = struct.unpack_from("<II", raw, 0)
    if nbucket < 1 or nchain < 1:
        raise ValueError(f"a DT_HASH table with {nbucket} bucket(s) and "
                         f"{nchain} chain(s) is not one a loader can use")
    return nchain


def _st_name(strings: bytes, offset: int) -> str:
    end = strings.find(b"\0", offset)
    if end < 0:
        raise ValueError(f"the .dynstr entry at {offset} is not terminated")
    return strings[offset:end].decode("utf-8", "replace")


def elf_needed(deps: list, has_externs: bool) -> list:
    """The `DT_NEEDED` list for an image: the libraries it was given, plus the
    C library when it has anything to bind through it.

    **One function, because the list is written into the image AND read back to
    compute the addresses the code was patched against.** `build_elf_dylib` and
    `compile_formal_dylib`'s ELF branch both need it and a `.got` layout that
    disagrees with the `.dynamic` about how many dependencies there are is an
    image whose call sites branch through the wrong slots — a wrong answer, not
    a refusal, and one that only shows up at run time on a machine with the
    dependency installed.

    Order is the caller's: the C library goes last, which is where `ld` puts it
    and where an executable's single entry already was.
    """
    out = list(deps or [])
    if has_externs and DEFAULT_LIBC not in out:
        out.append(DEFAULT_LIBC)
    return out


def build_elf_dylib(code: bytes, base_addr: int = DYLIB_BASE,
                    exports: list = None, soname: str = None,
                    external_syms: list = None, deps: list = None,
                    globals_image=None, namespace: bool = False,
                    mod_init_addrs: list = None) -> bytes:
    """An x86-64 `ET_DYN` shared object around `code`.

    **The ELF counterpart of `formal/macho_linker.py::build_macho_dylib`, and
    the thing whose absence made `fmt="elf"` unbuildable for any module.** The
    export table is the SAME information `build_macho_dylib` writes into its
    trie — a name and an address per export — so what differs is the container
    and nothing else; `exports` is that list, read once here and once there.

    Three things an `ET_EXEC` does not have and a shared object must:

      * a `DT_SONAME` carrying `soname`, which is how a consumer names it in its
        own `DT_NEEDED` and how the loader records what it opened;
      * an export table — `STB_GLOBAL`/`STT_FUNC` entries in `.dynsym` with the
        real `st_value`, which is what `elf_dylib_exports` reads back;
      * a `.hash`, because the loader looks a name up by hashing it and a
        library with no hash table exports nothing a dynamic linker can find.

    **No `.plt`, and that is not an omission.** A `PLT` exists so a call to an
    undefined function can be redirected lazily, which needs the call site to
    name a per-symbol stub. This backend's ELF extern form is `call [rip+disp32]`
    through a `.got` slot the loader fills with `R_X86_64_GLOB_DAT`, and a
    GOT slot resolves a FUNCTION symbol exactly as it resolves `printf` — so the
    same six bytes and the same relocation serve both, and a module export is
    bound by the same mechanism as an extern. A `.plt` here would be a second
    mechanism for one job.

    `deps` are the SONAMEs of the libraries this one links, one `DT_NEEDED`
    each, in the order given. `libc.so.6` is added when there is anything to
    bind through it, and a `DT_NEEDED` per dependency is the whole difference
    from an executable's single one: an image whose `.dynstr` carries a module's
    exported symbol with no `DT_NEEDED` naming a provider is the silent wrong
    image this function exists to stop producing.

    `base_addr` is where the code is emitted AND where the PT_LOAD maps it, for
    the reason `DYLIB_BASE` gives.

    `namespace=True` is a library whose EMPTY export table is the design rather
    than a mistake — `formal/build.py::_namespace_library`'s package
    `__init__`, whose API is re-exported from libraries already on the link
    line. The default refuses an empty table because that is nearly always a
    build that lost its API, and a `.so` with no exports is an image that loads
    and provides nothing, which is the one outcome worse than refusing.

    `mod_init_addrs` are the ADDRESSES of the functions the LOADER must run when
    it loads this object — the module body's wrapper, one per source file that
    had one, in that order — and they become the `.init_array` the
    `DT_INIT_ARRAY`/`DT_INIT_ARRAYSZ` pair points at. This is the ELF counterpart
    of the `__TEXT,__init_offsets` array
    `formal/macho_linker.py::build_macho_dylib` writes, and it exists for the
    same reason: a library with a module body needs an entry point that runs at
    load, and without one the body compiles to a function nothing calls. Empty —
    the ordinary case — writes no array and no dynamic tags, so an image without
    a module body is byte-for-byte what it was before this argument existed.
    """
    exports = list(exports or [])
    if not exports and not namespace:
        raise ValueError("an ELF shared object with no exported symbols "
                         "provides nothing; the module's API decides this, and "
                         "a package whose API is re-exported from its "
                         "submodules says so with namespace=True")
    if not soname:
        raise ValueError("an ELF shared object needs a DT_SONAME; the name a "
                         "consumer records in its own DT_NEEDED is this "
                         "library's identity and it is not derivable here")
    external_syms = sorted(external_syms or [])
    needed = elf_needed(deps, bool(external_syms))
    gblob = b"" if globals_image is None else bytes(globals_image.blob)
    # One pointer per entry, in the order given, verbatim: the emitters report
    # ADDRESSES (`Assembler.label` records `org + len(text)`), and this image's
    # relocations cover the `.got` and nothing else, so an address written here
    # is one the loader will not touch.
    init_array = b"".join(struct.pack("<Q", int(addr))
                          for addr in (mod_init_addrs or []))

    lay = _layout(len(code), external_syms, needed, soname, exports, len(gblob),
                  len(init_array))
    dynstr_data, str_offsets = _sym_name_offsets(lay["names"])
    syms = [(sym, 0, STT_NOTYPE, _STN_UNDEF) for sym in external_syms]
    # The export's `entry` is an address in the code emitter's own space, which
    # is this library's `base_addr` plus an offset — so it is written straight
    # into `st_value` and needs no rebasing. The Mach-O trie subtracts
    # `TEXT_BASE` because it stores an OFFSET; an ELF `st_value` is an address.
    syms.extend((e["symbol"], e["entry"], STT_FUNC, _SHNDX_ABS)
                for e in exports)
    dynsym_data = _build_dynsym(syms, str_offsets)
    hash_data = _build_hash([s[0] for s in syms])
    # `sym_index` is what `r_info` packs, and it indexes `.dynsym`, so the
    # undefined symbols keep indices 1..n whether or not there are exports
    # after them.
    sym_index = {s: i + 1 for i, s in enumerate(external_syms)}
    got_slots = [(sym, base_addr + lay["got_off"] + i * _GOTSLOT)
                 for i, sym in enumerate(external_syms)]
    rela_data = _build_rela_dyn(got_slots, sym_index)
    dynamic_data = _dynamic_for(lay, str_offsets, base_addr, needed, soname)
    lay["vaddr"] = base_addr
    return _assemble(lay, code, dynstr_data, dynsym_data, dynamic_data,
                     rela_data, gblob, ET_DYN, base_addr, hash_data,
                     init_array)
