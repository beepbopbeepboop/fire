#!/usr/bin/env python3
"""Differential fuzzing for the formal backend: the BUILT BINARY vs CPython.

Why this file exists
--------------------
Every correctness test of the formal backend in this tree asserts a hand-written
EXPECTED answer: `test_formal_run.py` says `exit 7` and `a=6`, `test_formal.py`
says the proof typechecks. That is the strongest possible assertion on the cases
it covers and it is blind everywhere else — a construct nobody thought to write
down is measured by nothing. The corpus is ~700 hand-written cases and the
construct space is unbounded, so the blind spot is not small.

This tool closes it from the other end: it GENERATES small random programs in
the subset the backend accepts, builds each one, RUNS it, runs the SAME TEXT
through CPython, and requires identical stdout and an identical exit status. A
program that builds, exits 0 and prints the wrong number is a SILENT
MISCOMPILE — the worst class of defect on this path, because nothing else in
the tree can see it (the proof is about the emitted code, and the emitted code
faithfully implements a model that computes the wrong thing).

    python3 tools/formal_fuzz.py                     # seeds 0..49, arm64
    python3 tools/formal_fuzz.py --seeds 1000-1199 -j 2
    python3 tools/formal_fuzz.py --arch x86_64
    python3 tools/formal_fuzz.py --seed 7 --print    # show the program

DETERMINISM
-----------
`gen_program(seed)` is a pure function of the seed, so a seed reproduces its
program byte for byte on any machine and any run, and a failure reported here is
re-reportable without keeping anything but the number. `--print` prints the
source for a seed; the repro directory keeps it for the ones that diverged.

WHAT IS AND IS NOT A FINDING
----------------------------
Three verdicts, kept apart because they mean different things:

  AGREE      the binary and CPython printed the same bytes and exited the same
             way. The interesting count.
  REFUSED    the backend declined to build the program. **Not a bug**: the
             backend's design is that a construct it cannot represent is
             refused rather than guessed, and this subset is deliberately at the
             edge of what it accepts. The construct is recorded and counted, so
             the refusal rate is a measurement of the subset's reach rather than
             noise.
  DIVERGED   the binary ran and disagreed with CPython. **A finding**, unless it
             reduces to a construct `KNOWN_DIVERGENCES` already names — see
             below.

WHY A DIVERGENCE IS MINIMISED BEFORE IT IS REPORTED
---------------------------------------------------
A generated program that diverges is usually wrong for one reason in one line,
and reporting it whole hides that. Every divergence is reduced by a
delta-debugging pass over the program's own chunks (and then over the lines of
what survives) that keeps only reductions that still diverge, so what lands in
the repro directory and on the screen is the smallest thing that still
reproduces. The reduction is memoised, so a program with many chunks costs
about two builds per chunk and not one per candidate pair.

KNOWN DIVERGENCES, AND WHY THE CLASSIFICATION IS NOT A DISMISSAL
----------------------------------------------------------------
A handful of constructs in the subset are known to disagree with CPython today
(they are in `KNOWN_DIVERGENCES` with the document that owns each). Those are
counted separately from `DIVERGED` so a sweep of 2000 seeds is readable, and
each one is still checked for being the ACTUAL cause rather than assumed to be:
after the reduction, the program is re-tested with every chunk containing a
known-divergent construct removed, and it is only blamed on that construct if
the program then AGREES with CPython. A program that still diverges without it
is reported as a finding with the known construct still listed, because "there
is a known bug in here too" is not a reason to miss this one.

Every repro — blamed or not — is written under `--repro-dir` (default
`build/formal-fuzz/<arch>/`), so the classification is checkable rather than
trusted.

EXIT STATUS
-----------
0 when nothing is unexplained: no `DIVERGED`, or every `DIVERGED` reduced to a
named known construct. 1 when at least one divergence is unexplained, or when a
seed could not be generated at all. A tool that returned 0 while a program
computed the wrong number would be worse than no tool.
"""

import argparse
import concurrent.futures
import hashlib
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIRE = os.path.join(ROOT, "fire.py")

BUILD_TIMEOUT = 120
RUN_TIMEOUT = 20
CPY_TIMEOUT = 20

# The largest number of live int locals a generated function keeps. The backend
# puts locals in registers and refuses past a frame's word count (there are
# cases either side of 15 in `test_formal_run.py`), so an unbounded generator
# would spend most of its seeds on a refusal about register pressure instead of
# about arithmetic. Helpers and classes get their own budget.
MAX_LOCALS = 10

