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

def run_fire(args, cwd=None):
    return subprocess.run([sys.executable, FIRE] + args, capture_output=True,
                          text=True, timeout=600, cwd=cwd or HERE)


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
    from formal.lean import check_proof
    ok, detail = check_proof(proof, repo_root=root)
    check(ok, f"lean rejected the generated dylib proof: {detail[-400:]}")
    check(call_exported_by_name(out, "triple", 14) == 42,
          "triple(14) did not return 42")


def test_duplicate_function_names_rejected(tmpdir, shared):
    one = os.path.join(tmpdir, "one.mojo")
    two = os.path.join(tmpdir, "two.mojo")
    with open(one, "w") as f:
        f.write("def same(n):\n  return n\n")
    with open(two, "w") as f:
        f.write("def same(n):\n  return n\n")
    out = os.path.join(tmpdir, "dup.dylib")
    result = run_fire(["dylib", "--formal", "--no-prove", "-o", out, one, two])
    check(result.returncode != 0,
          "two modules defining the same function name built successfully")
    check("duplicate" in (result.stderr + result.stdout).lower(),
          f"duplicate function name was not reported clearly: "
          f"{(result.stderr or result.stdout).strip()[-200:]}")


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
    ("duplicate function names rejected", test_duplicate_function_names_rejected),
    ("module with no public functions rejected", test_private_only_module_rejected),
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
