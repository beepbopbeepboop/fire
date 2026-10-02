#!/usr/bin/env python3
"""Build `hashlib` for the formal backend and RUN it, compared BYTE FOR BYTE
with CPython's own digests.

    python3 test_formal_hashlib.py [-v] [group ...]

Why an oracle rather than a table of expected digests. A digest is a pure
function of its input: `sha256(b"abc")` has one answer forever, and a table of
those answers is a table that is wrong the moment someone transposes a
character. So every case here is computed twice — once through
`python3 fire.py build --formal --no-prove` and executed, once through
`hashlib` in this process — and the two hex strings have to be equal. Nothing
in this file states what `sha256("abc")` is; it asks.

The BLAKE2b group is the reason this file is longer than the module. BLAKE2b
is computed from scratch in `formal/hostmods/hashlib.mojo` (libSystem has no
BLAKE2), so it is the only export with real arithmetic in it, and the inputs
are chosen for the SHAPES rather than the values:

  * every length from 0 to 139, which covers the empty message, the
    single-block case, the 127/128/129 boundary where the last-block rule
    changes, and the two-block case;
  * digest sizes 1, 16, 20, 32, 48 and 64, because BLAKE2b's `digest_length`
    is part of the INITIAL STATE, so `digest_size=20` is a different hash and
    not a prefix of the 64-byte one — a real and easy thing to get wrong;
  * a seeded random spread of lengths past 139, so the property is not only
    checked at boundaries.

That last point is load-bearing for this module in particular. Writing
BLAKE2b meant working around FOUR separate defects in the backend, three of
which produce plausible wrong answers rather than refusals:

  * the immediate `lsl` encoder carried a base opcode with stray bits in `immr`
    (`0xd3780000` where its own docstring said `0xd3400000`), so a shift
    AMOUNT was corrupted while `Rn`/`Rd` stayed right — `1 << 12` returned
    `16`, and only amounts 1-8, whose intended `immr` already had those bits
    set, came out correct. `test_arm64_encoders.py` now sweeps all three shift
    encoders over the whole 0..63 range for exactly that reason, and its
    comment there is where this now lives.
  * a ninth argument was silently dropped rather than refused: a cross-module
    call whose arity exceeded the eight the arm64 ABI passes in registers
    produced a plausible answer from the wrong registers instead of a
    diagnosis. `test_formal_run.py` asserts the refusal, and
    `formal/build.py` emits it.
  * `UInt64 >> Int` shifted ARITHMETICALLY, because the shift AMOUNT's type
    was promoted into the decision that the VALUE's type should make. Fixed:
    `formal/model.py`'s `shift_signedness` reads the LEFT operand alone, and
    `test_formal_run.py` carries the five rows. The bug's doc is deleted with
    its fix; the one durable thing in it was a fact about the LANGUAGE rather
    than about this compiler, and it is `FORMAL.md` §4 decision 5 — `>>` on a
    signed value is arithmetic, so a "make every `>>` logical" fix would have
    passed that document's own repro and broken Python, and `>>>` is not the
    way to spell the alternative because it does not parse here and CPython
    3.14.7 rejects it too.
  * a shift of 64 or more WRAPPED (the amount was masked to the register width)
    instead of saturating. The rule is `formal/model.py`'s
    `shift_saturated_is_zero`, and both backends branch on it.

Each was found by bisecting a digest that was wrong, and each is guarded here
by the same assertion that found it: the digest must equal CPython's.

Building and RUNNING, not building. `test_formal.py` typechecks the generated
proof and never executes the image; every case here exits with a status this
file checks.

    --backend=x86_64 runs the WHOLE file on the other codegen, and it is not a
    repeat of the arm64 run. `hashlib.mojo` used to be refused outright for
    x86-64 — `b2_g: 7 parameters exceeds the 6 …` and, behind that, an
    `encode_mov_r64_imm64` that CRASHED on any 64-bit constant with bit 63 set,
    which is four of BLAKE2b's eight IVs — so there was no x86-64 digest to
    compare and this file could only ever ask one architecture. Two backends
    that lower the same module are two lowerings of it, and a digest is exactly
    the thing where a second lowering can be wrong without failing to build.

Groups: `commoncrypto`, `blake2b`, `raw`, `absent`. With no argument, all.
"""
import argparse
import hashlib
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 120

