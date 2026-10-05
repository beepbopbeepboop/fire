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
  4. a symbol that PREFIXES another symbol is still bindable — the case the
     trie's layout decides and the only reading that can see it is dyld's
     (`dlsym`), because a flat trie and a radix trie both decode here;
  5. `--no-prove` writes a dylib and no proof; the default (prove) path
     writes a proof that Lean typechecks.

Invoked via `make check-formal-dylib` or directly:
    python3 test_formal_dylib.py [-v]
"""
import argparse
import ctypes
import itertools
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


REC = "@@"
RUN_TIMEOUT = 300


class Failure(Exception):
    """The exception `build_and_run` raises.

    Distinct from `TestFailure` below on purpose: `TestFailure` is a FAILED
    ASSERTION about this file's subject and the suite counts it, while `Failure`
    is this file refusing to produce an answer at all — a build that failed, an
    image that crashed, a record count that does not line up. A caller of
    `build_and_run` converts it into whatever its own harness reports, and
    conflating the two would make a build failure look like a wrong answer.
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


def manifest_exports(dylib_path):
    """`{name: export entry}`, straight out of the dylib's manifest."""
    with open(dylib_path + ".manifest.json") as f:
        return {e["name"]: e for e in json.load(f)["exports"]}


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


BACKENDS = ("arm64", "x86_64")


def host_machine():
    """`True` when this host can BUILD a formal image at all.

    arm64 is the only architecture `fire.py build --formal` emits by default and
    the only one every other formal suite in the tree assumes, so a host that is
    neither arm64 nor aarch64 skips those suites rather than failing them. This
    is the shared spelling of that rule, because three hostmod test files now ask
    it and three copies of it would be three places to keep true.
    """
    return platform.machine() in ("arm64", "aarch64")


def rosetta():
    """`True` when this host can also RUN an x86-64 image.

    Rosetta 2 exists on Apple Silicon and nowhere else, so the x86-64 half of a
    hostmod suite is skipped on any other host — with the reason printed, which
    is the half that matters, because a silent skip reads as a pass. The reason
    is a string here rather than a bare `False` so no caller can skip without
    saying why.
    """
    if host_machine():
        return True, ""
    return False, (f"host is {platform.machine()}; an x86-64 image needs "
                   f"Rosetta 2, which only Apple Silicon has")


def build_and_run(src, name, tmpdir, compare, backends=None, cross=None,
                  env=None, cwd=None):
    """Build `src` on every backend, run it, and hand `compare(arch, records)` each.

    The two-architecture machinery for a `formal/hostmods` suite, in ONE place,
    because the second copy of it is a second thing to keep true:

      * `compare(arch, records)` is called once per architecture and raises on a
        disagreement, so no group can accidentally run on one architecture — and
        it is told WHICH one, so a message can name it.
      * the records of the two architectures are then compared with EACH OTHER,
        so a module that lowers differently on the two is caught even when both
        answers happen to agree with CPython on the corpus at hand. `cross` is an
        optional filter for that comparison, for the one case where two
        architectures cannot be compared (a float-valued `printf` operand, where
        x86-64 reads `XMM0`; see
        `“FORMAL_x86_64_a_float_printf_operand_reads_XMM0: `printf("%f"”`).

    Records are the `@@`-separated fields of the image's stdout. `@@` is the
    record terminator every hostmod test in this tree uses, and it is here for a
    reason that does not expire: a separator this suite can read back WITHOUT
    asking whether the image decoded the literal, two bytes that a real newline
    cannot collide with. A suite that went on to depend on the decoder's answer
    would be a suite whose reader has to know it.

    This is the comment the other hostmod suites in the family follow, so it is
    the one whose wording has to be right for a reader who arrives in one of
    them.

    `cwd` is where the image RUNS, and it defaults to `tmpdir` because a hostmod
    suite that puts a program anywhere but its own scratch directory is asking
    for a test that depends on the repository's contents. It is a parameter
    because `test_formal_shutil.py` runs inside the tree it is mutating, and
    that tree is per-group: `rmtree` and `move` destroy theirs, so the second
    architecture cannot run in the directory the first one emptied.

    Returns the first architecture's records.
    """
    if backends is None:
        backends = BACKENDS
    got = {}
    for arch in backends:
        path = os.path.join(tmpdir, name + ".mojo")
        with open(path, "w") as f:
            f.write(src)
        out = os.path.join(tmpdir, name + "." + arch)
        r = run_fire(["build", "--formal", "--no-prove", "--backend=" + arch,
                      "-o", out, path], env=env)
        if r.returncode != 0 or not os.path.isfile(out):
            raise Failure(f"[{arch}] build failed: "
                          f"{(r.stderr or r.stdout or '').strip()[-400:]}")
        argv = ["arch", "-x86_64", out] if arch == "x86_64" else [out]
        p = subprocess.run(argv, capture_output=True, timeout=RUN_TIMEOUT,
                           cwd=cwd or tmpdir)
        if p.returncode != 0:
            raise Failure(
                f"[{arch}] image exited {p.returncode}: "
                f"{p.stderr.decode('utf-8', 'replace').strip()[-200:]}")
        recs = [rec for rec in p.stdout.decode("latin-1").split(REC) if rec]
        compare(arch, recs)
        got[arch] = recs
    if len(got) == 2:
        a, b = backends
        keep = cross or (lambda recs: recs)
        ra, rb = keep(got[a]), keep(got[b])
        if len(ra) != len(rb):
            raise Failure(f"{a} reported {len(ra)} records and {b} reported "
                          f"{len(rb)}, so the two architectures are not even "
                          f"running the same program")
        diff = [(x, y) for x, y in zip(ra, rb) if x != y]
        if diff:
            raise Failure(
                f"{len(diff)} of {len(ra)} records differ between {a} and {b}. "
                f"A host module is pure work over values the model already "
                f"represents, so a disagreement here is a two-architecture "
                f"lowering bug with nothing in the module to blame. First "
                f"three:\n      " +
                "\n      ".join(f"{a} {x!r}, {b} {y!r}" for x, y in diff[:3]))
    return got[backends[0]]


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
    check(linkedit["vmaddr"] % 0x1000 == 0,
          "__LINKEDIT vmaddr is not page aligned")
    # No two segments may OVERLAP, in memory or in the file, and the link edit
    # must sit above the code.
    #
    # This replaced "⟨LINKEDIT starts where __TEXT ends⟩", which was not an
    # invariant but a coincidence: it held for as long as an image had no data
    # segment, and it stopped holding the moment every image got one
    # (`formal/model.py`'s `STACK_FLOOR_BUDGET_BYTES`). The data segment is
    # mapped at a FIXED address well above the image's slide — `__DATA` is
    # `GLOBALS_VM`, not "the next page" — so the three segments are neither
    # contiguous nor in file order, and a contiguity assertion would be
    # asserting the coincidence again on the next change. What the loader
    # actually requires is disjoint ranges, and that is what is checked: two
    # segments sharing an address is memory corruption, which is the failure
    # this whole file's segment checks exist to catch.
    segs = info["segments"]
    for a, b in itertools.combinations(sorted(segs), 2):
        sa, sb = segs[a], segs[b]
        vm_overlap = (sa["vmaddr"] < sb["vmaddr"] + sb["vmsize"]
                      and sb["vmaddr"] < sa["vmaddr"] + sa["vmsize"])
        check(not vm_overlap,
              f"segments {a} [{sa['vmaddr']:#x}, "
              f"{sa['vmaddr'] + sa['vmsize']:#x}) and {b} "
              f"[{sb['vmaddr']:#x}, {sb['vmaddr'] + sb['vmsize']:#x}) overlap "
              f"in memory, so the loader maps them over each other")
        f_overlap = (sa["fileoff"] < sb["fileoff"] + sb["filesize"]
                     and sb["fileoff"] < sa["fileoff"] + sa["filesize"])
        check(not f_overlap,
              f"segments {a} and {b} overlap in the FILE "
              f"({a} [{sa['fileoff']}, {sa['fileoff'] + sa['filesize']}) vs "
              f"{b} [{sb['fileoff']}, {sb['fileoff'] + sb['filesize']})")
    check(linkedit["vmaddr"] >= text["vmaddr"] + text["vmsize"],
          f"__LINKEDIT at {linkedit['vmaddr']:#x} is not above __TEXT, which "
          f"ends at {text['vmaddr'] + text['vmsize']:#x}")

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


