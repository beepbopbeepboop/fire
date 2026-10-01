#!/usr/bin/env python3
"""Module-global state: build the image, RUN it, and check the answer.

`test_formal_run.py` covers expressions; this covers state that lives in the
module rather than in a frame, and it exists because of a specific way that goes
wrong. Before module-global storage existed, `GlobalStmt` was a no-op in both
backends, so

    G = 5
    def bump():
        global G
        G = G + 1

compiled, linked, and PRINTED 5 — the write landed in a dead register and the
read was folded to the module's constant. Nothing failed. The proof obligations
were discharged; the binary was wrong. So every case here is executed, and the
number it produces is the assertion.

THREE ENGINES PER CASE. A module global is the one feature in this backend whose
correctness depends on a second module agreeing about where a slot lives — the
codegen computes an address, the linker maps a segment, and nothing in between
checks them. That is exactly the class of defect where one architecture can be
right and the other wrong with both green elsewhere, and it was not
hypothetical: an x86-64 image whose `__DATA` was addressed RIP-relative ran
correctly under lldb and died of SIGSEGV standalone, because the loader slides
the image and `GLOBALS_VM` is a fixed address.

So each case runs the same source three ways and requires all three to agree:

  * `fire.py run` — the Mojo interpreter, which is the reference SEMANTICS. It
    shares no code with the formal backend below the parser, so agreement is
    evidence rather than a tautology.
  * the arm64 image, natively.
  * the x86-64 image, under Rosetta.

Requiring the backends to agree with each other is not redundant with the
interpreter comparison: the interpreter has no `__DATA`, no slot index and no
image, so a whole class of bug (address arithmetic, segment placement, lazy
initialization ordering) is invisible to it and can only be caught by two
independent codegens landing on the same number.

    python3 test_formal_globals.py [-v] [case ...]
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

# (name, source, expected stdout)
#
# `print` rather than `printf`, because `printf` is not in the interpreter's
# namespace and a case that only ran on the images would have no reference to
# compare against. The formal arm64 path also refuses to `print` a bare
# `IdentExpr` — it cannot tell a string from a number and guessing would print
# an address as if it were text — so each case binds the global to an annotated
# local first. That annotation is not incidental: it is the ordinary Mojo way to
# say what a name holds, and every case below uses it.
CASES = [
    # ── the case this whole capability exists for ──
    # The measured wrong answer before module-global storage was 5. The write
    # reached a dead register, the read was constant-folded to the module
    # initializer, and the image exited 0 the whole time.
    ("write_int_through_global",
     "G = 5\n"
     "\n"
     "def bump():\n"
     "    global G\n"
     "    G = G + 1\n"
     "\n"
     "def main(n):\n"
     "    bump()\n"
     "    bump()\n"
     "    g: Int = G\n"
     "    print(g)\n"
     "    return 0\n", "7\n"),

    # A function that TOUCHES the global but does not write it still has to see
    # the current value, which is the lazy initializer's other half: the check
    # has to run before the read, not only before a write.
    ("read_int_through_global",
     "G = 41\n"
     "\n"
     "def get():\n"
     "    global G\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    bump: Int = get()\n"
     "    print(bump)\n"
     "    return 0\n", "41\n"),

    # THE CONTROL for the row above, and the one that would catch an
    # over-correction: a name assigned WITHOUT `global` binds a local, so the
    # module's value must survive it. This is not a restatement — before the
    # gate in `_module_global` was drawn at the function's local set rather than
    # at "does the name have a slot", `bump_local`'s store went to `__DATA` and
    # this case printed 99-then-5 where CPython says the module is untouched.
    # A function silently writing a variable it never declared is the failure
    # mode, and nothing else in the suite would catch it.
    #
    # `bump_local` never READS `G`, which is deliberate and is the limit of what
    # is asserted. `G = G + 1` with no `global` is a different question, and the
    # row below answers it.
    #
    # `set_it` exists so the name does have a slot at all: with no `global`
    # write anywhere in the module, `G` is a read-only module constant and this
    # case would be testing the folding path instead of what it is for.
    ("assign_without_global_is_local",
     "G = 5\n"
     "\n"
     "def bump_local():\n"
     "    var G = 99\n"
     "\n"
     "def set_it():\n"
     "    global G\n"
     "    G = 100\n"
     "\n"
     "def main(n):\n"
     "    bump_local()\n"
     "    g: Int = G\n"
     "    print(g)\n"
     "    set_it()\n"
     "    h: Int = G\n"
     "    print(h)\n"
     "    return 0\n", "5\n100\n"),

    # Two globals, both written, in an interleaved order that matters: if the
    # slots were assigned in the order the WRITES appear rather than in
    # declaration order, one of these would land in the other's slot and the
    # two numbers would come out swapped.
    ("two_globals_interleaved",
     "A = 1\n"
     "B = 10\n"
     "\n"
     "def bump_a():\n"
     "    global A\n"
     "    A = A + 1\n"
     "\n"
     "def bump_b():\n"
     "    global B\n"
     "    B = B + 1\n"
     "\n"
     "def main(n):\n"
     "    bump_b()\n"
     "    bump_a()\n"
     "    bump_a()\n"
     "    a: Int = A\n"
     "    b: Int = B\n"
     "    print(a)\n"
     "    print(b)\n"
     "    return 0\n", "3\n11\n"),

    # ── containers ──
    # A module-level list is an address-valued slot: the slot holds a POINTER to
    # the blob, so it is the case that exercises the initializer at all — an
    # int global is fully described by the bytes in its slot, so a broken
    # initializer still leaves a readable number behind.
    ("read_list_elements",
     "NUMS = [10, 20, 30]\n"
     "\n"
     "def main(n):\n"
     "    first: Int = NUMS[0]\n"
     "    last: Int = NUMS[2]\n"
     "    print(first)\n"
     "    print(last)\n"
     "    return 0\n", "10\n30\n"),

    # Subscripting a global from inside a FUNCTION, so the function's prologue
    # has to run the lazy initializer before the load rather than relying on
    # `main` having done it already.
    ("read_list_from_function",
     "NUMS = [10, 20, 30]\n"
     "\n"
     "def total():\n"
     "    return NUMS[0] + NUMS[1] + NUMS[2]\n"
     "\n"
     "def main(n):\n"
     "    t: Int = total()\n"
     "    print(t)\n"
     "    return 0\n", "60\n"),

    # TWO module-level stores of one container name. `collect_global_slots` keeps
    # the LAST binding as the slot's initializer, so this pins that the earlier
    # store is not what the reads see — and, just as much, that NEITHER store is
    # a top-level statement the module body has to run.
    #
    # The second half is the reason this case exists rather than a one-line
    # variant of the one above. A module-level store of a container is realized
    # as the `__DATA` slot's initializer, so it is not body; but the entry point
    # IS the module body when there is one (`entry_function` rule 1), and the
    # whole body here is the two stores. Left in, the image materialised the
    # second list on its own stack, discarded it, never called `main` and exited
    # 0 — printing nothing, on both architectures, with a green build. A test
    # that only asked "is the right number printed" would have caught it; what
    # this row adds is the second store, so the case is about WHICH store is the
    # initializer as well as about the entry.
    ("rebound_list_global",
     "NUMS = [1, 2]\n"
     "NUMS = [30, 40, 50]\n"
     "\n"
     "def main(n):\n"
     "    first: Int = NUMS[0]\n"
     "    last: Int = NUMS[2]\n"
     "    print(first)\n"
     "    print(last)\n"
     "    return 0\n", "30\n50\n"),

    # Bound to a local first. This is the shape that most exposed the lazy
    # initializer: the load of the slot happens once, in the prologue's shadow,
    # and every later use goes through the register — so a slot filled after
    # the load reads stale, and a slot never filled reads the zero an unwritten
    # slot gives.
    ("alias_list_then_index",
     "NUMS = [10, 20, 30]\n"
     "\n"
     "def main(n):\n"
     "    p = NUMS\n"
     "    v: Int = p[1]\n"
     "    print(v)\n"
     "    return 0\n", "20\n"),

    # ── strings ──
    # `printf` rather than `print` for strings, and the reason is worth stating
    # because it is not a style preference: a string global's slot holds an
    # ADDRESS, and `print` on an `Int`-rendered value of one prints the address
    # — measured, "bye" printed as the decimal for its own bytes. `printf("%s")`
    # is the idiom the rest of the formal suite uses for a string and is the
    # one that distinguishes the two.
    #
    # These two cases therefore opt out of the interpreter comparison (see
    # `run_case`), because `printf` is not in the interpreter's namespace; the
    # expected value is the literal below, which is what CPython's semantics say
    # the program computes.
    ("read_string_global",
     "NAME = \"hi\"\n"
     "\n"
     "def setname():\n"
     "    global NAME\n"
     "    NAME = NAME\n"
     "\n"
     "def main(n):\n"
     "    setname()\n"
     "    printf(\"%s\", NAME)\n"
     "    return 0\n", "hi\n"),

    # Reassigning a string global is the case where the slot's old contents are
    # the wrong answer rather than a plausible one, so it is worth its own row.
    ("write_string_global",
     "NAME = \"hi\"\n"
     "\n"
     "def setname():\n"
     "    global NAME\n"
     "    NAME = \"bye\"\n"
     "\n"
     "def main(n):\n"
     "    setname()\n"
     "    printf(\"%s\", NAME)\n"
     "    return 0\n", "bye\n"),

    # A string ELEMENT inside a container global, which is the case
    # `bugs/FORMAL_module_global_string_elements.md` was about. The word is a
    # `char *` and the only `char *` to those bytes on this path is the INTERNED
    # literal — so the initializer stores the address a `"a"` written anywhere
    # in the program already has, rather than a copy of the bytes into `__DATA`.
    # A copy would satisfy this row and be wrong: `printf("%s")` cannot tell two
    # copies of the same text apart, which is exactly why a row that only checks
    # output is not enough here, and why the dict row below is in the file.
    ("read_list_of_strings",
     "L = [\"a\", \"b\"]\n"
     "\n"
     "def main(n):\n"
     "    printf(\"%s\", L[0])\n"
     "    printf(\"%s\", L[1])\n"
     "    return 0\n", "ab"),

    # The same shape as a DICT, and the row that would fail if the elements
    # were copied rather than interned. A dict subscript is a raw 64-bit compare
    # of the key against each pair's key word (`_emit_dict_lookup_addr`), so a
    # `__DATA` copy of "a" is not the key the lookup is looking for: the image
    # exits 1 on a missing key, where CPython answers 1. This is also the only
    # row here that needs `global_slot_is_dict` — without it a dict global's
    # `D["a"]` is emitted as a SEQUENCE subscript and the key's address becomes
    # an element offset, which is a load from a nonsense address.
    ("read_dict_of_strings_by_key",
     "D = {\"a\": 1, \"b\": 2}\n"
     "\n"
     "def main(n):\n"
     "    x: Int = D[\"a\"]\n"
     "    printf(\"%d\", x)\n"
     "    y: Int = D[\"b\"]\n"
     "    printf(\"%d\", y)\n"
     "    return 0\n", "12"),

    # A dict whose VALUES are strings, so both halves of a pair are pointers and
    # the interleave in the blob is two string cells per pair.
    ("read_dict_string_values",
     "M = {\"k\": \"v\", \"j\": \"w\"}\n"
     "\n"
     "def main(n):\n"
     "    printf(\"%s\", M[\"k\"])\n"
     "    printf(\"%s\", M[\"j\"])\n"
     "    return 0\n", "vw"),

    # THE CONTROL for the interning claim, and the reason the two rows above are
    # worth having: a string global and a string LITERAL are the same string, so
    # the comparison is true. Before, the global's bytes were a COPY in
    # `__DATA` and the literal's were the interned one in `__TEXT`; this row
    # passed anyway, because a name bound to a string literal classifies as a
    # string and its `==` lowers to a content compare. So it pins the address
    # identity that the dict row needs without pinning it by proxy.
    ("string_global_is_the_interned_literal",
     "NAME = \"hi\"\n"
     "\n"
     "def main(n):\n"
     "    c: Int = 0\n"
     "    if NAME == \"hi\":\n"
     "        c = 1\n"
     "    printf(\"%d\", c)\n"
     "    return 0\n", "1"),

    # ── module boundaries ──
    # A dylib's `__DATA` is emitted with `emit_startup=False`, so there is no
    # startup stub to run an initializer from: the lazy per-function check is
    # the ONLY thing that can fill it. This case is the whole argument for that
    # design, and it is the one case here that needs two files.
    ("cross_module_counter",
     {"state.mojo": "HITS = 0\n"
                    "\n"
                    "def hit():\n"
                    "    global HITS\n"
                    "    HITS = HITS + 1\n"
                    "\n"
                    "def get_hits():\n"
                    "    return HITS\n",
      "prog.mojo": "from state import hit\n"
                   "from state import get_hits\n"
                   "\n"
                   "def main(n):\n"
                   "    hit()\n"
                   "    hit()\n"
                   "    hit()\n"
                   "    h: Int = get_hits()\n"
                   "    print(h)\n"
                   "    return 0\n"}, "3\n"),
]

# Cases that must be REFUSED, and why each one is a refusal rather than a wrong
# number.
#
# The distinction is the point. A module global's value has to be known before
# the program runs, because its storage is eight bytes of static image. An
# initializer this backend cannot materialise leaves those bytes zero, and zero
# is a plausible value: a list would read as length 0 and a string as an empty
# one, so the program would produce an answer rather than an error. Refusing is
# the only honest option, and these rows pin that it still does.
REFUSALS = [
    # A string ELEMENT inside a container global is NOT a refusal any more —
    # `read_list_of_strings` above runs it. What is still refused is a container
    # element that is neither an int nor a string, and the pin is here because
    # the refusal machinery is what stops a slot with no initializer from
    # reading as the zero an unwritten slot gives: a list would report length 0
    # and print an answer.
    #
    # A nested container is the interesting one, because its element IS a word
    # (a pointer to a blob) and only the SECOND level of fixups is missing — so
    # this is a real extension rather than a limit, and the message says which.
    ("nested_container_global_refused",
     "L = [[1, 2], [3]]\n"
     "\n"
     "def main(n):\n"
     "    v: Int = L[0][1]\n"
     "    print(v)\n"
     "    return 0\n",
     "no initializer"),

    # A local that SHADOWS a module global, read before the local is stored. The
    # refusal is the point of the row, and the reason is a fact about CPython
    # that is easy to get backwards:
    #
    #     G = 5
    #     def bump():
    #         G = G + 1
    #
    # Python decides a name's scope at COMPILE time, from the whole function
    # body — `G` is assigned here, so `G` is local throughout `bump` — and the
    # right-hand read therefore raises `UnboundLocalError`. It does NOT read the
    # module's 5. Verified:
    #
    #     $ python3 -c 'G = 5
    #     > def bump():
    #     >     G = G + 1
    #     > bump()'
    #     UnboundLocalError: cannot access local variable 'G' where it is not
    #     associated with a value
    #
    # So the two homes are not a missed feature here; there is no answer to
    # compute, and a backend that resolved the read against the module slot
    # would print 6 for a program CPython refuses. `model.read_before_store`
    # refuses it, and this row pins that it still does on BOTH architectures —
    # the shape specific to this construct, because the read name is a real
    # module global here and so the alternative was a live `__DATA` load rather
    # than a dead register. The general read-before-store rule is pinned by
    # `test_formal_run.py`'s three refusal rows, none of which has a
    # module-level binding for the name it reads.
    #
    # The Mojo interpreter disagrees with CPython here (`fire.py run` prints 6),
    # which is worth knowing and is NOT what this row asserts: the test
    # contract for the images is CPython's semantics, and a program CPython
    # raises on has no reference answer to be lowered to.
    ("local_shadow_of_global_read_before_store_refused",
     "G = 5\n"
     "\n"
     "def bump():\n"
     "    G = G + 1\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    v: Int = bump()\n"
     "    print(v)\n"
     "    return 0\n",
     "before anything in this function stores it"),
]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=kw.pop("timeout", BUILD_TIMEOUT), cwd=HERE, **kw)


def interpreter_stdout(tmpdir, name, files):
    """`fire.py run` on the entry file — the reference SEMANTICS.

    The interpreter has no `__DATA`, no slot index and no image, so it cannot
    catch an addressing bug; it is here to catch a SEMANTIC one, and it shares
    no code with either backend below the parser."""
    entry = files["prog.mojo"] if isinstance(files, dict) else files
    src = os.path.join(tmpdir, name + ".interp.mojo")
    with open(src, "w") as f:
        f.write(entry)
    p = run([sys.executable, FIRE, "run", src], timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout


def write_sources(tmpdir, name, files):
    """Write a case's files and return (entry_path, {basename: path})."""
    if not isinstance(files, dict):
        path = os.path.join(tmpdir, name + ".mojo")
        with open(path, "w") as f:
            f.write(files)
        return path, {name + ".mojo": path}
    paths = {}
    for base, text in files.items():
        p = os.path.join(tmpdir, f"{name}.{base}")
        with open(p, "w") as f:
            f.write(text)
        paths[base] = p
    return paths["prog.mojo"], paths


