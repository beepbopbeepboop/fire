#!/usr/bin/env python3
"""The returned-frame convention: build it, RUN it, and compare with CPython.

A multi-field struct's receiver on this path is the ADDRESS of a frame of
8-byte slots in the function's own scratch, so `return p` used to hand the
caller a pointer into reclaimed stack — which is why `formal/build.py` refused
it, correctly, and why 11 of this repository's own arm64 sweep findings named
that one line. The refusal is gone because the block is now COPIED into a
block the CALLER reserves and passes the address of as one hidden trailing
argument (`model.struct_returned_frame_sites`,
`model.returned_frame_convention_refusal`).

Lifting a refusal is half the work: the image that builds in its place has to
be RIGHT, and "right" here means it runs and computes the program's answer. So
every positive case is built for BOTH architectures, EXECUTED, and its answer
compared against CPython running the same source — not against a number typed
in here, because a wrong answer that matches a mistyped constant is still a
wrong answer.

The channel is the EXIT STATUS, and that is not a limitation: a formal image's
status is its entry function's return value masked to a byte, and
`sys.exit(int)` is masked to a byte by CPython's own exit path, so the two
runtimes share an oracle exactly. It is also why no case here uses `printf`:
that is a formal builtin with no CPython counterpart, and checking its output
against a hand-written expectation would be the same failure mode with a
different hat.

The `refuse:` cases are the other half: the shapes the convention still cannot
describe must not build on either machine, and must say why in the same words.

    python3 test_formal_returned_frame.py [-v] [case ...]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BACKENDS = ("arm64", "x86_64")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60

# The argument the entry function is called with. `formal/build.py`'s
# `test_input` default is 10 and the startup stub is what passes it, so the
# oracle calls `main` with the same number rather than with whatever is
# convenient here. No case below reads it.
ENTRY_ARG = 10

# The two-field struct every case below is written in terms of.
#
# The `class` / `def __init__` SPELLING, and the reason every positive case
# uses it: it is also a Python program, so CPython can be the reference rather
# than a number written by hand. `struct R: var a: Int` is not Python syntax,
# so a case written that way has to carry its own expectation — which is the
# `expect` mode below, used exactly once, for the one shape whose reference
# Python cannot provide.
R2 = ("class R:\n"
      "    def __init__(self):\n"
      "        self.a = 0\n"
      "        self.b = 0\n"
      "    def total(self):\n"
      "        return self.a * 10 + self.b\n")

# (name, source, mode, expectation) — `ok` compares against CPython on the same
# text, `expect` is a hand-computed value with the arithmetic in the case's own
# comment, and `refuse` must fail to build on both machines naming `expectation`.
CASES = [
    # ── the plain shape, with the use-after-free it replaces ────────────
    # `clobber` builds two frames of its own between the call and the read.
    # Without the copy, the block the caller holds names the callee's reclaimed
    # scratch, and this returns one of the two frames clobber wrote instead of
    # the caller's — measured on the pre-convention tree as 10 on arm64 and 0 on
    # x86-64 where the source says 78.
    ("returned_frame_outlives_its_creator",
     R2 +
     "def mk():\n"
     "    p = R()\n"
     "    p.a = 7\n"
     "    p.b = 8\n"
     "    return p\n"
     "\n"
     "def clobber(k):\n"
     "    q = R()\n"
     "    r = R()\n"
     "    q.a = 111\n"
     "    r.a = 222\n"
     "    return k + q.a + r.a\n"
     "\n"
     "def main(n):\n"
     "    s = mk()\n"
     "    k = clobber(0)\n"
     "    return s.total() + k\n", "ok", 0),

    # ── three fields, and a THREE-SLOT copy ─────────────────────────────
    # The width is the point: the block is `8 * n` rounded up, so a copy that
    # hard-coded two slots would leave the third field at its default and this
    # would be 340 rather than 345.
    ("returned_frame_three_fields",
     "class W:\n"
     "    def __init__(self):\n"
     "        self.p = 0\n"
     "        self.q = 0\n"
     "        self.r = 0\n"
     "\n"
     "def mk(k):\n"
     "    w = W()\n"
     "    w.p = k\n"
     "    w.q = k + 1\n"
     "    w.r = k + 2\n"
     "    return w\n"
     "\n"
     "def main(n):\n"
     "    w = mk(3)\n"
     "    return w.p * 100 + w.q * 10 + w.r\n", "ok", 0),

    # ── a NESTED frame, which is the half that is easy to get wrong ─────
    # `inner` is a framed struct of this module and nothing writes it, so the
    # constructor PLACES its frame inside `Outer`'s own block and the slot
    # holds its address. A returned block has to carry those bytes AND
    # re-point the slot at the COPY: copying the bytes without re-pointing
    # leaves the caller's `o.inner` naming a frame in the callee's reclaimed
    # scratch. Two reads of the same nested field, with a call in between, is
    # what tells a re-point from a copy.
    #
    # The one `expect` case: the nested placement needs the field's DECLARED
    # type and only a `struct` field declaration carries one, so this program is
    # not a Python program and CPython cannot be its reference. The arithmetic,
    # once: `o.inner.a * 100 + o.inner.b * 10 + o.z` is 9*100 + 4*10 + 3 = 943,
    # read twice and added is 1886, and 1886 masked to a byte is 94. A copy
    # without the re-point reads the clobbered 111s and gives 22446 -> 174.
    ("returned_frame_carries_its_nested_frame",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "    var z: Int\n"
     "def mk() -> Outer:\n"
     "    var o = Outer()\n"
     "    o.inner.a = 9\n"
     "    o.inner.b = 4\n"
     "    o.z = 3\n"
     "    return o\n"
     "def clobber(k: Int) -> Int:\n"
     "    var q = Inner()\n"
     "    q.a = 111\n"
     "    q.b = 111\n"
     "    return k + q.a\n"
     "def main(n: Int) -> Int:\n"
     "    var o = mk()\n"
     "    var s = o.inner.a * 100 + o.inner.b * 10 + o.z\n"
     "    var k = clobber(0)\n"
     "    var t = o.inner.a * 100 + o.inner.b * 10 + o.z\n"
     "    return s + t\n", "expect", 94),

    # ── a frame RECEIVED as a parameter, handed straight back ───────────
    # The creator is the caller, and the copy happens while the caller's frame
    # is still live — which is the whole of what makes this sound, and the
    # reason the old refusal ("returned from a function that did not create
    # it") named the right hazard and the wrong remedy.
    ("returned_frame_from_a_parameter",
     R2 +
     "def fwd(r):\n"
     "    return r\n"
     "\n"
     "def main(n):\n"
     "    r = R()\n"
     "    r.a = 4\n"
     "    r.b = 5\n"
     "    return fwd(r).a * 10 + fwd(r).b\n", "ok", 0),

    # …and through a method's receiver, which is the same copy with the
    # address arriving in the receiver's home.
    ("returned_frame_from_a_method_receiver",
     R2 +
     "    def give(self):\n"
     "        return self\n"
     "\n"
     "def main(n):\n"
     "    r = R()\n"
     "    r.a = 4\n"
     "    r.b = 5\n"
     "    return r.give().a * 10 + r.give().b\n", "ok", 0),

    # ── two live results at once, which is what killed a fixed slot ─────
    # The design rejected "the callee computes the caller's block itself"
    # precisely because one fixed slot collides here: the inner and outer
    # results must both be readable after the outer call returns. With the
    # per-call-site blocks the two are distinct addresses, and a fixed slot
    # would make both reads see the inner result.
    ("returned_frame_nested_calls_two_blocks",
     R2 +
     "def inner(k):\n"
     "    r = R()\n"
     "    r.a = k\n"
     "    r.b = 1\n"
     "    return r\n"
     "\n"
     "def outer(k):\n"
     "    t = inner(k)\n"
     "    t.b = 2\n"
     "    return t\n"
     "\n"
     "def main(n):\n"
     "    a = inner(3)\n"
     "    b = outer(7)\n"
     "    return a.total() * 100 + b.total()\n", "ok", 0),

    # ── a returned frame in a LOOP ──────────────────────────────────────
    # The block is per CALL SITE and reserved in the prologue, so a call inside
    # a loop reuses one block and the stack cannot grow without bound. Read
    # immediately, which is the only lifetime the reserved block has.
    ("returned_frame_in_a_loop",
     R2 +
     "def mk(k):\n"
     "    r = R()\n"
     "    r.a = k\n"
     "    r.b = 1\n"
     "    return r\n"
     "\n"
     "def main(n):\n"
     "    s = 0\n"
     "    for i in range(4):\n"
     "        t = mk(i)\n"
     "        s = s + t.total()\n"
     "    return s\n", "ok", 0),

    # ── a frame returned through a NON-FIRST parameter, three levels deep ──
    ("returned_frame_three_levels",
     R2 +
     "def stash(x, y):\n"
     "    return y\n"
     "\n"
     "def mid(r):\n"
     "    return stash(1, r)\n"
     "\n"
     "def main(n):\n"
     "    r = R()\n"
     "    r.a = 6\n"
     "    r.b = 7\n"
     "    p = mid(r)\n"
     "    return p.a * 10 + p.b\n", "ok", 0),

    # ── a function with more locals than callee-saved registers ─────────
    # The hidden word is an ordinary local, so it has the same two homes every
    # other local has, and this is the case that says the SPILLED home is
    # addressed the same way the register home is. Eleven locals is past
    # arm64's ten callee-saved registers and well past x86-64's five, so the
    # word spills on both. It caught a real bug: the spill half of the
    # prologue's parameter path stored the ADDRESS of the slot through the
    # register holding the value, and that path had been unreachable only
    # because nothing could make an eleventh local.
    ("returned_frame_with_spilled_locals",
     R2 +
     "def mk(k):\n" +
     "".join(f"    v{i} = {i}\n" for i in range(11)) +
     "    r = R()\n"
     "    r.a = k + v10\n"
     "    r.b = 1\n"
     "    return r\n"
     "\n"
     "def main(n):\n"
     "    s = mk(2)\n"
     "    return s.total()\n", "ok", 0),

    # ── a METHOD called on a returned frame ─────────────────────────────
    # The result is a frame, so `q.total()` is a method call whose receiver is
    # a frame address — the by-reference convention's own shape, reached
    # through the return.
    ("method_on_a_returned_frame",
     R2 +
     "    def bump(self, v):\n"
     "        self.a = self.a + v\n"
     "        return self.a\n"
     "\n"
     "def mk():\n"
     "    r = R()\n"
     "    r.a = 1\n"
     "    r.b = 2\n"
     "    return r\n"
     "\n"
     "def main(n):\n"
     "    q = mk()\n"
     "    q.bump(5)\n"
     "    return q.total() * 10 + q.bump(1)\n", "ok", 0),

    # ── the ENTRY, which has no caller to give it a block ───────────────
    ("refuse_entry_returning_a_frame",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    return r\n", "refuse",
     "is this image's ENTRY"),

    # ── a frame on one path and a value on another ──────────────────────
    # One function cannot have two return conventions in one image: the caller
    # has to decide BEFORE the call whether to reserve a block, and there is no
    # reading of this program under which both branches are right.
    ("refuse_a_frame_and_a_value_on_two_paths",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def mk(c: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    r.b = 2\n"
     "    if c:\n"
     "        return r\n"
     "    return 7\n"
     "def main(n: Int) -> Int:\n"
     "    return mk(1)\n", "refuse",
     "one function cannot have two return conventions"),

    # ── a frame on one path and the body ENDS on another ─────────────────
    # The caller's block would be read without ever being written, and the one
    # thing this path must never invent is a struct's contents. A second
    # `return` would be the previous case; this one is the shape where there is
    # nothing to return at all.
    ("refuse_a_frame_that_falls_off_the_end",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def mk(c: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    r.b = 2\n"
     "    if c:\n"
     "        return r\n"
     "    printf(\"%d\\n\", c)\n"
     "def main(n: Int) -> Int:\n"
     "    return mk(1)\n", "refuse",
     "falls off the end of its body on another"),

    # ── the hidden word has nowhere to go ────────────────────────────────
    # Six source arguments is the whole budget on the machine with the smaller
    # one (x86-64 passes integer arguments in six registers), so the seventh
    # word — the caller's block — has no register. Refused by name on both
    # machines rather than dropped, because a dropped word is a copy into
    # whatever the register held.
    ("refuse_a_callee_with_no_argument_register_left",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def mk(p0: Int, p1: Int, p2: Int, p3: Int, p4: Int, p5: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = p0 + p1 + p2 + p3 + p4 + p5\n"
     "    r.b = 2\n"
     "    return r\n"
     "def main(n: Int) -> Int:\n"
     "    return mk(1, 2, 3, 4, 5, 6).a\n", "refuse",
     "one hidden word for the caller's block"),
]


def build(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out,
           f"--backend={backend}", src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def cpython_answer(source):
    """The exit status CPython gives the same source.

    Mojo is a Python superset, which is what makes this possible at all — the
    same text is both the program's source and its reference — and a
    `SystemExit(int)` is masked to a byte by CPython's own exit path, exactly
    as a formal image's status is.
    """
    p = subprocess.run(
        [sys.executable, "-c",
         source + f"\nimport sys\nsys.exit(main({ENTRY_ARG}))\n"],
        capture_output=True, text=True, timeout=RUN_TIMEOUT, cwd=HERE)
    if p.returncode < 0:
        return f"CPython died with signal {-p.returncode}: {p.stderr[-200:]}"
    return p.returncode


def run_case(name, source, mode, expectation, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)

    if mode == "refuse":
        # Both machines, and the same words: one construct, one language, and a
        # backend that answers it differently is the one thing this pair must
        # not do.
        for backend in BACKENDS:
            rc, text = build(src, os.path.join(tmpdir, f"{name}.{backend}"),
                             backend)
            if rc == 0:
                return False, (f"--backend={backend} BUILT a construct the "
                               f"convention cannot describe; the binary is "
                               f"the real answer here")
            if expectation not in text:
                return False, (f"--backend={backend} refused, but not naming "
                               f"{expectation!r}: {text.strip()[-200:]}")
        if verbose:
            print(f"      refused identically on both: {expectation!r}")
        return True, ""

    want = cpython_answer(source) if mode == "ok" else expectation
    if not isinstance(want, int):
        return False, want
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc != 0:
            return False, f"--backend={backend}: {text.strip()[-300:]}"
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.returncode != want:
            return False, (f"--backend={backend} exit {run.returncode} where "
                           f"{'CPython' if mode == 'ok' else 'the source'} "
                           f"gives {want}"
                           + (f"; stderr: {run.stderr.strip()[:120]}"
                              if run.stderr.strip() else ""))
        if verbose:
            print(f"      {backend}: exit={run.returncode} "
                  f"stdout={run.stdout!r}")
    if verbose and mode == "ok":
        print(f"      CPython: exit={want}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64", "x86_64"):
        print(f"SKIP: formal output needs an arm64 or x86-64 host, "
              f"this is {platform.machine()}")
        return 0

    selected = [c for c in CASES if not args.cases or c[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        missing = set(args.cases) - {c[0] for c in selected}
        print(f"no such case(s): {sorted(missing)}")
        return 2

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, mode, expectation in selected:
            try:
                ok, detail = run_case(name, source, mode, expectation,
                                      tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:                      # report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {name} ({mode})")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    print(f"\nformal returned-frame: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