def test_a_symbol_that_prefixes_another_is_still_exported(tmpdir, shared):
    """`_m_version` and `_m_version_info_major` are BOTH bindable.

    The export trie was written FLAT — every symbol one whole edge off the
    root — which is wrong as soon as one symbol is a prefix of another, and
    wrong in the one way nothing here could see. dyld narrows a lookup by
    walking edges; a flat trie makes the two symbols SIBLINGS, dyld matches
    the short one against the long one's leading bytes, descends into a node
    with no children, and does not go back to try the next edge. So the long
    symbol was in the file, in the manifest, and in this file's own trie
    reader, and dyld reported "Symbol not found" for it from a program that
    had built and passed every static check.

    Three independent readings, because the one that was wrong is the one
    everybody agreed on:

      * this file's trie reader, which walks the format's own layout;
      * `dlsym`, which is dyld — the only reader here that IMPLEMENTS the
        format rather than sharing the writer's assumption;
      * a real program that links the library and calls both, which is the
        only one that cannot be argued with.

    A shared prefix is now a shared trie node, so the two names are siblings
    one level down and neither is reachable only by luck.
    """
    src = os.path.join(tmpdir, "prefixes.mojo")
    with open(src, "w") as f:
        f.write("def version():\n  return 11\n\n"
                "def version_info_major():\n  return 22\n\n"
                "def unrelated():\n  return 33\n")
    out, data = build_dylib(tmpdir, [src], "prefixes.dylib")
    info = parse_macho(data)
    got = sorted(n.lstrip("_") for n in (info["exports"] or {}))
    check(got == ["prefixes_unrelated", "prefixes_version",
                  "prefixes_version_info_major"],
          f"the trie carries {got}, expected all three symbols")
    # dlsym is the reading that failed: with a flat trie the longer symbol was
    # in the file and unbindable, and this is the assertion that says so.
    check(call_exported_by_name(out, "version", 0) == 11,
          "the short symbol does not bind")
    check(call_exported_by_name(out, "version_info_major", 0) == 22,
          "the symbol that PREFIXES nothing else but follows one does not "
          "bind: the export trie is flat, and a flat trie cannot hold a "
          "symbol that extends another (see formal/macho_linker.py's "
          "_export_trie)")
    # …and the two must not share an address, which is what a trie that put
    # them at one node would produce.
    exports = info["exports"] or {}
    addrs = {n: v[1] for n, v in exports.items()}
    check(len(set(addrs.values())) == len(addrs),
          f"two symbols share an export address: {addrs}")


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
    # The generated file admits nothing, and that is the point.
    # [3]'s IR-3-to-2-dylib-stubs.md replaced three `sorry`s-over-false-claims
    # with two NAMED obligations -- `_semantics_total` (the run terminates for
    # every argument) and `_spec` (the export matches its specification) -- so
    # that the caller's theorem is proved and sorry-free.  Grepping for "no
    # sorry anywhere" would therefore be red for the right reason, and silencing
    # it would be wrong.
    #
    # What changed on 2026-10-03 is that an export whose spec `_dylib_spec_lean`
    # CAN derive no longer emits a `_spec` obligation at all: its contract is
    # emitted PROVED (`hreg`, `agrees_of_body`) and `bv_decide` checks the
    # machine against the source.  So the set is pinned per export as
    # "terminates, and EITHER a proved contract OR a named `_spec`
    # obligation" -- never equality against a fixed set, which cannot tell
    # "no obligation because it is PROVED" from "no obligation because the
    # emitter forgot", and treats those two as the same observation.  That
    # distinction is `FORMAL_dylib_export_loops_and_frame_bounds.md` §`OPUS-2`, and
    # the asymmetry is now checked in the direction that matters.
    import re as _re
    idents = set(_re.findall(r"^def (dylib_export_\w+) : DylibExport :=", text, _re.M))
    check(idents, "the generated proof names no export at all")
    for ident in sorted(idents):
        check(_re.search(rf"theorem {ident}_semantics_total\b", text),
              f"{ident} has no `_semantics_total` theorem: every export gets "
              f"one, proved or named")
        proved = (f"Contracts.agrees_of_body dylib_image {ident} bodyI" in text)
        named = bool(_re.search(rf"theorem {ident}_spec\b", text))
        # The emitter's THREE states for an export's contract, and the
        # difference between the last two is the whole point: "no claim, and it
        # says so" is honest, and "no claim, and it does not" is the emitter
        # having forgotten the export.  `NO SPEC DERIVED for <ident>` is the
        # marker the first one carries.
        declined = f"NO SPEC DERIVED for {ident}" in text
        check(proved != named,
              f"{ident} has "
              + ("both a proved contract and a named `_spec` obligation"
                 if proved and named else
                 "neither a proved contract nor a named `_spec` obligation, and "
                 "no `NO SPEC DERIVED` marker either -- the emitter dropped the "
                 "export's claim about its own result without saying why"))
        check(proved or named or declined,
              f"{ident} has no contract claim and no reason for having none")
    # NO obligation may be stated against a GUESSED spec.  This is the shape
    # `formal/admitted.py`'s `OPUS-9` rule is about and the one this file
    # emitted until 2026-10-03: `export_result_spec … (fun n => n) := by sorry`,
    # i.e. a `sorry` over the claim that EVERY dylib export computes the
    # identity.  That is false for every export in the tree except the ones
    # that do -- `export_result dylib_image triple 7 = 21`, `add1 7 = 8` -- and
    # the generated file states it without checking it, because a `Block` for a
    # body with a branch is never emitted and so Lean never sees the claim.
    check("(fun n => n) := by\n  sorry" not in text
          and "(fun n => n)) := by\n  sorry" not in text,
          "the generated proof states an obligation against a GUESSED identity "
          "spec -- a `sorry` over a false claim, which is worse than no "
          "obligation at all")
    # ... and the proved contract must be sorry-free, in its own namespace.
    # A `sorry` anywhere in the contract namespace is exactly the shape
    # `formal/admitted.py` counts, and a per-export grep is the only thing that
    # can see it: the census below reports a FILE total, which cannot say which
    # export admitted one.
    for ident in sorted(idents):
        if f"namespace {ident}_contract" not in text:
            continue
        ns = _re.search(rf"namespace {ident}_contract\n(.*?)\nend {ident}_contract",
                        text, _re.S)
        check(ns is not None,
              f"{ident}'s contract namespace is missing from the generated file")
        check("sorry" not in ns.group(1),
              f"{ident}'s proved contract contains a `sorry`")
    # `triple` is acyclic and call-free, so its termination is PROVED by the
    # CFG walk rather than left as the obligation above.  Pinned so a
    # regression to the `sorry` fallback is a failure, not a quiet extra hole.
    check(":=\n  DylibExport.total_of_halts dylib_image dylib_export_0_triple "
          "dylib_export_0_triple_halts" in text,
          "triple's termination is no longer proved by the CFG walk")
    # The caller's theorem must stay PROVED and sorry-free: it is the whole
    # reason the obligations are named rather than the contract being admitted.
    # The caller's theorem must be DERIVED from the export's spec obligation
    # and be sorry-free: that is the whole reason the obligation is named
    # rather than the contract admitted.  Two routes, and both are named
    # here because which one fires depends on whether the emitter could derive
    # a spec from the source -- `caller_uses_contract` off the PROVED
    # contract, `dylib_export_contract_of_spec` off the named `_spec`.
    check("Contracts.caller_uses_contract dylib_image " in text
          or ":=\n  Refine.dylib_export_contract_of_spec" in text,
          "the caller's contract is no longer derived from the spec")
    check("dylib_export_contract_stub" not in text,
          "the deleted identity-claim stub is still emitted")
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
    # Was {"in_image_stub", "semantics_stub", "dylib_export_contract_stub"}.
    # All three are GONE: [3] made `InImage` a decidable CHECK, split the
    # vacuous `Semantics` into `Total` and `Functional`, and deleted
    # `dylib_export_contract_stub` -- which was `by sorry` asserting that every
    # dylib export computes the identity, which is false
    # (`export_result dylib_image triple 7 = 21`).  The comment above called
    # this "a permanent red for something nobody here may fix" and named the
    # exception: fixing it IS this change.  The set is now empty, so the check
    # reads as what it now means -- the dylib proof rests on no library hole --
    # and the subset logic below still fails if a NEW one appears.
    KNOWN_LIB_HOLES: set = set()
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


def test_a_wrong_spec_is_rejected_not_believed(tmpdir, shared):
    """The contract has teeth: the wrong spec is a PROOF FAILURE.

    A generated proof that merely elaborates says nothing, and the shape this
    guards against is specific and has already happened in this very file: a
    `sorry` over a FALSE claim, and a contract whose composed effect ran the
    machine's steps more than once (`n * 243` where the machine computes
    `n * 3` — `formal/arm64_proof_gen.py`, 2026-10-03).  Both elaborate.  Only
    a wrong spec RUN THROUGH LEAN tells the two apart, so this is the
    `OPUS-9` check ("state the predicate at a concrete instance and see
    whether it survives") applied to the one obligation the emitter used to
    admit: the export's agreement with its spec.

    Three Lean runs, and the first is a control — the same bytes with the
    RIGHT spec must check, so a red on the other two is the spec and not the
    proof.  Reuses the dylib the case above already built (`--no-prove`, so no
    code generation happens twice), so the cost is three Lean runs and nothing
    else.
    """
    from formal.lean import find_lean
    root = HERE
    if not find_lean(root):
        print("    SKIP: no lean found (proof part of the dylib path)")
        return
    src = os.path.join(tmpdir, "teeth.mojo")
    with open(src, "w") as f:
        f.write("def triple(n):\n  return n * 3\n")
    out = os.path.join(tmpdir, "teeth.dylib")
    # `prove=False` for the dylib and `--no-prove` on the line, because the
    # proof is written by hand below from the same code.
    build_dylib(tmpdir, [src], "teeth.dylib")
    from formal.build import compile_formal_dylib
    from formal.arm64_proof_gen import generate_dylib_proof
    from formal.lean import check_proof
    built = compile_formal_dylib([src], output=out, prove=False)
    check(call_exported_by_name(out, "triple", 14) == 42,
          "the control dylib does not compute 42, so this test says nothing")

    def with_spec(spec: str) -> str:
        path = os.path.join(tmpdir, f"teeth_{abs(hash(spec)) % 10 ** 8}.lean")
        with open(path, "w") as f:
            f.write(generate_dylib_proof(built["code"], built["info"],
                                         built["exports"], {"triple": spec}))
        return path

    ok, detail = check_proof(with_spec("(fun n => (n * (3 : UInt64)))"),
                             repo_root=root)
    check(ok, f"the CONTROL proof (the right spec) was rejected, so the two "
              f"rejections below would prove nothing: {detail[-300:]}")
    for label, spec in [("a wrong multiplier", "(fun n => (n * (5 : UInt64)))"),
                        ("the identity", "(fun n => n)"),
                        ("the negation", "(fun n => (0 : UInt64) - n)")]:
        ok, detail = check_proof(with_spec(spec), repo_root=root)
        check(not ok,
              f"lean ACCEPTED a contract claiming triple computes {label} — the "
              f"per-export contract is not being checked against the machine, "
              f"so it is an admitted claim wearing a proof's clothes")
        check("counterexample" in detail or "unsolved goals" in detail,
              f"the {label} spec was rejected for the wrong reason, so this "
              f"test is not measuring what it claims: {detail[-300:]}")


