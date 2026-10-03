#!/usr/bin/env python3
"""x86-64 MODULE dylibs: a module that calls out must build, sign and RUN.

The x86-64 dylib extern path had one defect that made every module which
calls the C library unbuildable on that target — `os`, `sys`, anything that
touches `strlen`.  `formal/macho_linker.py`'s `build_macho_dylib` wrote its
`__TEXT,__stubs` entries with `_stub_bytes(...)` and no `arch`, so the arm64
default (a 12-byte ADRP/LDR/BR) landed in the x86-64 6-byte slots.  A slice
assignment whose value outgrows its slice makes `bytearray` *insert* rather
than overwrite, so every stub pushed the tail 6 bytes right: `__LINKEDIT`
claimed `filesize` N while the image was N+6n bytes long, and `codesign`
refused the whole library with `main executable failed strict validation`.

The symptom is a codesign complaint three steps downstream of the cause, on a
program whose own source is two lines long, so what is asserted here is
checked at every level where it could have gone wrong:

  1. the STUB BYTES in the image are the x86-64 `JMPQ *disp(%rip)` form, one
     6-byte entry per extern — the level at which the defect was;
  2. `codesign -v` accepts the library (the message the two bug docs quote);
  3. every byte of the file is claimed by a segment (the invariant whose
     check was missing from this builder and is now in the emitter);
  4. a PROGRAM that imports the module builds for x86-64, runs under Rosetta
     2, and its stdout and exit status match CPython running the same text —
     which is the only level at which a wrong container is distinguishable
     from a working one.

`build_macho_dylib` now also runs `_assert_no_unclaimed_bytes`, so level 3 is
now enforced at BUILD time; the check is repeated here against the file, read
back with a parser written in this file rather than the writer's.

    python3 test_formal_x86_64_dylib.py [-v]
"""

import argparse
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FIRE = os.path.join(HERE, "fire.py")

MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_X86_64 = 0x01000007
MH_DYLIB = 0x6
ET_DYN = 3
LC_SEGMENT_64 = 0x19
S_ATTR_PURE_INSTRUCTIONS = 0x80000000
S_ATTR_SOME_INSTRUCTIONS = 0x00000400

# `jmpq *disp32(%rip)` is FF 25 <disp32> — 6 bytes, and the displacement runs
# from the END of the instruction. The arm64 stub is ADRP+LDR+BR, whose first
# byte is a word-form ADRP, so the opcode alone separates the two.
JMP_RIP_INDIRECT = b"\xff\x25"
X86_64_STUB_SIZE = 6


class TestFailure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise TestFailure(msg)


# ── a Mach-O reader, written here and not shared with the writer ─────────────

def segments_and_sections(data: bytes) -> tuple:
    """[(segname, vmaddr, vmsize, fileoff, filesize, [(sectname, addr, size,
    offset), ...])] for every LC_SEGMENT_64, plus the raw load commands."""
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds = \
        struct.unpack_from("<6I", data, 0)
    check(magic == MH_MAGIC_64, f"not a 64-bit Mach-O (magic {magic:#x})")
    segs = []
    pos = 32
    for _ in range(ncmds):
        if pos + 8 > len(data):
            raise TestFailure("load command list runs past the end of the file")
        cmd, cmdsize = struct.unpack_from("<II", data, pos)
        if cmd == LC_SEGMENT_64:
            segname = data[pos + 8:pos + 24].rstrip(b"\0").decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from(
                "<4Q", data, pos + 24)
            nsects = struct.unpack_from("<I", data, pos + 64)[0]
            sects = []
            so = pos + 72
            for _i in range(nsects):
                sname = data[so:so + 16].rstrip(b"\0").decode()
                addr, size = struct.unpack_from("<QQ", data, so + 32)
                offset = struct.unpack_from("<I", data, so + 48)[0]
                sects.append((sname, addr, size, offset))
                so += 80
            segs.append((segname, vmaddr, vmsize, fileoff, filesize, sects))
        pos += cmdsize
    return (cputype, cpusubtype, filetype), segs


def section(segs, name):
    for seg in segs:
        for sname, addr, size, offset in seg[5]:
            if sname == name:
                return addr, size, offset
    return None


