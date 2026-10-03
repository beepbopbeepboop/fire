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
        `bugs/FORMAL_x86_64_a_float_printf_operand_reads_XMM0.md`).

    Records are the `@@`-separated fields of the image's stdout, which is the
    convention every hostmod test in this tree uses: a Mojo string
    literal's BACKSLASH-N is NOT unescaped on this path, so an image
    prints the two characters backslash and `n` and a
    record-structured program has to choose its own terminator.

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
    # distinction is `FORMAL_OPUS_dylib_termination_handoff.md` §`OPUS-2`, and
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
        check(proved != named,
              f"{ident} has "
              + ("both a proved contract and a named `_spec` obligation"
                 if proved and named else
                 "neither a proved contract nor a named `_spec` obligation -- "
                 "the emitter dropped the export's claim about its own result"))
    # ... and the proved contract must be sorry-free, in its own namespace.
    # A `sorry` anywhere in the contract namespace is exactly the shape
    # `formal/admitted.py` counts, and a per-export grep is the only thing that
    # can see it: the census below reports a FILE total, which cannot say which
    # export admitted one.
    for ident in sorted(idents):
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


TESTS = [
    ("dylib structure and export trie", test_dylib_structure_and_exports),
    ("exported functions execute", test_exported_functions_execute),
    ("a symbol that prefixes another is still exported",
     test_a_symbol_that_prefixes_another_is_still_exported),
    ("--no-prove skips proof generation", test_no_prove_skips_proof),
    ("default path emits a checked proof", test_default_prove_emits_checked_proof),
    ("a wrong spec is rejected, not believed",
     test_a_wrong_spec_is_rejected_not_believed),
    ("overloads build and export once", test_overloads_do_not_collide),
    ("same name in two modules", test_same_name_in_two_modules),
    ("module with no public functions rejected", test_private_only_module_rejected),
    ("the refusal names the real reason", test_refusal_names_the_real_reason),
    ("a dylib is built for the requested arch",
     test_dylib_is_built_for_the_requested_arch),
    ("executable links a dylib and runs", test_executable_links_a_dylib),
    ("dylib calls out to libSystem", test_dylib_calls_out_to_libSystem),
    ("a frame parameter's contract is published, not empty",
     test_frame_params_are_published_not_empty),
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
