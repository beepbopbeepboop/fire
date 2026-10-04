#!/usr/bin/env python3
"""DIFFERENTIAL FUZZING for the formal backend's PROOF LAYER: is a proof that
Lean's run accepted a proof about what the program MEANS?

    python3 tools/formal_proof_fuzz.py --count 40 --arch x86_64 -j 4

`tools/formal_fuzz.py` compares a compiled image against CPython and builds
every program with `--no-prove`, so it measures the CODE GENERATOR: a
disagreement there is a miscompile, and the largest thing it cannot say is
whether the backend BELIEVES the wrong answer.  This tool asks that question.
For each generated program it runs the two halves of the formal build and puts
their verdicts in one table:

    proof        what Lean said about the generated `.lean`
      pass       0 declarations admitted a `sorry` — the whole chain
                 (machine == bytes == AST == `mojo`, the semantic model) is
                 proved, so a disagreement below it is a statement about the
                 MODEL and nothing else
      admitted   it typechecked with N holes, and N is printed on every row
                 because `N = 0` and `N = 2` are different claims
      lean-rejected / bound-exceeded / proof-refused / codegen-refused /
      no-proof    the rest, all decided before Lean runs or without it

    behaviour    what the IMAGE did against CPython on the same text
      match / MISMATCH / refusal / trapped / timeout

and the cell this tool exists for is **`MISMATCH` under `pass`**.  A `pass`
says Lean checked that the compiled bytes compute the semantic model; the
mismatch says the semantic model is not what the program means.  That is a
SOUNDNESS bug of the model — the proof is a proof about a wrong model — and no
amount of fixing the code generator would touch it.  The same cell under
`admitted` is a weaker claim, in a way this file is careful about: on x86-64 the
generator's declared floor is exactly two holes (`<fn>_compile_correct`, the
AST-to-bytes link, and the step certificates), so what an x86-64 `admitted`
still FULLY proves is the AST-to-`mojo` half — which is where a wrong model
lives.  That is why every row carries its hole count and why `--holes-below`
exists: a campaign can declare how many holes it is still willing to argue
about, and the default is zero.

WHY A SECOND TOOL AND NOT A `--prove` ON THE FIRST
--------------------------------------------------
The two share everything mechanical and share nothing generative, and the
sharing is by IMPORT: this file takes `formal_fuzz`'s CPython oracle, its image
runner, its build command, its known-divergence table and its attribution, so
there is exactly ONE of each in the repository and a fix to the oracle reaches
both.  The generator is the only thing that is new, and it is new because the
two subjects need different programs.  `formal_fuzz.py`'s corpus is `main()` with
a dozen statements, loops, `print`s, lists and classes — the shape that stresses
the CODE GENERATOR, and a shape this backend's proof layer refuses nearly
everywhere (measured on this tree: 20 of 20 programs of each of two mixes
generate no arm64 proof at all, and the refusals name the `while` and the
`ForStmt`).  The corpus here is the shape the proof layer can actually reach: one
function, the entry, a few straight-line `int` statements, one final `print`.
Two corpora, one oracle.

WHAT IS GENERATED, AND WHY IT IS THE MODEL'S SUBSET
---------------------------------------------------
Every program is

    def main(n: Int) -> Int:
        <2..7 straight-line int statements: no loop, no call, no container>
        print(<one int expression>)
        return 0

and the statement vocabulary is `_stmts_go`'s own list of arms — `Return`,
`Pass`/`ExprStmt`, `Assign`, `AugAssign`, `VarDecl`, `IfStmt`, `WhileStmt` —
because `ForStmt`, `Break` and `Continue` raise there by name.  A corpus
outside that set would measure refusals, and refusals are not this subject.

The value discipline is `formal_fuzz.py`'s, restated here rather than imported
because it is a property of the GENERATOR and not of the harness: CPython's
integers are unbounded and a formal value is one 64-bit word, so every growing
term is masked back into `0..0xFFFF`; the signed family is `-32..32` combined
with `+`/`-` only; and `//`/`%` appear only over a non-negative dividend and an
odd divisor (`| 1`), because a zero divisor is a trap on the oracle.

The dividend restriction is no longer about the FLOORING question: both backends
floor now (`formal/model.py::division_floors` and `lib/ProofLib.lean`'s
`fdiv64`/`frem64`), and `tools/formal_fuzz.py`'s `signed` mix puts a signed
dividend over a signed divisor through the RUNTIME half with 100/100 matches.
It is here because of the PROOF half: a signed dividend over a free `n` reaches
`eval_eq_mojo`, whose rewrite is not decidable over a free `UInt64`
(`bugs/FORMAL_eval_eq_mojo_is_undecidable_over_a_free_n.md`, and the sweep
ledger `bugs/FORMAL_fuzz_ledger.md` §2.1a for the runtime side).  Lifting the
restriction is that doc's fix, not this file's.

One thing is generated ON PURPOSE and is the reason a corpus of unsigned words
would still be worth building: comparisons MIX the two families.  A signed
comparison is rendered by this backend as a sign-flipped unsigned one
(`^^^ 0x8000000000000000`), so every `>`/`<` in the emitted model is that flip,
and a corpus that only ever compared values below `2^31` could not notice the
day the flip was wrong.

OBSERVATION IS A `print`, NOT A RETURN VALUE
-------------------------------------------
On both backends the entry's return value IS the process exit status, and an exit
status is eight bits wide (`formal_fuzz.py`'s `cpython_answer` masks CPython's
the same way), so a 16-bit value is not observable that way.  The last statement
therefore prints one word and the comparison is over stdout.  It also keeps
`main`'s return at 0 on every engine, which keeps the two channels from being
confused with one another.

THE INPUTS, AND WHY THE PROVEN BUILD IS ONE OF THEM
----------------------------------------------------
`compile_formal`'s `test_input` is BAKED INTO THE IMAGE — the startup stub
materialises it — so a program's input is part of its identity and the proof is
generated for the binary built at that input.  So the input is drawn per
program from the seed, the proving build uses it, and it is one of the inputs
the behaviour comparison runs: the report marks it `PROVEN-INPUT`, because it is
the input with the proof's certificate behind it.  The other inputs are
codegen-only builds (`--no-prove`) of the same source, and a mismatch there is
reported without the soundness name, because what carries those into the proof
is the UNIVERSAL theorem (`for all n, the run from the entry equals mojo n`)
rather than the concrete run test — a weaker but still stated certificate.

WHAT A FINDING IS, AND WHAT IT IS NOT
-------------------------------------
  SOUNDNESS-MISMATCH   Lean ACCEPTED the proof with no holes and the image
                       disagrees with CPython at the proven input.  The model is
                       wrong about the source and the proof is about the model.
                       Minimised and reported; this is the bug class, and the
                       only one that sets the exit status.
  admitted-MISMATCH    the same disagreement with N holes in the file.  Reported
                       as its own name, because "the model is wrong" and "the
                       model is wrong and a hole is what let it through" are
                       different bugs.
  MISMATCH             the image disagrees with CPython and the proof did not
                       reach Lean, or reached it and was REJECTED.  A code
                       generator finding — `tools/formal_fuzz.py`'s class, kept
                       under its own name so the two are never counted together.
  KNOWN:<construct>    reduced to a row of `formal_fuzz.KNOWN_DIVERGENCES`
                       (`//`, `%`, `s[i]`) by the same minimise-then-neutralise
                       attribution.

EXIT STATUS: 1 when an unexplained `SOUNDNESS-MISMATCH` is reported.  A refusal,
a rejection, a bound and a known divergence are all reported and counted, and
none of them is a finding — a fuzzer that counted those would spend its whole
budget re-discovering `bugs/FORMAL_known_limits.md`.

WHAT IS NOT HERE, so the next reader does not have to measure it
----------------------------------------------------------------
  * loops, containers, strings, calls, a second function, or anything requiring
    an interface or a module — the model refuses those by name, and
    `formal/examples` plus `tools/formal_proof_breadth.py` own those shapes.
  * the TYPED model (`_stmts_go_t`: `Int8`, `UInt32`, the sign-extension
    invariant).  It is a second model and would need a second oracle: CPython
    has no `Int8`, so every generated program would need a hand-written
    wrap-around emulation, and an oracle written from the same reading of the
    language as the model under test cannot catch that model.  Stated as a
    limit, not hidden.
  * dylib contracts (`generate_dylib_proof`'s `Contracts.agrees_of_body`), whose
    spec derivation is its own subject with its own refusals
    (`bugs/FORMAL_per_export_contracts.md`) and its own teeth
    (`test_formal_dylib.py::a_wrong_spec_is_rejected_not_believed`).  This file
    is the PROGRAM path.
  * cross-architecture disagreement.  `tools/formal_fuzz.py` builds every program
    twice for that, and it is a codegen question rather than a model question:
    the semantic model here is SHARED (`x86_64_proof_gen` imports the model
    generator `arm64_proof_gen` drives), so a model bug is found on the cheaper
    architecture and both would report it.
"""
import argparse
import collections
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, HERE)          # `formal.build`, `formal.lean`