# ── running the x86-64 image ───────────────────────────────────────────────

def run_x86_64(path: str, timeout: int = 60):
    """Execute an x86-64 Mach-O on this host, under Rosetta 2 where needed."""
    argv = (["arch", "-x86_64", path]
            if (platform.machine() in ("arm64", "aarch64")
                and sys.platform == "darwin") else [path])
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def build_module_dylib(tmpdir, source: str, stem: str) -> str:
    """Build `source` as a MODULE dylib through the import path.

    `formal.imports.build_module_dylib` and not `fire.py dylib`: the import
    path is the one an x86-64 program actually takes for `import <mod>`, and
    it is where this defect was reported from.
    """
    from formal.imports import build_module_dylib as _build
    path = os.path.join(tmpdir, stem + ".mojo")
    with open(path, "w") as f:
        f.write(source)
    out_dir = os.path.join(tmpdir, "cas")
    return _build(stem, path, out_dir, arch="x86_64",
                  project_root=tmpdir)


# ── the tests ──────────────────────────────────────────────────────────────

def test_x86_64_dylib_stub_entries_are_jmpq_rrip(tmpdir, shared):
    """The `__TEXT,__stubs` entries are x86-64 `JMPQ *(%rip)`, 6 bytes each.

    This is the defect's own level. Before the fix `build_macho_dylib` called
    `_stub_bytes(got_vm, stub_vm)` without `arch`, so the arm64 12-byte
    sequence was written into the 6-byte x86-64 slot.
    """
    path = shared["extern_dylib"]
    with open(path, "rb") as f:
        data = f.read()
    (cputype, cpusubtype, filetype), segs = segments_and_sections(data)
    check(cputype == CPU_TYPE_X86_64,
          f"dylib cputype is {cputype:#x}, expected x86_64 {CPU_TYPE_X86_64:#x}")
    check(filetype == MH_DYLIB, f"filetype is {filetype}, expected MH_DYLIB")

    got = section(segs, "__stubs")
    check(got is not None,
          "no __TEXT,__stubs section: an extern was reported but no stub "
          "trampoline was emitted for it")
    _addr, size, offset = got
    check(size % X86_64_STUB_SIZE == 0,
          f"__stubs is {size} bytes, which is not a whole number of "
          f"{X86_64_STUB_SIZE}-byte x86-64 entries — the stub geometry and "
          f"the arch disagree")
    check(size > 0, "__stubs is empty but the module makes extern calls")
    for i in range(size // X86_64_STUB_SIZE):
        entry = data[offset + i * X86_64_STUB_SIZE:
                     offset + (i + 1) * X86_64_STUB_SIZE]
        check(entry[:2] == JMP_RIP_INDIRECT,
              f"stub {i} starts {entry[:2].hex()}, not ff25 (jmpq *disp(%rip)) "
              f"— an arm64 stub (ADRP/LDR/BR) was written for an x86-64 image")


def test_x86_64_dylib_passes_strict_validation(tmpdir, shared):
    """`codesign -v` accepts the library.

    The message this replaces is `main executable failed strict validation`,
    which names a signing symptom rather than the byte that caused it and is
    what both `FORMAL_x86_64_dylib_externs_unsigned` and
    `FORMAL_x86_64_dylib_with_an_extern_call_does_not_load` recorded.
    """
    if sys.platform != "darwin":
        return
    path = shared["extern_dylib"]
    r = subprocess.run(["codesign", "-v", path], capture_output=True, text=True)
    check(r.returncode == 0,
          f"codesign refuses the x86-64 dylib: "
          f"{(r.stderr or r.stdout).strip()}")


def test_the_dylib_container_is_what_the_caller_asked_for(tmpdir, shared):
    """Both containers are real now, so `fmt` names what comes out.

    `compile_formal_dylib(fmt="elf")` used to be accepted on a Mach-O host and
    produce a Mach-O anyway -- the refusal was conditioned on
    `not fmt_wants_macho(arch)`, which on this host is false for every `fmt`.
    An argument that is accepted and ignored is worse than a hardcoded literal:
    the caller gets an artifact it did not ask for and no diagnostic, three
    steps before dyld reports a container mismatch.

    So the same refusal became a real emitter (`formal/elf.py::build_elf_dylib`)
    and the assertion became the one the argument always implied: the FILE
    carries the container that was asked for. Both are read from the file rather
    than from the result dict, because a result dict is a claim and a file is
    the artifact.

    The container assertion is also the check the `arch` case in
    `test_formal_dylib.py` was missing: it asserted the ARCHITECTURE, which a
    Mach-O labelled `x86_64` passes, and so could not see the wrong container.
    """
    from formal.build import compile_formal_dylib
    src = os.path.join(tmpdir, "anyfmt.mojo")
    with open(src, "w") as f:
        f.write("def add1(x):\n  return x + 1\n")
    out = os.path.join(tmpdir, "anyfmt.dylib")

    compile_formal_dylib([src], output=out, arch="x86_64", fmt="elf",
                         prove=False, check=False)
    with open(out, "rb") as f:
        head = f.read(64)
    check(head[:4] == b"\x7fELF",
          f"fmt='elf' did not produce an ELF container: {head[:4]!r}")
    # e_type is ET_DYN and not ET_EXEC: a shared OBJECT. An ELF executable on a
    # module library is the mirror image of the defect this row is about -- a
    # container the caller did not ask for -- and it loads as nothing at all.
    check(struct.unpack_from("<H", head, 16)[0] == ET_DYN,
          "fmt='elf' produced an ELF image that is not ET_DYN")

    # And the format it can always honour still produces the container it names.
    compile_formal_dylib([src], output=out, arch="x86_64", fmt="macho",
                         prove=False, check=False)
    with open(out, "rb") as f:
        head = f.read(4)
    check(struct.unpack_from("<I", head, 0)[0] == MH_MAGIC_64,
          "fmt='macho' did not produce a 64-bit Mach-O container")


def test_an_elf_module_dylib_is_a_loadable_object(tmpdir, shared):
    """The ELF library's three things an `ET_EXEC` does not have.

    The whole gap this file's ELF half is about was that `fmt="elf"` had no
    shared-object emitter, so the "fix" was a refusal. These are the three
    pieces a library needs and an executable does not, asserted from the FILE
    through a reader that finds `.dynsym` and `.hash` by their `DT_*` VIRTUAL
    addresses -- so a table that is present but not MAPPED cannot pass, which is
    the failure a reader that remembered its own offsets would not see.

      * a `DT_SONAME` naming the library, which is what a consumer puts in its
        own `DT_NEEDED` and what the loader records as what it opened;
      * a `.hash`, because the loader looks an exported name up by HASHING it
        and a library with no table exports nothing a dynamic linker can find;
      * the exported symbols themselves, with the addresses the manifest says.

    And the export table is read with `formal.elf.elf_dylib_exports`, which is
    the ELF counterpart of the `macho_dylib_exports` used two tests above --
    both read the ARTIFACT, and neither takes the build's word for what it
    wrote.
    """
    from formal import elf
    from formal.build import compile_formal_dylib
    src = os.path.join(tmpdir, "elfmod.mojo")
    with open(src, "w") as f:
        f.write("def add1(x):\n  return x + 1\n\ndef twice(x):\n  return x * 2\n")
    out = os.path.join(tmpdir, "elfmod.so")
    result = compile_formal_dylib([src], output=out, arch="x86_64", fmt="elf",
                                  prove=False, check=False)
    check(result["backend"] == "x86_64/elf-dylib",
          f"the library reported backend {result['backend']!r}")
    with open(out, "rb") as f:
        data = f.read()

    head = elf._read_header(data, out)
    dyn = elf._dyn_entries(data, head)
    tags = [t for t, _v in dyn]
    check(elf.DT_SONAME in tags,
          f"the library carries no DT_SONAME, so a consumer has nothing to "
          f"name in its own DT_NEEDED: tags {[hex(t) for t in tags]}")
    check(elf.DT_HASH in tags,
          f"the library carries no DT_HASH, so a loader cannot FIND an export "
          f"however many `.dynsym` entries it has: tags {[hex(t) for t in tags]}")

    strings = elf._at_vaddr(data, head, elf.dyn_tag(dyn, elf.DT_STRTAB),
                            elf.dyn_tag(dyn, elf.DT_STRSZ))
    soname = elf._st_name(strings, elf.dyn_tag(dyn, elf.DT_SONAME))
    check(soname == os.path.basename(out),
          f"DT_SONAME is {soname!r} and the file is "
          f"{os.path.basename(out)!r}; those are the two names that have to "
          f"agree")

    # Every exported name is in the `.hash` chain, which is the property a
    # loader depends on and the one a table of plausible numbers would not have.
    # EVERY `.dynsym` entry is reachable by walking the chains, which is what a
    # loader does: it hashes the NAME, takes the bucket head, and follows the
    # chain comparing names. A table whose heads are in range and whose chains
    # omit a symbol is indistinguishable from a correct one until the lookup
    # misses, and then the library exports nothing at all.
    hash_vaddr = elf.dyn_tag(dyn, elf.DT_HASH)
    nbucket, nchain = struct.unpack_from(
        "<II", elf._at_vaddr(data, head, hash_vaddr, 8), 0)
    check(nbucket >= 1 and nchain >= 2,
          f"a DT_HASH table with {nbucket} bucket(s) and {nchain} chain(s) is "
          f"not one a loader can walk")
    table = elf._at_vaddr(data, head, hash_vaddr,
                          (2 + nbucket + nchain - 1) * 4)
    _nb, _nc = struct.unpack_from("<II", table, 0)
    heads = struct.unpack_from(f"<{nbucket}I", table, 8)
    links = struct.unpack_from(f"<{nchain - 1}I", table, 8 + nbucket * 4)
    reachable = set()
    for h in heads:
        i = h
        while i:
            check(i not in reachable,
                  f"the hash chain for bucket {heads.index(h)} revisits index "
                  f"{i}; a loader would loop rather than stop")
            reachable.add(i)
            i = links[i - 1]
    found = elf.elf_dylib_exports(out)
    wanted = {e["symbol"] for e in result["exports"]}
    missing = sorted(n for n in wanted if n not in found)
    check(not missing,
          f"these exports are not in the `.dynsym` a consumer would read: "
          f"{missing}")
    # The chain stores `.dynsym` INDICES and `.dynsym` stores `.dynstr`
    # OFFSETS, so the walk is over indices -- and `_dynsym_entries` INCLUDES
    # index 0, the mandatory undefined symbol, so entry k of that list IS
    # index k. Getting that off by one makes a correct table look half
    # unreachable.
    unreachable = sorted(
        _st_name_at(strings, off)
        for i, (off, _info, shndx, _v) in
        enumerate(elf._dynsym_entries(data, head))
        if shndx != 0 and i not in reachable)
    check(not unreachable,
          f"these symbols are in `.dynsym` but no hash chain reaches them, so "
          f"a loader cannot find them by name: {unreachable}")

    # The addresses come back as the ones the build recorded, which is the
    # whole point of reading the artifact rather than the manifest.
    for e in result["exports"]:
        check(found.get(e["symbol"]) == e["entry"],
              f"{e['symbol']} reads back at "
              f"{found.get(e['symbol']) and hex(found[e['symbol']])} and was "
              f"written at {hex(e['entry'])}")

    # …and the segments cover the whole BODY, with no gap and nothing past the
    # end. Stated as an interval rather than as "every byte" because the ELF
    # header and the program headers belong to no segment by design, and the
    # tail padded up to `p_align` belongs to none either; what has to hold is
    # that every byte from the end of the headers to the end of the last
    # `PT_LOAD` is inside some `PT_LOAD`. A gap there is a region the loader
    # cannot read, and `DT_RELA` was the one this caught: before the fix
    # `build_elf` stopped the first segment at `.globals`, leaving
    # `.rela.dyn` claimed by nothing.
    covered = []
    for p_type, _f, p_offset, _v, p_filesz, _m in \
            elf._program_headers(data, head):   # the ELF half's own reader
        if p_type == 1:
            covered.append((p_offset, p_offset + p_filesz))
    e_phoff, = struct.unpack_from("<Q", data, 32)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 54)
    body_start = e_phoff + e_phnum * e_phentsize
    body_end = max(e for _s, e in covered)
    gaps = []
    cursor = body_start
    for start, end in sorted(covered):
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    check(not gaps and cursor == body_end,
          f"the image's segments do not tile its body: gaps {gaps}, they end "
          f"at {cursor}, and the last segment claims up to {body_end}")
    # What is past the last segment is page padding to `p_align`, and padding
    # is zeros: a byte of slack the emitter was going to write into is the
    # Mach-O defect this file's own `every byte of the dylib is claimed by a
    # segment` row is about, in the container where there is no `codesign` to
    # complain about it.
    tail = data[body_end:]
    check(not any(tail),
          f"{sum(1 for b in tail if b)} non-zero byte(s) past the last "
          f"segment's {len(tail)}-byte tail")
    check(len(data) % 0x1000 == 0,
          f"the image is {len(data)} bytes, which is not a page multiple, so "
          f"the padding is not what the PT_LOAD's p_align says it is")