def test_several_exports_and_no_derivable_spec(tmpdir, shared):
    """A MULTI-EXPORT dylib gets a PROVED contract per export, and one export
    whose spec cannot be derived gets nothing claimed about it.

    Every other case in this file is a ONE-export dylib.  The other two shapes
    went untested, and both were broken for the whole history of this file
    without anything noticing:

    * **several exports.**  `Contracts.ExportBody`'s `atExit` used to be stated
      at `image.base + image.codeSize` — the IMAGE's exit — so a `Block` for one
      export of several could not end where it must, and every export of a
      multi-export dylib got a NAMED `sorry` instead of a contract.  The emitter
      used to build a `Block` over the WHOLE image's addresses anyway, and the
      result did not elaborate.  The fix is on both sides of the boundary:
      `DylibExport.exportEnd` gives an export its own end (which is also what
      `runExport` and `startState` now halt at, and the address an export's own
      `ret` returns to), and the emitter's block is `pcs` over `[entry, func_end)`
      with the image-wide `dylib_sr_` lemmas indexed from there.  So this case
      now requires `Contracts.agrees_of_body` for each derivable export.
    * **no derivable spec.** The fallback obligation was stated against
      `(fun n => n)`: a `sorry` over the claim that every dylib export computes
      the identity, which is false (`add1 7 = 8`) and which Lean never sees,
      because there is no `Block` to check it against.

    What it also checks, and what keeps the first half honest: **zero admitted
    holes** for this image (both contracts proved, not named), and a WRONG spec
    for one export of a multi-export image is a proof FAILURE.  A contract that
    merely elaborates says nothing — three of the four defects fixed in this
    emitter on 2026-10-03 were things only a `lean` run finds (`instance` on a
    non-class, `interval_cases`, `body.step` one step short of the block it
    certifies) — and a per-export block at a per-export exit is exactly the
    shape that could quietly prove a statement about the wrong addresses.
    """
    import re as _re
    from formal.lean import find_lean
    root = HERE
    src = os.path.join(tmpdir, "several.mojo")
    with open(src, "w") as f:
        f.write("def add1(n):\n  return n + 1\n\n\n"
                "def mul2(n):\n  return n * 2\n\n\n"
                "def pick(n):\n  if n > 3:\n    return 1\n  return 0\n")
    out = os.path.join(tmpdir, "several.dylib")
    build_dylib(tmpdir, [src], "several.dylib")
    from formal.build import compile_formal_dylib
    from formal.arm64_proof_gen import generate_dylib_proof
    built = compile_formal_dylib([src], output=out, prove=False)
    check(call_exported_by_name(out, "add1", 41) == 42
          and call_exported_by_name(out, "mul2", 21) == 42,
          "the dylib does not compute what the specs will claim, so the "
          "obligations below would be false and this test would be measuring "
          "the wrong thing")
    # The exit each contract is about is the EXPORT's own end, which is the next
    # export's entry -- so the two contracts are about different addresses and
    # neither is about the image's.
    entries = sorted(e["entry"] for e in built["exports"])
    base = built["info"]["base_addr"]
    path = os.path.join(tmpdir, "several_proof.lean")
    with open(path, "w") as f:
        f.write(generate_dylib_proof(
            built["code"], built["info"], built["exports"],
            {"add1": "(fun n => (n + (1 : UInt64)))",
             "mul2": "(fun n => (n * (2 : UInt64)))"}))
    text = open(path).read()
    check("(fun n => n) := by\n  sorry" not in text,
          "the generated proof still states an obligation against a guessed "
          "identity spec")
    # Two exports have a derived spec, so each gets a PROVED contract naming
    # the spec derived from its own source.  A named `_spec` obligation is the
    # shape this case used to require and must not come back.
    for i, (ident, spec) in enumerate(
            [("dylib_export_0_add1", "n + (1 : UInt64)"),
             ("dylib_export_1_mul2", "n * (2 : UInt64)")]):
        check(_re.search(rf"Contracts\.agrees_of_body dylib_image {ident} bodyI",
                         text),
              f"{ident}'s contract is not proved: a dylib with several exports "
              f"still gets a named obligation instead, which is the defect this "
              f"case exists to keep fixed")
        check(_re.search(rf"theorem {ident}_spec\b", text) is None,
              f"{ident} has a PROVED contract and also a named obligation, so "
              f"one of the two is not what it claims")
        check(spec in text,
              f"{ident}'s contract does not name the spec derived from its "
              f"source ({spec}): the contract is about something else")
        check(_re.search(rf"theorem {ident}_contract\b|theorem caller\b", text),
              f"{ident} has a contract but no caller's theorem derived from "
              f"it, so a caller has nothing to consume")
        # `exportEnd_here` is what says the exit is this export's end, and it is
        # proved by `native_decide` over the image's export table -- so it is a
        # check that the emitter's extent and the library's fold agree.
        end = entries[i + 1] if i + 1 < len(entries) else base + len(built["code"])
        check(f"DylibExport.exportEnd dylib_image {ident} = {end}" in text,
              f"{ident}'s contract is not stated at its OWN end ({end}), so it "
              f"is about the image's exit or another export's code")
    # `pick`'s body is not a single `return` of arithmetic over its parameter,
    # so no spec is derivable and the emitter must SAY that rather than assert
    # something.  `_dylib_spec_lean` used to count top-level returns and derive
    # one ARM's spec — `(fun n => 0)` — for a body with a branch, which is
    # false for `n = 7` and which Lean never checks.
    pick = _re.search(r"def (dylib_export_\w*pick) : DylibExport :=", text)
    check(pick is not None, "the branching export is not in the generated proof")
    check(f"NO SPEC DERIVED for {pick.group(1)}" in text,
          "the branching export has no spec and no marker saying so, so its "
          "absence of a contract is indistinguishable from the emitter having "
          "forgotten it")
    check(not _re.search(rf"theorem {pick.group(1)}_spec\b", text),
          "the branching export was given a contract obligation anyway")
    if not find_lean(root):
        print("    SKIP: no lean found (the emitted file is not typechecked)")
        return
    from formal.lean import check_proof_cached
    ok, detail, _, n_sorries = check_proof_cached(path, repo_root=root)
    check(ok, f"lean rejected the proof of a {len(built['exports'])}-export "
              f"dylib: {detail[-400:]}")
    # Zero holes, and not merely "the file checked": a NAMED obligation also
    # checks, and this image used to consist of two of them.  The count is
    # Lean's own elaboration report rather than a grep for the word, so an
    # unreached `all_goals … sorry` fallback cannot keep the figure up.
    check(n_sorries == 0,
          f"the {len(built['exports'])}-export proof admits {n_sorries} hole(s); "
          f"every export with a derived spec should have a PROVED contract")