import formal_fuzz as F  # noqa: E402  — the oracle, the build, the attribution

#: Which half of `compile_formal` is running, per worker thread.  The proof
#: generators are wrapped rather than the messages being read, because "the
#: model refuses a construct" and "the generator crashed" arrive as the same
#: Python exception types and only the generator's frame tells them apart
#: (`tools/formal_proof_breadth.py`'s `_instrument_generators`, for the same
#: reason).
_PHASE = threading.local()

#: The source and the input the current worker's proving build is about.  Thread
#: locals rather than module globals because `compile_formal` takes both as
#: arguments and the wrapper around the generators does not: a leak across
#: workers would be a verdict about a program nobody generated.
_JOB = threading.local()

#: Verdicts `-v` is not needed to see: the common ones.  A printout of 200
#: agreements is noise, and a run that only printed its failures would be
#: indistinguishable from one that never looked.
QUIET_VERDICTS = ("match", "not-checked", "pass", "admitted", "refused-import")

# The classes `check_proof_cached`'s answer is folded into.  `pass` and `admitted`
# are the only two in which Lean accepted the file, and the difference between
# them is the hole count — which is why both carry it instead of being collapsed
# into "green".
PROOF_CLASSES = ("pass", "admitted", "lean-rejected", "bound-exceeded",
                 "lean-memory-exceeded", "proof-refused", "codegen-refused",
                 "refused-import", "proof-crash", "build-crash", "no-proof",
                 "not-checked")