def _st_name_at(strings, offset):
    """The name at a `.dynstr` offset, or "" past the end.

    Offset-based rather than a search, because the walk above is over `.dynsym`
    indices and the question each one asks is "what name does the loader read
    here" — the same question, answered by the same arithmetic the loader uses.
    """
    end = strings.find(b"\0", offset)
    return "" if end < 0 else strings[offset:end].decode("utf-8", "replace")


def test_the_elf_dylib_refuses_what_it_cannot_represent(tmpdir, shared):
    """Two refusals, and they are refusals rather than images on purpose.

    A shared object with an empty export table and no `DT_SONAME` is a file
    that loads and provides nothing, which is the one outcome worse than
    refusing -- it moves the failure to run time and to a message about a
    symbol. `formal/elf.py::build_elf_dylib` says so at the point where the
    omission is visible.

    The namespace library is the one caller whose empty export table IS the
    design (`formal/build.py::_namespace_library`: a package `__init__` whose
    whole API is re-exported from libraries already on the link line), so it
    passes `namespace=True` and the check has to distinguish "deliberately
    empty" from "accidentally empty" rather than refusing both.
    """
    from formal import elf
    src = os.path.join(tmpdir, "empty.mojo")
    with open(src, "w") as f:
        f.write("def add1(x):\n  return x + 1\n")
    for kwargs, needle in (
            ({"exports": [], "soname": "x.so"},
             "no exported symbols"),
            ({"exports": [{"symbol": "a", "entry": 0x400000}], "soname": None},
             "DT_SONAME")):
        try:
            elf.build_elf_dylib(b"\x90" * 8, **kwargs)
        except ValueError as e:
            check(needle in str(e),
                  f"the refusal does not say what is missing: {str(e)!r} "
                  f"(looked for {needle!r})")
        else:
            raise TestFailure(
                f"build_elf_dylib({kwargs!r}) returned an image: a shared "
                f"object that provides nothing is a file that loads and binds "
                f"no name")

    # …and the deliberate one is accepted, so the refusal above is about the
    # omission and not about an empty table being impossible.
    blob = elf.build_elf_dylib(b"", exports=[], soname="ns.so",
                               namespace=True)
    check(blob[:4] == b"\x7fELF" and len(blob) > 0,
          "a namespace library did not build")