def test_an_export_that_binds_a_local_still_gets_a_proved_contract(tmpdir, shared):
    """The ceiling on proved contracts was SPEC DERIVATION, and it was wider
    than the proof layer behind it.

    `_dylib_spec_lean` required the body to be EXACTLY one `return` of
    arithmetic over the parameter.  Measured over six one-`return` bodies,
    `var m = n * 3` then `return m` is 17 instructions of straight-line code
    that `_dylib_contract_proof` emits a complete `Block` and `BlockCert` for --
    and it got NO contract, because the statement list had two entries.  So the
    binding constraint was never `Refine.Block`: it was this function, and an
    export that reads its argument into a local before computing with it (most
    of them) was silently outside it.

    The widened derivation accepts a chain of bindings to FRESH names ending in
    the `return`, and refuses a name bound twice -- which is what makes the
    substitution let-elimination rather than an interpretation of reassignment.
    All three claims are checked here, and the first two by Lean:

      * `one_local` and `two_locals` get PROVED contracts, and the proof checks
        clean with no hole (`bv_decide` against the machine, so a derivation
        that was subtly wrong would be a build failure rather than a claim);
      * `rebound` -- `var m = n * 3` then `m = m + 1` -- gets NO spec and no
        contract claim of any kind.  The `ifexp`/`and` shapes do get a spec now
        (`a conditional expression derives a spec`, which is where their exact
        renderings are pinned) and still get no PROVED contract, for a reason
        that is not this function's: their code contains a `CSEL`, and
        `arm64_step` does not step one, so the walk declines above this layer.
        This case does not pretend otherwise: what it pins is that widening the
        derivation did not widen it past a reassignment.
    """
    import re as _re
    from formal.lean import find_lean
    from formal.build import parse_module
    from formal.arm64_proof_gen import _dylib_spec_lean, generate_dylib_proof
    root = HERE
    src = os.path.join(tmpdir, "locals.mojo")
    with open(src, "w") as f:
        f.write("def one_local(n):\n  var m = n * 3\n  return m\n\n\n"
                "def two_locals(n):\n  var m = n * 3\n"
                "  var k = m + 1\n  return k\n\n\n"
                "def rebound(n):\n  var m = n * 3\n  m = m + 1\n  return m\n")
    out = os.path.join(tmpdir, "locals.dylib")
    from formal.build import compile_formal_dylib
    built = compile_formal_dylib([src], output=out, prove=False)
    check(call_exported_by_name(out, "one_local", 14) == 42
          and call_exported_by_name(out, "two_locals", 14) == 43
          and call_exported_by_name(out, "rebound", 14) == 43,
          "the dylib does not compute the values the specs will claim, so the "
          "obligations below would be false and this test would be measuring "
          "the wrong thing")
    # The derivation itself, before any Lean: what each body yields, and that
    # the inlined value is the one the source computes (no leftover name, no
    # `n` standing for a local).
    specs = {fn.name: _dylib_spec_lean(fn) for fn in parse_module(
        open(src).read())}
    check(specs.get("one_local") == "(fun n => (n * (3 : UInt64)))",
          f"one_local's spec is {specs.get('one_local')!r}, not the inlined "
          f"value of its one binding")
    check(specs.get("two_locals") == "(fun n => ((n * (3 : UInt64)) + (1 : UInt64)))",
          f"two_locals' spec is {specs.get('two_locals')!r}: a chain of "
          f"bindings must inline, not chain `let`s the block layer cannot read")
    check(specs.get("rebound") is None,
          f"a name bound twice got the spec {specs.get('rebound')!r}: the "
          f"inlining assumes a fresh binding, and that assumption is the whole "
          f"soundness argument")
    specs = {k: v for k, v in specs.items() if v is not None}
    path = os.path.join(tmpdir, "locals_proof.lean")
    with open(path, "w") as f:
        f.write(generate_dylib_proof(built["code"], built["info"],
                                     built["exports"], specs))
    text = open(path).read()
    for name in ("one_local", "two_locals"):
        ident = ("dylib_export_%d_%s"
                 % ([e["name"] for e in built["exports"]].index(name), name))
        check(_re.search(rf"Contracts\.agrees_of_body dylib_image {ident} bodyI",
                         text),
              f"{name}'s contract is not proved, so widening the derivation "
              f"did not reach the proof layer")
    check(not _re.search(r"rebound\b.*_spec\b", text, _re.S)
          or "agrees_of_body dylib_image dylib_export_2_rebound" not in text,
          "the rebound export was given a contract anyway")
    check("dylib_export_2_rebound" in text
          and "NO SPEC DERIVED for dylib_export_2_rebound" in text,
          "the rebound export is not marked as having no spec, so its silence "
          "is indistinguishable from the emitter having forgotten it")
    if not find_lean(root):
        print("    SKIP: no lean found (the emitted file is not typechecked)")
        return
    from formal.lean import check_proof_cached
    ok, detail, _, n = check_proof_cached(path, repo_root=root)
    check(ok, f"lean rejected the proof of a dylib whose exports bind locals: "
              f"{detail[-400:]}")
    check(n == 0, f"the proof admits {n} hole(s); both contracts should be "
                  f"proved, not named")


def test_a_wrong_spec_on_a_multi_export_image_is_rejected(tmpdir, shared):
    """The per-export contract has TEETH, for an export that is not the image.

    `a wrong spec is rejected, not believed` does this for a one-export dylib,
    where the export's block and the image's exit are the same address range.
    That is the easy case: the contract is about everything in the image.  Here
    the contract is about `[entry, func_end)` — a sub-range, with another
    export's instructions after it — which is the case where a block built at
    the wrong extent, or an `x30` at the image's end rather than the export's,
    would still elaborate and would be a theorem about the wrong function.

    A control first, for the same reason as the case above: the right specs must
    check, so a red on the wrong one is the spec and not the proof.
    """
    from formal.lean import find_lean
    root = HERE
    if not find_lean(root):
        print("    SKIP: no lean found (proof part of the dylib path)")
        return
    src = os.path.join(tmpdir, "teeth3.mojo")
    with open(src, "w") as f:
        f.write("def add1(n):\n  return n + 1\n\n\n"
                "def mul2(n):\n  return n * 2\n")
    out = os.path.join(tmpdir, "teeth3.dylib")
    from formal.build import compile_formal_dylib
    from formal.arm64_proof_gen import generate_dylib_proof
    from formal.lean import check_proof
    built = compile_formal_dylib([src], output=out, prove=False)
    check(call_exported_by_name(out, "add1", 41) == 42
          and call_exported_by_name(out, "mul2", 21) == 42,
          "the control dylib does not compute 42/42, so this test says nothing")

    def with_specs(a: str, m: str) -> str:
        path = os.path.join(
            tmpdir, f"teeth3_{abs(hash((a, m))) % 10 ** 8}.lean")
        with open(path, "w") as f:
            f.write(generate_dylib_proof(built["code"], built["info"],
                                         built["exports"],
                                         {"add1": a, "mul2": m}))
        return path

    right = ("(fun n => (n + (1 : UInt64)))", "(fun n => (n * (2 : UInt64)))")
    ok, detail = check_proof(with_specs(*right), repo_root=root)
    check(ok, f"the CONTROL proof (the right specs) was rejected, so the "
              f"rejections below would prove nothing: {detail[-300:]}")
    # What a rejection looks like depends on where the wrongness shows up, and
    # all three are `bv_decide` refusing the goal rather than a parse error:
    # a SPURIOUS COUNTEREXAMPLE (the machine model reached and disagreed),
    # UNSOLVED GOALS (a side condition could not be discharged at all), and "the
    # original goal was reduced to False" (the fragment checker reduced it to
    # `False` and said so).  The single-export case above only ever saw the
    # first; a per-export block at a per-export exit can also produce the other
    # two, and each is a refusal of the CLAIM.
    rejected = ("counterexample", "unsolved goals", "reduced to False")
    for label, a, m in [
            ("add1's identity", "(fun n => n)", right[1]),
            ("mul2's identity", right[0], "(fun n => n)"),
            ("add1 doubling", "(fun n => (n * (2 : UInt64)))", right[1]),
            ("both identities", "(fun n => n)", "(fun n => n)")]:
        ok, detail = check_proof(with_specs(a, m), repo_root=root)
        check(not ok,
              f"lean ACCEPTED a multi-export contract with {label} — the "
              f"per-export block is not being checked against the machine, so "
              f"the exit it is stated at is not being checked either")
        check(any(r in detail for r in rejected),
              f"{label} was rejected for the wrong reason, so this test is "
              f"not measuring what it claims: {detail[-300:]}")


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


def test_a_library_source_can_use_a_sibling_sources_struct(tmpdir, shared):
    """A struct declared in one source of a LIBRARY is usable from another.

    A library is ONE image compiled from SEVERAL sources, so "which structs does
    this image declare" is a question about all of them — and
    `_prepare_functions` is run once per source, with that source's own
    declarations. Every fact that is a property of the image rather than of the
    file was therefore answered from a SUBSET: the frame-holder analysis (which
    writes `fn._frame_slots`, the table an emitter lays a field out with) and
    the method dispatch table. The emitter was meanwhile handed the MERGED
    `library_structs`, so the two halves of one build disagreed about one image.

    The refusal that came out named the construct and not the cause:

        build: liby.mojo: use_it: 't.v' is a field access through 't', and this
        path has no way to say what 't' holds … Bind the base from a constructor
        whose declaration THIS IMAGE can see

    — and `libx.mojo`, one file above it on the same command line, declares it.
    Measured before the fix, both architectures, one field or two, field store
    or method call; the second row here is the framed one, where the receiver is
    a frame ADDRESS rather than the field itself.

    **Both architectures**, because the merge is in `formal/build.py` and the
    thing it feeds is a table both emitters read — a fix that worked on one and
    not the other would be a rewrite that reached one backend's pipeline.

    **AND the export qualifier**, which is the half that could have gone wrong
    in the other direction. `_method_exports` derives a method's module
    qualifier from the FILE its struct was declared in, so letting each source's
    table carry its siblings' declarations publishes `Wide.total` under the
    prefix of the file that USES it: a library that builds, links, and then
    fails to load with "Symbol not found" for a method it does export. So the
    merge is dropped again the moment the analysis has had it, and the assertion
    is that `Wide_total` is qualified by the DECLARING file.
    """
    lib_a = ("struct Wide:\n"
             "  var a: Int\n"
             "  var b: Int\n"
             "\n"
             "  def total(self) -> Int:\n"
             "    return self.a + self.b\n")
    lib_b = ("def use_wide() -> Int:\n"
             "  var w = Wide()\n"
             "  w.a = 20\n"
             "  w.b = 22\n"
             "  return w.total()\n")
    prog = "def main():\n  return use_wide() - 1\n"      # 42 - 1 = 41
    sys.path.insert(0, HERE)
    from formal.build import compile_formal_dylib
    for arch in ("arm64", "x86_64"):
        src_a = os.path.join(tmpdir, f"sib_a_{arch}.mojo")
        src_b = os.path.join(tmpdir, f"sib_b_{arch}.mojo")
        with open(src_a, "w") as f:
            f.write(lib_a)
        with open(src_b, "w") as f:
            f.write(lib_b)
        out = os.path.join(tmpdir, f"siblib_{arch}.dylib")
        # In-process rather than through `fire.py dylib`, because that CLI
        # refuses an x86-64 library outright (there is no `DylibExport` model
        # for the other machine — `test_a_proved_dylib_is_an_arm64_artifact_and
        # _says_so` is that refusal) while the function behind it honours `arch`,
        # which is how every x86-64 module dylib in the tree is built
        # (`formal/imports.py::build_module_dylib`).
        try:
            compile_formal_dylib([src_a, src_b], output=out, prove=False,
                                 check=False, arch=arch)
        except Exception as e:                     # noqa: BLE001 — reported
            raise TestFailure(
                f"[{arch}] a library using its own second source's struct did "
                f"not build: {str(e)[-400:]}") from None
        with open(out + ".manifest.json") as f:
            exports = {e["name"]: e["symbol"]
                       for e in json.load(f)["exports"]}
        check(exports.get("Wide_total") == "sib_a_%s_Wide_total" % arch,
              f"[{arch}] Wide.total is published as "
              f"{exports.get('Wide_total')!r}, which is not qualified by the "
              f"file that DECLARES the struct: {exports}")
        check(exports.get("use_wide") == "sib_b_%s_use_wide" % arch,
              f"[{arch}] use_wide is published as {exports.get('use_wide')!r}, "
              f"which is not qualified by the file that declares it: {exports}")

        # …and it computes the right answer across the boundary, not merely
        # builds: 20 + 22, less the 1 the program takes off.
        src = os.path.join(tmpdir, f"sib_prog_{arch}.mojo")
        with open(src, "w") as f:
            f.write(prog)
        exe = os.path.join(tmpdir, f"sib_prog_{arch}.aout")
        result = run_fire(["build", "--formal", "--no-prove", f"--backend={arch}",
                           "-o", exe, "--link-dylib", out, src])
        check(result.returncode == 0,
              f"[{arch}] the program did not link: "
              f"{(result.stderr or result.stdout).strip()[-300:]}")
        run = subprocess.run([exe], capture_output=True, text=True)
        check(run.returncode == 41,
              f"[{arch}] the linked program returned {run.returncode}, expected "
              f"41 — the struct's method and its field stores have to compute "
              f"the source's own arithmetic")


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