#: The number of `sorry`s EVERY proof a generator emits carries, by
#: architecture — its DESIGNED trust boundaries, not a defect in any one proof.
#: x86-64's two are `<fn>_compile_correct` (the AST-to-bytes link, stated with a
#: hypothesis attached) and the step certificates; arm64's is 0. This is the
#: default for `--holes-below`, and it is a default rather than a constant
#: because a reader of an x86-64 campaign should not have to know that its
#: architecture can never emit a hole-free proof before a `SOUNDNESS` verdict is
#: possible at all: what that verdict asserts at the floor is still the whole of
#: the model, since the two holes are both in the machine half and the AST-to-
#: `mojo` half is fully proved.
HOLES_FLOOR = {"x86_64": 2, "arm64": 0}

# The verdict a mismatch is reported under when Lean accepted the proof.
SOUNDNESS = "SOUNDNESS-MISMATCH"
ADMITTED_BUG = "admitted-MISMATCH"
PLAIN = "MISMATCH"

# Inputs every program is also run at, beyond its own.  Five is enough to move a
# value across a sign boundary (`0x8000`) and across a branch threshold without
# making a run's cost quadratic: each is one codegen build and one process
# launch, against one Lean run that is 25x more expensive on arm64.
EXTRA_INPUTS = (0, 1, 3, 7, 32768)


# ── the generator ───────────────────────────────────────────────────────────

