#!/usr/bin/env python3
"""Regression tests for the formal arm64 *dylib* path
(`fire.py dylib --formal`).

test_formal.py covers the MH_EXECUTE `build --formal` path; this covers the
dylib path, which has its own Mach-O emitter, its own export naming scheme
and its own proof entry point, so none of test_formal.py's checks reach it.

What is asserted, in order:

  1. the emitted file is a Mach-O arm64 MH_DYLIB whose load commands and
     segments are internally consistent;
  2. its export trie decodes (with a reader written here, not the writer in
     formal/macho_linker.py, so a bug that corrupts the trie in both the same
     way still fails) to exactly the expected symbol set, with entry
     addresses that fall inside the __text section;
  3. dlopen() accepts the file and every exported function is callable and
     computes the right answer, while a `_`-prefixed function is *not*
     reachable through dlsym;
  4. `--no-prove` writes a dylib and no proof; the default (prove) path
     writes a proof that Lean typechecks.

Invoked via `make check-formal-dylib` or directly:
    python3 test_formal_dylib.py [-v]
"""
import argparse
import ctypes
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")

MH_MAGIC_64 = 0xFEEDFACF
MH_DYLIB = 0x6
CPU_TYPE_ARM64 = 0x0100000C
CPU_TYPE_X86_64 = 0x01000007
LC_SEGMENT_64 = 0x19
LC_ID_DYLIB = 0x0D
LC_UUID = 0x1B
LC_BUILD_VERSION = 0x32
LC_DYLD_INFO_ONLY = 0x80000022
LC_DYLD_EXPORTS_TRIE = 0x80000033
LC_CODE_SIGNATURE = 0x1D

VM_PROT_READ = 0x1
VM_PROT_WRITE = 0x2
VM_PROT_EXECUTE = 0x4

SAMPLE_A = """\
def add1(n):
  return n + 1


def mul2(n):
  return n * 2


def _hidden(n):
  return n
"""

SAMPLE_B = """\
def neg(n):
  return 0 - n
"""


class TestFailure(Exception):
    pass


def check(condition, message):
    if not condition:
        raise TestFailure(message)


# ── an independent Mach-O reader ────────────────────────────────────────────

def read_uleb(data, pos):
    result = 0
    shift = 0
    while True:
        check(pos < len(data), "ULEB128 runs past end of export trie")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        check(shift < 64, "ULEB128 too wide in export trie")


def read_export_trie(trie):
    """Decode an export trie into {symbol: flags, address}, independently of
    formal/macho_linker._export_trie (the writer under test)."""
    exports = {}

    def walk(offset, prefix):
        check(0 <= offset < len(trie),
              f"trie node offset {offset} outside trie of {len(trie)} bytes")
        pos = offset
        terminal_size, pos = read_uleb(trie, pos)
        end = pos + terminal_size
        if terminal_size:
            check(end <= len(trie),
                  f"terminal payload at {offset} runs past end of trie")
            flags, p = read_uleb(trie, pos)
            check(p < end, "flags field overruns terminal payload")
            check(flags == 0,
                  f"only regular (non-reexport, non-absolute) exports are "
                  f"expected, got flags {flags} at node {offset}")
            address, p = read_uleb(trie, p)
            check(p <= end,
                  f"address field at node {offset} overruns terminal payload")
            check(prefix not in exports, f"duplicate export {prefix}")
            exports[prefix] = (flags, address)
        check(end < len(trie),
              f"child-count byte at node {offset} runs past end of trie")
        child_count = trie[end]
        pos = end + 1
        for _ in range(child_count):
            nul = trie.index(b"\0", pos)
            name = trie[pos:nul].decode("utf-8")
            pos = nul + 1
            child, pos = read_uleb(trie, pos)
            walk(child, prefix + name)

    walk(0, "")
    return exports