def test_a_proved_dylib_is_an_arm64_artifact_and_says_so(tmpdir, shared):
    """`arch` is honoured for the CODE and refused for the PROOF, by name.

    `a dylib is built for the requested arch` already pins that `arch` reaches
    the code generator, for both architectures. What it does not reach is the
    proof layer, and there the two used to disagree in the worst possible way:
    `compile_formal_dylib(arch="x86_64", prove=True)` fed x86-64 machine code to
    `formal/arm64_proof_gen.py`, which raised `KeyError 4294967948` out of
    `_gen_run_cert` -- the generator decoding x86-64 words as arm64 and not
    finding one. No refusal, no message, a raw traceback.

    And on the command line it was worse than a crash: `--backend` is a GLOBAL
    flag and `dylib --formal` never read it, so `fire.py dylib --formal
    --backend=x86_64` built an **arm64** image and printed `Built:`. Both files
    read `Mach-O 64-bit dynamically linked shared library arm64`. On a command
    whose entire subject is a PER-EXPORT contract that is the silent-wrong-answer
    shape: a reader measuring the x86-64 boundary would get an arm64 answer and
    conclude "the same argument applies", which is exactly the hypothesis
    `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §OPUS-6 says must be
    measured rather than assumed.

    So: the refusal has to be at the function (every caller goes through it, and
    `formal/imports.py`'s `build_module_dylib` does), and the CLI's own check is
    only there because its message is better. Both are exercised.
    """
    from formal.build import compile_formal_dylib, FormalBuildError
    src = os.path.join(tmpdir, "archproof.mojo")
    with open(src, "w") as f:
        f.write("def triple(n):\n  return n * 3\n")

    # The CODE for x86-64 builds and is an x86-64 image -- asserted on the
    # Mach-O header, because "it built" is not the claim.
    out = os.path.join(tmpdir, "archproof_x86.dylib")
    r = compile_formal_dylib([src], output=out, prove=False, check=False,
                             arch="x86_64")
    check(not r.get("proof_path"),
          "prove=False produced a proof path, so the refusal below would be "
          "testing nothing")
    with open(out, "rb") as f:
        head = f.read(16)
    check(struct.unpack_from("<I", head, 0)[0] == MH_MAGIC_64
          and struct.unpack_from("<I", head, 4)[0] == CPU_TYPE_X86_64,
          f"the x86_64 dylib is cputype "
          f"{struct.unpack_from('<I', head, 4)[0]}, so this case is not testing "
          f"what it claims: the point is that the CODE builds and the PROOF "
          f"does not")

    # The PROOF for x86-64 is refused, by name, and the message says which half
    # is missing -- a reader who concluded "x86-64 dylibs are unsupported"
    # would be wrong about the image.
    try:
        compile_formal_dylib([src], output=out + ".2", prove=True,
                             check=False, arch="x86_64")
        check(False, "arch=x86_64 with prove=True was accepted; the arm64 "
                     "generator will be handed x86-64 machine code")
    except FormalBuildError as e:
        msg = str(e)
        check("generate_dylib_proof" in msg and "DylibExport" in msg,
              f"the refusal does not name the missing generator or the model "
              f"it is stated over, so a reader has to find that out "
              f"separately: {msg[:200]}")
        check("prove=False" in msg,
              f"the refusal does not say how to ASK for the x86-64 image that "
              f"does build: {msg[:200]}")

    # The CLI, which is where the silent arm64 answer was.
    def cli(*args):
        return subprocess.run([sys.executable, FIRE, *args],
                              capture_output=True, text=True, timeout=600,
                              cwd=HERE)
    p = cli("dylib", "--formal", "--no-prove", "--backend=x86_64",
            "-o", os.path.join(tmpdir, "cli_x86"), src)
    check(p.returncode != 0,
          "dylib --formal --backend=x86_64 exited 0, so it either built "
          "something or the flag never reached the branch that refuses it")
    check("Built:" not in p.stdout,
          f"the CLI printed Built: for --backend=x86_64 -- stdout: "
          f"{p.stdout[-300:]}")
    check("generate_dylib_proof" in (p.stderr or ""),
          f"the CLI's refusal does not name the missing generator: "
          f"{p.stderr[-300:]}")
    # And the plain path, which has no formal backend to select at all.
    p = cli("dylib", "--backend=arm64", "-o", os.path.join(tmpdir, "cli_g"),
            src)
    check(p.returncode != 0,
          "dylib --backend=arm64 (no --formal) exited 0: the gimple path "
          "compiles for the HOST's architecture, so that request is right only "
          "by coincidence on an arm64 host")


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


def test_frame_params_are_published_not_empty(tmpdir, shared):
    """A module that takes a FRAME publishes a per-parameter frame contract.

    The point is the *publication*, at the point of publication, and that is
    where this was found: the four `byref_*` cases in `test_formal_run.py` were
    red for four layers of the wrong reason. `frame_params` is the answer to a
    question an importing module cannot answer for itself — "did your
    compilation make parameter 0 a frame holder, and of which struct?" — and
    `model.resolve_frame_parameter_contract` reads it POSITIONALLY, with three
    separate "no contract" answers. `[]` collides with the "not exported at all"
    one, whose message claims the manifest does not list the export, so a
    consumer was sent to look for an export filter that was never the problem.

    The defect behind it was four `.get(fn.name)` reads of tables filed under
    `_fn_key(fn)` (`id(fn)`), so the parameter list arrived as `()` and the
    contract was `[]` for every export of every module — a function with one
    parameter publishing `[]` is the shape to assert against, and `arity` is
    right there in the same entry to disagree with.

    A `[]` is still LEGITIMATE for a function with no parameters, so this only
    says what it can: where the manifest says there is a parameter, there is a
    contract entry for it.
    """
    src = os.path.join(tmpdir, "byframe.mojo")
    with open(src, "w") as f:
        f.write("struct P:\n"
                "    var a: Int\n"
                "    var b: Int\n"
                "def take_it(p: P) -> Int:\n"
                "    return p.a * 10 + p.b\n")
    out, _ = build_dylib(tmpdir, [src], "byframe.dylib")
    exports = manifest_exports(out)
    check("take_it" in exports,
          f"the module exported {sorted(exports)}, expected take_it")
    entry = exports["take_it"]
    contract = entry.get("frame_params")
    check(contract is not None,
          "the export carries no `frame_params` at all, so a consumer "
          "cannot tell a published contract from an absent one")
    check(len(contract) == entry["arity"],
          f"take_it takes {entry['arity']} parameter(s) and published a "
          f"contract of {len(contract)}: {contract!r}. `frame_params` is "
          f"positional — one entry per parameter, in call-site order — so a "
          f"short one reads as 'no contract' for every parameter it omits")

    # And the entry must actually SAY it is a holder, not just be there. A
    # one-parameter function publishing `[None]` would mean the entry exists and
    # the classification did not happen, which is the same defect wearing a
    # different length.
    holders = [c for c in contract if c and c[0] != "one-word"]
    check(holders,
          f"take_it takes a P receiver in position 0, so position 0 of the "
          f"contract must name P as a frame holder; published {contract!r}")