class ProveGen:
    """One provable program: a parameter, a few straight-line statements, a print.

    `words` are masked into `0..0xFFFF` and `smalls` are signed and stay in
    `-32..32`; comparisons MIX the two, which is the only way a sign decision
    the model makes has somewhere to be observed.

    Every local is DECLARED UP FRONT with the value CPython would not otherwise
    have.  A name that is only sometimes assigned — and here that is every name
    an `if` body assigns — is a `NameError` on the oracle and whatever the slot
    held on this path, so a generator that did not do this would report its own
    shape as a disagreement, which is `formal_fuzz.py`'s first generator
    invariant for the same reason.
    """

    def __init__(self, rng, input_value=10, stmts=(2, 7), params=1,
                 mix="plain"):
        self.rng = rng
        self.mix_name = mix
        self.input_value = input_value
        self.stmt_lo, self.stmt_hi = stmts
        self.params = ["n", "m"][:max(1, min(2, params))]
        self.counter = 0
        self.words = []
        self.smalls = []
        self.decls = []       # (name, initialiser) — emitted before the body
        self.out = []

    # ── plumbing ──
    def fresh(self, prefix):
        """A new local name, and its preamble declaration.

        `fresh` is the ONLY way a local comes into being, so every local is
        declared exactly once here — including the ones an `if` body assigns,
        which is what makes a read before that assignment zero on both engines.
        """
        self.counter += 1
        name = f"{prefix}{self.counter}"
        self.decls.append(name)
        return name

    def emit(self, indent, text):
        self.out.append("    " * indent + text)

    # ── expressions ──
    def lit(self):
        if self.rng.random() < 0.4:
            return str(self.rng.randint(-9, 9))
        return str(self.rng.choice([0, 1, 2, 3, 7, 8, 15, 16, 100, 255, 1000,
                                    32767, 32768, 65535]))

    def param(self):
        return self.rng.choice(self.params)

    def small_expr(self, depth=1):
        """Signed, and bounded so no engine's word width is reached."""
        if depth <= 0 or self.rng.random() < 0.45:
            if self.smalls and self.rng.random() < 0.6:
                return self.rng.choice(self.smalls)
            return str(self.rng.randint(-32, 32))
        op = self.rng.choice(["+", "-"])
        return f"({self.small_expr(depth - 1)} {op} {self.small_expr(depth - 1)})"

    def word_expr(self, depth=2):
        """A word expression: a non-negative value under `0xFFFF`, or a SMALL
        negative one.

        The bound is what keeps CPython's unbounded integers and a formal 64-bit
        word describing the same number: every `*` masks its own operands and
        every shift masks its left one, so a depth-two product cannot climb and
        the word-size model never reports itself as a finding.  What is NOT done
        is masking every subtraction — a negative intermediate is FINE on both
        engines (the codegen is signed and `print` shows the sign), and masking
        it away would remove the negative operand that the model's sign-flipped
        comparison exists to be checked against.
        """
        if depth <= 0 or self.rng.random() < 0.35:
            return self.rng.choice(self.words + [self.param()])
        kind = self.rng.choice(["mask", "add", "mul", "bit", "shift"])
        if kind == "mask":
            return f"({self.word_expr(depth - 1)} & 0xFFFF)"
        if kind == "add":
            op = self.rng.choice(["+", "-"])
            return (f"({self.word_expr(depth - 1)} {op} "
                    f"{self.word_expr(depth - 1)})")
        if kind == "mul":
            return (f"(({self.word_expr(depth - 1)} & 0xFF) * "
                    f"({self.word_expr(depth - 1)} & 0xF))")
        if kind == "shift":
            return (f"(({self.word_expr(depth - 1)} & 0xFFFF) >> "
                    f"{self.rng.randint(0, 15)})")
        op = self.rng.choice(["&", "|", "^"])
        left = (f"({self.word_expr(depth - 1)} & 0xFFFF)" if op == "&"
                else self.word_expr(depth - 1))
        return f"({left} {op} {self.rng.choice([1, 3, 7, 15, 255, 4095])})"

    def int_expr(self, depth=2):
        """Any integer-valued expression, still inside the value discipline."""
        if depth <= 0 or self.rng.random() < 0.5:
            pool = self.words + self.smalls + [self.param()]
            if pool and self.rng.random() < 0.8:
                return self.rng.choice(pool)
            return self.lit()
        r = self.rng.random()
        if r < 0.4:
            return self.word_expr(depth)
        if r < 0.6:
            return self.small_expr(1)
        if r < 0.75:
            # A division with a non-negative dividend and an ODD divisor: `| 1`
            # cannot be zero, so this stays a program on both engines instead of
            # becoming a ZeroDivisionError on the oracle.  The dividend stays
            # unsigned because of the PROOF layer rather than the model — see
            # this file's docstring.
            return (f"((({self.word_expr(1)}) & 0xFFFF) "
                    f"{self.rng.choice(['//', '%'])} "
                    f"(({self.word_expr(1)} & 0xFF) | 1))")
        op = self.rng.choice(["+", "-", "*"])
        return f"({self.small_expr(1)} {op} {self.small_expr(1)})"

    def cond(self, depth=1):
        """A comparison, half of them with a signed operand on one side.

        The signed half is the point: a signed comparison is rendered by this
        backend as a sign-flipped UNSIGNED one (`^^^ 0x8000000000000000`), so
        every `>` and `<` in the emitted model is that flip, and a corpus of
        unsigned words alone would never exercise it.
        """
        op = self.rng.choice(["<", "<=", ">", ">=", "==", "!="])
        if self.rng.random() < 0.4:
            return f"(({self.small_expr(1)}) {op} ({self.small_expr(1)}))"
        return (f"(({self.word_expr(1)}) {op} "
                f"(({self.word_expr(1)}) & 0xFFFF))")

    # ── statements ──
    def stmt(self, indent):
        # No `vardecl` here, and that is not an oversight: `var x = 1` is a
        # `VarDecl` arm of the model's statement fold and CPython cannot PARSE
        # the keyword, so a corpus containing it would be comparing two
        # different programs (the oracle's text would have to be rewritten, and
        # an oracle built from a rewritten source is an oracle for the rewrite).
        # `formal/examples/vardecl.mojo` and `formal_proof_breadth.py` are where
        # that arm is measured.
        kind = self.rng.choice(MIXES[self.mix_name])
        if kind == "assign":
            name = self.fresh("w")
            self.emit(indent, f"{name} = {self.word_expr(2)}")
            self.words.append(name)
        elif kind == "augassign":
            if not self.words:
                name = self.fresh("w")
                self.emit(indent, f"{name} = {self.word_expr(1)}")
                self.words.append(name)
                return
            target = self.rng.choice(self.words + [self.param()])
            op = self.rng.choice(["+=", "-=", "*=", "&=", "|=", "^="])
            rhs = (f"({self.int_expr(0)} & 0xF)" if op in ("+=", "-=", "*=")
                   else self.int_expr(0))
            self.emit(indent, f"{target} {op} {rhs}")
            if op in ("+=", "-=", "*="):
                # The mask bounds the ACCUMULATED value, and it is a second
                # statement because an augmented assignment cannot carry one.
                self.emit(indent, f"{target} = {target} & 0xFFFF")
        elif kind == "bool_local":
            # A boolean stored in a local.  The model renders a Bool as 1/0 and
            # the codegen as a word, so a program that keeps one and prints it
            # compares the two renderings rather than a truthiness.
            name = self.fresh("b")
            self.emit(indent, f"{name} = 1 if {self.cond(1)} else 0")
            self.words.append(name)
        else:
            self.emit(indent, f"if {self.cond(1)}:")
            first = self.fresh("w")
            self.emit(indent + 1, f"{first} = {self.word_expr(2)}")
            self.words.append(first)
            if self.rng.random() < 0.5:
                self.emit(indent, "else:")
            else:
                self.emit(indent, f"elif {self.cond(1)}:")
                self.emit(indent + 1, f"{first} = {self.word_expr(2)}")
                self.words.append(first)
                self.emit(indent, "else:")
            second = self.fresh("w")
            self.emit(indent + 1, f"{second} = {self.word_expr(2)}")
            self.words.append(second)

    def printed(self):
        """The one expression the comparison is about, and it READS something.

        A `print` of a literal is a program whose output does not depend on the
        input: it agrees with CPython no matter what the model says about the
        source, which is a green run that measures nothing.  So the printed
        expression is built over the parameters and the locals and is always
        at least one operand wide.
        """
        name = self.rng.choice(self.words + self.smalls + self.params
                               if (self.words or self.smalls) else self.params)
        kinds = ["name", "masked", "arith", "div"]
        if "bool_local" in MIXES[self.mix_name]:
            kinds.append("cond")
        kind = self.rng.choice(kinds)
        if kind == "name" or not self.words:
            return name
        if kind == "masked":
            return f"({name} & 0xFFFF)"
        if kind == "cond":
            return f"(1 if {self.cond(1)} else {self.word_expr(1)})"
        if kind == "div":
            return (f"(({name} & 0xFFFF) % ((({self.word_expr(1)} & 0xFF) | 1)))")
        op = self.rng.choice(["+", "-", "*", "^", "|"])
        return f"(({name} & 0xFFFF) {op} ({self.word_expr(1)} & 0xFF))"

    def program(self):
        for _ in range(self.rng.randint(self.stmt_lo, self.stmt_hi)):
            self.stmt(1)
        body = [f"    {name} = 0" for name in self.decls] + self.out
        body.append(f"    print({self.printed()})")
        body.append("    return 0")
        return "\n".join([f"def main({', '.join(self.params)}) -> Int:"]
                         + body) + "\n"

    def arg_words(self, value):
        """The argument list `main` is called with, one word per parameter.

        Past the first parameter this is `0`, and it has to be: `-n` supplies
        ONE value and `formal/build.py`'s `entry_arg_values` pads the rest with
        the `0` the startup stub leaves in the registers it materialises no
        argument into — so `m` is 0 in every image, and a reference that passed
        anything else would be a different program and would report its own
        difference as a finding about the model.
        """
        return ", ".join([str(value)] + ["0"] * (len(self.params) - 1))


