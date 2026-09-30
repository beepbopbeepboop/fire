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
    """A Mach-O container is what this path has, and `fmt` says so out loud.

    `compile_formal_dylib(fmt="elf")` used to be accepted on a Mach-O host and
    produce a Mach-O anyway — the refusal was conditioned on
    `not fmt_wants_macho(arch)`, which on this host is false for every `fmt`.
    An argument that is accepted and ignored is worse than a hardcoded
    literal: the caller gets an artifact it did not ask for and no
    diagnostic, three steps before dyld reports a container mismatch.

    The container assertion is also the check the `arch` case in
    `test_formal_dylib.py` was missing: it asserted the ARCHITECTURE, which a
    Mach-O labelled `x86_64` passes, and so could not see the wrong container.
    """
    from formal.build import compile_formal_dylib, FormalBuildError
    src = os.path.join(tmpdir, "anyfmt.mojo")
    with open(src, "w") as f:
        f.write("def add1(x):\n  return x + 1\n")
    out = os.path.join(tmpdir, "anyfmt.dylib")
    try:
        compile_formal_dylib([src], output=out, arch="x86_64", fmt="elf",
                             prove=False, check=False)
    except FormalBuildError as e:
        msg = str(e)
        check("elf" in msg,
              f"the refusal does not name the format it cannot honour: {msg!r}")
        check("mach-o" in msg.lower(),
              f"the refusal does not say what the container IS, so a reader "
              f"cannot tell whether the gap is the code or the container: "
              f"{msg!r}")
    else:
        raise TestFailure(
            "compile_formal_dylib(fmt='elf') returned an image: this path "
            "has no ELF dylib emitter, so it is handing the caller a Mach-O "
            "under the name of the format it did not ask for")

    # And the format it CAN honour produces the container it names.
    compile_formal_dylib([src], output=out, arch="x86_64", fmt="macho",
                         prove=False, check=False)
    with open(out, "rb") as f:
        head = f.read(4)
    check(struct.unpack_from("<I", head, 0)[0] == MH_MAGIC_64,
          "fmt='macho' did not produce a 64-bit Mach-O container")


def test_an_elf_image_with_a_module_import_is_refused(tmpdir, shared):
    """`fmt="elf"` plus an import is refused, not emitted as a broken image.

    This was the worst shape the container gap took. `formal/imports.py` builds
    module libraries with `build_macho_dylib`, so on an ELF build they are Mach-O
    — and `formal/elf.py`'s `build_elf` carries ONE `lib_name`
    (`libc.so.6`) and writes exactly one `DT_NEEDED`, with no `.dynamic` entry
    for anything else. The libraries were built, audited (so their symbols
    counted as `provided` and `_audit_bound_symbols` passed) and then put
    nowhere.

    Measured before the fix, on this exact program:

        external_syms    ['ANY_add1_9f63a2', 'printf']
        DT_NEEDED count  1        (libc.so.6)
        .dynstr          ANY_add1_9f63a2, printf, libc.so.6

    so the image built, passed the audit that exists to catch exactly this,
    and would die at load on a symbol its own source imports. The audit passes
    because the library's manifest says the symbol is provided — which is true,
    and irrelevant, since no ELF loader will ever open that Mach-O.

    An ELF image with NO import still builds; that is the assertion that the
    refusal is about the import and not about the format.
    """
    from formal.build import compile_formal, FormalBuildError
    lib = os.path.join(tmpdir, "elfmod.mojo")
    with open(lib, "w") as f:
        f.write("def add1(x):\n  return x + 1\n")
    prog = os.path.join(tmpdir, "elfimp.mojo")
    with open(prog, "w") as f:
        f.write("import elfmod\n\ndef main():\n  return elfmod.add1(41)\n")

    try:
        compile_formal(prog, output=os.path.join(tmpdir, "elfimp.elf"),
                       arch="x86_64", fmt="elf", prove=False, check=False)
    except FormalBuildError as e:
        msg = str(e)
        check("elf" in msg,
              f"the refusal does not name the format: {msg!r}")
        check("mach-o" in msg.lower(),
              f"the refusal does not say the module libraries are Mach-O, so "
              f"a reader cannot tell which half is missing: {msg!r}")
    else:
        raise TestFailure(
            "an ELF image importing a module was emitted: the module's "
            "library is a Mach-O that no ELF loader will open, so the image "
            "carries the symbol with nothing providing it")

    # The format itself is fine — it is the module link line it cannot carry.
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
    ("an ELF image with a module import is refused",
     test_an_elf_image_with_a_module_import_is_refused),
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