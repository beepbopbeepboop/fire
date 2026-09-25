#!/usr/bin/env python3
"""Regression tests for the formal arm64 *dylib* path
(`fire.py dylib --formal`).

test_formal.py covers the MH_EXECUTE `formalbuild` path; this covers the
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
    check(sorted(info["exports"]) == ["_extra__neg", "_libmath__add1",
                                      "_libmath__mul2"],
          f"unexpected export set {sorted(info['exports'])}")
    check("_libmath___hidden" not in info["exports"],
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
    check(call_exported(path, "libmath__add1", 37) == 38,
          "libmath__add1(37) did not return 38")
    check(call_exported(path, "libmath__mul2", 21) == 42,
          "libmath__mul2(21) did not return 42")
    check(call_exported(path, "extra__neg", 5) == -5,
          "extra__neg(5) did not return -5")
    lib = ctypes.CDLL(path)
    try:
        getattr(lib, "libmath___hidden")
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
    check(call_exported(out, "const2__const2", 37) == 2,
          "const2__const2(37) did not return 2")


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
    check(call_exported(out, "proved__triple", 14) == 42,
          "proved__triple(14) did not return 42")


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


TESTS = [
    ("dylib structure and export trie", test_dylib_structure_and_exports),
    ("exported functions execute", test_exported_functions_execute),
    ("--no-prove skips proof generation", test_no_prove_skips_proof),
    ("default path emits a checked proof", test_default_prove_emits_checked_proof),
    ("duplicate function names rejected", test_duplicate_function_names_rejected),
    ("module with no public functions rejected", test_private_only_module_rejected),
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