def parse_macho(data):
    check(len(data) >= 32, "file is too small to be a Mach-O")
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, _ = \
        struct.unpack_from("<8I", data, 0)
    check(magic == MH_MAGIC_64, f"not a 64-bit Mach-O (magic {magic:#x})")
    check(cputype == CPU_TYPE_ARM64,
          f"not arm64 (cputype {cputype:#x})")
    check(filetype == MH_DYLIB, f"not MH_DYLIB (filetype {filetype})")
    check(flags & 0x4, "MH_DYLDLINK is not set, so exports cannot be used")
    check(sizeofcmds <= len(data) - 32,
          "sizeofcmds runs past end of file")

    info = {"flags": flags, "ncmds": ncmds, "commands": {}, "segments": {},
            "exports": None}
    pos = 32
    for i in range(ncmds):
        check(pos + 8 <= 32 + sizeofcmds,
              f"load command {i} starts past sizeofcmds")
        cmd, cmdsize = struct.unpack_from("<II", data, pos)
        check(cmdsize >= 8, f"load command {i} has cmdsize {cmdsize}")
        check(pos + cmdsize <= 32 + sizeofcmds,
              f"load command {i} overruns sizeofcmds")
        if cmd == LC_SEGMENT_64:
            name = data[pos + 8:pos + 24].rstrip(b"\0").decode("ascii")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from(
                "<4Q", data, pos + 24)
            maxprot, initprot, nsects, segflags = struct.unpack_from(
                "<4I", data, pos + 56)
            sections = []
            sect = pos + 72
            for s in range(nsects):
                sname = data[sect:sect + 16].rstrip(b"\0").decode("ascii")
                segname = data[sect + 16:sect + 32].rstrip(b"\0").decode("ascii")
                addr, size = struct.unpack_from("<2Q", data, sect + 32)
                offset, = struct.unpack_from("<I", data, sect + 48)
                sections.append({"sectname": sname, "segname": segname,
                                 "addr": addr, "size": size, "offset": offset})
                sect += 80
            info["segments"][name] = {
                "vmaddr": vmaddr, "vmsize": vmsize, "fileoff": fileoff,
                "filesize": filesize, "maxprot": maxprot, "initprot": initprot,
                "sections": sections,
            }
        elif cmd == LC_ID_DYLIB:
            name_offset, = struct.unpack_from("<I", data, pos + 8)
            check(24 <= name_offset < cmdsize,
                  f"LC_ID_DYLIB name offset {name_offset} outside cmdsize")
            nul = data.index(b"\0", pos + name_offset, pos + cmdsize)
            info["commands"]["LC_ID_DYLIB"] = \
                data[pos + name_offset:nul].decode("utf-8")
        elif cmd == LC_DYLD_EXPORTS_TRIE:
            dataoff, datasize = struct.unpack_from("<II", data, pos + 8)
            check(dataoff + datasize <= len(data),
                  "LC_DYLD_EXPORTS_TRIE data runs past end of file")
            info["exports"] = read_export_trie(data[dataoff:dataoff + datasize])
            info["commands"]["LC_DYLD_EXPORTS_TRIE"] = (dataoff, datasize)
        else:
            info["commands"].setdefault(hex(cmd), (cmdsize, pos))
        pos += cmdsize
    return info


# ── driving the CLI ─────────────────────────────────────────────────────────

def run_fire(args, cwd=None, env=None):
    """`fire.py …`, as a CompletedProcess.

    `env` is merged over this process's environment rather than replacing it,
    so a test can flip one backend switch without having to restate PATH."""
    child = os.environ.copy()
    if env:
        child.update(env)
    return subprocess.run([sys.executable, FIRE] + args, capture_output=True,
                          text=True, timeout=600, cwd=cwd or HERE, env=child)


def build_dylib(tmpdir, sources, out_name, extra_args=()):
    out = os.path.join(tmpdir, out_name)
    args = ["dylib", "--formal", "--no-prove", "-o", out] + list(extra_args)
    result = run_fire(args + sources)
    check(result.returncode == 0,
          f"`fire.py {' '.join(args)}` failed: "
          f"{(result.stderr or result.stdout).strip()[-400:]}")
    check(os.path.isfile(out), f"no dylib written at {out}")
    with open(out, "rb") as f:
        return out, f.read()