def image_stdout(tmpdir, name, backend, files):
    """Build and RUN the case as an image on one backend."""
    entry, paths = write_sources(tmpdir, name, files)
    if isinstance(files, dict):
        # A second module has to be importable by name, so both files sit in
        # the same directory under the names they are imported by.
        for base, p in paths.items():
            os.replace(p, os.path.join(tmpdir, base))
        for base in files:
            paths[base] = os.path.join(tmpdir, base)
        entry = os.path.join(tmpdir, "prog.mojo")
    out = os.path.join(tmpdir, f"{name}.{backend}")
    p = run([sys.executable, FIRE, "build", "--formal", "--no-prove",
             f"--backend={backend}", "-o", out, entry])
    if p.returncode != 0:
        return None, f"build failed on {backend}: {(p.stderr or p.stdout).strip()[-300:]}"
    q = run([out], timeout=RUN_TIMEOUT)
    return (q.returncode, q.stdout), None


def run_case(name, files, want_stdout, tmpdir, verbose):
    want = want_stdout
    got = {}
    for backend in BACKENDS:
        result, err = image_stdout(tmpdir, name, backend, files)
        if err:
            return False, err
        got[backend] = result

    # A case written with `printf` has no interpreter reference: `printf` is
    # not a name the interpreter resolves, so the case's expected value stands
    # on its own. Everything else is checked against the interpreter, because
    # that comparison is the one that catches a SEMANTIC divergence rather than
    # an addressing one.
    entry = files["prog.mojo"] if isinstance(files, dict) else files
    if "printf(" not in entry:
        rc, text = interpreter_stdout(tmpdir, name, files)
        if rc != 0:
            return False, (f"the interpreter refused the case, so there is no "
                           f"reference answer to compare the images against: "
                           f"{text.strip()[-300:]}")
        if text.strip() != want.strip():
            return False, (f"the interpreter disagrees with the case's "
                           f"expected answer: got {text.strip()!r}, want "
                           f"{want.strip()!r}")

    arm, x86 = got["arm64"], got["x86_64"]
    for backend, (rc2, out) in got.items():
        if rc2 != 0:
            return False, f"{backend} image exited {rc2}"
        if out.strip() != want.strip():
            return False, (f"{backend} image printed {out.strip()!r}, "
                           f"want {want.strip()!r}")
    if arm != x86:
        return False, (f"the two architectures disagree: arm64 {arm!r} vs "
                       f"x86_64 {x86!r}. They are one language implementation, "
                       f"so this is a bug in whichever of the two is wrong, not "
                       f"a platform difference.")
    if verbose:
        via = "the interpreter" if "printf(" not in entry else "the expected value"
        print(f"      arm64, x86_64 and {via} agree: {want.strip()!r}")
    return True, ""


