#!/usr/bin/env python3
"""test_struct_formal.py -- `struct.mojo` is byte-for-byte CPython's `struct`.

The formal backends refused seven files in this repository because they
`import struct` and `struct` was in `formal/imports.py`'s HOST_MODELLED
("reachable in principle, not implemented"). `struct.mojo` implements it, and
this file is the evidence that the implementation is RIGHT rather than merely
present.

**Why byte-for-byte and not "it built".** A byte packer that is subtly wrong is
the worst thing in this tree to get wrong quietly: every caller here writes
Mach-O and ELF headers, so a wrong byte is a malformed binary that still links.
The oracle is CPython's own `struct` — this process's — so every case computes
the expected bytes with `struct.pack` and requires the formal-built program's
output to match them exactly.

**What is compared.** A formal program cannot print a list, so each case emits
one integer per assertion and this file compares them element-wise against the
CPython answer. The three axes that matter:

  * `calcsize` — every format string in the corpus, all thirteen.
  * `pack` — the bytes themselves, read back out of the returned list and
    reassembled, for every format `pack` can serve.
  * `pack_into` / `unpack_from` — the round trip through a CALLER-owned
    buffer, which is the form the corpus's patching call sites use and the
    only one whose lifetime is sound (a list built inside a function lives in
    that function's frame; see `struct.mojo`'s limit 4).

**What is deliberately not here.** `<IIQQQQQQ` and `<4sBBBBBBB5x` are two
corpus formats `pack` cannot serve — eight values do not fit the eight
argument registers once the format takes one. `struct.mojo` returns an empty
list for them rather than a wrong answer, and `test_unservable_formats_are_refused_not_wrong`
pins that it does so.

Run:  python3 test_struct_formal.py [-v]
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60

# Values chosen to exercise the parts that are easy to get wrong, not to be
# round numbers: every one has a non-zero byte in every position of its width,
# so a byte that is dropped, duplicated, or emitted at the wrong shift shows
# up as a difference rather than cancelling out in a sum.
V_I1 = 0xd65f03c0        # a real `ret` instruction, and the corpus's own
V_I2 = 0x11223344
V_I3 = 0xffffffff        # all bits set: catches a mask that is too narrow
V_Q1 = 0x1122334455667788
V_Q2 = 0x99aabbccddeeff00
V_Q3 = 0xffffffffffffffff
V_NEG = 0 - 5            # signed: the arithmetic-shift case

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f": {detail}" if detail else ""), flush=True)
    return bool(ok)


def build_and_run(tmpdir, name, source):
    """Compile `source` through the formal arm64 backend and run it.

    Returns the stdout lines, or raises AssertionError with the build output —
    a build failure is a test failure here, never a skip: `struct.mojo` is in
    this repository and a program that imports it must build.
    """
    path = os.path.join(tmpdir, f"{name}.py")
    with open(path, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, f"{name}.bin")
    result = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "-o", out, path],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    if result.returncode != 0:
        raise AssertionError(
            f"build failed: {(result.stderr or result.stdout).strip()[-600:]}")
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    return [ln for ln in run.stdout.split("\n") if ln.strip() != ""]


def expect_lines(tmpdir, name, source, expected, what):
    """The program's printed integers must equal `expected`, element-wise."""
    try:
        got = build_and_run(tmpdir, name, source)
    except AssertionError as e:
        check(False, what, str(e))
        return None
    if not check(len(got) == len(expected), what,
                 f"expected {len(expected)} numbers, program printed "
                 f"{len(got)}: {got}"):
        return None
    bad = [(i, g, e) for i, (g, e) in enumerate(zip(got, expected))
           if int(g) != e]
    check(not bad, what,
          f"{len(bad)} of {len(expected)} differ, first: "
          + ", ".join(f"line {i}: got {g}, CPython says {e}"
                      for i, g, e in bad[:4]))
    return got


# ── 1. the corpus, DISCOVERED from the tree rather than listed ───────────────

def discover_corpus_formats():
    """Every format-shaped string literal in the files that import `struct`.

    Discovered, not listed, and that is the point. An earlier version of this
    file listed the thirteen formats the SWEEP reported — the seven files it
    blocks — and a byte-for-byte comparison against all thirteen passed while
    `formal/build.py` used two more (`<II`, `<8I`) that no list mentioned.
    `build.py` was not in the sweep's seven because it is not itself blocked on
    `import struct`; it is blocked on `json`, further down. A hand-kept list is
    a list of what somebody remembered, and this is the test that would have
    caught its own blind spot if it had been reading the tree.
    """
    import glob
    import re
    pat = re.compile(r'"(<[bBhHiIlLqQfdspcx?0-9]{1,14})"')
    out = set()
    for path in sorted(glob.glob(os.path.join(HERE, "formal", "*.py"))) + \
            [os.path.join(HERE, "test_x86_64_decode.py")]:
        with open(path) as f:
            text = f.read()
        if "import struct" not in text:
            continue
        for m in pat.finditer(text):
            fmt = m.group(1)
            try:
                struct.calcsize(fmt)
            except struct.error:
                continue          # not a format after all (e.g. "<8I" typo)
            out.add(fmt)
    return sorted(out)