def exported_symbol(dylib_path, name):
    """The boundary symbol a dylib advertises for `name`, from its manifest.

    Read from the manifest rather than recomputed with reflect.export_csym, so
    this checks that the manifest and the export TRIE agree about the ABI
    spelling instead of both being handed the same helper's answer.
    """
    import json
    with open(dylib_path + ".manifest.json") as f:
        payload = json.load(f)
    for e in payload["exports"]:
        if e["name"] == name:
            return e["symbol"]
    raise TestFailure(f"{os.path.basename(dylib_path)} exports no {name!r} "
                      f"(has {[e['name'] for e in payload['exports']]})")


def call_exported_by_name(dylib_path, name, *args):
    return call_exported(dylib_path, exported_symbol(dylib_path, name), *args)


def call_exported(path, symbol, *args):
    lib = ctypes.CDLL(path)
    fn = getattr(lib, symbol)
    fn.restype = ctypes.c_int64
    fn.argtypes = [ctypes.c_int64] * len(args)
    return fn(*args)


# ── the tests ───────────────────────────────────────────────────────────────

def test_dylib_structure_and_exports(tmpdir, shared):
    out = shared["dylib"]
    with open(out, "rb") as f:
        data = f.read()
    info = parse_macho(data)

    check("LC_ID_DYLIB" in info["commands"],
          "no LC_ID_DYLIB: dyld has no identity for the image")
    check(info["commands"]["LC_ID_DYLIB"].endswith("libmath.dylib"),
          f"LC_ID_DYLIB names {info['commands']['LC_ID_DYLIB']!r}, "
          f"expected it to end with the output file name")
    for cmd in (LC_UUID, LC_BUILD_VERSION, LC_DYLD_INFO_ONLY):
        check(hex(cmd) in info["commands"],
              f"missing load command {hex(cmd)}")

    check("__TEXT" in info["segments"] and "__LINKEDIT" in info["segments"],
          f"expected __TEXT and __LINKEDIT segments, got "
          f"{sorted(info['segments'])}")
    text = info["segments"]["__TEXT"]
    linkedit = info["segments"]["__LINKEDIT"]
    check(text["initprot"] == VM_PROT_READ | VM_PROT_EXECUTE,
          f"__TEXT initprot {text['initprot']:#x} is not r-x")
    check(text["vmaddr"] % 0x1000 == 0, "__TEXT vmaddr is not page aligned")
    check(linkedit["vmaddr"] == text["vmaddr"] + text["vmsize"],
          "__LINKEDIT does not start where __TEXT ends")
    check(linkedit["vmaddr"] % 0x1000 == 0,
          "__LINKEDIT vmaddr is not page aligned")

    dataoff, datasize = info["commands"]["LC_DYLD_EXPORTS_TRIE"]
    check(linkedit["fileoff"] <= dataoff
          and dataoff + datasize <= linkedit["fileoff"] + linkedit["filesize"],
          "export trie is not inside the __LINKEDIT segment's file range")

    check(info["exports"] is not None, "no export trie in the emitted dylib")
    # ABI.md's spelling: a dylib export is module-qualified with the overload
    # suffix, so two modules' same-named functions cannot collide inside one
    # library. Learn the exact names from the manifest rather than hardcoding
    # a hash — the point is the SHAPE (qualified + suffixed), and the trie must
    # carry the same string the manifest does.
    import json as _json
    with open(out + ".manifest.json") as _f:
        _exports = _json.load(_f)["exports"]
    _by_name = {e["name"]: e["symbol"] for e in _exports}
    check(sorted(_by_name) == ["add1", "mul2", "neg"],
          f"manifest exports {sorted(_by_name)}, expected add1/mul2/neg")
    # TWO conventions, deliberately: the manifest records the C identifier
    # (that is what an importer's bind stream carries — dyld prepends the
    # underscore itself), while the export trie records the Mach-O name, which
    # is that identifier with a leading underscore. Asserting the relationship
    # rather than string equality is what pins the pair together: writing the
    # trie with the bare C name exports a symbol nothing can bind, and the
    # program dies in dyld with "Symbol not found" for a function that is
    # right there in the library.
    for _n, _sym in _by_name.items():
        check(not _sym.startswith("_"),
              f"the manifest's symbol {_sym!r} should be the C identifier")
        check("_" + _sym in info["exports"],
              f"manifest says {_n} -> {_sym!r}, so the trie should carry "
              f"{'_' + _sym!r}, but it carries {sorted(info['exports'])}")
    check(not any("_hidden" in e for e in info["exports"]),
          "a `_`-prefixed function was exported")

    sections = {(s["segname"], s["sectname"]): s for s in text["sections"]}
    check(("__TEXT", "__text") in sections,
          f"no __text section in __TEXT (have {sorted(sections)})")
    code = sections[("__TEXT", "__text")]
    check(code["offset"] + code["size"] <= linkedit["fileoff"],
          "the __text section's file range overlaps __LINKEDIT")
    # Export-trie addresses are image-relative (the segment's own vmaddr is
    # the base), not absolute: the image is rebased wherever dyld loads it.
    image_base = text["vmaddr"]
    for symbol, (_, address) in info["exports"].items():
        check(code["addr"] - image_base <= address
              < code["addr"] - image_base + code["size"],
              f"export {symbol} address {address:#x} is outside __text "
              f"[{code['addr'] - image_base:#x}, "
              f"{code['addr'] - image_base + code['size']:#x})")
        file_off = code["offset"] + (address - (code["addr"] - image_base))
        check(file_off < len(data),
              f"export {symbol} points past end of file")