def test_a_receiver_writeback_is_not_a_returned_frame(tmpdir, shared):
    """A one-word mutator's receiver write-back is not a frame return — and one
    of the two ways of doing it hands a frame back anyway.

    `model.receiver_writeback_name` hands the receiver of a one-field struct's
    mutator over BY REFERENCE: the caller passes the ADDRESS of its own one-word
    cell, so a store to that cell reaches the caller with no return register and
    no statement-position rewrite (it used to be `_return_the_receiver`
    appending `return <receiver>`; that walk is gone and the tag it set had no
    producer left). Both constructors below are that mechanism, and they differ
    in exactly one thing, and only one of them is an escape:

      * WRITING THROUGH (`self.inner.a = a`, below) writes the caller's own
        bytes. It used to be refused on both counts — "`Box1___init__` returns a
        frame address, so it cannot be compiled into a dylib", and, once that
        was out of the way, "a Inner receiver is returned from a method of Box1,
        which did not create the frame". The second sentence was the check
        refusing its own convention: the frame it names is the CALLER's and is
        still there. This one is exported, with `frame_params` naming `Inner`,
        and the emitted arm64 code is what says the contract is true —
        `ldr x19, [x0]` once, then `str` to `[x19]` and `[x19, #8]`.
      * ASSIGNING A FRAME (`self.inner = Inner(a, b)`) really does hand back a
        block the CALLEE built: the two stores go into this function's own
        prologue scratch and the last instruction stores the SCRATCH's address
        into the receiver cell. A caller that followed the published
        `frame_params` — reserve a two-word `Inner` frame, pass its address —
        would read a dead block through a contract the callee does not honour,
        so it is refused (`receiver_writeback_frame_library_refusal`) and no
        manifest is written.

    Neither of the two rules can be the other's, which is why this case is one
    case: `_collect_receiver_rebinds` exempts `__init__` because a constructor
    is INLINED at a construction site rather than called, and
    `_collect_one_field_dropped_stores` stands aside for every nested-frame
    owner because "`self.inner = o` is `self = o` there, and
    `_collect_receiver_rebinds` refuses exactly that". Both are true of a
    program and false of an exported constructor, which is a call.

    The refusal is asserted with its own sentence rather than as "something was
    refused", and the manifest is asserted both ways, because a `returncode`
    check alone passes on a library that published a contract it does not
    honour.
    """
    write_through = (
        "struct Inner:\n"
        "    var a: Int\n"
        "    var b: Int\n"
        "\n"
        "struct Box1:\n"
        "    var inner: Inner\n"
        "\n"
        "    def __init__(out self, a: Int, b: Int):\n"
        "        self.inner.a = a\n"
        "        self.inner.b = b\n"
        "\n"
        "def mk(x: Int) -> Int:\n"
        "    return x + 1\n")
    src = os.path.join(tmpdir, "writethrough.mojo")
    with open(src, "w") as f:
        f.write(write_through)
    out, _ = build_dylib(tmpdir, [src], "writethrough.dylib")
    exports = manifest_exports(out)
    check("mk" in exports,
          f"the module built but exported {sorted(exports)}, expected mk; a "
          f"library whose write-back constructor is classified as a returned "
          f"frame is refused, not exported")
    # …and the CONTRACT it publishes, which is the half a `returncode` check
    # cannot see: the write-through constructor writes into the block the
    # IMPORTER reserved, so `frame_params[0]` naming `Inner` is the truth about
    # the emitted code and has to keep being published. Measured on the arm64
    # image this module produces (`ldr x19, [x0]` then `str x0, [x19]` /
    # `str x0, [x19, #8]`, read out of `info["labels"]` and `otool`), the
    # importer's address is dereferenced once and both slots are written
    # through it.
    entry = exports.get("Box1___init__")
    check(entry is not None,
          f"the write-through constructor is not in the manifest at all "
          f"({sorted(exports)}); it is callable across the boundary and its "
          f"contract is what makes the call sound")
    contract = (entry or {}).get("frame_params") or []
    holders = [c for c in contract if c]
    check(holders and all("Inner" in c for c in holders),
          f"the write-through constructor published {contract!r} for a "
          f"receiver whose only field is an Inner frame; position 0 is the "
          f"receiver, so it has to name Inner as the block the caller reserves")

    rebinds = write_through.replace(
        "        self.inner.a = a\n        self.inner.b = b\n",
        "        self.inner = Inner(a, b)\n")
    src2 = os.path.join(tmpdir, "rebinds.mojo")
    with open(src2, "w") as f:
        f.write(rebinds)
    out2 = os.path.join(tmpdir, "rebinds.dylib")
    result = run_fire(["dylib", "--formal", "--no-prove", "-o", out2, src2])
    text = (result.stderr + result.stdout).strip()
    check(result.returncode != 0,
          "a constructor that ASSIGNS a frame to its own one word was built as "
          "a dylib: the frame it hands back is one the CALLEE built, and an "
          "importer has no way to learn the width of the block it must reserve")
    check("returns a frame address" in text,
          f"the assigning constructor was refused without naming the returned "
          f"frame it really is: {text}")
    # …and nothing published. A `returncode` check alone would pass on a
    # library that refused nothing and wrote a manifest whose `frame_params`
    # told the importer to reserve a two-word Inner block the callee never
    # writes: the emitted code here builds that frame in its own prologue
    # scratch and stores the scratch's ADDRESS into the receiver cell
    # (`str <scratch>, [x0]`), so the contract and the code disagree about the
    # size of the caller's block. This is the assertion the doc's next step
    # asked for, and it is the one that would still hold if the refusal were
    # ever downgraded to a warning.
    check(not os.path.exists(out2 + ".manifest.json") and not os.path.exists(
        out2),
          f"the build refused but left {sorted(os.listdir(tmpdir))} behind; a "
          f"manifest published for this constructor is an ABI contract the "
          f"image does not honour")


def test_the_manifest_offers_nothing_the_image_does_not_define(tmpdir, shared):
    """The check on the direction that used to be unchecked, both ways.

    `_audit_bound_symbols` asks whether every name an image BINDS has a
    provider, and it has asked it on both paths since it was factored out. The
    other direction — a library whose MANIFEST advertises a symbol its export
    trie does not contain — was never asked, and it is the one that reaches
    another build: the consumer's bind audit reads the name out of the manifest,
    so it is satisfied, the image links cleanly, and dyld fails at load. The
    honest fix is the `nm`-style verification `build_stdlib_dylib.py` has for
    the gimple path, reading the file back with an independent parser
    (`formal/build.py`'s `_advertised_but_absent` over `macho_dylib_exports`)
    rather than asking the writer.

    Both directions are asserted here, and the negative one is manufactured by
    ADDING an entry to a real export list — the shape of the defect is "the two
    lists disagree", so the test has to make them disagree, and it cannot do
    that by making the emitter drop code (that would need a codegen bug to
    exist first, which is the whole reason the check is wanted).

    The positive half is not decoration: this is the check every dylib build in
    the tree now runs, so a library whose real exports are not all in its own
    trie would fail this case on the shared fixture.
    """
    from formal import build as B
    out = shared["dylib"]
    exports = list(manifest_exports(out).values())
    check(exports, "precondition: the shared dylib advertises something")
    check(B._advertised_but_absent(out, exports) == [],
          "a library advertises exports its own image does not define, and "
          "the build did not notice")

    fabricated = {"name": "not_emitted", "symbol": "libmath_not_emitted",
                  "module": "libmath", "arity": 1, "kind": None,
                  "signature": "not_emitted", "frame_params": []}
    missing = B._advertised_but_absent(out, exports + [fabricated])
    check(missing == ["libmath_not_emitted"],
          f"the check reported {missing!r} for one advertised symbol the "
          f"image does not define; it must name that one and only that one")
    report = B._advertised_absent_report("libmath.mojo", missing)
    check("libmath_not_emitted" in report,
          f"the report does not name the symbol: {report}")
    check("manifest" in report and "dyld" in report,
          f"the report does not say which side is wrong: {report}")


def test_the_library_admits_no_hole(tmpdir, shared):
    """No module under `lib/` admits a `sorry` or an `admit`.

    A TEXT census and deliberately a weaker one than
    `formal/lean.py::library_census`, which elaborates each module in a private
    directory and reads what Lean says — the only sound way to count a hole,
    because a module consumed as a pre-built `.olean` produces no warning and a
    cached elaboration is precisely the one that does not look. That function
    needs Lean runs this suite must not start, so what is pinned here is the
    thing a text check CAN settle, and it is not nothing:

      * a hole in `lib/` is invisible to every other check in this repository.
        `test_default_prove_emits_checked_proof` greps the GENERATED proof,
        which imports the library as an `.olean`, so a `by sorry` in
        `lib/Refine.lean` is what every generated dylib contract rests on and
        nothing here would report it. The three holes this row was written for
        — `in_image_stub`, `semantics_stub`, `dylib_export_contract_stub` —
        were exactly that, and `library_census`'s own docstring records that its
        first version reported all four modules clean;
      * a `sorry` in a DOCSTRING is not a hole, and there are several — the
        records above are quoted in prose — so the check reads for the tactic
        rather than for the word.

    What it cannot see is a hole written any other way, and that is stated here
    rather than left for a reader to assume. Running `library_census` is the
    integrator's: it is the measurement this file stands in for, not a
    replacement for it.
    """
    import re as _re
    lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
    modules = sorted(f for f in os.listdir(lib) if f.endswith(".lean"))
    check(modules, f"no .lean modules found in {lib}")
    # `by sorry`, `:= sorry`, and `admit`, each with the shape that makes it a
    # tactic rather than a word in prose. A comment line is excluded outright,
    # which is what keeps this from red for the records quoted in the docstrings
    # above.
    hole = _re.compile(r"(^|\s)(by\s+sorry|:=\s*sorry|\badmit\b)")
    found = []
    for name in modules:
        with open(os.path.join(lib, name)) as fh:
            for n, line in enumerate(fh, 1):
                if line.lstrip().startswith("--"):
                    continue
                if hole.search(line):
                    found.append(f"{name}:{n}: {line.strip()[:90]}")
    check(not found,
          "the library admits a hole, and no other check in this tree can see "
          "it (a generated proof imports these modules as .olean files, so Lean "
          "warns about nothing):\n      " + "\n      ".join(found))