CORPUS_FORMATS = discover_corpus_formats()


def test_the_corpus_was_discovered_and_is_not_empty(_tmpdir=None):
    """The discovery found something, and found more than the sweep's seven.

    A discovery that silently returned nothing would make every other test in
    this file vacuous — which is exactly how a test stops testing anything
    without going red. The floor is the seven formats the sweep's blocked files
    use; the ceiling is asserted by `test_every_corpus_format_is_implemented`
    below, which is the check that would fail if a format were missed.
    """
    check(len(CORPUS_FORMATS) >= 13,
          f"the corpus was walked and yielded {len(CORPUS_FORMATS)} formats, "
          f"expected at least 13: {CORPUS_FORMATS}")
    for f in ("<I", "<i", "<Q", "<q", "<QQ", "<II", "<8I"):
        check(f in CORPUS_FORMATS,
              f"{f} is one of the discovered corpus formats")


def test_every_corpus_format_is_implemented(tmpdir):
    """`calcsize` answers for every format the corpus uses — the gap check.

    The test that would have caught `<II` being missing: a format the table does
    not know returns 0, and 0 is a plausible-looking answer rather than an
    error, so a missing format is invisible unless something compares against
    CPython for every discovered format.
    """
    for fmt in CORPUS_FORMATS:
        src = (f'from struct import calcsize\n\ndef main():\n'
               f'    print(calcsize("{fmt}"))\n')
        expect_lines(tmpdir, f"corpus_{fmt.strip('<>')}", src,
                     [struct.calcsize(fmt)],
                     f'calcsize("{fmt}") == {struct.calcsize(fmt)} '
                     f'(every corpus format is implemented)')


def test_calcsize_each_format(tmpdir):
    """Each format's own size, not just the sum.

    A summed case cannot say WHICH format was wrong, and a dispatcher that
    produced the right total for the wrong reasons is exactly what passes one.
    """
    for fmt in CORPUS_FORMATS:
        src = (f'from struct import calcsize\n\ndef main():\n'
               f'    print(calcsize("{fmt}"))\n')
        expect_lines(tmpdir, f"calcsize_{fmt.strip('<>')}", src,
                     [struct.calcsize(fmt)],
                     f'calcsize("{fmt}") == {struct.calcsize(fmt)}')


# ── 2. pack, byte for byte ───────────────────────────────────────────────────

def _pack_program(fmt, values, n_slots):
    """A program that packs `values` and prints each resulting byte.

    The bytes come back out of the returned list one at a time, because a
    formal program cannot print a list — and `print` of a subscript is refused
    without a binding first, so each byte goes through a named local. That
    refusal is a property of `print`, not of `struct`, and the binding is the
    documented way round it.

    `n_slots` is how many arguments the call supplies: `struct.pack` takes the
    format plus seven value slots and reads only what the format names.
    """
    args = ", ".join(str(v) for v in values)
    if len(values) < n_slots:
        args += ", 0" * (n_slots - len(values))
    body = "\n".join(
        f"    x{i} = b[{i}]\n    print(x{i})"
        for i in range(struct.calcsize(fmt)))
    return ("from struct import pack\n\n"
            f"def main():\n    b = pack(\"{fmt}\", {args})\n{body}\n")


def test_pack_single_value_formats(tmpdir):
    """`<I`, `<i`, `<Q`, `<q`: the 122 of 130 call sites that pack one value.

    Each byte is printed, so the comparison is against `struct.pack`'s exact
    output and not a summary of it. The all-ones and negative cases are the
    ones that catch a mask that is too narrow or a shift that is not
    arithmetic.

    CPython RANGE-CHECKS the signed codes (`struct.pack('<i', 0xd65f03c0)`
    raises), so a signed case only ever carries a value in range — the point
    of the check is that a negative value's bytes are two's complement, and an
    out-of-range one is an error CPython raises and this path has no way to.
    """
    cases = [
        ("<I", V_I1), ("<I", V_I2), ("<I", V_I3),
        ("<i", 0x7ffffff), ("<i", V_NEG),
        ("<Q", V_Q1), ("<Q", V_Q3),
        ("<q", V_Q1), ("<q", V_NEG),
    ]
    for i, (fmt, value) in enumerate(cases):
        expect_lines(tmpdir, f"pack{i}", _pack_program(fmt, [value], 7),
                     list(struct.pack(fmt, value)),
                     f'pack("{fmt}", {value}) is CPython\'s bytes')