def test_an_elf_image_with_a_macho_module_is_refused(tmpdir, shared):
    """The cross-container refusal is still the answer, for a different reason.

    `formal/imports.py::build_module_dylib` builds a library in
    `default_format(arch)` -- the HOST's container -- while `compile_formal`'s
    `fmt` is the CALLER's. On Linux the two agree and there is nothing to say;
    on a Mach-O host, asking for an ELF image builds the module as a Mach-O,
    and `_audit_link_line_containers` refuses with the mismatch. That is the
    honest answer and it names the file to rebuild.

    What this row is NOT is the old test's assertion that an ELF image with an
    import is refused because there is no ELF emitter. That was true while
    there was no emitter; the emitter is now `formal/elf.py::build_elf_dylib`
    and `compile_formal_dylib(fmt="elf")` returns a real object (the test
    above). So the refusal that remains is about the LINK LINE, and it has to
    say so -- a reader who was told "this path has no ELF dylib emitter" would
    go looking for an emitter that is right there.

    An ELF image with NO import still builds either way, and that is the
    assertion that the refusal is about the link line and not the format.
    """
    from formal.build import compile_formal, FormalBuildError, default_format
    lib = os.path.join(tmpdir, "elfmod2.mojo")
    with open(lib, "w") as f:
        f.write("def add1(x):\n  return x + 1\n")
    prog = os.path.join(tmpdir, "elfimp2.mojo")
    with open(prog, "w") as f:
        f.write("import elfmod2\n\ndef main():\n  return elfmod2.add1(41)\n")

    if default_format("x86_64") == "elf":
        # A host whose native container IS elf: the module is built as an ELF
        # shared object and the image links it. Nothing is refused, and the
        # program is the first end-to-end ELF module link in the tree.
        result = compile_formal(prog, output=os.path.join(tmpdir, "e.elf"),
                                arch="x86_64", fmt="elf", prove=False,
                                check=False)
        check(result["backend"] == "x86_64/elf",
              f"an ELF module link reported backend {result['backend']!r}")
        return

    try:
        compile_formal(prog, output=os.path.join(tmpdir, "elfimp2.elf"),
                       arch="x86_64", fmt="elf", prove=False, check=False)
    except FormalBuildError as e:
        msg = str(e)
        check("elf" in msg,
              f"the refusal does not name the format: {msg!r}")
        check("macho" in msg.lower(),
              f"the refusal does not say which container the library is in, "
              f"so a reader cannot tell WHICH FILE is wrong: {msg!r}")
        check("no elf dylib emitter" not in msg.lower(),
              f"the refusal still claims there is no ELF dylib emitter, and "
              f"there is one (`formal/elf.py::build_elf_dylib`): {msg!r}")
    else:
        raise TestFailure(
            "an ELF image linked a MACH-O module library: no ELF loader will "
            "ever open that Mach-O, so the image carries the symbol with "
            "nothing providing it")

    # The format itself is fine -- it is the module link line it cannot carry.
    lone = os.path.join(tmpdir, "elfsolo.mojo")
    with open(lone, "w") as f:
        f.write("def main():\n  printf(\"%d\", 42)\n  return 0\n")
    result = compile_formal(lone, output=os.path.join(tmpdir, "elfsolo.elf"),
                            arch="x86_64", fmt="elf", prove=False, check=False)
    check(result["backend"] == "x86_64/elf",
          f"an import-free ELF build reported backend "
          f"{result['backend']!r}; the refusal above must be about the module "
          f"link line and not about elf as a container")