def test_an_export_symbol_that_already_begins_with_an_underscore(tmpdir, shared):
    """A module whose own NAME begins with `_`, end to end, on both halves.

    Every other symbol in the tree begins with a letter, because
    `reflect.export_exclusions` denies a private `def _foo` and `doc/ABI.md` has
    no other way to mint one. The exception is a MODULE name: `abi_module_name`
    flattens dots to `_` (`a.b` -> `a_b`) and nothing else, so a module called
    `__pkg` qualifies its imports as `__pkg__helper` and exports
    `__pkg__helper_twice_9f63a2` — a legal C identifier that starts with an
    underscore, and the only shape on this path that does.

    Three places used to spell "the Mach-O name of this C identifier" and two of
    them spelled it CONDITIONALLY, from opposite ends: `_export_trie` wrote a
    name that already began with `_` unchanged, and `_bind_info` removed one
    leading `_` from the bind-stream name. So the trie held
    `__pkg__helper_twice_9f63a2` while a consumer's bind stream asked dyld for
    `_pkg__helper_twice_9f63a2`, and dyld died at load for a function that was
    right there. The library's own audit did not see it, because it re-derived
    the export name with the unconditional prepend — so it refused the BUILD
    first, naming a symbol the image did not lack, and the shape never got far
    enough to be observed as a load failure.

    All three now ask `macho_linker.macho_export_name`, which is one function and
    has no case in it. What is asserted, in the order the failure appeared:

      1. the writer puts the export where `macho_export_name` says, read back by
         THIS FILE's trie reader rather than by the writer;
      2. the audit ACCEPTS the library it just wrote — the build-time half;
      3. the bind stream carries the C name AS GIVEN, and the name dyld forms
         from it is the export the library has — the run-time half, and the one
         that turns a correct refusal into a silent load failure if it regresses
         alone;
      4. and the audit still REFUSES a name the image really lacks, including the
         one-character-short spelling, so the check was corrected rather than
         removed. Without this the fix could equally well have been "delete the
         check", and every assertion above would still pass.
    """
    from formal import build as B
    from formal import macho_linker as ML
    # `formal_sweep` is the committed reader for a bind stream (`tools/`, imported
    # the way test_formal_sweep.py imports it) rather than a fourth reader here:
    # this file's own trie reader covers the export half, and the bind opcodes
    # have exactly one reader in the tree.
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_sweep                       # tools/: the bind-stream reader
    symbols = ["__pkg__helper_twice_9f63a2", "helper_add_2dbb98"]
    out = os.path.join(tmpdir, "lead.dylib")
    data = ML.build_macho_dylib(
        b"", ML.TEXT_BASE + ML.dylib_code_offset(out, False, [], False),
        [{"symbol": s, "entry": ML.TEXT_BASE + 16 * (i + 1)}
         for i, s in enumerate(symbols)],
        out, arch="arm64")
    with open(out, "wb") as f:
        f.write(data)
    trie = parse_macho(data)["exports"] or {}
    for s in symbols:
        check(ML.macho_export_name(s) in trie,
              f"the trie carries {sorted(trie)}, so it does not carry "
              f"{ML.macho_export_name(s)!r} for the ABI symbol {s!r}: "
              f"macho_export_name is not what _export_trie writes")

    # The audit, on the library it just wrote, and on one name short of it.
    absent = B._advertised_but_absent(out, [{"symbol": s} for s in symbols])
    check(absent == [],
          f"the audit refuses a library that advertises exactly what its own "
          f"trie carries, reporting {absent!r}; a symbol already beginning "
          f"with an underscore is a C identifier like any other and the Mach-O "
          f"name is that with ONE underscore in front (formal/macho_linker.py's "
          f"macho_export_name)")
    fabricated = {"symbol": "__pkg__helper_absent_9f63a2", "name": "absent",
                  "module": "__pkg__helper", "arity": 1, "kind": None,
                  "signature": "absent", "frame_params": []}
    short = {"symbol": symbols[0][1:], "name": "short", "module": "x",
             "arity": 1, "kind": None, "signature": "short", "frame_params": []}
    missing = B._advertised_but_absent(
        out, [{"symbol": s} for s in symbols] + [fabricated, short])
    check(missing == ["__pkg__helper_absent_9f63a2", "_pkg__helper_twice_9f63a2"],
          f"the audit reported {missing!r} for two advertised names the image "
          f"does not define; it must name both, and in particular the "
          f"one-character-short spelling of a name it DOES define is a "
          f"different name")

    # The run-time half: what dyld is asked for is what the library exports.
    # Built here rather than by a real program because the property is about the
    # bind stream alone, and the sweep's end-to-end case
    # (`test_formal_sweep.py`'s `test_a_bind_name_that_itself_begins_with_an_underscore_resolves`)
    # runs the image on both architectures for exactly this shape.
    image = ML.build_macho_executable_extern(
        ML.build_macho_executable(b"\x1f\x20\x03\xd5" * 4), symbols, "arm64",
        dylibs=[{"install_name": out, "symbols": set(symbols)}])
    binds = [name for _ordinal, name in formal_sweep._binds(image)]
    check(binds == symbols,
          f"the image binds {binds!r} for the C names {symbols!r}; the bind "
          f"stream carries the C identifier as given and dyld prepends the "
          f"underscore, so a name that already begins with one must not lose "
          f"it (formal/macho_linker.py's _bind_info)")
    for name in binds:
        check(ML.macho_export_name(name) in trie,
              f"the image binds {name!r}, so dyld looks for "
              f"{ML.macho_export_name(name)!r}, which the library does not "
              f"export: {sorted(trie)}")


def test_a_conditional_expression_derives_a_spec(tmpdir, shared):
    """`a if c else b`, `and`, `or` and a comparison as a CONDITION.

    `_dylib_spec_lean` required the body to be EXACTLY one `return` of
    arithmetic over the parameter, so a conditional expression got no spec — and
    the ceiling was this function rather than the proof layer behind it, which
    is the same mistake `an export that binds a local still gets a proved
    contract` records for the binding case.

    The three node kinds are asserted with their EXACT renderings, because each
    one is a decision rather than a transcription:

      * `a if c else b` tests `c` for TRUTHINESS (`!= 0`), not for equality with
        zero, which is what Python's ternary does and what
        `arm64_codegen.py`'s `_emit_csel_ternary` says in so many words;
      * `and`/`or` select an OPERAND rather than producing a boolean, so
        `(n * 3) and (n + 1)` is `(n + 1)` when `n * 3` is non-zero and `n * 3`
        otherwise — `_emit_truthy_word`'s rule, and a 0/1 rendering would be a
        different function;
      * a comparison is rendered SIGNED, as `(a ^^^ SIGN) > (b ^^^ SIGN)`, which
        is the statement `arm64_flag_gt_s` makes. Signed is both what CPython
        means for an `Int` and what the code computes: measured,
        `(n if n > 3 else 0) * 3` answers 0 at `n = 2^63`.

    And two shapes are still REFUSED, because a spec that over-reaches is worse
    than none — it is a claim about the source that nothing checks:

      * a comparison in VALUE position (`return n > 3`). This path's only
        word-shaped encoding of a comparison's answer is 0/1 by convention
        rather than by a rule anything states, so there is nothing here to
        derive it from;
      * a compound condition (`if n and n > 1`), which would need the
        short-circuit that two separately-inlined operands do not carry.

    Both refusals are asserted as `None` rather than left implicit, because a
    derivation that quietly starts accepting them is the failure this whole
    family of checks is for.
    """
    from formal.build import parse_module
    from formal.arm64_proof_gen import _dylib_spec_lean
    src = (
        "def ifexp(n):\n  return (n * 3) if n else 0\n\n\n"
        "def andop(n):\n  return (n * 3) and (n + 1)\n\n\n"
        "def orop(n):\n  return (n * 3) or (n + 1)\n\n\n"
        "def cmpcond(n):\n  return (n if n > 3 else 0) * 3\n\n\n"
        "def cmp_in_value(n):\n  return n > 3\n\n\n"
        "def compound_cond(n):\n  return (n * 3) if (n and n > 1) else 0\n\n\n"
        "def rebounded(n):\n  var m = (n * 3) if n else 0\n"
        "  m = m + 1\n  return m\n")
    specs = {fn.name: _dylib_spec_lean(fn)
             for fn in parse_module(src)}
    want = {
        "ifexp": "(fun n => (if (n) != 0 then (n * (3 : UInt64)) "
                 "else (0 : UInt64)))",
        "andop": "(fun n => (if ((n * (3 : UInt64))) != 0 then "
                 "(n + (1 : UInt64)) else (n * (3 : UInt64))))",
        "orop": "(fun n => (if ((n * (3 : UInt64))) != 0 then "
                "(n * (3 : UInt64)) else (n + (1 : UInt64))))",
        "cmpcond": "(fun n => ((if ((n) ^^^ 0x8000000000000000) > "
                   "(((3 : UInt64)) ^^^ 0x8000000000000000) then n "
                   "else (0 : UInt64)) * (3 : UInt64)))",
    }
    for name, spec in want.items():
        check(specs.get(name) == spec,
              f"{name}'s derived spec is {specs.get(name)!r}, expected {spec!r}")
    for name, why in (
            ("cmp_in_value",
             "a comparison in value position is a 0/1 encoding this path does "
             "not state, so deriving a spec for it would be guessing"),
            ("compound_cond",
             "a compound condition needs the short-circuit that two "
             "separately-inlined operands do not carry"),
            ("rebounded",
             "the inlining assumes a fresh binding, and a name bound twice "
             "breaks exactly that")):
        check(specs.get(name) is None,
              f"{name} got the spec {specs.get(name)!r}, but {why}: a spec is "
              f"a claim about the source and nothing downstream checks it "
              f"against anything except the machine")