#: Statement families per mix.  `plain` is the corpus that reaches Lean on BOTH
#: architectures; `ternary` adds the conditional expression, which the arm64
#: semantic model refuses by name ("a TernaryExpr has no value in the semantic
#: model") — a documented gap the census counts, and one that must not be paid
#: for by three quarters of every other corpus.
MIXES = {
    "plain": ("assign", "assign", "augassign", "if"),
    "ternary": ("assign", "assign", "augassign", "if", "bool_local"),
}


#: The input a program is built at, drawn from the seed rather than passed in.
#: It is part of the program's identity because the image has it baked in, and a
#: generator whose input and program could disagree is not reproducible from its
#: index.
DRAWN_INPUTS = (0, 1, 2, 3, 5, 7, 9, 10, 17, 42, 100, 255, 1000, 32767, 32768,
                65535)


def make_program(seed, index, stmts=(2, 7), mix="plain"):
    """`(text, input_value, nparams)` for program `index` of `seed` — a pure
    function of the three, as `formal_fuzz.make_program` is of its two, so a
    reported index reproduces byte for byte on any machine.

    The parameter count is returned rather than re-derived from the text
    because the reference call needs it: a two-parameter entry has to be handed
    the same words the image was, and reading the count off the text is a second
    answer waiting to disagree with this one.
    """
    rng = random.Random(f"{seed}:{index}:proof:{mix}")
    value = rng.choice(DRAWN_INPUTS)
    nparams = 1 if rng.random() < 0.75 else 2
    return ProveGen(rng, value, stmts, nparams, mix).program(), value, nparams


# ── the proof half ──────────────────────────────────────────────────────────

def _instrument_generators():
    """Wrap both proof generators so `_PHASE` says which half is running.

    `compile_formal` imports the generator INSIDE itself, so patching the module
    attribute is picked up by the call: no source change to the backend and no
    reliance on a message's wording, which is the only other way to tell
    `arm64_proof_gen`'s deliberate `NotImplementedError` from a genuine crash.
    Idempotent — calling it twice does not double-wrap.
    """
    if getattr(_instrument_generators, "done", False):
        return
    import formal.arm64_proof_gen as APG
    import formal.x86_64_proof_gen as XPG

    def wrap(real):
        def inner(*a, **kw):
            # `generate_entered` is set and NOT cleared here: an exception raised
            # by the generator unwinds through this `finally` on its way out, so a
            # flag restored on the way out would read False by the time the
            # handler that needs it runs.
            _PHASE.generate_entered = True
            was = getattr(_PHASE, "what", "build")
            _PHASE.what = "generate"
            try:
                return real(*a, **kw)
            finally:
                _PHASE.what = was
        return inner

    APG.generate_arm64_proof = wrap(APG.generate_arm64_proof)
    XPG.generate_x86_64_proof = wrap(XPG.generate_x86_64_proof)
    _instrument_generators.done = True


def _refused_import(detail):
    """Whether a refusal is about the TARGET rather than about a construct.

    A program that reaches for a CPython module is `not-answerable/host-import`
    in the sweep's vocabulary, already counted 241 times there; calling it a
    code-generator limit would dilute the class this tool is measuring.
    """
    text = str(detail or "")
    return ("host module" in text or "imports '" in text
            or "unresolved import" in text)


def _bound_detail(detail):
    text = str(detail or "")
    return "exceeded" in text and ("wall" in text or "CPU" in text)


def _lean_memory_detail(detail):
    """Whether Lean hit its OWN memory ceiling rather than rejecting anything.

    `formal/lean.py` gives every proof 6 GB (`LEAN_MEMORY_MB`) and Lean answers
    an elaboration it cannot hold with

        libc++abi: terminating due to uncaught exception of type
        lean::memory_exception: excessive memory consumption detected

    which is a statement about the MACHINE and not about the proof: the file was
    never finished with. It is its own class for the reason `run_lean`'s
    `bound-exceeded` is one — `bugs/FORMAL_proof_coverage_census_2026-10-03.md`
    §0.3 measured Lean's memory ceiling as the binding constraint on this half —
    and a campaign that counted it as `lean-rejected` would report a resource
    outcome as a fact about the generator, which is the one inference this tool
    must never make.
    """
    return "excessive memory consumption" in str(detail or "")