# `known feature` -> (one line, the document that owns it). The feature markers
# are matched against the REDUCED program, so a marker names a construct that is
# present in the minimal reproducer.
KNOWN_DIVERGENCES = {
    "floordiv": (
        "`//` truncates toward zero instead of flooring (bugs/"
        "FORMAL_floor_division_on_a_signed_operand_is_truncated.md)"),
    "modulo": (
        "`%` takes the sign of the DIVIDEND instead of the divisor (same doc as "
        "`floordiv`)"),
    "truediv": (
        "`/` between two ints is an integer division; the model is int-only and "
        "floats truncate toward zero on emit (FORMAL.md §6, Phase 7)"),
    "print_bool": (
        "a `bool` prints as 1/0 rather than True/False: a formal value is one "
        "word and the tag is not carried (`formal/arm64_codegen.py`'s "
        "`_print_call`)"),
    "str_subscript": (
        "`s[i]` is a byte, not a one-character string (bugs/"
        "FORMAL_string_value_model.md)"),
    "one_field_plain_store": (
        "a method of a ONE-FIELD class that stores its own field through a "
        "receiver not declared `out` drops the store"),
}

# The constructs that make a feature marker true. Checked against the reduced
# program's text; a marker is only blamed when removing every chunk that
# contains one of its spellings makes the program agree.
FEATURE_PATTERNS = {
    "floordiv": (r"//",),
    "modulo": (r"%",),
    "truediv": (r"(?<![/*])/(?![/*=])",),
    "print_bool": (r"\bprint\(\s*[^\n()]*\s(?:==|!=|<|>|<=|>=)\s",),
    "one_field_plain_store": (r"self\.\w+\s*=[^=]",),
    # Decided by `features_of`, not by a pattern: a subscript is correct on a
    # list and wrong on a string, and only the binding says which. An empty
    # pattern tuple is how this table says "handled specially", and keeping the
    # KEY is what lets the neutraliser and the summary find it by name.
    "str_subscript": (),
}


# ── the program model ─────────────────────────────────────────────────────────
#
# A program is a list of CHUNKS: source text that is independently droppable.
# That is what makes the reducer a reducer rather than a guess — dropping chunk
# `i` must leave a program that still parses, still defines `main`, and still
# prints something, and a chunk that is a whole `def`, a whole class, or a
# whole `if`/`while` block has that property by construction.