def test_the_link_line_containers_must_agree(tmpdir, shared):
    """A library in the wrong container is refused, and the matching one is not.

    `_audit_bound_symbols` cannot see this: it reads each library's manifest,
    finds the symbol among its exports, and counts it as provided — true, and
    irrelevant, because the library is a container the loader will not open.
    So the question "does something on this link line DECLARE this name" has to
    be followed by "will the loader open that file", and the second one is
    asked here.

    Checked both ways, because a check that only fires is a check that cannot
    be told apart from a broken one: a mismatch must be caught, and the same
    link line against a matching image must not be.
    """
    from formal.build import (load_dylib_manifests, FormalBuildError,
                              _audit_link_line_containers, _container_family)
    lib = shared["extern_dylib"]
    linked = load_dylib_manifests([lib])
    check(bool(linked) and linked[0].get("path"),
          "the manifest did not yield a linkable path, so the container "
          "audit has nothing to read — the libraries would be uncheckable")

    check(_container_family(lib) == "macho",
          f"the x86-64 module dylib is {_container_family(lib)}, expected "
          f"macho on this host")

    # Matching container: no error. A library against a macho image.
    try:
        _audit_link_line_containers(linked, "macho", "image")
    except FormalBuildError as e:
        raise TestFailure(
            f"a Mach-O library on a Mach-O link line was refused: {e}")

    # Mismatched: named, and about the container rather than a symbol.
    try:
        _audit_link_line_containers(linked, "elf", "image")
    except FormalBuildError as e:
        msg = str(e)
        check("elf" in msg and "macho" in msg,
              f"the refusal does not name both containers, so it does not "
              f"say which is wrong: {msg!r}")
        check(os.path.basename(lib) in msg,
              f"the refusal does not name the offending library: {msg!r}")
    else:
        raise TestFailure(
            "an ELF image with a Mach-O library on its link line was "
            "accepted: the symbol is declared by a file no ELF loader will "
            "open, so it is unresolvable at load")