def proof_verdict(arch, work, timeout, check=True):
    """`(cls, detail, holes, proof_path)` for this worker's program.

    Phase A is `compile_formal(prove=True, check=False)` — the code generator AND
    the proof generator, which is what separates "the code generator refused"
    from "the proof generator refused" without a tactician.  Phase B is
    `formal.lean.check_proof_cached`, the same entry point `check=True` calls and
    therefore the same `formal/lean.py::run_lean` bounds; the per-item WALL bound
    is passed EXPLICITLY because the library's own default is 1500 s and a
    campaign of 200 programs needs a per-item bound to exist at all.  The CPU
    bound is left at Lean's own default, which is the half a wall clock
    under-counts.
    """
    import formal.build as FB
    from formal.lean import check_proof_cached

    def out(cls, detail, holes=0, path=None):
        return cls, str(detail)[:400], holes, path

    _instrument_generators()
    # Every path is per-PROGRAM, not per-architecture: `compile_formal` reads
    # the source it is handed and writes `<stem>_proof.lean` next to its output,
    # so two workers sharing a stem read each other's program (which a smoke run
    # showed as four parse errors out of sixty in a generator that emits none)
    # and would check each other's proof.
    src = os.path.join(work, f"{_JOB.name}.{arch}.mojo")
    with open(src, "w") as f:
        f.write(_JOB.text)
    _PHASE.what = "build"
    _PHASE.generate_entered = False
    try:
        result = FB.compile_formal(src, output=os.path.join(work, f"{_JOB.name}.{arch}"),
                                   test_input=_JOB.input, prove=True,
                                   check=False, arch=arch)
    except (FB.CodegenError, FB.FormalBuildError) as e:
        return out("refused-import" if _refused_import(str(e)) else
                   "codegen-refused", e)
    except NotImplementedError as e:
        # Only the proof generators raise this — the x86-64 one CATCHES it and
        # emits its documented placeholder — so which frame it came out of is
        # what separates `proof-refused` from a build crash.
        return out("proof-refused" if getattr(_PHASE, "generate_entered", False)
                   else "build-crash", e)
    except Exception as e:                      # noqa: BLE001 — a class here
        import traceback
        cls = ("proof-crash" if getattr(_PHASE, "generate_entered", False)
               else "build-crash")
        return out(cls, f"{type(e).__name__}: {e}\n"
                        f"{traceback.format_exc()[:500]}")
    proof_path = result.get("proof_path")
    if not proof_path or not os.path.isfile(proof_path):
        return out("no-proof", "an image that built emitted no proof")
    if not check:
        return out("not-checked", "", 0, proof_path)
    try:
        ok, detail, _cached, n_sorries = check_proof_cached(
            proof_path, repo_root=HERE, timeout=timeout)
    except Exception as e:                      # noqa: BLE001 — a class here
        return out("proof-crash", f"the proof check raised: {e}", path=proof_path)
    if ok:
        return out("pass" if not n_sorries else "admitted", detail,
                   n_sorries, proof_path)
    if _bound_detail(detail):
        return out("bound-exceeded", detail, n_sorries or 0, proof_path)
    if _lean_memory_detail(detail):
        return out("lean-memory-exceeded", detail, n_sorries or 0, proof_path)
    return out("lean-rejected", detail, n_sorries or 0, proof_path)


# ── the behaviour half ──────────────────────────────────────────────────────

def behaviour(arch, text, inputs, proven_input, nparams, tmpdir, name):
    """`(verdict, per_input)` for the image against CPython, one build per input.

    Each input is its own codegen-only build because the input is baked into the
    image; the build command, the runner and the oracle are `formal_fuzz`'s, so
    a refusal here is classified by the same code that classifies it there.
    """
    per = {}
    verdict = "match"
    for value in inputs:
        src = os.path.join(tmpdir, f"{name}.{value}.mojo")
        out = os.path.join(tmpdir, f"{name}.{value}.{arch}")
        with open(src, "w") as f:
            f.write(text)
        rc, diag = F.build(src, out, arch, test_input=value)
        if rc != 0:
            crashed = ("Traceback (most recent call last)" in diag or rc < 0
                       or rc in (134, 139, 136, 132, 133, 135, 137))
            cls = "crash" if crashed else "refusal"
            per[value] = {"verdict": cls, "detail": diag.strip()[-200:],
                          "proven": value == proven_input}
            verdict = cls if verdict in ("match", "crash", "trapped",
                                         "timeout") else verdict
            if cls == "crash":
                verdict = "crash"
            continue
        got, gerr = F.run(out, arch)
        if got is None:
            per[value] = {"verdict": "timeout", "detail": gerr,
                          "proven": value == proven_input}
            if verdict == "match":
                verdict = "timeout"
            continue
        exit_code, stdout = got
        info = {"verdict": "ok", "exit": exit_code, "stdout": stdout,
                "proven": value == proven_input}
        if exit_code == F.STACK_TRAP_STATUS:
            info["verdict"] = "trapped"
            info["detail"] = ("the stack-floor guard stopped it; CPython ran "
                              "the same text")
            if verdict == "match":
                verdict = "trapped"
            per[value] = info
            continue
        # The same words the image was handed: `-n` supplies ONE value and
        # `entry_arg_values` pads the remaining parameters with 0, so a
        # reference that passed anything else in those positions would be a
        # different program.
        words = ", ".join([str(value)] + ["0"] * (nparams - 1))
        ref, rerr = F.cpython_answer(text, tmpdir, f"{name}.{value}",
                                     args=words)
        if isinstance(ref, tuple) and ref and ref[0] == "error":
            info["verdict"] = "generator-error"
            info["detail"] = ref[1]
            verdict = "generator-error"
            per[value] = info
            continue
        if not F.has_oracle(ref):
            # The oracle could not finish, which is not the same as the oracle
            # saying the generator is wrong — `has_oracle` is the one reader of
            # the three answers, and reading it any other way unpacks the
            # timeout's `None` three lines below. These programs are RECURSIVE
            # by construction (`--stmts` grows the recursion depth), so a
            # CPython recursion-limit or wall-clock timeout is reachable here
            # and not hypothetical.
            info["verdict"] = "CPYTHON-TIMEOUT"
            info["detail"] = rerr
            if verdict == "match":
                verdict = "CPYTHON-TIMEOUT"
            per[value] = info
            continue
        info["want_exit"], info["want_stdout"] = ref
        if exit_code != ref[0] or stdout != ref[1]:
            info["verdict"] = "MISMATCH"
            # A mismatch at ANY input is a disagreement; the record says which
            # of them the proof was generated for, because that is what decides
            # the verdict's name.
            if info["proven"] or verdict in ("match", "crash"):
                verdict = "MISMATCH"
        per[value] = info
    return verdict, per