def test_pack_multi_value_formats(tmpdir):
    """The multi-value formats `pack` can serve, each byte compared.

    `<QQ` and `<QQq` and `<III` and `<HH` and `<HHHHHH` — every corpus format
    naming at most seven values, which is what the eight argument registers
    allow once the format has taken one.
    """
    cases = [
        ("<QQ", [V_Q1, V_Q2]),
        ("<QQ", [V_Q3, 0]),
        ("<QQq", [V_Q1, V_Q2, V_NEG]),
        ("<III", [V_I1, V_I2, V_I3]),
        ("<II", [V_I1, V_I2]),
        ("<HH", [0x1111, 0x2222]),
        ("<HHHHHH", [1, 2, 3, 4, 5, 6]),
    ]
    for i, (fmt, values) in enumerate(cases):
        expect_lines(tmpdir, f"packmv{i}", _pack_program(fmt, values, 7),
                     list(struct.pack(fmt, *values)),
                     f'pack("{fmt}", {values}) is CPython\'s bytes')


# ── 3. pack_into / unpack_from: the round trip through a caller's buffer ────

def test_pack_into_matches_cpython(tmpdir):
    """`pack_into` writes CPython's bytes into the caller's buffer.

    This is the form the twelve `pack_into` call sites use, and the only one
    whose result is lifetime-sound: the buffer is the CALLER's list, so
    nothing built inside `struct.mojo` has to outlive the call.
    """
    cases = [
        ("<I", [V_I1]),
        ("<I", [V_I3]),
        ("<Q", [V_Q1]),
        ("<Q", [V_Q2]),
        ("<q", [V_NEG]),
        ("<III", [V_I1, V_I2, V_I3]),
        ("<QQ", [V_Q1, V_Q2]),
        ("<II", [V_I1, V_I2]),
    ]
    for i, (fmt, values) in enumerate(cases):
        size = struct.calcsize(fmt)
        expect_lines(tmpdir, f"packinto{i}", _pack_into_program(fmt, values,
                                                                size),
                     list(struct.pack(fmt, *values)),
                     f'pack_into("{fmt}", {values}) is CPython\'s bytes')


def _pack_into_program(fmt, values, size):
    args = ", ".join(str(v) for v in values)
    while len(values) < 5:
        args += ", 0"
        values = list(values) + [0]
    zeros = ", ".join(["0"] * size)
    body = "\n".join(f"    x{j} = buf[{j}]\n    print(x{j})"
                     for j in range(size))
    return ("from struct import pack_into\n\n"
            "def main():\n"
            f"    buf = [{zeros}]\n"
            f'    pack_into("{fmt}", buf, 0, {args})\n{body}\n')


def test_pack_into_at_offset(tmpdir):
    """A non-zero offset, which is what the patching call sites use.

    `formal/arm64.py` patches at `idx` and `idx + 4` into a section that is
    already built, so an implementation that only ever wrote at offset 0 would
    pass everything above and corrupt every Mach-O this compiler emits.
    """
    size = 12
    fmt = "<II"
    src = ("from struct import pack_into\n\n"
           "def main():\n"
           f"    buf = [{', '.join(['0'] * size)}]\n"
           f'    pack_into("{fmt}", buf, 4, {V_I1}, {V_I2})\n'
           + "\n".join(f"    x{j} = buf[{j}]\n    print(x{j})"
                       for j in range(size))
           + "\n")
    expected = [0] * 4 + list(struct.pack(fmt, V_I1, V_I2))
    expect_lines(tmpdir, "packinto_off", src, expected,
                 "pack_into at a non-zero offset writes CPython's bytes there")