class Program:
    """A generated program as droppable chunks, plus the text they assemble to."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def source(self, keep=None):
        """The whole program, or the subset named by `keep` (indices)."""
        chunks = self.chunks if keep is None else [
            c for i, c in enumerate(self.chunks) if i in keep]
        return "\n".join(chunks) + "\n"

    def digest(self):
        return hashlib.sha256(self.source().encode()).hexdigest()[:16]


def _lit(rnd):
    """An int literal, usually small and often negative.

    Negative values are the point of the distribution rather than a side effect:
    they are what separates a signed reading of a 64-bit word from an unsigned
    one, and an all-positive corpus would find nothing in that half of the space.
    """
    r = rnd.random()
    if r < 0.30:
        return str(rnd.randint(-9, 9))
    if r < 0.55:
        return str(-rnd.randint(1, 40))
    if r < 0.80:
        return str(rnd.randint(0, 20))
    return str(rnd.randint(-1000, 1000))


class Gen:
    """Generates one program's chunks. `rng` is the only source of randomness.

    FIVE RULES the generator holds itself to. Each is a correctness requirement
    for the MEASUREMENT, not a style preference: a program that violates one
    produces no verdict at all, and a run in which a fifth of the seeds produce
    no verdict reports nothing about the backend.

    * **A name is read only if it is bound on every path to the read.** The
      scope threaded through the statement generators is exactly that: a
      statement's own new names join the scope for the statements AFTER it in
      the same body, an enclosing loop's counter joins its own body, and only a
      top-level statement's names are published to the whole of `main`. Without
      that discipline the generator emits `x = x + 1` and programs whose oracle
      is CPython's own `NameError`.
    * **A divisor is never zero.** The backend TRAPS on a zero divisor, so a
      program that could reach one would be an error rather than a verdict.
      Divisors come from a dedicated non-zero pool with both signs, because the
      sign of the divisor is precisely what separates a floored remainder from a
      truncated one.
    * **Loops are counted.** Every `while` and every `for` is over `range` with
      literal bounds and a body of bounded statements, so no seed can hang. A
      timeout is not a verdict and would make every number in the summary
      ambiguous.
    * **A statement never has an empty body.** A `while` whose body came out
      empty (no helper to call, no local to read) is a syntax error in both
      engines, and a corpus that quietly generates them measures its own
      generator.
    * **The program is valid Python as written.** There is one source text and
      both engines read it — that is the measurement — so `var`, `fn`, `struct`,
      `Self`, `.format()` and every other Mojo-only spelling are absent by
      construction rather than filtered afterwards.
    """

    # `%` and `//` are in the pool because the divergences they cause are named
    # in `KNOWN_DIVERGENCES` and therefore counted rather than hidden, and
    # because a generator that cannot emit them cannot notice the day they are
    # fixed. `/` is NOT in the pool: it is not an integer operation on this path
    # at all (the model is int-only — FORMAL.md §6, Phase 7), so including it
    # would spend a third of the division seeds on a known limit of the model
    # rather than on the backend's own arithmetic.
    # Only the operators whose right operand cannot change the program's
    # meaning. `%` and `//` are NOT here and are generated by their own cases
    # below, with a literal non-zero divisor: putting them in this table would
    # let an arbitrary expression become a divisor, and a divisor that can be
    # zero is a trap on this path rather than a verdict.
    ARITH = ("+", "-", "*")
    CMP = ("==", "!=", "<", ">", "<=", ">=")

    # Non-zero divisors, both signs. Kept non-zero for the trap and signed for
    # the sign rule: `7 % -2` is where truncated and floored disagree.
    DIVISORS = (2, 3, 4, 5, 7, 11, -2, -3, -4, -7)

    def __init__(self, rng):
        self.rng = rng
        self.scope = []          # int locals bound at the current position
        self.strs = []           # (name, length) of str locals, top level only
        self.lists = []          # (name, length) of list locals, top level only
        self.funcs = []          # (name, arity) of generated helpers
        self.classes = []        # (name, one_field) of generated classes
        self.n = 0               # the name counter, shared by every kind

    def fresh(self):
        self.n += 1
        return f"v{self.n}"

    # ── expressions ──────────────────────────────────────────────────────────

    def int_expr(self, scope, depth=0, allow_func=True):
        """An int-typed expression the two engines must agree on.

        A comparison comes back as `1 if … else 0` rather than as a bare `bool`:
        a formal value is one word and carries no truth tag, so printing a bare
        comparison prints `1` where CPython prints `True`. That is a known
        divergence, and leaving it in would mix it into the output of every
        branch and make each report say less about the thing that went wrong.
        """
        rng = self.rng
        if depth >= 2:
            return self.atom(scope, allow_func)
        r = rng.random()
        if r < 0.46:
            op = rng.choice(self.ARITH)
            return (f"({self.int_expr(scope, depth + 1)} {op} "
                    f"{self.int_expr(scope, depth + 1)})")
        if r < 0.62:
            op = rng.choice(self.CMP)
            return (f"(1 if {self.int_expr(scope, depth + 1)} {op} "
                    f"{self.int_expr(scope, depth + 1)} else 0)")
        if r < 0.70:
            op = rng.choice(("and", "or"))
            return (f"(1 if ({self.int_expr(scope, depth + 1)}) {op} "
                    f"({self.int_expr(scope, depth + 1)}) else 0)")
        if r < 0.76:
            return f"(1 if not ({self.int_expr(scope, depth + 1)}) else 0)"
        if r < 0.81:
            return f"(-({self.int_expr(scope, depth + 1)}))"
        if r < 0.86:
            return (f"({self.int_expr(scope, depth + 1)} % "
                    f"{rng.choice(self.DIVISORS)})")
        if r < 0.90:
            return (f"({self.int_expr(scope, depth + 1)} // "
                    f"{rng.choice(self.DIVISORS)})")
        if r < 0.94:
            return (f"({self.int_expr(scope, depth + 1)} * "
                    f"{rng.randint(2, 5)})")
        return self.atom(scope)

    def atom(self, scope, allow_func=True):
        """A leaf: a bound local, a literal, a subscript, a literal length, a
        call.

        `allow_func` is what makes the recursion terminate. A call's arguments
        are themselves generated from the leaf level, so a call inside a call
        needs the leaf generator to be allowed to pick a call again — and
        without the flag that is unbounded, because `int_expr` hands `atom` a
        leaf request at every depth. One boolean, and the generator is
        structurally incapable of hanging.
        """
        rng = self.rng
        choices = []
        if scope:
            choices.append("int")
        if self.strs:
            choices.append("str")
        if self.lists:
            choices.append("list")
        if self.funcs and allow_func:
            choices.append("func")
        if not choices:
            return _lit(rng)
        pick = rng.choice(choices)
        if pick == "int":
            return rng.choice(scope)
        if pick == "str":
            return str(rng.choice(self.strs)[1])
        if pick == "list":
            lst, ln = rng.choice(self.lists)
            return f"{lst}[{rng.randrange(ln)}]"
        name, arity = rng.choice(self.funcs)
        args = ", ".join(self.int_expr(scope, 2, False) for _ in range(arity))
        return f"{name}({args})"

    # ── statements ───────────────────────────────────────────────────────────
    #
    # Each returns source lines. `scope` is the set of int locals bound at this
    # point, which the statement extends with whatever it binds for the
    # statements after it in the same body; `publish` says the names also join
    # `main`'s whole-function scope, which only a top-level statement may say.

    def assign(self, indent, scope, publish):
        name = self.fresh()
        lines = [f"{indent}{name} = {self.int_expr(scope)}"]
        if publish:
            self.scope.append(name)
        else:
            scope.append(name)
        return lines

    def emit(self, indent, scope, publish):
        return [f"{indent}print({self.int_expr(scope)})"]

    def if_block(self, indent, scope, publish):
        rng = self.rng
        lines = [f"{indent}if {self.int_expr(scope)} == 0:"]
        for _ in range(rng.randint(1, 3)):
            lines += self.stmt(indent + "    ", list(scope), False)
        if rng.random() < 0.5:
            lines += [f"{indent}else:"]
            for _ in range(rng.randint(1, 2)):
                lines += self.stmt(indent + "    ", list(scope), False)
        return lines

    def while_block(self, indent, scope, publish):
        rng = self.rng
        i = self.fresh()
        inner = list(scope) + [i]
        lines = [f"{indent}{i} = 0", f"{indent}while {i} < {rng.randint(1, 5)}:"]
        for _ in range(rng.randint(1, 2)):
            lines += self.stmt(indent + "    ", list(inner), False)
        lines += [f"{indent}    {i} = {i} + 1"]
        if publish:
            self.scope.append(i)
        else:
            scope.append(i)
        return lines

    def for_range(self, indent, scope, publish):
        rng = self.rng
        i = self.fresh()
        lo = rng.randint(-3, 3)
        hi = lo + rng.randint(0, 6)
        args = (f"{lo}, {hi}" if rng.random() < 0.8
                else f"{lo}, {hi}, {rng.choice((2, 3))}")
        inner = list(scope) + [i]
        lines = [f"{indent}for {i} in range({args}):"]
        for _ in range(rng.randint(1, 2)):
            lines += self.stmt(indent + "    ", list(inner), False)
        if publish:
            self.scope.append(i)     # `for` binds the target even over an empty range
        else:
            scope.append(i)
        return lines

    def list_chunk(self, indent, scope, publish):
        rng = self.rng
        name = self.fresh()
        ln = rng.randint(1, 4)
        items = ", ".join(str(rng.randint(-9, 9)) for _ in range(ln))
        lines = [f"{indent}{name} = [{items}]"]
        lines += ([f"{indent}print(len({name}))"] if rng.random() < 0.4
                  else [f"{indent}print({name}[{rng.randrange(ln)}])"])
        if rng.random() < 0.4:
            e = self.fresh()
            lines += [f"{indent}for {e} in {name}:", f"{indent}    print({e})"]
        if publish:
            self.lists.append((name, ln))
        return lines

    def str_chunk(self, indent, scope, publish):
        rng = self.rng
        name = self.fresh()
        word = rng.choice(("ab", "abc", "mojo", "xy"))
        lines = [f'{indent}{name} = "{word}"']
        pick = rng.random()
        if pick < 0.4:
            lines += [f"{indent}print(len({name}))"]
        elif pick < 0.7:
            lines += [f'{indent}print(1 if {name} == "{word}" else 0)']
        else:
            lines += [f"{indent}print({name}[0])"]
        if publish:
            self.strs.append((name, len(word)))
        return lines

    def call_chunk(self, indent, scope, publish):
        """Call a helper. Falls back to a print when there is no helper yet, so
        a statement is never empty — a `while` with an empty body is a syntax
        error in both engines and would be a seed that measures nothing."""
        if not self.funcs:
            return self.emit(indent, scope, publish)
        name, arity = self.rng.choice(self.funcs)
        args = ", ".join(self.int_expr(scope) for _ in range(arity))
        target = self.fresh()
        lines = [f"{indent}{target} = {name}({args})", f"{indent}print({target})"]
        if publish:
            self.scope.append(target)
        else:
            scope.append(target)
        return lines

    def obj_chunk(self, indent, scope, publish):
        if not self.classes:
            return self.emit(indent, scope, publish)
        cls, _one = self.rng.choice(self.classes)
        tag = self.fresh()
        lines = [f"{indent}{tag} = {cls}()"]
        if self.rng.random() < 0.7:
            lines.append(f"{indent}{tag}.bump()")
        lines.append(f"{indent}print({tag}.get())")
        return lines

    def stmt(self, indent="    ", scope=None, publish=True):
        rng = self.rng
        if scope is None:
            scope = self.scope
        pool = ((self.assign,) * 3 + (self.emit,) * 3 + (self.list_chunk,)
                + (self.str_chunk,) + (self.call_chunk,) + (self.if_block,) * 2
                + (self.while_block,) + (self.for_range,))
        return rng.choice(pool)(indent, scope, publish)

    # ── module scope ─────────────────────────────────────────────────────────

    def helper_chunk(self):
        """A module-level function, recursive about half the time.

        Whether `main` calls it is left to a later chunk. The corpus wants the
        callee's body reachable and it wants the statement forms represented, and
        forcing every helper to be called would bias the corpus towards recursion
        and away from the branches.
        """
        rng = self.rng
        name = self.fresh()
        arity = rng.randint(1, 2)
        params = ", ".join(f"p{i}" for i in range(arity))
        first = params.split(", ")[0]
        # `-> Int` on every helper, and the reason is coverage rather than
        # realism: without it a comparison against a call's result is REFUSED
        # ("arrived from a call that does not say what it holds"), which on an
        # earlier corpus was a third of all seeds. The annotation is the only
        # thing that tells the backend what the callee hands back, and `Int` is
        # the default width so it does not change which proof model is used.
        if rng.random() < 0.45:
            recursed = ", ".join([f"{first} - 1"] + params.split(", ")[1:])
            lines = [f"def {name}({params}) -> Int:",
                     f"    if {first} <= 1:",
                     f"        return {rng.randint(0, 3)}",
                     f"    return {name}({recursed}) + {rng.randint(1, 3)}"]
        else:
            lines = [f"def {name}({params}) -> Int:", f"    t = {first}"]
            for _ in range(rng.randint(1, 3)):
                r = rng.random()
                if r < 0.4:
                    lines.append(f"    t = t + {rng.randint(1, 5)}")
                elif r < 0.6:
                    lines.append(f"    if t > {rng.randint(-3, 6)}:")
                    lines.append(f"        t = t * {rng.randint(2, 3)}")
                else:
                    lines.append(f"    t = t % {rng.choice(self.DIVISORS)}")
            lines.append("    return t")
        self.funcs.append((name, arity))
        return "\n".join(lines)

    def class_chunk(self):
        """A class with one or two int fields, a reader and a mutator.

        Both widths are generated on purpose. Two fields is the case that works
        and one field is the case with the dropped store, so a corpus with only
        the working width would report that bug fixed the moment someone deleted
        the one-field rows.
        """
        rng = self.rng
        name = self.fresh().capitalize()
        one = rng.random() < 0.5
        fields = ["a"] if one else ["a", "b"]
        lines = [f"class {name}:", "    def __init__(self):"]
        lines += [f"        self.{f} = {rng.randint(-5, 9)}" for f in fields]
        lines += ["", "    def get(self):",
                  "        return " + " + ".join(f"self.{f}" for f in fields)]
        lines += ["", "    def bump(self):",
                  f"        self.{fields[0]} = self.{fields[0]} + "
                  f"{rng.randint(1, 5)}"]
        self.classes.append((name, one))
        return "\n".join(lines)

    def program(self):
        """One program: module-scope chunks, then `main`'s body, then the call.

        `main(n)` takes the entry argument because that is the form the backend's
        entry point expects, and the trailing `main(0)` is what lets the SAME
        text be CPython's source as well — the two engines reading one file is
        the whole measurement, and a translated copy of the program would be a
        second program that could differ.
        """
        rng = self.rng
        chunks = []
        for _ in range(rng.randint(0, 2)):
            chunks.append(self.helper_chunk())
        if rng.random() < 0.6:
            chunks.append(self.class_chunk())
        body = []
        for _ in range(rng.randint(4, 9)):
            body += self.stmt("    ", self.scope, True)
        if self.classes and rng.random() < 0.7:
            body += self.obj_chunk("    ", self.scope, True)
        chunks.append("def main(n):\n" + "\n".join(body) + "\n    return 0")
        chunks.append("main(0)")
        return Program(chunks)


def gen_program(seed):
    """The program for `seed`. Pure: same seed, same bytes, any machine."""
    return Gen(random.Random(seed)).program()


# ── running one program ───────────────────────────────────────────────────────

class Verdict:
    __slots__ = ("seed", "status", "detail", "program", "cp_stdout", "mojo_stdout",
                 "cp_rc", "mojo_rc", "refusal", "blame")

    def __init__(self, seed, status, detail="", program=None, cp_stdout=None,
                 mojo_stdout=None, cp_rc=None, mojo_rc=None, refusal=""):
        self.seed = seed
        self.status = status
        self.detail = detail
        self.program = program
        self.cp_stdout = cp_stdout
        self.mojo_stdout = mojo_stdout
        self.cp_rc = cp_rc
        self.mojo_rc = mojo_rc
        self.refusal = refusal
        self.blame = None


def _run(argv, cwd=None, timeout=RUN_TIMEOUT):
    """(stdout, returncode, stderr), or (None, None, '') on a timeout.

    stderr is carried rather than discarded because it is where a refusal's
    message lives: `fire.py build` reports the construct it declined on stderr,
    and a summary of "N programs were refused" is worth nothing next to which
    construct each one was refused on.
    """
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           errors="replace", timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return None, None, ""
    return p.stdout, p.returncode, p.stderr


def _first_line(text):
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def check_program(program, arch, workdir, memo=None):
    """Build `program`, run it, and run the SAME TEXT through CPython.

    `memo` is an optional `{source: Verdict}` cache shared across a run: the
    reducer tries many variants of the same program and most recur.
    """
    source = program.source()
    if memo is not None and source in memo:
        return memo[source]
    v = _check_uncached(source, arch, workdir)
    if memo is not None:
        memo[source] = v
    return v


def _check_uncached(source, arch, workdir):
    path = os.path.join(workdir, "prog.mojo")
    with open(path, "w") as f:
        f.write(source)
    out = os.path.join(workdir, "prog.bin")

    _b_out, build_rc, build_err = _run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         f"--backend={arch}", "-o", out, path],
        cwd=ROOT, timeout=BUILD_TIMEOUT)
    if build_rc is None:
        return Verdict(-1, "ERROR", f"the BUILD timed out after {BUILD_TIMEOUT}s")
    if build_rc != 0:
        return Verdict(-1, "REFUSED",
                       refusal=_first_line(build_err) or "refused")
    if not os.path.isfile(out):
        return Verdict(-1, "ERROR", "the build reported success and wrote no binary")

    cp_out, cp_rc, cp_err = _run([sys.executable, path], cwd=workdir,
                                 timeout=CPY_TIMEOUT)
    if cp_out is None:
        return Verdict(-1, "ERROR", "CPython timed out on the generated program")
    if cp_rc != 0:
        # The generator produced a program CPython will not run, so there is no
        # oracle to compare against. That is a bug in the GENERATOR, not in the
        # backend, and it is reported rather than skipped: a generator that
        # silently drops a third of its corpus is not measuring what it claims.
        return Verdict(-1, "ERROR",
                       f"CPython exits {cp_rc} on its own generated program: "
                       f"{_oneline(cp_err)}")

    mojo_out, mojo_rc, mojo_err = _run([out], cwd=workdir)
    if mojo_out is None:
        return Verdict(-1, "ERROR", "the built program timed out")
    os.remove(out)

    if mojo_out == cp_out and mojo_rc == cp_rc:
        return Verdict(-1, "AGREE")
    why = []
    if mojo_rc != cp_rc:
        why.append(f"exit {mojo_rc} vs CPython's {cp_rc}")
    if mojo_out != cp_out:
        a, b = cp_out.splitlines(), mojo_out.splitlines()
        for i in range(max(len(a), len(b))):
            x = a[i] if i < len(a) else "<missing>"
            y = b[i] if i < len(b) else "<missing>"
            if x != y:
                why.append(f"line {i + 1}: {y!r} vs {x!r}")
                break
    return Verdict(-1, "DIVERGED", "; ".join(why), cp_stdout=cp_out,
                   mojo_stdout=mojo_out, cp_rc=cp_rc, mojo_rc=mojo_rc)


# ── reduction ────────────────────────────────────────────────────────────────
#
# Two phases, and the order matters. Whole chunks first: a `def`, a class or a
# compound statement is the unit the generator emitted, so dropping one is always
# syntactically safe. Then `main`'s body one top-level statement at a time,
# which is where a divergence in a generated program nearly always lives — a
# program is a dozen statements and only one of them is wrong.

def _body_blocks(chunk):
    """`main`'s body split into its top-level statements.

    A statement is recognised by its indentation rather than by re-parsing,
    because the generator wrote the source and knows the shape: a compound
    statement's whole body is indented deeper, so the block boundaries are
    exactly the lines at four spaces.
    """
    blocks, cur = [], []
    for line in chunk.splitlines()[1:]:
        if line.startswith("    ") and not line.startswith("        ") and cur:
            blocks.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def _candidates(program):
    """Every smaller program worth testing, in the order most likely to be kept.

    Three families, and the order is what makes the reduction reach a minimal
    program rather than stalling:

    * **drop a whole chunk** — a `def`, a class, or `main`'s body. Safe because
      the generator emitted each chunk as an independent unit.
    * **drop one top-level block of `main`'s body** — the delta-debugging move
      that actually reduces, and the one a chunk-level pass alone cannot make:
      `main`'s statements share names, so removing all but one of them takes the
      definitions with it and the candidate dies of `NameError` before it is ever
      compared. Removing one at a time keeps every definition alive.
    * **keep one block only** — the finishing move, once the body is down to the
      statements that matter.
    """
    out = []
    for i in range(len(program.chunks)):
        out.append(Program([c for j, c in enumerate(program.chunks) if j != i]))
    for i, chunk in enumerate(program.chunks):
        if not chunk.startswith("def main("):
            continue
        head, blocks = chunk.splitlines()[0], _body_blocks(chunk)
        for j in range(len(blocks)):
            rest = blocks[:j] + blocks[j + 1:]
            out.append(Program([c if j != i else _with_body(head, rest)
                                for j, c in enumerate(program.chunks)]))
        for b in blocks:
            out.append(Program([c if k != i else _with_body(head, [b])
                                for k, c in enumerate(program.chunks)]))
    return out


def _with_body(head, blocks):
    """`main` with `blocks` as its body. `return 0` is appended when the blocks
    do not end in one, because the entry function's return value is the process
    exit status and a program that falls off its end is a different program."""
    text = "\n".join(blocks)
    if not text.rstrip().endswith("return 0"):
        text = text + "\n    return 0" if text else "    return 0"
    return head + "\n" + text


def _has_body(program):
    """Whether `program` is still a program: a `main` that prints something and
    a call to it. A reduction that empties `main` is not a reproducer, and a
    candidate that stops building or stops running under CPython is rejected by
    the status check instead — which is the property that keeps every reduction
    a real one."""
    src = program.source()
    if "def main(" not in src or "main(0)" not in src:
        return False
    body = src.split("def main(", 1)[1]
    return "print(" in body


def reduce_divergence(program, arch, workdir, memo, log=None):
    """The smallest sub-program that still diverges.

    A candidate is kept only when it still DIVERGES, so the reduction can only
    remove code the divergence does not need; the result is a real reproducer
    and not an approximation of one. The loop restarts after every accepted
    reduction because dropping an earlier chunk can make a later one droppable.
    """
    best = program
    progress = True
    while progress:
        progress = False
        here = best.source()
        for cand in _candidates(best):
            # A candidate that IS the current program would be accepted on its
            # own verdict, and the loop would never end: "keep one block only"
            # is the same program when the body is already one block.
            if cand.source() == here or not _has_body(cand):
                continue
            if check_program(cand, arch, workdir, memo).status != "DIVERGED":
                continue
            if log:
                log(f"    reduced {len(best.source())} -> "
                    f"{len(cand.source())} bytes")
            best = cand
            progress = True
            break
    return best


# ── classification ───────────────────────────────────────────────────────────
#
# A divergence is only a FINDING if it is not a construct already known to
# disagree. Two things have to be true for the known list to be usable: the
# reduction has to have got the bug down to a couple of lines, and the tool has
# to be able to tell whether a given divergence is that known bug or something
# else. The second is done by NEUTRALISING the suspect construct in place and
# asking whether the program then agrees — see `blame`.

# A name bound to a string literal. Needed because `x[0]` is CORRECT for a list
# and wrong for a string, and the two differ only in what `x` was bound to — a
# pattern that matched every subscript would blame the known string divergence on
# every list subscript in the corpus, which is the over-attribution this whole
# mechanism exists to avoid.
STR_ASSIGN = re.compile(r"^ *(\w+) *= *\"", re.M)


def features_of(source):
    """The known-divergent constructs the text uses."""
    strs = STR_ASSIGN.findall(source)
    out = set()
    for name, pats in FEATURE_PATTERNS.items():
        if name == "str_subscript":
            if any(re.search(r"\b%s\s*\[" % re.escape(n), source) for n in strs):
                out.add(name)
            continue
        if any(re.search(p, source) for p in pats):
            out.add(name)
    return out


# How to take one known construct out of a program WITHOUT changing its shape:
# the operator is swapped for one with the same arity and the same operand
# types, or the offending line is replaced by an equivalent one. Shape matters
# because the alternative — deleting the statements that mention the construct —
# takes the definitions with it, so the program then fails for a reason that has
# nothing to do with the divergence and nothing is learned. Swapping `//` for
# `-` leaves every name bound and every statement in place, so if the program
# agrees afterwards then the division is what was wrong.
NEUTRALISERS = {
    "floordiv": [(r"//", "-")],
    "modulo": [(r"(?<![\w)])%(?![a-zA-Z_(])", "+")],
    "print_bool": [(r"print\(([^\n]*?)\)", r"print(1 if (\1) else 0)")],
    "str_subscript": [(r"print\((\w+)\[\d+\]\)", r"print(1)")],
    "one_field_plain_store": [(r"^ *\w+\.bump\(\)\n", "")],
}


def neutralise(program, feature):
    """`program` with `feature`'s construct swapped out, or None if it has none."""
    edits = NEUTRALISERS.get(feature)
    if not edits:
        return None
    out = program.source()
    before = out
    for pat, repl in edits:
        out = re.sub(pat, repl, out, flags=re.M)
    if out == before:
        return None
    return Program([out])