def test_exported_functions_execute(tmpdir, shared):
    path = shared["dylib"]
    check(call_exported_by_name(path, "add1", 37) == 38,
          "add1(37) did not return 38")
    check(call_exported_by_name(path, "mul2", 21) == 42,
          "mul2(21) did not return 42")
    check(call_exported_by_name(path, "neg", 5) == -5,
          "neg(5) did not return -5")
    lib = ctypes.CDLL(path)
    try:
        getattr(lib, "_hidden")
    except AttributeError:
        return
    raise TestFailure("dlsym resolved the private _hidden function")


def test_no_prove_skips_proof(tmpdir, shared):
    src = os.path.join(tmpdir, "const2.mojo")
    with open(src, "w") as f:
        f.write("def const2(n):\n  return 2\n")
    out, _ = build_dylib(tmpdir, [src], "const2.dylib")
    proof = os.path.splitext(out)[0] + "_proof.lean"
    check(not os.path.exists(proof),
          f"--no-prove still wrote {proof}")
    # ... and the dylib it did write is still loadable and correct.
    check(call_exported_by_name(out, "const2", 37) == 2,
          "const2(37) did not return 2")


def test_default_prove_emits_checked_proof(tmpdir, shared):
    from formal.lean import find_lean
    root = HERE
    if not find_lean(root):
        print("    SKIP: no lean found (proof part of the dylib path)")
        return
    src = os.path.join(tmpdir, "proved.mojo")
    with open(src, "w") as f:
        f.write("def triple(n):\n  return n * 3\n")
    out = os.path.join(tmpdir, "proved.dylib")
    result = run_fire(["dylib", "--formal", "-o", out, src])
    check(result.returncode == 0,
          "default (prove) dylib build failed: "
          f"{(result.stderr or result.stdout).strip()[-400:]}")
    proof = os.path.splitext(out)[0] + "_proof.lean"
    check(os.path.isfile(proof), f"prove path did not write {proof}")
    with open(proof) as f:
        text = f.read()
    check("DylibImage" in text and "dylib_export_0_triple" in text,
          "generated dylib proof does not mention the exported function")
    check("sorry" not in text and "admit" not in text,
          "generated dylib proof contains sorry/admit")
    # The check above reads the GENERATED file, and the three holes that decide
    # this proof's verdict are in lib/, not in it:
    #
    #   lib/ProofLib.lean  in_image_stub              := by sorry
    #   lib/ProofLib.lean  semantics_stub             := by sorry
    #   lib/Refine.lean    dylib_export_contract_stub := by sorry
    #
    # Lean emits no warning for a hole in a module consumed from a pre-built
    # .olean, so the grep above is green today and would stay green. The census
    # asks Lean instead, and reports them by name. The text check stays: it
    # still catches a hole in the generated file, which this one cannot see.
    #
    # Pinned as a subset, not asserted empty, and the asymmetry is deliberate.
    # These three are pre-existing and lib/ is out of scope for this round, so
    # demanding zero would be a permanent red for something nobody here may fix
    # -- the exact hole in coverage a permanently-red check becomes. Demanding a
    # SUBSET fails in the direction that matters: a FOURTH hole appearing is a
    # regression somebody has to know about, while one of the three closing is
    # progress and stays green. The count is re-measured either way, so the
    # figure is read on every run rather than merely known.
    KNOWN_LIB_HOLES = {"in_image_stub", "semantics_stub",
                       "dylib_export_contract_stub"}
    try:
        from formal.lean import library_census, find_lean
        lib = library_census(find_lean(HERE), os.path.join(HERE, "lib"))
        holes = {n for _c, names in lib.values() for n in names}
        new_holes = holes - KNOWN_LIB_HOLES
        check(not new_holes,
              f"the dylib proof rests on holes nobody has recorded: "
              f"{sorted(new_holes)} (and {sorted(holes & KNOWN_LIB_HOLES)} "
              f"are the pre-existing ones, being closed separately)")
        print(f"    note: {len(holes & KNOWN_LIB_HOLES)} of "
              f"{len(KNOWN_LIB_HOLES)} known lib/ hole(s) still open — "
              f"the grep above cannot see these")
    except ImportError:
        pass
    from formal.lean import check_proof
    ok, detail = check_proof(proof, repo_root=root)
    check(ok, f"lean rejected the generated dylib proof: {detail[-400:]}")
    check(call_exported_by_name(out, "triple", 14) == 42,
          "triple(14) did not return 42")