def test_unpack_from_round_trip(tmpdir):
    """What `pack_into` wrote, `unpack_from` reads back as the same numbers.

    The round trip is the property the corpus actually depends on:
    `formal/arm64.py` packs an instruction, patches it in place, and later
    reads the same word back out to mask fields out of it.
    """
    cases = [
        ("<I", [V_I1]),
        ("<I", [V_I3]),
        ("<Q", [V_Q1]),
        ("<III", [V_I1, V_I2, V_I3]),
        ("<II", [V_I1, V_I2]),
    ]
    for i, (fmt, values) in enumerate(cases):
        size = struct.calcsize(fmt)
        args = ", ".join(str(v) for v in values)
        while len(values) < 5:
            args += ", 0"
            values = list(values) + [0]
        zeros = ", ".join(["0"] * size)
        n = len(struct.unpack(fmt, bytes(size)))
        body = "\n".join(f"    y{j} = v[{j}]\n    print(y{j})"
                         for j in range(n))
        src = ("from struct import pack_into, unpack_from\n\n"
               "def main():\n"
               f"    buf = [{zeros}]\n"
               f'    pack_into("{fmt}", buf, 0, {args})\n'
               f'    v = unpack_from("{fmt}", buf, 0)\n{body}\n')
        expect_lines(tmpdir, f"roundtrip{i}", src,
                     list(struct.unpack(fmt,
                                        struct.pack(fmt, *values[:n]))),
                     f'pack_into/unpack_from round trip for "{fmt}"')


def test_unpack_from_eight_values(tmpdir):
    """`<8I`: eight values read out of one buffer, which `build.py` does.

    `formal/build.py` reads a dylib's 32-byte header with
    `struct.unpack_from("<8I", data, 0)` and a load command with
    `struct.unpack_from("<II", data, pos)`. Eight is the widest `unpack_from`
    has to serve and it is the one shape with no `pack` counterpart, so a
    buffer is filled directly and every one of the eight words is compared —
    the all-ones word is in the middle rather than first, so a reader that
    stopped early would be caught.
    """
    words = [0x01020304, 0x11223344, 0xffffffff, 0, 0, 0, 0, 0xdeadbeef]
    buf = []
    for w in words:
        b = struct.pack("<I", w)
        buf += list(b)
    literals = ", ".join(str(x) for x in buf)
    body = "\n".join(f"    y{j} = v[{j}]\n    print(y{j})"
                     for j in range(len(words)))
    src = ("from struct import unpack_from\n\n"
           "def main():\n"
           f"    buf = [{literals}]\n"
           '    v = unpack_from("<8I", buf, 0)\n' + body + "\n")
    expect_lines(tmpdir, "unpack8", src, words,
                 'unpack_from("<8I") reads all eight words CPython would')


# ── 4. the formats pack cannot serve, refused rather than wrong ──────────────

def test_unservable_formats_are_refused_not_wrong(tmpdir):
    """A format needing more values than registers returns nothing.

    `<IIQQQQQQ` names eight values and `<4sBBBBBBB5x` names eight, and the
    format itself takes one of the eight argument registers — so those values
    have nowhere to arrive. `struct.mojo` returns an empty list rather than a
    plausible wrong answer, and this pins that: an empty list prints nothing,
    while a wrong answer would print eight bytes and the caller would splice
    them into a header.
    """
    for fmt, values in (("<IIQQQQQQ", [1] * 8),
                        ("<4sBBBBBBB5x", [1] * 8)):
        args = ", ".join(str(v) for v in values)
        while len(values) < 7:
            args += ", 0"
            values = list(values) + [0]
        # A refused pack yields an empty list, and a list literal is the only
        # shape this path can print a length for — so the program counts the
        # bytes itself and prints the count.  A WRONG answer would print the
        # format's real size and the check below would see it.
        size = struct.calcsize(fmt)
        src = ("from struct import pack\n\n"
               "def main():\n"
               f'    b = pack("{fmt}", {args})\n'
               "    n = 0\n"
               f"    i = 0\n    while i < {size}:\n"
               "        if b[i] == b[i]:\n"
               "            n = n + 1\n"
               "        i = i + 1\n"
               "    print(n)\n")
        try:
            got = build_and_run(tmpdir, f"refuse_{fmt.strip('<>')}", src)
        except AssertionError as e:
            check(False, f'pack("{fmt}") is refused, not wrong', str(e))
            continue
        # Reading b[i] for i in 0..size-1 of an EMPTY list exits(1) rather
        # than printing, so a refusal shows up as a nonzero exit; a wrong
        # answer would print `size`. Accept either "printed 0" or "the read
        # of the empty list stopped the program".
        run = subprocess.run(
            [os.path.join(tmpdir, f"refuse_{fmt.strip('<>')}.bin")],
            capture_output=True, text=True, timeout=RUN_TIMEOUT)
        refused = (got == ["0"]) or (run.returncode != 0)
        check(refused,
              f'pack("{fmt}") must produce nothing (it needs 8 values and '
              f"only 8 argument registers exist, one of which is the format); "
              f"the program instead read {size - len(got)} of {size} bytes "
              f"and exited {run.returncode}")