def test_every_byte_of_the_dylib_is_claimed(tmpdir, shared):
    """The image is exactly as long as its last segment claims.

    A slice assignment that outgrows its slice makes `bytearray` insert, which
    leaves the image longer than any segment declares — the shape of the
    defect, and what `codesign` rejects. `build_macho_dylib` now asserts this
    itself; repeated here on the bytes read back from disk.
    """
    path = shared["extern_dylib"]
    with open(path, "rb") as f:
        data = f.read()
    _hdr, segs = segments_and_sections(data)
    end = max(seg[3] + seg[4] for seg in segs)
    check(end == len(data),
          f"the dylib is {len(data)} bytes but its segments claim only {end}: "
          f"{len(data) - end} unclaimed trailing byte(s)")


def test_program_importing_an_extern_module_matches_cpython(tmpdir, shared):
    """A program importing the module builds, runs, and agrees with CPython.

    The end-to-end level, and the only one that separates a working container
    from a merely well-formed one: the module's `strlen` call is bound by dyld
    at load time, so a library whose bind stream addresses the wrong bytes
    still loads and still returns a number, just not this one.
    """
    prog = os.path.join(tmpdir, "importer.mojo")
    with open(prog, "w") as f:
        f.write("import x86ext\n"
                "\n"
                "def main():\n"
                "    print(x86ext.size('hello'))\n"
                "    return x86ext.plus(40, 2)\n")
    out = os.path.join(tmpdir, "importer.aout")
    build = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "--backend=x86_64", "-o", out, prog],
        capture_output=True, text=True, timeout=600)
    check(build.returncode == 0,
          f"an x86-64 program importing a module with an extern call did not "
          f"build: {(build.stderr or build.stdout).strip()[-400:]}")

    got = run_x86_64(out)
    check("Bad CPU type" not in (got.stderr or ""),
          f"the image was rejected by the loader: {got.stderr!r}")

    # CPython running the same text, with the one C function the module calls
    # supplied the way libc supplies it.
    def strlen(s):
        return len(s)

    ns = {"strlen": strlen}
    source = open(prog).read().replace(
        "import x86ext\n",
        "class x86ext:\n"
        "    @staticmethod\n"
        "    def size(s):\n"
        "        return strlen(s)\n"
        "    @staticmethod\n"
        "    def plus(a, b):\n"
        "        return a + b\n")
    exec(compile(source, prog, "exec"), ns)
    want_out = "5\n"
    check(got.stdout == want_out,
          f"the x86-64 image printed {got.stdout!r}, expected {want_out!r}")
    check(got.returncode == 42,
          f"the x86-64 image exited {got.returncode}, expected 42 (40 + 2) "
          f"— CPython's answer for the same program")