def run_refusal(name, source, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        p = run([sys.executable, FIRE, "build", "--formal", "--no-prove",
                 f"--backend={backend}", "-o", out, src])
        if p.returncode == 0:
            return False, (f"--backend={backend} BUILT a module global whose "
                           f"initializer it cannot materialise. The image would "
                           f"run and read the zeros in an unwritten slot, which "
                           f"is a plausible wrong answer rather than an error.")
        text = (p.stderr or p.stdout)
        if needle not in text:
            return False, (f"--backend={backend} refused, but not naming the "
                           f"missing initializer ({needle!r}): "
                           f"{text.strip()[-300:]}")
    if verbose:
        print(f"      refused identically on both backends: {needle!r}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: the images are arm64, host is {platform.machine()}")
        return 0

    everything = ([(c[0], c[1], c[2]) for c in CASES]
                  + [(c[0], c[1], c[2]) for c in REFUSALS])
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    known = {c[0] for c in everything}
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): {sorted(set(args.cases) - known)}",
              file=sys.stderr)
        return 2
    refusal_names = {c[0] for c in REFUSALS}

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, files, want in selected:
            try:
                if name in refusal_names:
                    ok, detail = run_refusal(name, files, want, tmpdir,
                                             args.verbose)
                else:
                    ok, detail = run_case(name, files, want, tmpdir,
                                          args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                if args.verbose:
                    print(f"  PASS  {name}")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    total = passed + failed
    print(f"\nformal globals: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