# The record terminator. NOT a newline: `\n` inside a Mojo string literal is
# not unescaped on this path — a formal image prints the two characters `\` and
# `n` — so every program here emits its records back to back. Same convention,
# and the same reason, as `test_formal_os.py` and `test_formal_time.py`.
REC = "@@"

TEMP = None


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def mojo_string(s):
    """A Mojo string literal for `s`."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


BACKEND = None      # None = the default (arm64); `--backend` on the command line


def build(src, name):
    """Build `src` through the formal backend, on `BACKEND`.

    The module is compiled for BOTH architectures and every group here is
    executed on the one this process selected, so the digests are checked
    against CPython on each rather than on one and assumed for the other.
    """
    tmp = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, name)
    with open(tmp, "w") as f:
        f.write(src)
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove"]
    if BACKEND:
        argv.append("--backend=%s" % BACKEND)
    argv += ["-o", out, tmp]
    r = subprocess.run(argv,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"build failed: {(r.stderr or r.stdout).strip()[-500:]}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def run(out):
    r = subprocess.run([out], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT, cwd=HERE)
    check(r.returncode == 0, f"image exited {r.returncode}: "
                             f"{(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


# ── the messages every group is run over ────────────────────────────────────
#
# Chosen for shapes, not for words, and the same set in every group so a
# failure in one is comparable with a failure in another:
#
#   ""        the empty message, which is one all-zero block
#   "a"       one byte
#   "abc"     the RFC 7693 known-answer vector for BLAKE2b
#   "ab"      two bytes — one byte PAST the point where a 16-bytes-per-word
#             reading of the block and an 8-bytes-per-word reading stop
#             agreeing, which is the bug that made the first BLAKE2b here
#             correct for short messages and wrong for every other one
#   "0123456789abcdef"  exactly 16 bytes, one full message word
#   a 200-byte run and a 300-byte run, for the two-block and three-block paths
MESSAGES = [
    "", "a", "ab", "abc", "0123456789abcdef",
    "The quick brown fox jumps over the lazy dog",
    "x" * 200, "y" * 300, "z" * 1000,
]

# The six digests libSystem provides, and their output sizes. Asked of
# libSystem with dlsym before any of them was relied on; see the module.
COMMONCRYPTO = [
    ("md5", 16), ("sha1", 20), ("sha224", 28),
    ("sha256", 32), ("sha384", 48), ("sha512", 64),
]


def _records(text, pattern):
    return dict(re.findall(pattern + REC, text))


def _chunks(items, n):
    """`items` in lists of at most `n`.

    Needed because a generated program of a few hundred statements makes the
    backend's own `_always_returns` walk recurse past Python's limit — a
    `RecursionError` out of `formal/arm64_codegen.py`, i.e. a crash in the
    compiler's plumbing rather than a claim about the source. Chunking keeps
    each program small enough to compile. Filed as
    `bugs/FORMAL_always_returns_recurses_past_the_stack_on_a_large_function.md`;
    until it is fixed, a test that needs many cases builds many small programs
    rather than one large one.
    """
    for i in range(0, len(items), n):
        yield i // n, items[i:i + n]


def group_commoncrypto(tmpdir, verbose):
    """Every CommonCrypto digest, every message, against CPython."""
    expected = {}
    for i, msg in enumerate(MESSAGES):
        lit = mojo_string(msg)
        for name, size in COMMONCRYPTO:
            expected[f"{name}_{i}"] = hashlib.new(name, msg.encode()).hexdigest()
    got = {}
    for chunk, keys in _chunks(sorted(expected), 24):
        lines = ["import hashlib", "", "def main() -> int:"]
        for k in keys:
            name, i = k.rsplit("_", 1)
            msg = MESSAGES[int(i)]
            lines.append(f'  printf("{k}=%s@@", '
                         f'hashlib.{name}({mojo_string(msg)}, {len(msg)}))')
        lines.append("  return 0")
        got.update(_records(run(build("\n".join(lines) + "\n", "cc")),
                            r"([a-z0-9_]+)=([0-9a-f]*)"))
    check(len(got) == len(expected),
          f"got {len(got)} records for {len(expected)} cases")
    bad = [(k, v, expected[k]) for k, v in got.items() if v != expected[k]]
    check(not bad,
          f"{len(bad)}/{len(got)} digests differ from CPython"
          + (f"; first: {bad[0][0]} got {bad[0][1][:24]} "
             f"want {bad[0][2][:24]}" if bad else ""))
    if verbose:
        print(f"    {len(got)} CommonCrypto digests byte-exact")
    return True, f"{len(got)} digests byte-exact"


# ── BLAKE2b ─────────────────────────────────────────────────────────────────

def blake2b_lengths():
    """The message lengths the BLAKE2b group runs over. See the module docstring."""
    import random
    random.seed(23)
    lens = list(range(0, 140))
    lens += [199, 200, 201, 255, 256, 257, 300, 383, 384, 385, 1000]
    lens += [random.randrange(140, 5000) for _ in range(40)]
    return lens


BLAKE2B_DIGEST_SIZES = [64, 32, 20, 16, 1, 48]


def _bnkey(k):
    """Sort key for a `b<len>_<size>` record name: by length, then size.

    Numeric rather than lexicographic, so the chunks are ordered by message
    length and a failure in the first chunk is about a short message — where
    the 8-vs-16-bytes-per-word block-reading bug lives.
    """
    n, d = k[1:].split("_")
    return (int(n), int(d))


def group_blake2b(tmpdir, verbose):
    lens = blake2b_lengths()
    expected = {}
    for n in lens:
        for d in BLAKE2B_DIGEST_SIZES:
            expected[f"b{n}_{d}"] = hashlib.blake2b(
                b"a" * n, digest_size=d).hexdigest()
    got = {}
    for _, chunk in _chunks(sorted(expected, key=_bnkey), 24):
        lines = ["import hashlib", "", "def main() -> int:"]
        for k in chunk:
            n, d = k[1:].split("_")
            n = int(n)
            lines.append(f"  var m{n}: Pointer[UInt8] = malloc({max(n, 1)})")
            lines.append(f"  memset(m{n}, 97, {n})")
            lines.append(f'  printf("{k}=%s@@", '
                         f'hashlib.blake2b_hex(m{n}, {n}, {d}))')
        lines.append("  return 0")
        got.update(_records(run(build("\n".join(lines) + "\n", "b2")),
                            r"(b\d+_\d+)=([0-9a-f]*)"))
    check(len(got) == len(expected),
          f"got {len(got)} records for {len(expected)} cases")
    bad = [(k, v, expected[k]) for k, v in got.items() if v != expected[k]]
    check(not bad,
          f"{len(bad)}/{len(got)} BLAKE2b digests differ from CPython"
          + (f"; first: {bad[0][0]} got {bad[0][1][:24]} "
             f"want {bad[0][2][:24]}" if bad else ""))

    # The truncated digests are DIFFERENT HASHES, not prefixes. Asserted
    # explicitly because it is the one property of `digest_size` that a
    # plausible implementation gets wrong: returning the first 20 bytes of the
    # 64-byte digest passes every length check above and is not BLAKE2b.
    for d in (20, 32):
        full = hashlib.blake2b(b"a" * 200, digest_size=64).hexdigest()
        trunc = hashlib.blake2b(b"a" * 200, digest_size=d).hexdigest()
        check(trunc != full[:2 * d],
              f"CPython's digest_size={d} is a prefix of its 64-byte digest, "
              f"so this oracle cannot tell the two implementations apart")

    if verbose:
        print(f"    {len(got)} BLAKE2b digests byte-exact over "
              f"{len(lens)} lengths x {len(BLAKE2B_DIGEST_SIZES)} sizes")
    return True, f"{len(got)} digests byte-exact"


# ── the _raw variants ───────────────────────────────────────────────────────

RAW_PROGRAM = """\
import hashlib