def test_overloads_do_not_collide(tmpdir, shared):
    """A repeated function name is an overload, and it must BUILD.

    It used to be refused outright, with a message that named the same file
    on both sides — `duplicate function 'same' in one.mojo and one.mojo` —
    because the check treated a second definition as a cross-module
    collision. doc/ABI.md excludes an overloaded name from the export set
    precisely because no single symbol denotes it, so there is nothing at the
    boundary that needs disambiguating; refusing only threw away modules that
    are fine. `std/algorithm/backend/tile.mojo` defines `tile` three times.

    What still has to hold, and is the part worth a test:

      * BOTH definitions are compiled. Silently keeping the first and
        dropping the second would lose code with no diagnostic at all.
      * The export table carries the name ONCE. Two trie entries sharing one
        symbol is not a de-duplication nuisance, it is a corrupt table that
        dyld resolves to whichever it finds first.
    """
    one = os.path.join(tmpdir, "ovl.mojo")
    with open(one, "w") as f:
        f.write("def same(n):\n  return n + 1\n"
                "\n"
                "def same(n, m):\n  return n + m\n"
                "\n"
                "def other(n):\n  return n * 2\n")
    out = os.path.join(tmpdir, "ovl.dylib")
    result = run_fire(["dylib", "--formal", "--no-prove", "-o", out, one])
    check(result.returncode == 0,
          f"a module with overloads failed to build: "
          f"{(result.stderr or result.stdout).strip()[-300:]}")
    check(os.path.isfile(out), "no dylib written for a module with overloads")

    with open(out + ".manifest.json") as f:
        exports = json.load(f)["exports"]
    names = [e["name"] for e in exports]
    check(len(names) == len(set(names)),
          f"the export table repeats a name: {names} — one trie entry per "
          f"symbol is required or dyld picks arbitrarily")
    check("other" in names,
          f"an unrelated function was lost to the overload: {names}")

    # The trie must agree, and must not carry a symbol twice either.
    with open(out, "rb") as f:
        info = parse_macho(f.read())
    for e in exports:
        check("_" + e["symbol"] in info["exports"],
              f"the trie is missing the manifest's export {e['symbol']}")


