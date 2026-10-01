#!/usr/bin/env python3
"""A frame address at an argument position of a COMPTIME-SPECIALIZED call.

The receiver-position family (`bugs/FORMAL_frame_receiver_handoff.md` §6-§13)
has three cases, and this file covers the one that is not about a method call
at all: `f[T](r)` — a generic being specialized with a frame address in an
argument.

    python3 test_formal_receiver_position.py [-v] [case ...]

WHAT THE CONSTRUCT IS.  A struct of more than one field has a FRAME for its
receiver on this path (`formal/model.py`'s `struct_is_framed`): the receiver word
is the ADDRESS of a block of 8-byte slots, one per field.  Handing that address
to a callee's parameter is the hand-off the by-reference design exists for, and
wave 5 established it for a BARE-NAME callee in every position.  A
comptime-specialized callee is the same hand-off: `f[T](r)` names the function
`f`, and the brackets are a compile-time binding rather than an argument, so
call-time position `i` is the `i`th entry of `function_param_shape(f).names` —
which is the list every frame table is keyed by (`formal/model.py`'s
`call_callee_name` says this, and its docstring carries the measurement).

WHY IT WAS REFUSED, AND WHY THE REASON WAS FALSE.  The terminal message was
"a method call on a value receiver is dispatched by NAME, so `recv.m(x)` carries
no type" — about a callee that is a plain name with no receiver, no method and
no dispatch in it.  Six of the 25 files `bugs/FORMAL_sweep_work_map_2026-09-30.md`
blocks on that message have a comptime specialization at the callee
(`std/algorithm/reduction.mojo`, `std/builtin/string_literal.mojo`,
`std/collections/bitset.mojo`, `std/collections/string/format.mojo`,
`std/memory/span.mojo`, `std/python/bindings.mojo`) and not one of them contains
a method call at that site.  §4 of the handoff doc is three examples of a
refusal for a reason that was not operating; this was a fourth, in the family
that §4 exists to police.

WHY THE HOST IS arm64 AND x86-64 IS A REFUSAL, which is the one thing here a
reader should not skim.  `f[1](3, 7)` builds and returns 307 on arm64 and is
REFUSED on x86-64 with "unsupported call target on the formal x86-64 path (got
SubscriptExpr)", and that asymmetry is correct rather than a gap in the change:
the two backends do not share the comptime ABI.  arm64's `_emit_call` evaluates
the bracket expressions in the caller's scope and passes them AHEAD of the
call-time arguments (`_specialization_args`), and `model.incoming_args` puts a
generic's comptime parameters first, so both sides agree.  x86-64's `_emit_call`
has no specialization pass at all — its own constructor docstring says so — and
its `_callee_symbol` answers `None` for a `SubscriptExpr`.  That refusal is
LOAD-BEARING: the callee prologue on x86-64 reserves a register per comptime
parameter (`incoming_args` is shared), so a caller that passed only the
call-time arguments would read `type` from `x`'s register and `x` from `y`'s —
silently.  `x86_abi_refusal_is_load_bearing` pins that, and
`bugs/FORMAL_x86_64_comptime_specialization_abi.md` carries the rest.

Every case is DIFFERENTIAL: the same program is written twice, once as Mojo and
once as plain Python, and the two are made to AGREE rather than the expectation
being written by hand.  `printf` is used for the Mojo side rather than the exit
status, because a process exit status is a byte on this host and some of these
answers are larger than 255.
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")
# The architecture whose comptime ABI this construct needs.  Every refusal case
# below is still checked on BOTH, because a refusal raised by the shared build
# pass has to be the same refusal on both.
COMPTIME_ABI = "arm64"

# ── the differential cases ──────────────────────────────────────────────────
#
# (name, mojo_source, python_source)
DIFF_CASES = [
    # THE TERMINAL CONSTRUCT, in miniature: a frame address at a NON-FIRST
    # position of a specialized generic.  This is the shape the sweep blocks
    # `std/algorithm/reduction.mojo` on (`_reduce_generator[…](shape, init=…)`
    # with `shape: Coord`), and it is the case the position family says must be
    # followed, because a parameter is a parameter wherever it sits.
    ("generic_frame_reads_at_a_nonfirst_position",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take[type: Int](x: Int, r: R) -> Int:\n"
     "    return r.a * 10 + r.b\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     '    printf("v=%d", take[1](0, r))\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 7\n"
     "        self.b = 8\n\n"
     "def take(type, x, r):\n"
     "    return r.a * 10 + r.b\n\n"
     "def main():\n"
     "    r = R()\n"
     '    print("v=%d" % take(1, 0, r), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # A WRITE THROUGH THE ADDRESS, which is the half a read cannot establish: a
    # read would still come out right if the word handed over were a COPY of the
    # frame, and `put` writes `r.a` and main reads `r.a` afterwards, so the
    # answer is only 5252 if the callee's store landed in the caller's frame.
    # (The CPython twin writes the same attribute, so the comparison is of the
    # same question and not of a constant.)
    ("generic_frame_writes_through_to_the_caller",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def put[type: Int](x: Int, y: Int, v: Int) -> Int:\n"
     "    y.a = v\n"
     "    return y.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    r.b = 8\n"
     '    printf("got=%d back=%d", put[1](0, r, 52), r.a)\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 1\n"
     "        self.b = 8\n\n"
     "def put(type, x, y, v):\n"
     "    y.a = v\n"
     "    return y.a\n\n"
     "def main():\n"
     "    r = R()\n"
     '    print("got=%d back=%d" % (put(1, 0, r, 52), r.a), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # THE CREATOR ONE FRAME DEEPER.  `main` holds no frame at all here, so this
    # is the case that would catch a lifetime error rather than a missing slot
    # table: the frame is built in `build()`, and `build` is still on the stack
    # when `take` runs, which is the whole of the argument that a frame address
    # may travel down an active call chain.
    ("generic_frame_creator_one_frame_deeper",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take[type: Int](x: Int, r: R) -> Int:\n"
     "    return r.a * 10 + r.b\n\n"
     "def build() -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return take[1](0, r)\n\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", build())\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 7\n"
     "        self.b = 8\n\n"
     "def take(type, x, r):\n"
     "    return r.a * 10 + r.b\n\n"
     "def build():\n"
     "    r = R()\n"
     "    return take(1, 0, r)\n\n"
     "def main():\n"
     '    print("v=%d" % build(), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # POSITION 0 OF A SPECIALIZED CALLEE — the literal shape the sweep's row 4
    # is named for, and the one a fix to the non-first case could plausibly
    # break: a receiver as the FIRST parameter of `f[T]`.
    ("generic_frame_at_position_zero",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def show[type: Int](r: R) -> Int:\n"
     "    return r.a * 10 + r.b\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     '    printf("v=%d", show[1](r))\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 7\n"
     "        self.b = 8\n\n"
     "def show(type, r):\n"
     "    return r.a * 10 + r.b\n\n"
     "def main():\n"
     "    r = R()\n"
     '    print("v=%d" % show(1, r), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # **GUARD** — the same program with a BARE-NAME callee, which has always
    # been followed and must stay followed.  Labelled as a guard rather than a
    # demonstration because it is correct before the change as well as after,
    # and it is here so that a fix which resolved `f[T](x)` by rewriting the
    # call into some new spelling could not pass every case above while breaking
    # the ordinary one.
    ("GUARD_bare_name_callee_is_unchanged",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take(x: Int, r: R) -> Int:\n"
     "    return r.a * 10 + r.b\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     '    printf("v=%d", take(0, r))\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 7\n"
     "        self.b = 8\n\n"
     "def take(x, r):\n"
     "    return r.a * 10 + r.b\n\n"
     "def main():\n"
     "    r = R()\n"
     '    print("v=%d" % take(0, r), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # **GUARD** — a specialized generic with a comptime parameter and NO frame
    # anywhere.  It was already correct on arm64 and the change must not have
    # moved it: it is what makes "the comptime ABI is unchanged" a measurement
    # rather than an assumption, and it is the case that would catch a
    # `call_callee_name` which shifted call-time positions by the number of
    # comptime parameters (the answer would be 3, not 307).
    ("GUARD_specialization_binds_its_own_arguments",
     "def f[type: Int](x: Int, y: Int) -> Int:\n"
     "    return x * 100 + y\n\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", f[1](3, 7))\n'
     "    return 0\n",
     "def f(type, x, y):\n"
     "    return x * 100 + y\n\n"
     "def main():\n"
     '    print("v=%d" % f(1, 3, 7), end="")\n'
     "    return 0\n\n"
     "main()\n"),
]

# ── the refusals ────────────────────────────────────────────────────────────
#
# (name, mojo_source, needle)
#
# All of these fire in the SHARED build pass (`formal/build.py`'s
# `_check_frame_escapes` / `_check_holder_agreements`), which runs before either
# emitter is reached, so each one is required to refuse identically on arm64
# and on x86-64.  That is the right shape for these cases and the opposite of
# the differential ones above: a frame address still reaching something that may
# outlive its creator has to stop on BOTH machines whatever each emitter can do.
REFUSALS = [
    # TWO CALL SITES THAT DISAGREE — the measured SIGSEGV of wave 5, reached
    # through the new spelling.  `f[1](r, 1)` makes `x` a frame holder and
    # `f[1](2, 3)` arrives with `x = 2`, so `x.a` is a load eight bytes from
    # wherever 2 points.  The needle is the whole sentence rather than a word,
    # because the interesting part is that it names BOTH sites.
    ("refuse_two_specialized_call_sites_that_disagree",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def f[type: Int](x: Int, r: R) -> Int:\n"
     "    return x.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return f[1](r, 1) + f[1](2, 3)\n",
     "One parameter, two kinds of value"),

    # …and the two call sites are quoted the way the source spells them.  This
    # is a separate assertion from the one above because it is a different
    # defect: a spelling that printed the AST (`SubscriptExpr(r, 1)`) is a
    # refusal whose reason is still right and whose EVIDENCE is unreadable, and
    # `_call_spelling` raised on exactly these calls until `formal/build.py`'s
    # `_expr_spelling` learned a subscript.
    ("refuse_disagreement_spells_both_call_sites",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def g[type: Int](x: Int, r: R) -> Int:\n"
     "    return x.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return g[1](r, 1) + g[1](2, 3)\n",
     "at g[1](r, 1) here, and something that is not a frame address at "
     "g[1](2, 3)"),

    # A RECEIVED FRAME ADDRESS RETURNED.  The return family, not the position
    # family, and the message says so: the creator is up the call chain and
    # nothing here establishes it is still there when the caller reads the slot.
    ("refuse_a_specialized_parameter_returned",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def stash[type: Int](x: Int, r: R) -> Int:\n"
     "    return r\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    return stash[1](0, r).a\n",
     "returned from a function that did not create it"),

    # A CALLEE THIS PASS CANNOT NAME, and the message must NAME IT rather than
    # call it a method call.  `Box.run[1](0, r)` is a specialization of a
    # DOTTED callee: `_rewrite_method_calls` lifts `recv.m(x)` and not
    # `Struct.m[T](x)`, so there is no parameter list to read.  The needle is
    # the callee's own spelling, which is the whole point — before the change
    # this program was reported as "a method call on a value receiver is
    # dispatched by NAME", naming a receiver and a dispatch it does not have.
    ("refuse_a_dotted_specialized_callee_names_it",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Box:\n"
     "    var k: Int\n\n"
     "    def run[type: Int](x: Int, r: R) -> Int:\n"
     "        return r.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    var bx = Box()\n"
     "    bx.k = 1\n"
     "    return Box.run[1](0, r)\n",
     "The callee of this call is Box.run[1], which names no function this pass "
     "has a parameter list for"),

    # A specialization does NOT rescue the value-only callees: `origin_of`
    # wants the object, and a frame address is not one.  `origin_of` is spelled
    # `self.origin` here because `origin_of` is a builtin on this path and the
    # check is about the callee, not the spelling.
    ("refuse_a_value_only_callee_through_a_specialization",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def ask[type: Int](x: Int, r: R) -> Int:\n"
     "    return origin_of(r)\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return ask[1](0, r)\n",
     "which is lowered as an operation on a VALUE"),
]

# ── the x86-64 half, which is a refusal and a LOAD-BEARING one ─────────────
#
# (name, mojo_source, needle)
X86_ABI_REFUSALS = [
    ("x86_abi_refusal_is_load_bearing",
     "def f[type: Int](x: Int, y: Int) -> Int:\n"
     "    return x * 100 + y\n\n"
     "def main(n: Int) -> Int:\n"
     "    return f[1](3, 7)\n",
     "unsupported call target on the formal x86-64 path (got SubscriptExpr)"),
]


def build_formal(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_cpython(source, tmpdir):
    """The oracle: the same program under CPython, whose exit status and stdout
    the formal image has to match.

    Not `mojo run` and not the interpreter in this repository.  The point of a
    differential case is that the two answers come from two independent
    implementations of the language, and `myinterpreter.py` is not one of them
    — it shares the AST, so a mistake in the AST cannot be caught by comparing
    against it.
    """
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(source)
    return subprocess.run([sys.executable, path], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)


def run_diff_case(case, tmpdir, verbose):
    """CPython's answer, then the image's answer, and require the two to agree.

    The order is the order of trust: the oracle runs FIRST, so a broken
    expectation is reported as a broken expectation and not as a consistently
    wrong backend.  A case whose Python twin does not produce the answer the
    case is about is a bug in the case.

    Built on the architecture whose comptime ABI has the construct, which for
    every case here is `COMPTIME_ABI`.  `X86_ABI_REFUSALS` is where the other
    architecture's answer is pinned, and it is a separate table rather than a
    loop over `BACKENDS` because the two answers DIFFER and the difference is
    the finding — see this file's docstring.
    """
    name, source, oracle = case
    want = run_cpython(oracle, tmpdir)
    if want.returncode != 0:
        return False, (f"the CPython oracle itself failed (exit "
                       f"{want.returncode}): "
                       f"{(want.stderr or '').strip()[-200:]}")
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, f"{name}.{COMPTIME_ABI}")
    rc, text = build_formal(src, out, COMPTIME_ABI)
    if rc != 0:
        return False, (f"--backend={COMPTIME_ABI} did not build: "
                       f"{text.strip()[-300:]}")
    if not os.path.isfile(out):
        return False, f"--backend={COMPTIME_ABI} built but wrote no binary"
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    if run.returncode != want.returncode:
        return False, (f"--backend={COMPTIME_ABI} exit status {run.returncode}, "
                       f"CPython {want.returncode}")
    if run.stdout != want.stdout:
        return False, (f"--backend={COMPTIME_ABI} stdout {run.stdout!r}, CPython "
                       f"{want.stdout!r}")
    if verbose:
        print(f"      --backend={COMPTIME_ABI} stdout={run.stdout!r}")
    return True, ""


def run_refusal_case(case, tmpdir, verbose):
    """BOTH backends must refuse, and both must refuse with the needle.

    Both architectures, because a refusal raised by the shared build pass has to
    be the same refusal on both — a construct one machine stops and the other
    lowers is precisely the divergence this backend's design is built to make
    impossible.
    """
    name, source, needle = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct that has no "
                           f"representation (expected a refusal naming "
                           f"{needle!r}); the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-300:]}")
        if verbose:
            print(f"      --backend={backend} refused naming {needle!r}")
    return True, ""


def run_x86_abi_case(case, tmpdir, verbose):
    """x86-64 must refuse the specialization, and arm64 must build it.

    Both halves, and the second one is not decoration: the reason x86-64 has to
    refuse is that its caller does not pass the comptime arguments while its
    callee reserves a register for them.  Asserting only the refusal would let a
    change that made x86-64 "work" by answering the name without the ABI pass
    this case while producing a silently wrong image.
    """
    name, source, needle = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.x86_64"),
                            "x86_64")
    if rc == 0:
        return False, ("x86-64 BUILT a comptime-specialized call. That backend "
                       "does not pass the bracket expressions ahead of the "
                       "call-time arguments while its callee prologue reserves "
                       "a register per comptime parameter, so a build here is a "
                       "silently wrong image, not a feature")
    if needle not in text:
        return False, (f"x86-64 refused, but not with the expected words "
                       f"{needle!r}: {text.strip()[-300:]}")
    rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.arm64"), "arm64")
    if rc != 0:
        return False, (f"arm64 refused the same source ({text.strip()[-200:]}) "
                       f"while this case says it lowers; if that is no longer "
                       f"true the case and the docstring are both stale")
    if verbose:
        print("      x86-64 refused naming the missing ABI; arm64 built it")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0

    diff_names = {c[0] for c in DIFF_CASES}
    refuse_names = {c[0] for c in REFUSALS}
    x86_names = {c[0] for c in X86_ABI_REFUSALS}
    runners = [
        (DIFF_CASES, diff_names, run_diff_case),
        (REFUSALS, refuse_names, run_refusal_case),
        (X86_ABI_REFUSALS, x86_names, run_x86_abi_case),
    ]
    everything = [c for group, _n, _r in runners for c in group]
    known = {c[0] for c in everything}
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): {sorted(set(args.cases) - known)}",
              file=sys.stderr)
        return 2

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for case in selected:
            name = case[0]
            runner = next(r for _g, n, r in runners if name in n)
            try:
                ok, detail = runner(case, tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {name}")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")
    print(f"\nformal receiver position: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