def show(tag: str, n: int, out: Pointer[UInt8], size: int):
    var i = 0
    while i < size:
        printf("%s-%d=%d@@", tag, i, hashlib.byte_at(out, i))
        i = i + 1
    printf("done-%s=%d@@", tag, n)

def main() -> int:
    var d = "abc"
    var n = 3
    var a: Pointer[UInt8] = malloc(64)
    memset(a, 0, 64)
    hashlib.md5_raw(d, n, a)
    show("md5", n, a, 16)
    var b: Pointer[UInt8] = malloc(64)
    memset(b, 0, 64)
    hashlib.sha256_raw(d, n, b)
    show("sha256", n, b, 32)
    return 0
"""


def group_raw(tmpdir, verbose):
    """The `_raw` digests, byte by byte, against CPython's `.digest()`.

    Checked byte-wise rather than as a hex string because that is the point of
    the `_raw` form: it is the only way to get the digest's BYTES rather than
    its hex on this path, and a program that concatenates them is relying on
    the layout. A hex comparison would pass for a module that wrote the bytes
    in the wrong order.
    """
    got = run(build(RAW_PROGRAM, "raw"))
    bad = []
    for name, size in (("md5", 16), ("sha256", 32)):
        want = hashlib.new(name, b"abc").digest()
        vals = [int(v) for k, v in
                re.findall(rf"{name}-(\d+)=(\d+)" + REC, got)]
        check(len(vals) == size,
              f"{name}_raw wrote {len(vals)} bytes, want {size}")
        for i, (have, w) in enumerate(zip(vals, want)):
            if have != w:
                bad.append((name, i, have, w))
    check(not bad, f"{len(bad)} raw digest bytes differ from CPython; "
                   f"first: {bad[0] if bad else ''}")
    check("done-md5=3@@" in got and "done-sha256=3@@" in got,
          "a _raw call did not return 0")
    if verbose:
        print("    48 raw digest bytes byte-exact")
    return True, "48 raw bytes byte-exact"


# ── what this module cannot do ──────────────────────────────────────────────

def group_absent(tmpdir, verbose):
    """The absent names, asserted as refusals rather than left to discovery.

    Each of these is a CPython `hashlib` name with no representation on this
    target, and the module docstring says which capability each one needs
    (libSystem provides no SHA-3 and no BLAKE2s, so each would be a
    from-scratch implementation of a specification nobody has checked here;
    and SHAKE additionally needs an extendable output, which is a
    run-time-length sequence this path cannot build). An omission that is not
    pinned is indistinguishable from an implementation, so each is pinned here
    as a build that fails with a message naming the module and the name.
    """
    absent = ["blake2s", "sha3_224", "sha3_256", "sha3_384", "sha3_512",
              "shake_128", "shake_256", "new"]
    for name in absent:
        src = (f"import hashlib\n\ndef main() -> int:\n"
               f"  hashlib.{name}(b\"abc\")\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_{name}"), tmp],
            capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"hashlib.{name}() built, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"hashlib.{name}() failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent names refused"


GROUPS = {
    "commoncrypto": group_commoncrypto,
    "blake2b": group_blake2b,
    "raw": group_raw,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    ap.add_argument("--backend", default=None,
                    help="formal backend to build for (default: arm64)")
    args = ap.parse_args()
    global BACKEND
    BACKEND = args.backend
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: this host cannot run the formal images at all, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        TEMP = tmpdir
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, args.verbose)
            except Exception as e:
                import traceback
                if args.verbose:
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + name + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
