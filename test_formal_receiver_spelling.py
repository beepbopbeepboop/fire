#!/usr/bin/env python3
"""test_formal_receiver_spelling.py — ONE rule for "does this method take a receiver".

There are two places in `formal/build.py` that have to answer that question, and
for a while this tree carried two answers to it:

  * `_receiverless_methods`, which decides whether `_rewrite_method_calls`
    prepends the receiver to a call — `def first():` and a `@staticmethod`
    take none;
  * the frame-holder fixpoint in `_annotate_frame_receivers`, which seeds a
    method's receiver names — `this`, `cls` or anything else the class spells
    its receiver with — into the set a field access is looked up in.

Both asked `fire_compiler.method_receiver_kind`, which decides by the first
parameter's NAME (`self`, `cls`) after the decorator.  That is the right rule
for the three consumers that read it (`mojo/middle/coro.py` and the two
registration paths in `mojo/middle/module_shared.py`), and the wrong one here,
because this path reads a receiver however it is spelled: `model
.struct_receivers` seeds `{"self"}` and ADDS each method's own first
parameter.  A class that spells its receiver `this` therefore looked receiver-
less in both places at once, and the two failures are different because the two
consumers are different:

    p.total()          ->  call Pair_total(): missing required argument 'this'
    Pair___init__      ->  'this.b' is a field access through 'this', and this
                            path has no way to say what 'this' holds

Both are refusals rather than wrong answers, which is the only reason this could
sit unfixed for as long as it did — a program using `this` was refused, and a
refusal is at least loud.  `model.method_receiver_name` is the rule the rest of
the pipeline already derives its FIELD SET from (decorator first, then the first
parameter), so it cannot disagree with the emitter about what a receiver is,
and both sites read it now.

Every case is DIFFERENTIAL: the same program as Mojo and as plain Python, and
the two must AGREE on stdout and on the exit status.  Each `this` case has a
`self` twin that must compute the same thing, which is what stops this file from
passing for the wrong reason — a build that stopped passing ANY receiver would
satisfy "the `this` case computes 31" if the two spellings were not compared
against each other.

    python3 test_formal_receiver_spelling.py [-v] [case ...]
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

# ── the cases ───────────────────────────────────────────────────────────────
#
# (name, mojo_source, python_source)
#
# The exit status is the formal entry point's return value, which is a byte on
# this host, so the answers are all under 256 and `printf` carries the digits
# that matter.
DIFF_CASES = [
    # A receiver named `this` on a TWO-FIELD struct, which is the shape where
    # the receiver is a FRAME ADDRESS rather than the field itself — so it needs
    # the holder fixpoint, not just the call rewrite.  `this.n * 3` is 21 and
    # `C.double(5)` is 10.
    ("this_receiver_and_a_static_method_agree_with_cpython",
     "class C:\n"
     "    def __init__(this):\n"
     "        this.n = 7\n"
     "        this.m = 1\n"
     "\n"
     "    @staticmethod\n"
     "    def double(x: Int) -> Int:\n"
     "        return x * 2\n"
     "\n"
     "    def scaled(this) -> Int:\n"
     "        return this.n * 3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = C()\n"
     "    printf(\"%d\", c.scaled() + C.double(5))\n"
     "    return 0\n",
     "class C:\n"
     "    def __init__(self):\n"
     "        self.n = 7\n"
     "        self.m = 1\n"
     "\n"
     "    @staticmethod\n"
     "    def double(x):\n"
     "        return x * 2\n"
     "\n"
     "    def scaled(self):\n"
     "        return self.n * 3\n"
     "\n"
     "import sys\n"
     "def main():\n"
     "    c = C()\n"
     "    sys.stdout.write(\"%d\" % (c.scaled() + C.double(5)))\n"
     "main()\n"),

    # THE SAME PROGRAM with the receiver spelled `self`, and it must print the
    # same digits.  This is the control for the case above: it is what says the
    # `this` spelling is answered the same way rather than being answered by a
    # rule that stopped threading a receiver at all.
    ("self_receiver_prints_the_same_digits",
     "class C:\n"
     "    def __init__(self):\n"
     "        self.n = 7\n"
     "        self.m = 1\n"
     "\n"
     "    @staticmethod\n"
     "    def double(x: Int) -> Int:\n"
     "        return x * 2\n"
     "\n"
     "    def scaled(self) -> Int:\n"
     "        return self.n * 3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = C()\n"
     "    printf(\"%d\", c.scaled() + C.double(5))\n"
     "    return 0\n",
     "class C:\n"
     "    def __init__(self):\n"
     "        self.n = 7\n"
     "        self.m = 1\n"
     "\n"
     "    @staticmethod\n"
     "    def double(x):\n"
     "        return x * 2\n"
     "\n"
     "    def scaled(self):\n"
     "        return self.n * 3\n"
     "\n"
     "import sys\n"
     "def main():\n"
     "    c = C()\n"
     "    sys.stdout.write(\"%d\" % (c.scaled() + C.double(5)))\n"
     "main()\n"),

    # A `@staticmethod` with NO parameters at all — the shape the receiverless
    # rule was written for, and the other end of the same question.  If the
    # receiver were prepended here the call would bind the receiver to `x` and
    # print 24 rather than 12, which is a wrong answer rather than a refusal, so
    # this case is what keeps the rule from being "always pass the receiver".
    ("a_static_method_with_no_parameters_takes_no_receiver",
     "class D:\n"
     "    @staticmethod\n"
     "    def twelve() -> Int:\n"
     "        return 12\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"%d\", D.twelve())\n"
     "    return 0\n",
     "class D:\n"
     "    @staticmethod\n"
     "    def twelve():\n"
     "        return 12\n"
     "\n"
     "import sys\n"
     "def main():\n"
     "    sys.stdout.write(\"%d\" % D.twelve())\n"
     "main()\n"),

    # A module-level function whose name is a BARE METHOD name of a struct in
    # the same unit, in a unit that has a class-level `None` binding — which is
    # the pair a deleted bug doc measured (commit 95b3d73c), and it crashed the
    # compiler rather than refusing the program.
    #
    # Two tables in `formal/build.py` are both called "owners":
    # `M.method_owner_names` is keyed by the LIFTED `<Struct>_<method>` a
    # rewritten call spells and carries a `StructDef`; `_method_owners` is keyed
    # by the BARE name a `MemberExpr`'s `.member` is and carries a `str`.  The
    # frame pass was handed the second and every consumer inside it wanted the
    # first, so a function named `parse` next to a method named `parse` made
    # `owners.get(fn.name)` return a string and the pass did `owner.name` on it:
    # `AttributeError: 'str' object has no attribute 'name'`, out of the
    # compiler, on a program that is correct Mojo.  Three stdlib files in the
    # `std-c` sweep slice hit it (`std/subprocess/subprocess.mojo`,
    # `std/runtime/_asyncrt.mojo`, `std/_gpu/primitives/warp.mojo`), and
    # `test_dataclasses_formal.py`'s corpus case had it red on master.
    #
    # `Holder` is TWO fields on purpose: a one-field struct's receiver is a word
    # handed over by value, so the unit has no FRAMED struct, the frame pass
    # returns before it consults any table, and the case would pass for the
    # wrong reason.  `var tag: String = None` is the class-level `None` binding
    # the `refuse_none_comparisons` guard needs; without it the crash is not
    # reached.  `len` is 2 on both sides, so the case is a value as well as a
    # build.
    ("a_module_level_function_named_like_a_method_does_not_crash_the_pass",
     "struct Holder:\n"
     "    var tag: String = None\n"
     "    var other: Int = 0\n"
     "\n"
     "    def parse(this, s: String) -> String:\n"
     "        return s\n"
     "\n"
     "def parse(s: String) -> String:\n"
     "    return s\n"
     "\n"
     "def main() -> Int32:\n"
     "    var h = Holder(\"x\", 0)\n"
     "    printf(\"%d\", len(h.parse(\"hi\")))\n"
     "    return 0\n",
     "class Holder:\n"
     "    def __init__(self):\n"
     "        self.tag = None\n"
     "        self.other = 0\n"
     "    def parse(self, s):\n"
     "        return s\n"
     "\n"
     "def parse(s):\n"
     "    return s\n"
     "\n"
     "import sys\n"
     "sys.stdout.write(\"%d\" % len(Holder().parse(\"hi\")))\n"),

    # A `@classmethod`'s receiver is `cls`, and the rule has to thread it as one
    # — but there is NO case for it here, and that is a fact about this path
    # rather than about the rule: reaching a `@classmethod` means naming the
    # CLASS, and a module-level class name is a name with no storage
    # (`bugs/FORMAL_module_state_no_storage.md`), so `E.widen(x)` is refused as
    # a read of `E` before anything stores it.  Measured on this tree, both
    # spellings of the receiver irrelevant to the refusal.  What the rule still
    # has to get right for a classmethod is covered where the receiver IS
    # reachable: `model.struct_receivers` puts `cls` in the set, so a classmethod
    # body that stores through `cls.<field>` lowers, and `_receiverless_methods`
    # excludes it because `method_receiver_name` gives a name rather than None.
    # A row asserting that would be a row asserting a construct this path does
    # not have, which is the same mistake in the other direction.
]


def build_formal(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_cpython(source, tmpdir):
    """CPython's stdout and exit status, which the formal image has to match.

    CPython and not `myinterpreter.py`: a differential case is worth having
    because the two answers come from two independent implementations, and the
    interpreter here shares the AST with the backends, so a mistake in the AST
    cannot be caught by comparing against it.
    """
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(source)
    return subprocess.run([sys.executable, path], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)


def run_case(case, tmpdir, verbose):
    """CPython first, then BOTH images, and require all three to agree.

    The oracle runs FIRST so that a case whose Python twin is wrong is reported
    as a wrong case rather than as a consistently wrong backend.

    BOTH architectures because a refusal raised by the shared build pass has to
    be the same refusal on both — and because the defect this file covers was
    two SEPARATE refusals, one per site, either of which a one-sided assertion
    would have let through on the strength of the other backend agreeing.
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
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend)
        if rc != 0:
            return False, (f"--backend={backend} did not build: "
                           f"{text.strip()[-300:]}")
        if not os.path.isfile(out):
            return False, f"--backend={backend} built but wrote no binary"
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.returncode != want.returncode:
            return False, (f"--backend={backend} exit status {run.returncode}, "
                           f"CPython {want.returncode}")
        if run.stdout != want.stdout:
            return False, (f"--backend={backend} stdout {run.stdout!r}, CPython "
                           f"{want.stdout!r}")
        if verbose:
            print(f"      --backend={backend} stdout={run.stdout!r}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    known = {c[0] for c in DIFF_CASES}
    selected = [c for c in DIFF_CASES
                if not args.cases or c[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): {sorted(set(args.cases) - known)}",
              file=sys.stderr)
        return 2

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for case in selected:
            name = case[0]
            try:
                ok, detail = run_case(case, tmpdir, args.verbose)
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
    print(f"\nformal receiver spelling: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())