def test_same_name_in_two_modules(tmpdir, shared):
    """Two modules contributing the same name is the case the old check was
    reaching for, and it is also fine: the first definition keeps the name and
    the rest are renamed apart internally, so the codegen's per-name registry
    cannot let one displace the other. The export table still names it once."""
    one = os.path.join(tmpdir, "m_one.mojo")
    two = os.path.join(tmpdir, "m_two.mojo")
    with open(one, "w") as f:
        f.write("def shared(n):\n  return n + 1\n")
    with open(two, "w") as f:
        f.write("def shared(n):\n  return n * 3\n"
                "\n"
                "def only_two(n):\n  return n - 1\n")
    out = os.path.join(tmpdir, "shared.dylib")
    result = run_fire(["dylib", "--formal", "--no-prove", "-o", out, one, two])
    check(result.returncode == 0,
          f"two modules sharing a function name failed to build: "
          f"{(result.stderr or result.stdout).strip()[-300:]}")
    with open(out + ".manifest.json") as f:
        exports = json.load(f)["exports"]
    names = sorted(e["name"] for e in exports)
    check("only_two" in names,
          f"the second module's own function was lost: {names}")
    check(len(names) == len(set(names)),
          f"the export table repeats a name: {names}")


def test_private_only_module_rejected(tmpdir, shared):
    src = os.path.join(tmpdir, "private.mojo")
    with open(src, "w") as f:
        f.write("def _only(n):\n  return n\n")
    out = os.path.join(tmpdir, "private.dylib")
    result = run_fire(["dylib", "--formal", "--no-prove", "-o", out, src])
    check(result.returncode != 0,
          "a dylib with no public functions was built successfully")
    check("public" in (result.stderr + result.stdout),
          f"missing-export failure was not explained: "
          f"{(result.stderr or result.stdout).strip()[-200:]}")


# The four shapes a module can have no boundary symbol in, and the one fact
# that tells them apart. A module that is useful source and useless as a
# LIBRARY takes its importer down with it, so the refusal has to be right
# about which of the four it hit — and the four need completely different
# work, so a message that names the wrong one sends the reader after the wrong
# thing. (`std/sys/_io.mojo`, `std/stat/stat.mojo`,
# `std/reflection/function.mojo` and `std/utils/_select.mojo` are the real
# stdlib instances, and they are four different answers.)
NO_API_SHAPES = [
    ("constants only, no function and no type",
     "comptime stdin = 0\ncomptime stdout = 1\n", "no function and no type"),
    ("every public function is a generic template",
     "def pick[T: Copyable](a: T, b: T, c: Bool) -> T:\n  return a\n",
     "GENERIC template"),
    ("only a generic struct template",
     "struct Box[T: Copyable]:\n  var v: T\n", "generic struct template"),
    ("only struct types, no free function",
     "struct Pair:\n  var a: Int\n  var b: Int\n", "no free function"),
    ("every declaration is private",
     "def _helper(n: Int) -> Int:\n  return n\n", "private"),
]


def test_refusal_names_the_real_reason(tmpdir, shared):
    """Each no-API shape is refused, and the message names THAT shape.

    Before this, all five of these produced the same sentence — "a struct-only
    module has no free-function API, and this backend compiles no struct
    methods" — which is false for four of them: a generic-only module is not
    struct-only, a constants-only module has no struct either, and a
    constants-only module is not a gap in anything. A refusal that is wrong
    about the file is worse than a bare error, because it sends the reader
    looking for a struct that is not there.
    """
    for label, body, expected in NO_API_SHAPES:
        src = os.path.join(tmpdir, "noapi.mojo")
        with open(src, "w") as f:
            f.write(body)
        out = os.path.join(tmpdir, "noapi.dylib")
        result = run_fire(["dylib", "--formal", "--no-prove", "-o", out, src])
        text = (result.stderr + result.stdout).strip()
        check(result.returncode != 0,
              f"a module with {label} was built as a dylib successfully")
        check(expected in text,
              f"a module with {label} was refused without saying so: {text}")
        check("struct-only module has no free-function API" not in text,
              f"a module with {label} was refused with the shape-agnostic "
              f"wording, which is false for it: {text}")