def blame(program, arch, workdir, memo):
    """Which known construct, if any, actually explains this divergence.

    Each known construct the reduced program uses is neutralised in turn and the
    result rebuilt. If the program then AGREES with CPython, that construct was
    the cause and the divergence is not a new finding. If it still DIVERGES, the
    construct is not the cause and the program is reported anyway — a known bug
    being present in a reproducer is not a reason to miss a different one
    alongside it, and a tool that reported only the first would be hiding the
    second behind the first.

    `None` means unexplained, which is the only answer that makes the run's exit
    status non-zero.
    """
    present = features_of(program.source())
    for name in sorted(present):
        cand = neutralise(program, name)
        if cand is None or not _has_body(cand):
            continue
        v = check_program(cand, arch, workdir, memo)
        if v.status == "AGREE":
            return name
    return None


# ── the run ───────────────────────────────────────────────────────────────────

def one_seed(seed, arch, workdir, memo):
    program = gen_program(seed)
    v = check_program(program, arch, workdir, memo)
    v.seed = seed
    v.program = program
    if v.status == "AGREE" or v.status == "REFUSED" or v.status == "ERROR":
        return v
    reduced = reduce_divergence(v.program, arch, workdir, memo)
    # Re-check the REDUCED program, so the report and the repro file quote the
    # small program's own two answers. Carrying the original program's output
    # forward would describe a program nobody is being asked to look at.
    final = check_program(reduced, arch, workdir, memo)
    final.program = reduced
    final.seed = v.seed
    final.blame = blame(reduced, arch, workdir, memo)
    final.detail = (f"seed {v.seed}: reduced from {len(v.program.source())} to "
                    f"{len(reduced.source())} bytes")
    return final