# ── 5. the module is where the resolver looks, and the corpus imports it ─────

def test_module_resolves_and_is_exported(tmpdir):
    """`struct` resolves to `struct.mojo` and exports the four entry points.

    Without this the byte tests above would pass against a module the
    importer cannot reach, which is the shape of bug the HOST_MODELLED entry
    was: the file existed as far as `import struct` was concerned only if
    something answered it.
    """
    sys.path.insert(0, HERE)
    try:
        import formal.imports as I
    finally:
        sys.path.pop(0)
    path = I.resolve_module_path("struct", relative_to=os.path.join(
        HERE, "formal", "arm64.py"), project_root=os.path.join(
        HERE, "formal", "arm64.py"))
    check(path is not None and os.path.basename(path) == "struct.mojo",
          "`import struct` resolves to struct.mojo for a formal/arm64.py "
          f"importer; got {path!r}")
    check("struct" not in I.HOST_MODELLED,
          "`struct` is no longer in HOST_MODELLED — the entry claimed the "
          "module was reachable but unimplemented, and it is implemented")
    if path:
        with open(path) as f:
            text = f.read()
        for fn in ("def pack(", "def pack_into(", "def unpack_from(",
                   "def calcsize("):
            check(fn in text, f"struct.mojo exports {fn[:-1]}()")


def test_struct_is_a_builtin_name_not_a_host_module(tmpdir):
    """The build refuses a file that imports an UNIMPLEMENTED host module.

    The negative control for the test above: if `struct` had merely been
    renamed rather than implemented, `import struct` would resolve to nothing
    and this is the message that would come back instead.
    """
    with tempfile.TemporaryDirectory() as d:
        prog = os.path.join(d, "p.py")
        with open(prog, "w") as f:
            f.write("import struct\n\ndef main():\n    return 0\n")
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove", prog],
            capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
        text = r.stderr + r.stdout
        check("host module" not in text,
              "`import struct` is no longer refused as a host module; got: "
              f"{text.strip()[-300:]}")


# ── 6. the seven files that import struct ───────────────────────────────────

IMPORTERS = ["formal/arm64.py", "formal/elf.py", "formal/macho.py",
             "formal/macho_linker.py", "formal/x86_64.py",
             "formal/x86_64_decode.py", "test_x86_64_decode.py"]


def test_the_seven_importers_no_longer_refuse_on_the_import(tmpdir):
    """None of the seven is refused for `struct` any more.

    The measurement this whole change exists for. Each file is BUILT, and the
    verdict checked is specifically that `struct` is no longer what stops it.
    Four of them still fail — on `typing`, `enum`, `dataclasses` and `sys`,
    which are OTHER unimplemented host modules and are other workers' claims —
    and a file that has moved from "blocked on struct" to "blocked on enum" is
    exactly the progress this is meant to make. What must NOT happen is the
    `struct` message coming back, which is why the check looks for the module
    NAME in the refusal rather than for success.
    """
    for rel in IMPORTERS:
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            check(False, f"{rel} exists")
            continue
        try:
            r = subprocess.run(
                [sys.executable, FIRE, "build", "--formal", "--no-prove",
                 "-o", os.path.join(tmpdir, os.path.basename(rel) + ".bin"),
                 path],
                capture_output=True, text=True, timeout=600, cwd=HERE)
        except subprocess.TimeoutExpired:
            check(False, f"{rel} builds (timed out at 600s)")
            continue
        text = r.stderr + r.stdout
        check("imports 'struct'" not in text,
              f"{rel} is no longer refused for importing `struct`",
              text.strip()[-300:])


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    tests = [
        test_the_corpus_was_discovered_and_is_not_empty,
        test_every_corpus_format_is_implemented,
        test_calcsize_each_format,
        test_pack_single_value_formats,
        test_pack_multi_value_formats,
        test_pack_into_matches_cpython,
        test_pack_into_at_offset,
        test_unpack_from_round_trip,
        test_unpack_from_eight_values,
        test_unservable_formats_are_refused_not_wrong,
        test_module_resolves_and_is_exported,
        test_struct_is_a_builtin_name_not_a_host_module,
        test_the_seven_importers_no_longer_refuse_on_the_import,
    ]
    with tempfile.TemporaryDirectory(prefix="struct_formal_") as tmpdir:
        for t in tests:
            before = len(RESULTS)
            try:
                t(tmpdir)
            except Exception as e:            # a raising test is a failed test
                check(False, f"{t.__name__} raised", repr(e))
            if args.verbose:
                for ok, what in RESULTS[before:]:
                    print(f"  {'ok  ' if ok else 'FAIL'}  {what}")

    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