# ── one program ─────────────────────────────────────────────────────────────

def decide(proof, behaviour_verdict, holes_below):
    """The classification, and it is a CROSS of the two halves.

    A mismatch is a soundness finding only where Lean accepted the file, and
    even then the hole count decides how loudly it may be said.  A mismatch with
    no accepted proof is a code generator finding, named as one: conflating the
    two would either turn every miscompile into a claim about the model or lose
    the soundness findings among them.
    """
    if behaviour_verdict != "MISMATCH":
        return behaviour_verdict
    cls = proof["cls"]
    if cls == "pass":
        return SOUNDNESS
    if cls == "admitted" and (proof["holes"] or 0) <= holes_below:
        return ADMITTED_BUG
    return PLAIN


def check_one(index, args, tmpdir):
    """One program through both halves, and the cell where they meet."""
    text, drawn, nparams = make_program(args.seed, index,
                                        stmts=tuple(args.stmts),
                                        mix=args.mix)
    _JOB.text = text
    _JOB.input = drawn
    _JOB.name = f"p{index}.{threading.get_ident()}"
    inputs = [drawn] + [i for i in args.extra_inputs if i != drawn]
    rec = {"index": index, "text": text, "input": drawn, "inputs": inputs,
           "nparams": nparams, "proof": {}, "behaviour": {}}
    for arch in args.backends:
        cls, detail, holes, proof_path = proof_verdict(arch, args.work,
                                                       args.timeout,
                                                       args.check_lean)
        rec["proof"][arch] = {"cls": cls, "detail": detail, "holes": holes,
                              "proof_path": proof_path}
        if args.check:
            verdict, per = behaviour(arch, text, inputs, drawn, nparams,
                                     tmpdir, f"p{index}")
            rec["behaviour"][arch] = {"verdict": verdict, "per_input": per}
            rec["verdict"] = decide(rec["proof"][arch], verdict,
                                    args.holes_below)
    if "verdict" not in rec:
        rec["verdict"] = rec["proof"][args.backends[0]]["cls"]
    return rec


# ── reporting ───────────────────────────────────────────────────────────────

def shorten(text, limit=200):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def report(rec):
    verdict = rec.get("verdict")
    if verdict in (None, "match", "refusal", "trapped", "timeout"):
        return []
    if verdict not in (SOUNDNESS, ADMITTED_BUG, PLAIN):
        return [f"  {verdict}  #{rec['index']}  input={rec['input']}"]
    lines = [f"  {verdict}  #{rec['index']}  input={rec['input']}"]
    for arch, proof in sorted(rec["proof"].items()):
        lines.append(f"      proof/{arch:<6} {proof['cls']} "
                     f"({proof['holes']} hole(s))")
    for arch, b in sorted(rec["behaviour"].items()):
        for value, info in sorted(b.get("per_input", {}).items()):
            if info["verdict"] not in ("MISMATCH", "ok"):
                lines.append(f"      image/{arch:<6} n={value}: "
                             f"{info['verdict']}: "
                             f"{shorten(info.get('detail', ''), 140)}")
                continue
            if info["verdict"] == "MISMATCH":
                tag = "PROVEN-INPUT" if info.get("proven") else "codegen-only"
                lines.append(
                    f"      image/{arch:<6} n={value} [{tag}] want "
                    f"{shorten(info['want_stdout'])!r} got "
                    f"{shorten(info['stdout'])!r}")
    return lines