def test_dylib_is_built_for_the_requested_arch(tmpdir, shared):
    """`compile_formal_dylib` honours `arch` for BOTH the code and the header.

    A dylib is a target-specific image, not a host artifact, and this call
    used to hardwire arm64 for both: `_make_codegen` was bypassed for
    `ARM64Codegen(...)` and `build_macho_dylib` was given no `arch`, so an
    x86-64 program got an arm64 library on its link line — one that builds,
    links, and passes every check the toolchain makes statically, and then
    dies in dyld with "mach-o file, but is an incompatible architecture"
    before `main` runs. Asserted here on the Mach-O header's own cputype,
    read from the file rather than taken from the return value.
    """
    sys.path.insert(0, HERE)
    from formal.build import compile_formal_dylib
    src = os.path.join(tmpdir, "archsrc.mojo")
    with open(src, "w") as f:
        f.write("def triple(n):\n  return n * 3\n")
    seen = {}
    for arch, cputype in (("arm64", CPU_TYPE_ARM64),
                           ("x86_64", CPU_TYPE_X86_64)):
        out = os.path.join(tmpdir, f"arch_{arch}.dylib")
        compile_formal_dylib([src], output=out, prove=False, check=False,
                             arch=arch)
        with open(out, "rb") as f:
            head = f.read(16)
        check(struct.unpack_from("<I", head, 0)[0] == MH_MAGIC_64,
              f"{out} is not a 64-bit Mach-O")
        check(struct.unpack_from("<I", head, 4)[0] == cputype,
              f"{out} was built for cputype "
              f"{struct.unpack_from('<I', head, 4)[0]}, expected {cputype} "
              f"for arch={arch} — the architecture argument is not reaching "
              f"the emitter")
        seen[arch] = out
    # And the two must be different files with different content: the same
    # bytes under two names is the overwrite this is guarding against.
    with open(seen["arm64"], "rb") as f:
        a = f.read()
    with open(seen["x86_64"], "rb") as f:
        b = f.read()
    check(a != b, "the two architectures produced byte-identical dylibs")


def test_executable_links_a_dylib(tmpdir, shared):
    """An executable built with --link-dylib calls into the library and RUNS.

    This is the whole point of the mechanism: without it a cross-module call
    lowers to a BL against a symbol nothing defines, so the image builds and
    then dies in dyld at launch. The subtle part it pins down is that the
    entry offset has to agree across three places — the code the codegen
    emitted for, the stub addresses the call sites branch to, and LC_MAIN.
    Each linked dylib adds a load command and so moves that offset; when they
    disagreed the call branched into the caller's own epilogue padding
    (a SIGBUS at launch, with a perfectly well-formed image).
    """
    lib_a = os.path.join(tmpdir, "link_a.mojo")
    with open(lib_a, "w") as f:
        f.write("def triple(x):\n  return x * 3\n"
                "def square(x):\n  return x * x\n")
    lib_b = os.path.join(tmpdir, "link_b.mojo")
    with open(lib_b, "w") as f:
        f.write("def quad(x):\n  return x * x * x\n")
    dylibs = []
    for src, name in ((lib_a, "linklib_a"), (lib_b, "linklib_b")):
        out = os.path.join(tmpdir, name + ".dylib")
        rc = run_fire(["dylib", "--formal", "--no-prove", "-o", out,
                       src]).returncode
        check(rc == 0, f"dylib build failed: {rc}")
        check(os.path.exists(out + ".manifest.json"),
              "the dylib wrote no export manifest, so nothing can link it")
        dylibs.append(out)

    prog = os.path.join(tmpdir, "link_prog.mojo")
    with open(prog, "w") as f:
        f.write("def main():\n  return triple(2) + quad(3) + square(4) + 39\n")
    exe = os.path.join(tmpdir, "link_prog.aout")
    argv = ["build", "--formal", "--no-prove", "-o", exe]
    for d in dylibs:
        argv += ["--link-dylib", d]
    argv.append(prog)
    rc = run_fire(argv).returncode
    check(rc == 0, f"executable build failed: {rc}")

    # Both libraries must be real dependencies, not just recorded names.
    otool = subprocess.run(["/usr/bin/otool", "-L", exe],
                          capture_output=True, text=True)
    for d in dylibs:
        check(os.path.abspath(d) in otool.stdout,
              f"{os.path.basename(d)} is not an LC_LOAD_DYLIB dependency:\n"
              f"{otool.stdout}")

    # And it must actually run: 6 + 27 + 16 + 39 = 88.
    rc = subprocess.run([exe]).returncode
    check(rc == 88, f"linked program returned {rc}, expected 88")