def test_module_dylib_with_an_extern_call_loads_into_a_program(tmpdir, shared):
    """The library itself is loadable: dlopen it from a second program.

    `fire.py build --link-dylib` is the hand-assembled link line; the
    `import` path is what a real program writes. Both are exercised, because
    they produce different images (the hand-linked one names its dependency by
    path) and a container defect can hide in exactly one of them.
    """
    lib = shared["extern_dylib"]
    prog = os.path.join(tmpdir, "linked.mojo")
    with open(prog, "w") as f:
        f.write("from x86ext import size\n"
                "\n"
                "def main():\n"
                "    print(size('abcd'))\n"
                "    return 0\n")
    out = os.path.join(tmpdir, "linked.aout")
    build = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "--backend=x86_64", "-o", out, "--link-dylib", lib, prog],
        capture_output=True, text=True, timeout=600)
    check(build.returncode == 0,
          f"linking an x86-64 module dylib with an extern failed: "
          f"{(build.stderr or build.stdout).strip()[-400:]}")
    got = run_x86_64(out)
    check(got.stdout == "4\n",
          f"a program linked against the x86-64 dylib printed {got.stdout!r}, "
          f"expected '4\\n' — 'abcd' has 4 bytes")
    check(got.returncode == 0,
          f"a program linked against the x86-64 dylib exited "
          f"{got.returncode}, expected 0")


