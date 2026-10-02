#!/usr/bin/env python3
"""`external_call["sym", RetType](args…)` on the formal backends: build, run,
compare with CPython.

`formal/model.py`'s `external_call` section is the design; this is the test of
it. The construct was the terminal refusal behind the largest single family in
the sweep residue (55 stdlib files, `std/os/env.mojo`) and it was refused by
the multi-index text, which is true of the shape and wrong about the mechanism:
`external_call` is a function-like template whose bracket holds a C symbol and
a declared return type, not a coordinate.

Four things are asserted here, and the fourth is the one that was a live bug:

  1. it lowers, and the image computes what CPython computes for the same
     program — the `setenv`/`getenv`/`unsetenv` round trip of `std/os/env.mojo`
     is transcribed here verbatim in shape, and the expected values come from
     `os.environ` in THIS process rather than from a hand-written table;
  2. the C symbol is reached even when the image declares a Mojo function of
     the same name. `env.mojo` defines `getenv`, `setenv` and `unsetenv` over
     the same three C symbols, so this is the shape the terminal file has and
     not a synthetic one;
  3. every shape that is NOT lowerable is refused, on BOTH architectures, with
     the same words — one text in `formal/model.py`, so the two cannot drift;
  4. the return register is put in the shape the DECLARED type says. See the
     MARSHALLING note below on what that is and is not worth here.

    A `printf` format here never contains `\n`, and that is a property of the
    path rather than a style choice: a string literal reaching a format string
    keeps its backslash (measured — `printf("a\nb\n")` writes `a\nb\n` with
    literal backslashes), while `print` builds its own format and does emit a
    real newline. So a case that wants a line break uses `print`, and one that
    wants an exact byte sequence uses `printf` and a substring match.

    python3 test_formal_external_call.py [-v] [case ...]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 120
RUN_TIMEOUT = 60

# The variable the env cases read and write, so a run cannot be confused with
# the developer's own environment or with a parallel worker's.
VAR = "FIRE_TEST_EXTCALL"
ABSENT = "FIRE_TEST_EXTCALL_ABSENT"


# ── (name, source, expected exit status, expected stdout) ────────────────────
#
# Every expected value below is produced by `expected_stdout()`, which asks
# CPython — the same `os.environ` the C library underneath the image reads.
# That is the point: the reference is not a table someone wrote, it is the
# answer the same program has in the language the image is supposed to agree
# with.
CASES = [
    # ── 1. the env.mojo shapes, transcribed ────────────────────────────────
    # `std/os/env.mojo:26-47`, `50-62` and `65-85`, with
    # `as_c_string_slice().unsafe_ptr()` written as the string it evaluates to
    # on this path (a String IS a bare `char *`). Everything else is the
    # source's own text, including the `Int32(1 if overwrite else 0)` and the
    # `_CPointer[UInt8, UntrackedOrigin[mut=False]]` return type.
    ("env_round_trip",
     "def setenv(var name: String, var value: String,\n"
     "           overwrite: Bool = True) -> Bool:\n"
     "    var status = external_call[\"setenv\", Int32](\n"
     "        name,\n"
     "        value,\n"
     "        Int32(1 if overwrite else 0),\n"
     "    )\n"
     "    return status == 0\n"
     "\n"
     "def unsetenv(var name: String) -> Bool:\n"
     "    return external_call[\"unsetenv\", c_int](name) == 0\n"
     "\n"
     "def getenv(var name: String, default: String = \"\") -> String:\n"
     "    var ptr = external_call[\n"
     "        \"getenv\", _CPointer[UInt8, UntrackedOrigin[mut=False]]\n"
     "    ](name)\n"
     "    if not ptr:\n"
     "        return default\n"
     "    return String(unsafe_from_utf8_ptr=ptr)\n"
     "\n"
     "def main() -> Int32:\n"
     f"    if not setenv(\"{VAR}\", \"hello\", True):\n"
     "        return 1\n"
     f"    printf(\"set=%s|\", getenv(\"{VAR}\"))\n"
     f"    printf(\"absent=%s|\", getenv(\"{ABSENT}\", \"fallback\"))\n"
     f"    if not unsetenv(\"{VAR}\"):\n"
     "        return 2\n"
     f"    printf(\"after=%s|\", getenv(\"{VAR}\", \"gone\"))\n"
     "    return 0\n",
     0, "set=hello|absent=fallback|after=gone|"),

    # The two interesting halves of the same file, separated. `setenv` returns
    # the C `int` status and the source asks `status == 0`; `getenv` returns a
    # `char *` and the source asks `if not ptr`. One case cannot tell you which
    # of the two is right if the other is wrong, and the return REGISTER is the
    # same register for both.
    ("env_setenv_status_is_the_c_int",
     "def main() -> Int32:\n"
     "    var ok = external_call[\"setenv\", Int32](\n"
     f"        \"{VAR}\", \"v\", Int32(1)) == 0\n"
     f"    var bad = external_call[\"setenv\", Int32](\n"
     "        \"bad=name\", \"v\", Int32(1)) == 0\n"
     "    _ = external_call[\"unsetenv\", Int32](\"" + VAR + "\")\n"
     "    printf(\"ok=%d bad=%d\", ok, bad)\n"
     "    return 0\n",
     0, "ok=1 bad=0"),

    # `getenv`'s NULL. The declared return type is a POINTER, so the whole
    # register is the answer and no extension is emitted; the case is here
    # because "the source checks the pointer for null" is the one place a wrong
    # width would turn into a dereference of address 0.
    ("env_getenv_null_is_a_null_pointer",
     "def main() -> Int32:\n"
     "    var p = external_call[\"getenv\", Pointer[UInt8]](\"" + ABSENT + "\")\n"
     "    if not p:\n"
     "        print(\"null\")\n"
     "        return 0\n"
     "    print(\"not null\")\n"
     "    return 1\n",
     0, "null"),

    # ── 2. the C symbol is the C symbol, even when the image says otherwise ──
    # `env.mojo` declares Mojo functions called `getenv`, `setenv` and
    # `unsetenv` and calls the C symbols of the same names inside them. Before
    # the extern path was forced, the bare name was found in the image's own
    # function table and the call branched to the MODULE's `getenv` — which
    # takes an `Int` and returns an `Int`, so the call "succeeded" and the
    # program then read an integer where it had asked for a `char *` and
    # segfaulted dereferencing it. Both halves are asserted: the C symbol's
    # answer, and the Mojo function's own answer reached by its own name.
    ("c_symbol_wins_over_a_local_of_the_same_name",
     "def getenv(n: Int) -> Int:\n"
     "    return n * 10\n"
     "\n"
     "def main() -> Int32:\n"
     f"    var p = external_call[\"getenv\", Pointer[UInt8]](\"{ABSENT}\")\n"
     "    if p:\n"
     "        print(\"C getenv said non-null\")\n"
     "        return 1\n"
     "    printf(\"mojo getenv(4)=%d\", getenv(4))\n"
     "    return 0\n",
     0, "mojo getenv(4)=40"),

    # The same name as a STRUCT, which is the other table a bare name is looked
    # up in before the extern path. `external_call["Pointer", …]` is not a thing
    # any source writes, so the honest version of this case is that the local
    # struct must not capture the C symbol either — asserted by putting the
    # extern call and the struct construction in ONE program, which is the
    # only place the two could collide.
    ("c_symbol_wins_over_a_local_struct_of_the_same_name",
     "struct getenv:\n"
     "    a: Int\n"
     "    b: Int\n"
     "\n"
     "def main() -> Int32:\n"
     f"    var p = external_call[\"getenv\", Pointer[UInt8]](\"{ABSENT}\")\n"
     "    var g = getenv()\n"
     "    g.a = 3\n"
     "    g.b = 4\n"
     "    printf(\"ptr_null=%d sum=%d\", 0 - 1 if p else 1, g.a + g.b)\n"
     "    return 0\n",
     0, "ptr_null=1 sum=7"),

    # A TYPE argument that is ITSELF a two-element bracket. `_CPointer[UInt8,
    # UntrackedOrigin[…]]` is the shape `std/os/env.mojo` declares, and it is
    # the shape the name check walks when it sees a `SubscriptExpr` rooted at a
    # bare name — so it was two independent things going wrong at once and only
    # the outer one is this construct: the inner one is a type the module never
    # declares, there is no local by that spelling, and the answer is not that
    # the program has a bug but that the reader has reached the wrong pass.
    # `env_round_trip` above exercises it inside three functions; it is
    # separated here so a regression names itself.
    ("a_nested_bracket_in_the_type_argument_is_not_a_tuple_index",
     "def main() -> Int32:\n"
     "    var p = external_call[\"getenv\",\n"
     "        _CPointer[UInt8, UntrackedOrigin[mut=False]]\n"
     f"    ](\"{ABSENT}\")\n"
     "    printf(\"ptr_null=%d\", 0 - 1 if p else 1)\n"
     "    return 0\n",
     0, "ptr_null=1"),

    # ── 3. the declared return type, per kind ─────────────────────────────
    # A 64-bit signed integer is the whole register, so nothing is emitted;
    # a signed 32-bit one is the low half, so the register is extended (see
    # MARSHALLING below); a void one returns nothing at all.
    ("return_kind_64_is_the_whole_register",
     "def main() -> Int32:\n"
     "    var n = external_call[\"strlen\", Int64](\"hello\")\n"
     "    printf(\"n=%d\", n)\n"
     "    return 0 if n == 5 else 1\n",
     0, "n=5"),

    ("return_kind_32_signed_is_compared_as_a_word",
     "def main() -> Int32:\n"
     "    var a = external_call[\"strcmp\", Int32](\"a\", \"b\")\n"
     "    var b = external_call[\"strcmp\", Int32](\"b\", \"a\")\n"
     "    var c = external_call[\"strcmp\", Int32](\"x\", \"x\")\n"
     "    if a != 0 - 1 or b != 1 or c != 0:\n"
     "        printf(\"wrong: %d %d %d\", a, b, c)\n"
     "        return 1\n"
     "    printf(\"%d %d %d\", a, b, c)\n"
     "    return 0\n",
     0, "-1 1 0"),

    # A `NoneType` declared return is `void`: the C prototype has nothing in
    # the return register, so no instruction may be emitted for it and the
    # program must simply carry on. `srand` is libSystem's own
    # `void srand(unsigned)` and is here because a void case needs a symbol
    # that LINKS — the runtime's own `KGEN_CompilerRT_*` void entry points, the
    # other void returns in the corpus, are in a dylib this path does not link
    # by default, and a case that failed to link would be testing the linker.
    ("return_kind_void_returns_nothing",
     "def main() -> Int32:\n"
     "    external_call[\"srand\", NoneType](1)\n"
     "    printf(\"survived\")\n"
     "    return 0\n",
     0, "survived"),

    # A one-element bracket is the reference lowering's `void`
    # (`ret_ct = 'void'` when `len(elems) < 2`), so it is answered the same
    # way rather than refused — the compiler that HAS C types accepts it, and
    # disagreeing with it about the language would be the worse defect.
    ("one_element_bracket_is_void",
     "def main() -> Int32:\n"
     "    var n = external_call[\"strlen\"](\"hello\")\n"
     "    printf(\"n=%d\", n)\n"
     "    return 0\n",
     0, "n=5"),

    # ── 4. a call in ARGUMENT and RETURN position, and a variadic target ──
    # The extern path is the one every other extern call uses, so the argument
    # shapes it has to survive are the corpus's. `snprintf` is the interesting
    # one: it is variadic, so the unnamed arguments go in the area rather than
    # in registers, and the source's own `%lld` reaches printf through it. The
    # malloc/free pair around it is the return-into-a-constructor shape, which
    # is `env.mojo`'s `String(unsafe_from_utf8_ptr=…)` in another guise.
    ("variadic_through_the_unnamed_area",
     "def main() -> Int32:\n"
     "    var buf = String(unsafe_from_utf8_ptr=external_call[\n"
     "        \"malloc\", Pointer[UInt8]](64))\n"
     "    var label = StringSlice(unsafe_from_utf8=\"n=\")\n"
     "    var w = external_call[\"snprintf\", Int64](\n"
     "        buf, 64, \"%s%lld\", label, Int64(42))\n"
     "    printf(\"%s|\", buf)\n"
     "    external_call[\"free\", NoneType](buf)\n"
     "    return 0 if w == 4 else 1\n",
     0, "n=42|"),
]


# ── the shapes that must be REFUSED, identically on both backends ───────────
#
# `refuse:` is the same contract `test_formal_run.py` uses: the build must fail
# AND the message must contain the needle, on arm64 AND on x86-64. Every one of
# these used to be refused too — by the tuple-index text, which named a
# two-dimensional index that was not there. The needles below are the
# construct-specific sentences, so a case also fails if the message regresses
# to the old misdiagnosis.
REFUSALS = [
    # A template used as a VALUE. The bracket is not a container, so there is
    # nothing to read; before this the name-placement pass answered instead
    # ("`external_call` has no home"), which is true of that pass and useless
    # to a reader holding a file that is not missing a variable.
    ("refuse_value_use",
     "def main(n: Int) -> Int:\n"
     "    var s = external_call[\"strlen\", Int32]\n"
     "    return 0\n",
     "is applied as a value"),

    # A symbol that is not a string literal. This shape IS in the stdlib
    # (`std/sys/info.mojo` binds the name in a `comptime` parameter), and a
    # branch to a symbol read out of a register is a call to wherever that
    # register pointed.
    ("refuse_non_literal_symbol",
     "def main(n: Int) -> Int:\n"
     "    var s = external_call[n, Int32](\"x\")\n"
     "    return 0\n",
     "is not a string literal"),

    # A third bracket element. The reference lowering accepts one
    # (`("name", RetType, *ParamTypes)`) because C's own prototype states the
    # parameter types; this path has no parameter types to marshal with, so
    # taking the first two and dropping the rest would build a call that is not
    # the one the source wrote.
    ("refuse_three_elements",
     "def main(n: Int) -> Int:\n"
     "    var s = external_call[\"sym\", Int32, Int32](\"x\")\n"
     "    return 0\n",
     "applies the external_call template with 3 arguments"),

    # A return type this path has no value kind for. The width of what comes
    # back in the register is what the declaration establishes, and a
    # `Scalar[dtype]` or a `c_double` establishes none: dropping or inventing
    # bits is a number the source never wrote.
    ("refuse_unmodellable_return_type",
     "def main(n: Int) -> Int:\n"
     "    var s = external_call[\"sym\", Scalar[dtype]](x)\n"
     "    return 0\n",
     "has no value of that kind to put in the return register"),

    # The same for a float, which is a real and very common declared return
    # (`c_double` is `Float64`). Named separately because the repair differs
    # from the generic case's: there is no float kind to declare, ever, on this
    # path, so the sentence a reader needs is the one that says so.
    ("refuse_float_return_type",
     "def main(n: Int) -> Int:\n"
     "    var s = external_call[\"strtod\", c_double](\"1.5\")\n"
     "    return 0\n",
     "declares its return type as c_double"),

    # A multi-element subscript on a VALUE is still refused, and by the SAME
    # shared text as before this construct existed. The control matters: the
    # change taught the reader about `external_call` and must not have taught it
    # to lower tuple indices into a list.
    ("refuse_data_multi_index_still_refused",
     "def main(n: Int) -> Int:\n"
     "    a = [10, 20, 30]\n"
     "    i = 1\n"
     "    j = 2\n"
     "    return a[i, j]\n",
     "is a subscript whose index is a tuple"),
]


# ── MARSHALLING: what the return extension is and is not worth here ─────────
#
# `EXTERN_RETURN_INTS` puts `(bits, signed)` on the declared return, and the
# backends extend the return register to it. It is worth being precise about
# what that buys, because the obvious justification is FALSE on both of these
# ISAs: a narrow register WRITE zero-extends, so the value that arrives is
# `zero_extend(low N bits)` — not "whatever the callee left in the top half".
# What the extension actually does is convert a zero-extended narrow value into
# the SIGN-extended value a signed declared type means, and those are different
# numbers: `zero_extend(0xFFFFFFFF)` is 4294967295 and `sign_extend(0xFFFFFFFF)`
# is -1.
#
# MEASURED on this host: every libSystem symbol reachable from the corpus
# (`strcmp`, `atoi`, `memcmp`, `strcasecmp` were each built both ways) already
# hands back a sign-extended 64-bit word, so the emitted instruction is a no-op
# for all of them TODAY. It is kept anyway, and the reason is the paragraph
# above: a value model may not take its correctness from one libc's internal
# choice about a register the ABI leaves unspecified, and the answer to match is
# the reference lowering's — `emit_exprs.py::_lower_external_call` emits
# `extern int32_t setenv();` and lets C's typed assignment do this conversion.
#
# So `return_kind_32_signed_is_compared_as_a_word` above is a test of the
# VALUE, not of the instruction, and it would pass with the extension removed.
# That is a real limitation of testing through libSystem and it is stated here
# rather than left for the next reader to discover.


def build_formal(src, out, backend=None):
    """`fire.py build --formal --no-prove`, as a (returncode, output) pair."""
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(src)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_case(name, source, want_exit, want_stdout, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, name)
    rc, text = build_formal(src, out)
    if rc != 0:
        return False, text.strip()[-400:]
    if not os.path.isfile(out):
        return False, "build reported success but wrote no binary"
    run = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    if run.returncode != want_exit:
        return False, (f"exit status {run.returncode}, expected {want_exit}"
                       + (f"; stdout: {run.stdout.strip()[:120]}"
                          if run.stdout.strip() else ""))
    if want_stdout is not None and want_stdout not in run.stdout:
        return False, (f"stdout {run.stdout.strip()[:160]!r} does not contain "
                       f"{want_stdout!r}")
    if verbose:
        print(f"      stdout={run.stdout.strip()[:60]!r} exit={run.returncode}")
    return True, ""


def run_refusal(name, source, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                backend=backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct that has no "
                           f"representation (expected a refusal naming "
                           f"{needle!r}); the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-300:]}")
    if verbose:
        print(f"      refused identically on arm64 and x86-64: {needle!r}")
    return True, ""


# ── the model reader, without a build ──────────────────────────────────────
#
# `external_call_spec` is a decision three call sites and two architectures
# read, so its cases are worth holding without paying a build each. These parse
# a source string the same way the backends do, so a change in the parser that
# reshapes the bracket shows up here rather than as a mysterious None.
def model_cases():
    """`[(name, actual, expected)]` for the shared reader.

    Deliberately not raising on a mismatch: the runner compares and reports, so
    one wrong expectation prints what it got instead of aborting the suite.
    """
    import fire_compiler as F
    import formal.build as B
    import formal.model as M

    def spec(src):
        stmts = B.parse_module(src, "<model_cases>")
        for fn in B._extract_functions(stmts):
            for node in M.iter_nodes(fn.body):
                if isinstance(node, F.CallExpr) \
                        and M.is_external_call_template(node.func):
                    return M.external_call_spec(node.func)
        return None

    def why(src):
        got = spec(src)
        return None if got is None else got[2]

    out = []
    # The corpus's own three shapes, with the return type each one declares.
    out.append(("spec_setenv_int32",
                spec('def f(s):\n    return external_call["setenv", Int32]'
                     '(s, s, s)\n'),
                ("setenv", (32, True), None)))
    out.append(("spec_getenv_pointer",
                spec('def f(s):\n    return external_call["getenv", '
                     '_CPointer[UInt8, UntrackedOrigin[mut=False]]](s)\n'),
                ("getenv", M.EXTERN_RETURN_WORD, None)))
    out.append(("spec_void",
                spec('def f():\n    external_call["abort", NoneType]()\n'),
                ("abort", M.EXTERN_RETURN_VOID, None)))
    out.append(("spec_one_element_is_void",
                spec('def f():\n    external_call["abort"]()\n'),
                ("abort", M.EXTERN_RETURN_VOID, None)))
    # The C aliases `std/ffi` declares, read by name because a declared return
    # type is a type EXPRESSION and the alias is a module-level comptime
    # binding this path does not resolve to its target.
    out.append(("spec_c_int_is_32_signed",
                spec('def f(s):\n    return external_call["unsetenv", c_int](s)\n'),
                ("unsetenv", (32, True), None)))
    out.append(("spec_c_ssize_t_is_64",
                spec('def f():\n    return external_call["write", c_ssize_t]'
                     '(1, 1, 1)\n'),
                ("write", (64, True), None)))
    # The refusals, as a truthiness: each is "some sentence", and which
    # sentence is pinned by the `refuse:` builds above rather than by a string
    # that would have to be kept in two places.
    out.append(("spec_float_is_refused",
                bool(why('def f(s):\n'
                         '    return external_call["strtod", c_double](s)\n')),
                True))
    out.append(("spec_three_elements_refused",
                bool(why('def f(s):\n'
                         '    return external_call["sym", Int32, Int32](s)\n')),
                True))
    out.append(("spec_non_literal_symbol_refused",
                bool(why('def f(n):\n'
                         '    return external_call[n, Int32]("s")\n')),
                True))
    out.append(("not_a_template", spec('def f(a):\n    return a[1, 2]\n'), None))
    # The one entry `EXTERN_RETURN_INTS` and `POINTEE_WIDTHS` disagree about,
    # and the reason they are two tables: a declared `Int` is Mojo's Int64,
    # while a LOAD of an `Int` pointee is C's four-byte `int`.
    out.append(("return_kind_int_is_64_not_4",
                M.external_call_return_kind("Int"), (64, True)))
    out.append(("return_kind_pointer_is_a_word",
                M.external_call_return_kind("UnsafePointer[Int8, mut=False]"),
                M.EXTERN_RETURN_WORD))
    out.append(("return_kind_unknown_is_none",
                M.external_call_return_kind("Some[Thing]"), None))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: the arm64 formal image only runs on an arm64 host, "
              f"this is {platform.machine()}")
        return 0

    model = model_cases()
    passed = failed = 0
    everything = ([(c[0], "run") for c in CASES]
                  + [(c[0], "refuse") for c in REFUSALS]
                  + [(name, "model") for name, _a, _e in model])
    known = {c[0] for c in everything}
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 2

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, kind in selected:
            try:
                if kind == "model":
                    actual, expected = next((a, e) for n, a, e in model
                                            if n == name)
                    ok = actual == expected
                    detail = "" if ok else f"got {actual!r}, expected {expected!r}"
                elif kind == "refuse":
                    src, needle = next((c[1], c[2]) for c in REFUSALS
                                       if c[0] == name)
                    ok, detail = run_refusal(name, src, needle, tmpdir,
                                             args.verbose)
                else:
                    source, want_exit, want_stdout = next(
                        (c[1], c[2], c[3]) for c in CASES if c[0] == name)
                    ok, detail = run_case(name, source, want_exit, want_stdout,
                                          tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:      # unexpected: report, do not mask
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

    print(f"\nexternal_call: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