def test_dylib_calls_out_to_libSystem(tmpdir, shared):
    """A library that calls printf itself builds, loads, and RUNS.

    This is the shape a formal stdlib dylib needs: the stdlib calls out to
    libSystem everywhere, so a dylib that refuses externs can never hold it.
    Two things this pins down that the executable path does not exercise:

      * the dylib's own load-command list grows (__DATA_CONST plus an
        LC_LOAD_DYLIB), which moves its code, so the base the code is emitted
        for and the stub addresses its call sites branch to have to be
        derived for the same decision;
      * a MH_DYLIB has no __PAGEZERO, so its __DATA_CONST is segment ordinal 1
        while the executable's is 2 — with the executable's value the bind
        stream points at __LINKEDIT and dyld faults inside applyFixups.
    """
    lib = os.path.join(tmpdir, "shouty.mojo")
    with open(lib, "w") as f:
        f.write('def shout(x):\n  printf("from the dylib\\n")\n  return x + 1\n')
    out = os.path.join(tmpdir, "libshouty.dylib")
    rc = run_fire(["dylib", "--formal", "--no-prove", "-o", out,
                   lib]).returncode
    check(rc == 0, f"dylib with an extern failed to build: {rc}")

    # The library must declare libSystem itself, or its bind stream's
    # ordinal 1 names nothing.
    otool = subprocess.run(["/usr/bin/otool", "-L", out],
                          capture_output=True, text=True)
    check("libSystem" in otool.stdout,
          f"the library declares no libSystem dependency:\n{otool.stdout}")

    # And it must run: printf from inside the library, then x + 1.
    prog = os.path.join(tmpdir, "shouty_prog.mojo")
    with open(prog, "w") as f:
        f.write("def main():\n  return shout(41)\n")
    exe = os.path.join(tmpdir, "shouty_prog.aout")
    rc = run_fire(["build", "--formal", "--no-prove", "-o", exe,
                   "--link-dylib", out, prog]).returncode
    check(rc == 0, f"executable build failed: {rc}")
    r = subprocess.run([exe], capture_output=True, text=True)
    check("from the dylib" in r.stdout,
          f"the library's printf did not run; stdout={r.stdout!r}")
    check(r.returncode == 42, f"returned {r.returncode}, expected 42")


TESTS = [
    ("dylib structure and export trie", test_dylib_structure_and_exports),
    ("exported functions execute", test_exported_functions_execute),
    ("--no-prove skips proof generation", test_no_prove_skips_proof),
    ("default path emits a checked proof", test_default_prove_emits_checked_proof),
    ("overloads build and export once", test_overloads_do_not_collide),
    ("same name in two modules", test_same_name_in_two_modules),
    ("module with no public functions rejected", test_private_only_module_rejected),
    ("the refusal names the real reason", test_refusal_names_the_real_reason),
    ("a dylib is built for the requested arch",
     test_dylib_is_built_for_the_requested_arch),
    ("executable links a dylib and runs", test_executable_links_a_dylib),
    ("dylib calls out to libSystem", test_dylib_calls_out_to_libSystem),
]


def setup_shared(tmpdir):
    """The one multi-module dylib several tests inspect, built once: dlopen()ing
    it needs the file (and its directory) to still exist, so it cannot be
    rebuilt inside a per-test TemporaryDirectory that is deleted afterwards."""
    src_a = os.path.join(tmpdir, "libmath.mojo")
    src_b = os.path.join(tmpdir, "extra.mojo")
    with open(src_a, "w") as f:
        f.write(SAMPLE_A)
    with open(src_b, "w") as f:
        f.write(SAMPLE_B)
    out, _ = build_dylib(tmpdir, [src_a, src_b], "libmath.dylib")
    return {"dylib": out}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal dylib output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        shared = setup_shared(tmpdir)
        for name, fn in TESTS:
            try:
                fn(tmpdir, shared)
            except TestFailure as e:
                failed += 1
                print(f"  FAIL  {name}\n        {e}")
                continue
            except Exception as e:  # unexpected: report, do not mask
                failed += 1
                print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {name}")

    print(f"\nformal dylib: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