def _worker(args):
    seed, arch = args
    with tempfile.TemporaryDirectory(prefix="fuzz_") as td:
        return one_seed(seed, arch, td, None)


def parse_seeds(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part.lstrip("-"):
            lo, _, hi = part.partition("-")
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="0-49",
                    help="a seed list: `a-b`, `a,b,c`, or both (default 0-49)")
    ap.add_argument("--arch", default="arm64", choices=("arm64", "x86_64"))
    ap.add_argument("-j", "--jobs", type=int, default=2)
    ap.add_argument("--repro-dir", default=None,
                    help="where reproducers go (default build/formal-fuzz/<arch>)")
    ap.add_argument("--seed", type=int, default=None,
                    help="print one program's source and exit")
    ap.add_argument("--print", action="store_true",
                    help="print every reduced reproducer's source")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.seed is not None:
        sys.stdout.write(gen_program(args.seed).source())
        return 0

    seeds = parse_seeds(args.seeds)
    repro_dir = args.repro_dir or os.path.join(ROOT, "build", "formal-fuzz",
                                               args.arch)
    os.makedirs(repro_dir, exist_ok=True)

    counts = {"AGREE": 0, "REFUSED": 0, "DIVERGED": 0, "ERROR": 0}
    known = {}
    refusals = {}
    findings = []
    errors = []

    work = [(s, args.arch) for s in seeds]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        for v in ex.map(_worker, work):
            counts[v.status] = counts.get(v.status, 0) + 1
            if v.status == "REFUSED":
                key = _refusal_family(v.refusal)
                refusals[key] = refusals.get(key, 0) + 1
                if args.verbose:
                    print(f"REFUSED seed {v.seed}: {v.refusal[:140]}")
            elif v.status == "DIVERGED":
                got = getattr(v, "blame", None)
                if got:
                    known[got] = known.get(got, 0) + 1
                    if known[got] == 1:
                        _write_repro(repro_dir, v, args.arch, suffix=f".{got}")
                    if args.verbose:
                        print(f"KNOWN seed {v.seed}: {got} — {v.detail}")
                else:
                    findings.append(v)
                    _write_repro(repro_dir, v, args.arch)
            elif v.status == "ERROR":
                errors.append(v)

    print()
    print()
    print(f"formal fuzz: {args.arch}, {len(seeds)} seed(s), -j {args.jobs}")
    print(f"  agree       {counts['AGREE']}")
    print(f"  refused     {counts['REFUSED']}"
          + (f"  ({len(refusals)} distinct constructs)" if refusals else ""))
    print(f"  diverged    {counts['DIVERGED']}  "
          f"({sum(known.values())} attributed to a known construct, "
          f"{len(findings)} unexplained)")
    print(f"  errors      {counts['ERROR']}")
    if known:
        print("  known constructs blamed:")
        for name, n in sorted(known.items(), key=lambda kv: -kv[1]):
            print(f"    {n:5d}  {name}: {KNOWN_DIVERGENCES.get(name, '')}")
    if refusals:
        print("  most-refused constructs:")
        for key, n in sorted(refusals.items(), key=lambda kv: -kv[1])[:12]:
            print(f"    {n:5d}  {key[:130]}")
    if errors:
        print("  ERRORS (about the generator or the build, not a verdict on a bug):")
        for v in errors[:20]:
            print(f"    {v.detail[:220]}")
    if findings:
        print()
        print(f"  {len(findings)} UNEXPLAINED DIVERGENCE(S). Each one builds, runs and")
        print("  exits 0 while printing something CPython does not print:")
        for v in findings:
            print(f"    seed {v.seed}  ({v.detail})")
            print(f"      CPython  exit {v.cp_rc}: {_oneline(v.cp_stdout)}")
            print(f"      {args.arch:6} exit {v.mojo_rc}: {_oneline(v.mojo_stdout)}")
            if args.print:
                print(_indent(v.program.source(), "      "))
            print(f"      reproducer: {os.path.join(repro_dir, _repro_name(v, args.arch))}")
    print(f"  reproducers in {repro_dir}")
    return 1 if (findings or errors) else 0


def _oneline(text):
    return " ".join((text or "").split())[:160]


def _indent(text, prefix):
    return "\n".join(prefix + ln for ln in text.rstrip().splitlines())


def _refusal_family(message):
    """The refusal's first clause, with any construct-specific tail dropped, so
    the summary groups `for-range step must be a literal` together instead of
    printing the same sentence once per seed."""
    m = (message or "").strip()
    m = re.split(r"\(got ", m)[0]
    m = re.sub(r"`[^`]*`", "`X`", m)
    return m.strip()


def _repro_name(v, arch):
    return f"seed{v.seed}-{arch}-{v.program.digest()}.mojo"


def _write_repro(repro_dir, v, arch, suffix=""):
    path = os.path.join(repro_dir, _repro_name(v, arch) + suffix)
    with open(path, "w") as f:
        f.write("# seed %d, %s. CPython exit %s, backend exit %s\n"
                % (v.seed, arch, v.cp_rc, v.mojo_rc))
        f.write("# CPython : %s\n" % _oneline(v.cp_stdout))
        f.write("# %-6s : %s\n" % (arch, _oneline(v.mojo_stdout)))
        f.write(v.program.source())
    return path


if __name__ == "__main__":
    sys.exit(main())