# ── the run ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--count", type=int, default=20,
                    help="how many programs to generate")
    ap.add_argument("-s", "--seed", default="formal-proof-fuzz",
                    help="the seed; program i is a pure function of (seed, i)")
    ap.add_argument("--arch", default="x86_64",
                    choices=("x86_64", "arm64", "both"))
    ap.add_argument("--mix", default="plain", choices=sorted(MIXES),
                    help="which statement families: `plain` is the corpus that "
                         "reaches Lean on both architectures, `ternary` adds "
                         "the conditional expression the arm64 model refuses "
                         "by name")
    ap.add_argument("--stmts", nargs=2, type=int, metavar=("LO", "HI"),
                    default=(2, 7),
                    help="how many straight-line statements main's body carries")
    ap.add_argument("-t", "--timeout", type=float, default=300.0,
                    help="per-proof WALL bound in seconds, passed to "
                         "check_proof_cached (Lean's own CPU bound is its "
                         "default, and it is the half a wall clock misses)")
    ap.add_argument("--holes-below", type=int, default=None,
                    help="the largest hole count an `admitted` verdict may carry "
                         "and still be reported as a model bug (default: this "
                         "architecture's DESIGNED floor — 2 on x86-64, whose "
                         "declared trust boundaries are the AST-to-bytes link "
                         "and the step certificates, 0 on arm64)")
    ap.add_argument("--no-lean", action="store_true",
                    help="phase A and the images, but no Lean run: the "
                         "behaviour half alone, which is `tools/formal_fuzz.py`'s "
                         "measurement over this corpus.  Nothing here is then "
                         "a soundness verdict — there is no accepted proof to "
                         "have one.")
    ap.add_argument("--no-check", action="store_true",
                    help="phase A only — generate the proofs and classify what "
                         "the generators do, without running Lean or the "
                         "images.  A census of the proof layer's coverage.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every program and its two verdicts, not only the "
                         "findings")
    ap.add_argument("--print-program", type=int, default=None, metavar="INDEX",
                    help="print one generated program and its input, and exit")
    ap.add_argument("-j", "--jobs", type=int, default=2,
                    help="how many programs in flight; one Lean proof is ~6 GB, "
                         "so this is a MEMORY knob as much as a time one")
    ap.add_argument("--work", default=os.path.join(HERE, ".tmp",
                                                   "formal_proof_fuzz"))
    args = ap.parse_args()
    args.backends = (["arm64", "x86_64"] if args.arch == "both"
                     else [args.arch])
    args.extra_inputs = EXTRA_INPUTS
    if args.holes_below is None:
        args.holes_below = max(HOLES_FLOOR[b] for b in args.backends)
    args.check = not args.no_check
    args.check_lean = args.check and not args.no_lean
    if args.print_program is not None:
        text, drawn, nparams = make_program(args.seed, args.print_program,
                                            stmts=tuple(args.stmts),
                                            mix=args.mix)
        sys.stdout.write(text)
        print(f"# the image is built at n = {drawn}"
              + (", and m = 0 (a second parameter is 0 in every image)"
                 if nparams > 1 else ""))
        return 0
    if sys.version_info < (3, 10):
        print("ERROR: the formal backend needs python3 >= 3.10 "
              "(export PATH=/opt/homebrew/bin:$PATH first)", file=sys.stderr)
        return 2
    os.makedirs(args.work, exist_ok=True)

    started = time.time()
    counts = collections.Counter()
    proof_counts = collections.Counter()
    findings = []
    recs = []
    # The ledger is APPENDED as each program finishes, not written at the end.
    # A campaign is minutes to hours (arm64 is ~2 min a proof and x86-64 ~30 s,
    # and both are content-addressed so a re-run is free), and a tool that only
    # publishes at the end publishes NOTHING when the run is interrupted — which
    # is exactly the run whose results you want. One JSON line per program is
    # also the shape `bugs/sweeps/*.jsonl` already uses for the same reason.
    ledger_path = os.path.join(args.work, "records.jsonl")
    open(ledger_path, "w").close()
    tmpdir = tempfile.mkdtemp(prefix="proofuzz.", dir=args.work)
    try:
        with open(ledger_path, "a") as ledger:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                for rec in pool.map(lambda i: check_one(i, args, tmpdir),
                                     range(args.count)):
                    recs.append(rec)
                    counts[rec.get("verdict")] += 1
                    for arch, proof in rec["proof"].items():
                        proof_counts[(arch, proof["cls"])] += 1
                    if rec.get("verdict") in (SOUNDNESS, ADMITTED_BUG, PLAIN):
                        findings.append(rec)
                    ledger.write(json.dumps(rec, sort_keys=True) + "\n")
                    ledger.flush()
                    if args.verbose or rec.get("verdict") not in QUIET_VERDICTS:
                        for line in report(rec):
                            print(line, flush=True)
    finally:
        subprocess.run(["rm", "-rf", tmpdir])

    # The summary, next to the per-program ledger written as the run went: every
    # record goes in one of them or the other, so a census run is re-derivable as
    # a `Counter` over a file — and the rows that are NOT findings (the
    # refusals, the rejections, the bounds) are most of what such a counter is
    # read for.
    # `summary.json` and NOT the ledger: the ledger is opened "w" here, which
    # would truncate the per-program lines the run just wrote.
    summary = os.path.join(args.work, "summary.json")
    with open(summary, "w") as f:
        json.dump({"args": vars(args), "counts": dict(counts),
                   "proof": {f"{a}:{c}": n
                             for (a, c), n in sorted(proof_counts.items())},
                   "findings": findings, "records": recs}, f, indent=1)
    elapsed = time.time() - started
    print(f"\nformal_proof_fuzz seed={args.seed} arch={args.arch} "
          f"programs={args.count} in {elapsed:.1f}s (jobs={args.jobs}, "
          f"holes-below={args.holes_below})")
    print("  the proof half, per architecture (every class, zero included):")
    for arch in args.backends:
        print(f"    {arch:<7} " + "  ".join(
            f"{c}={proof_counts.get((arch, c), 0)}" for c in PROOF_CLASSES))
    print("  the behaviour half, and the cell the two meet in:")
    for v, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {v:<20} {n}")
    print(f"ledger: {ledger_path} (one JSON line per program), "
          f"summary: {summary}")
    return 1 if any(r.get("verdict") == SOUNDNESS for r in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