def test_a_conditional_value_is_not_a_branch(tmpdir, shared):
    """`cset` selects a VALUE; `b.cond` selects a PC. The contract layer has to
    tell them apart, and it was reading a substring.

    `_dylib_contract_proof` declined a block whose any step's model effect
    contained the text `if `. That is not the property `Refine.Block.step` needs
    — one function of one state — and the two spellings it conflated are both
    real: `CSET`'s effect is `arm64_set_reg rd s (if
    arm64_matches_condition c s.nzcv then 1 else 0)`, a conditional VALUE, and
    `B.cond`'s is the model answering `if c then some A else some B`, a
    conditional PC. So every export whose code contained a `cset` got no
    contract at all. Measured before the fix on the program below: 23
    instructions, one of them a `cset`, `_dylib_contract_proof` returned the
    empty string, and the image computes `n * 3` in both architectures.

    The fix asks the MODEL's shape instead of the text: `arm64_step` returns
    `some <state>` for a step that is one function of one state and two `some`s
    for a conditional branch, so `_step_rhs`'s own `some` prefix is the
    discriminator, and it is the same prefix `_body_of` already reads.

    Three claims, all of them real builds:

      * the control — the program computes `n * 3`, run through the image, so a
        spec supplied by hand below is a claim about what the machine does and
        `bv_decide` is checking it rather than believing it;
      * a `cset`-bearing block now gets a PROVED contract (`Block` + `BlockCert`
        + `agrees_of_body`), and the emitted file checks clean with 0 holes;
      * a body with a real BRANCH still gets none, and still gets the named
        `_spec` obligation rather than silence — a block layer that started
        accepting `b.cond` would be a theorem about a machine this path does not
        step, which is the shape
        `FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`
        is about.
    """
    import re as _re
    from formal.lean import find_lean
    from formal.build import compile_formal_dylib
    from formal.arm64_proof_gen import _step_branch_index, generate_dylib_proof
    src = os.path.join(tmpdir, "csetval.mojo")
    with open(src, "w") as f:
        f.write("def csetval(n):\n  var b = not n\n  var m = n * 3\n"
                "  return m\n\n\n"
                "def branched(n):\n  var m = n * 3\n"
                "  if n > 3:\n    return m\n  return 0\n")
    out = os.path.join(tmpdir, "csetval.dylib")
    built = compile_formal_dylib([src], output=out, prove=False)
    check(call_exported_by_name(out, "csetval", 14) == 42
          and call_exported_by_name(out, "csetval", 0) == 0
          and call_exported_by_name(out, "csetval", 100) == 300,
          "the image does not compute n * 3, so the spec below would be a "
          "guess and the obligations would be false")
    check(call_exported_by_name(out, "branched", 7) == 21
          and call_exported_by_name(out, "branched", 2) == 0,
          "the branching export's answers are not the ones its spec below "
          "claims, so the obligation would be stated over a falsehood")
    # The `cset` is really there, read off the IMAGE's own words through the
    # step table rather than taken from the source: the claim is about the code
    # the contract emitter is handed.
    code, exports, info = built["code"], built["exports"], built["info"]
    entry = [e for e in exports if e["name"] == "csetval"][0]["entry"]
    base = info["base_addr"]
    k0 = (entry - base) // 4
    words = [int.from_bytes(code[i:i + 4], "little")
             for i in range(0, len(code) - len(code) % 4, 4)]
    end = min([e["entry"] for e in exports if e["entry"] > entry]
              or [base + len(code)])
    own = words[k0:(end - base) // 4]
    check(any(_step_branch_index(w) == 30 for w in own),
          f"no CSET in the export's own {len(own)} instructions, so this test "
          f"is measuring something other than what it claims")
    # The spec is supplied BY HAND because `_dylib_spec_lean` cannot render
    # `not` — which is the filing's own method, and the reason it is safe: the
    # emitted proof checks the spec against the machine with `bv_decide`, so a
    # spec that did not describe this code would be a build failure.  The
    # branching export's spec is handed over for the same reason and is the
    # CONTROL: it is the one spec in this file whose contract must NOT be
    # emitted, so "a spec exists" and "a contract was proved" are two facts
    # rather than one.
    specs = {"csetval": "(fun n => (n * (3 : UInt64)))",
             "branched": "(fun n => (if ((n) ^^^ 0x8000000000000000) > "
                         "((3 : UInt64) ^^^ 0x8000000000000000) then "
                         "(n * (3 : UInt64)) else (0 : UInt64)))"}
    path = os.path.join(tmpdir, "csetval_proof.lean")
    with open(path, "w") as f:
        f.write(generate_dylib_proof(code, info, exports, specs))
    text = open(path).read()
    check(_re.search(r"Contracts\.agrees_of_body dylib_image "
                     r"dylib_export_\d+_csetval bodyI", text),
          "the cset-bearing export got no proved contract, so a step that "
          "chooses a VALUE is still being read as a step that chooses a pc")
    check(not _re.search(r"agrees_of_body dylib_image "
                         r"dylib_export_\d+_branched", text)
          and _re.search(r"theorem dylib_export_\w+_branched_spec\b", text),
          "the branching export must keep its NAMED obligation and get no "
          "contract: a block layer that accepted a real branch would be a "
          "theorem about a machine this path does not step")
    root = HERE
    if not find_lean(root):
        print("    SKIP: no lean found (the emitted file is not typechecked)")
        return
    from formal.lean import check_proof_cached
    ok, detail, _, n = check_proof_cached(path, repo_root=root)
    check(ok, "lean rejected a contract for a block whose steps choose values: "
              f"{detail[-400:]}")
    check(n == 1, f"the proof admits {n} hole(s); the cset-bearing contract "
                  f"should be proved, so the only hole left is the branching "
                  f"export's named `_spec`")


TESTS = [
    ("dylib structure and export trie", test_dylib_structure_and_exports),
    ("the manifest offers nothing the image does not define",
     test_the_manifest_offers_nothing_the_image_does_not_define),
    ("an export symbol that already begins with an underscore",
     test_an_export_symbol_that_already_begins_with_an_underscore),
    ("exported functions execute", test_exported_functions_execute),
    ("a symbol that prefixes another is still exported",
     test_a_symbol_that_prefixes_another_is_still_exported),
    ("--no-prove skips proof generation", test_no_prove_skips_proof),
    ("default path emits a checked proof", test_default_prove_emits_checked_proof),
    ("a wrong spec is rejected, not believed",
     test_a_wrong_spec_is_rejected_not_believed),
    ("several exports, and one with no derivable spec",
     test_several_exports_and_no_derivable_spec),
    ("an export that binds a local still gets a proved contract",
     test_an_export_that_binds_a_local_still_gets_a_proved_contract),
    ("a conditional expression derives a spec",
     test_a_conditional_expression_derives_a_spec),
    ("a conditional value is not a branch",
     test_a_conditional_value_is_not_a_branch),
    ("a wrong spec on a multi-export image is rejected",
     test_a_wrong_spec_on_a_multi_export_image_is_rejected),
    ("overloads build and export once", test_overloads_do_not_collide),
    ("same name in two modules", test_same_name_in_two_modules),
    ("a library source can use a sibling source's struct",
     test_a_library_source_can_use_a_sibling_sources_struct),
    ("module with no public functions rejected", test_private_only_module_rejected),
    ("the refusal names the real reason", test_refusal_names_the_real_reason),
    ("a dylib is built for the requested arch",
     test_dylib_is_built_for_the_requested_arch),
    ("a proved dylib is an arm64 artifact, and says so",
     test_a_proved_dylib_is_an_arm64_artifact_and_says_so),
    ("executable links a dylib and runs", test_executable_links_a_dylib),
    ("dylib calls out to libSystem", test_dylib_calls_out_to_libSystem),
    ("a frame parameter's contract is published, not empty",
     test_frame_params_are_published_not_empty),
("no module under lib/ admits a sorry or an admit",
     test_the_library_admits_no_hole),
    ("a receiver write-back is not a returned frame",
     test_a_receiver_writeback_is_not_a_returned_frame),
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