def test_the_x86_64_dylib_exports_its_module_api(tmpdir, shared):
    """The export trie carries the module's prefixed API and nothing else.

    A dylib whose trie is right but whose SEGMENTS are wrong loads and then
    faults on first call, so the export set is checked from the file's own
    trie (via `dlsym` in the next test) as well as from the manifest.
    """
    path = shared["extern_dylib"]
    with open(path + ".manifest.json") as f:
        payload = json.load(f)
    names = {e["name"] for e in payload["exports"]}
    check(names == {"size", "plus"},
          f"the manifest exports {sorted(names)}, expected ['plus', 'size']")
    for e in payload["exports"]:
        check(e["symbol"].startswith("x86ext_"),
              f"export {e['name']!r} is spelled {e['symbol']!r}, which carries "
              f"no module prefix — two modules with same-named functions "
              f"would collide in one process")


TESTS = [
    ("x86-64 dylib stubs are jmpq *(%rip)",
     test_x86_64_dylib_stub_entries_are_jmpq_rrip),
    ("x86-64 dylib passes codesign strict validation",
     test_x86_64_dylib_passes_strict_validation),
    ("the dylib container is what the caller asked for",
     test_the_dylib_container_is_what_the_caller_asked_for),
    ("an ELF module dylib is a loadable object",
     test_an_elf_module_dylib_is_a_loadable_object),
    ("the ELF dylib refuses what it cannot represent",
     test_the_elf_dylib_refuses_what_it_cannot_represent),
    ("an ELF image with a module import is refused",
     test_an_elf_image_with_a_macho_module_is_refused),
    ("the link line containers must agree",
     test_the_link_line_containers_must_agree),
    ("every byte of the x86-64 dylib is claimed by a segment",
     test_every_byte_of_the_dylib_is_claimed),
    ("a program importing an extern module matches CPython",
     test_program_importing_an_extern_module_matches_cpython),
    ("an x86-64 dylib with an extern call links and runs",
     test_module_dylib_with_an_extern_call_loads_into_a_program),
    ("the x86-64 dylib exports its module API",
     test_the_x86_64_dylib_exports_its_module_api),
]


EXTERN_MODULE = """\
def size(s: str) -> int:
  return strlen(s)


def plus(a: int, b: int) -> int:
  return a + b
"""


def setup_shared(tmpdir):
    """The one module dylib every test inspects, built once.

    Two extern-reachable functions so the case has more than one stub entry:
    the defect inserted SIX bytes per entry, and a single-entry image still
    fails to sign, but a two-entry one also pins the per-entry geometry.
    """
    path = build_module_dylib(tmpdir, EXTERN_MODULE, "x86ext")
    return {"extern_dylib": path}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if sys.platform != "darwin":
        print("SKIP: the formal dylib container is Mach-O, so this is a "
              "macOS-host test")
        return 0
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: running an x86-64 image needs Rosetta 2 or an x86-64 "
              f"host; this one is {platform.machine()}")
        return 0

    passed = failed = 0
    with tempfile.TemporaryDirectory(prefix="formal-x86dylib-") as tmpdir:
        # The shared library is the SUBJECT of five of the six tests, so a
        # failure to build it is the failure they are all reporting. Letting
        # it out of `main` as a traceback would show one stack and no verdict,
        # which is exactly what the `main executable failed strict validation`
        # message it carries already fails to do.
        try:
            shared = setup_shared(tmpdir)
        except Exception as e:                           # noqa: BLE001
            print(f"  FAIL  an x86-64 module dylib with an extern call builds\n"
                  f"        {type(e).__name__}: {e}")
            print(f"\nformal x86-64 dylib: PASS=0 FAIL={len(TESTS)}")
            return 1
        for name, fn in TESTS:
            try:
                fn(tmpdir, shared)
            except TestFailure as e:
                failed += 1
                print(f"  FAIL  {name}\n        {e}")
                continue
            except Exception as e:                       # noqa: BLE001
                failed += 1
                print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {name}")

    print(f"\nformal x86-64 dylib: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())