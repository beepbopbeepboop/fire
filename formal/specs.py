"""`@refines(...)` — asking a generated proof to check the program against an
INDEPENDENT specification.

## Why this module exists

Every generated proof in this tree ends in a theorem of the shape

    theorem <prog>_compiles_correctly_universal (n : UInt64) (hn : …) :
      (match runProg <prog>_prog n with | some s => s.x0 = mojo n | none => False)

and `mojo` is the generator's own model of the SOURCE.  So the theorem says the
machine code computes what the model of the source computes — and the model is
derived from the same source file, by the same front end, in the same pass.
That is a genuine theorem and a **self-consistency** theorem: a mistake in the
reading of the source is invisible to it, because both sides are that reading.
What it never says is anything about what the program was *supposed* to
compute, which is the question a reader of `formal/examples/fib.mojo` actually
has.

`lib/Specs.lean` is the other side of that question — reference definitions
written by hand in Lean's own `Nat`/`Int`/`List`, with no reference to
`ProofLib`'s machine model, to a generated file, or to each other.  This module
is the WIRING: it reads the annotation that names one of those definitions,
and emits the two theorems that put the machine and the specification on
opposite sides of an equation.

## The annotation

    @refines(Specs.fib64; 64)
    def fib(n):
        …

Two clauses, and BOTH are load-bearing:

  * the first is a dotted Lean name, naming a `UInt64 → UInt64` word reading
    from `lib/Specs.lean`.  It is spelled as a Lean term and is USED as one —
    the emitted theorem's right-hand side is that name, so a name that does not
    exist, or one with the wrong arity, is a Lean elaboration error rather than
    a string that happened to be written down.
  * the second is the RANGE: the refinement is stated for every input below it.

The range is not decoration.  A word reading is `UInt64.ofNat` of a
mathematical value, so `mojo n = Specs.fib64 n` is FALSE for an `n` whose
Fibonacci number does not fit in a word — the equation is only true where the
truncation cannot bite, and the range is where the author says it cannot.  A
second clause is required rather than defaulted because a defaulted range would
be a number nobody chose and everybody would read as a property of the
specification.

`@refines` is OPTIONAL in the strongest sense: an unannotated program gets no
refinement section, no `import Specs`, and a byte-identical proof file to the
one it got before this module existed.  That is checked, not hoped for —
`test_formal_specs.py` builds an unannotated example and compares.

## Why the check has teeth

`main_model_refines_spec` is discharged by `native_decide`, which EVALUATES
both sides — the generator's `mojo` and the hand-written specification — for
every input in the range.  A specification that does not match the program
therefore fails the build instead of being believed: the emitted goal is `false`
and Lean says so.  `test_formal_specs.py::test_a_wrong_specification_is_rejected`
is the negative control, and it is the only thing that would notice this module
quietly degenerating into emitting a theorem nobody checks.

The honest limit of the instrument is stated in the emitted theorem's own
docstring: it is a range, not all inputs.  The unbounded claim needs an
induction over the program's loop structure, which is a different proof for each
example and is not attempted here — see
`bugs/FORMAL_a_specification_layer_that_stops_at_a_finite_range.md`.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fire_compiler as F  # noqa: E402

#: The decorator that asks for the check.  One name, so a program's request is
#: greppable and so a second spelling cannot appear without being noticed.
REFINES_DECORATOR = "refines"

#: The range a `@refines(…)` may ask for, and why it is a ceiling.  The check is
#: `native_decide` over `List.range N`, so its cost is linear in `N` in the
#: model's own evaluation — and an annotation is SOURCE, so a range with no
#: ceiling is a way for a source file to make every build that reads it more
#: expensive, by an amount chosen by whoever wrote the file rather than by
#: whoever maintains the compiler.  1024 is far past any range in this corpus
#: (`factorial64` is exact for 21 inputs, `sumTo64` for billions) and small
#: enough that the check is a fraction of a second.
MAX_RANGE = 1024

#: The range used when a program is refined against a specification that needs
#: no bound at all (an `abs` of a two's-complement word, a popcount, a
#: comparison's answer).  Still finite, because the instrument is finite; see
#: the module docstring.
DEFAULT_RANGE = 64


class RefinesRefusal(NotImplementedError):
    """Why an `@refines(…)` annotation cannot be honoured, as a build refusal.

    A refusal rather than a guess, for the reason `_dylib_spec_lean` documents:
    a specification is a CLAIM about the program, and emitting the theorem
    against a specification the author did not name is a believed falsehood with
    a proof attached.

    **`NotImplementedError` is the base because that is how BOTH proof
    generators refuse**, and `formal/build.py::compile_formal` already catches
    it and re-raises a `FormalBuildError` carrying the sentence — so this
    refusal reaches the reader as `build: <why>` instead of as a traceback with
    forty frames of generator internals above the one line that says what is
    wrong.  A second exception type here would be a second refusal channel, and
    the one caller of it would have to know about both.
    """


def dotted_name(node) -> str:
    """`Specs.fib64` as one string, from the shapes a dotted name has here.

    The parser builds `A.b` as a `MemberExpr` over an `IdentExpr` when it is a
    plain dotted path, which is the only spelling `@refines(…)` accepts; an
    index, a call, or a subscript gives `""` and is refused rather than
    half-read.
    """
    if isinstance(node, F.IdentExpr):
        return str(node.name)
    if isinstance(node, F.MemberExpr):
        base = dotted_name(getattr(node, "obj", None))
        member = str(getattr(node, "member", "") or "")
        return f"{base}.{member}" if base and member else ""
    return ""


def _decorator_name(deco) -> str:
    """The bare `@name` a decorator names, from the three spellings.

    A bare `@deco` arrives as a string, `@deco(x)` as a `CallExpr`, and
    `@deco(c1; c2)` as a `DecoratorArgs` (see
    `fire_compiler.Parser._parse_decorator_args` — a `;` at the top level of a
    decorator's region is what makes it a specification rather than a call).
    All three can spell `@refines`, and a decorator that refused one and accepted
    another would be a construct whose behaviour depends on punctuation.
    """
    if isinstance(deco, str):
        return deco
    name = getattr(deco, "name", None)
    if isinstance(name, str) and name:
        return name
    func = getattr(deco, "func", None)
    if isinstance(func, F.IdentExpr):
        return str(func.name)
    if isinstance(func, F.MemberExpr):
        return dotted_name(func)
    return ""


class Refines:
    """What one `@refines(…)` annotation asks for."""

    __slots__ = ("spec", "rng")

    def __init__(self, spec: str, rng: int):
        self.spec = spec
        self.rng = rng

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Refines({self.spec!r}, {self.rng})"


_RANGE_RE = re.compile(r"^[0-9]+$")
_LEAFAN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(\.[A-Za-z_][A-Za-z0-9_']*)*$")
# `DecoratorArgs` keeps a clause as its TOKEN TEXT joined by single spaces, so a
# dotted name comes back as `Specs . id64` — the `.` is its own token.  Joining
# the dotted pieces back together is what makes one spelling of a Lean name
# rather than three (which only one of them is a name).
_DOT_SPACE_RE = re.compile(r"\s*\.\s*")


def _normalise_name(text: str) -> str:
    """A clause's token text as a Lean name: `Specs . id64` → `Specs.id64`."""
    return _DOT_SPACE_RE.sub(".", text.strip())


def spec_refinement(fn, where: str = "") -> Refines | None:
    """The `@refines(…)` on `fn`, or None when it carries none.

    `where` is the build's name for the function, used only in the refusal text
    — an annotation this module cannot honour has to say which file it was in,
    and the `FunctionDef` carries no source position for a decorator's argument.

    One reader, and both backends call it: a `@refines` that worked on arm64 and
    was refused on x86-64 would be a construct whose behaviour depends on which
    machine compiled it, which is the same defect `unapplied_decorator_refusal`
    exists to prevent for the decorators it classifies.
    """
    for deco in (getattr(fn, "decorators", None) or []):
        if _decorator_name(deco) != REFINES_DECORATOR:
            continue
        clauses = list(getattr(deco, "clauses", None) or [])
        if clauses:
            return _from_clauses(clauses, where)
        args = list(getattr(deco, "args", None) or [])
        return _from_args(args, where)
    return None


def _from_clauses(clauses: list, where: str) -> Refines:
    """`@refines(Name; Range)` — the `;` form, which is the one documented."""
    clauses = [c.strip() for c in clauses]
    if len(clauses) != 2:
        raise RefinesRefusal(
            f"@{REFINES_DECORATOR} takes exactly two clauses — the name of a "
            f"specification and the range of inputs it is checked on — and this "
            f"one has {len(clauses)}: {clauses!r}{_at(where)}. The range is not "
            f"optional: a word reading is `UInt64.ofNat` of a mathematical "
            f"value, so `mojo n = <spec> n` is false for an `n` whose value "
            f"does not fit in a word, and a range nobody chose is a number "
            f"everybody would read as a property of the specification")
    spec, rng = _normalise_name(clauses[0]), clauses[1]
    if not _LEAFAN_NAME_RE.match(spec):
        raise RefinesRefusal(
            f"@{REFINES_DECORATOR}'s first clause is {spec!r}, which is not a "
            f"Lean name{_at(where)}. It names a `UInt64 → UInt64` word reading "
            f"of `lib/Specs.lean` — `fib64`, `factorial64`, `abs64`, … — and it "
            f"is used as a Lean term, so a name that does not exist is an "
            f"elaboration error rather than a string that happened to be "
            f"written down")
    if not _RANGE_RE.match(rng):
        raise RefinesRefusal(
            f"@{REFINES_DECORATOR}'s second clause is {rng!r}, which is not a "
            f"decimal count{_at(where)}. It is the number of inputs the check "
            f"covers: the theorem is stated for every input below it, and "
            f"`native_decide` evaluates both sides once per input")
    value = int(rng)
    if value < 1:
        raise RefinesRefusal(
            f"@{REFINES_DECORATOR} was given the range {value}{_at(where)}, and "
            f"a range of {value} inputs checks nothing: the emitted theorem "
            f"would be a statement about an empty set of inputs, which is the "
            f"shape a vacuous proof looks like")
    if value > MAX_RANGE:
        raise RefinesRefusal(
            f"@{REFINES_DECORATOR} was given the range {value}, above this "
            f"module's ceiling of {MAX_RANGE}{_at(where)}. The check is "
            f"`native_decide` over `List.range N`, so its cost is linear in `N`, "
            f"and an annotation is SOURCE — a range with no ceiling is a way for "
            f"a file to make every build that reads it more expensive, by an "
            f"amount chosen by whoever wrote the file rather than by whoever "
            f"maintains the compiler")
    return Refines(spec, value)


def _from_args(args: list, where: str) -> Refines:
    """`@refines(Name)` — the one-clause form, and what it does.

    Accepted, and given `DEFAULT_RANGE`, because a program whose specification
    is total (an `abs`, a popcount, a comparison) is genuinely being checked on
    every input and a range is then only bounding what the finite instrument can
    enumerate.  The range is NOT taken from the specification: that would make
    the emitted theorem's range a property of `lib/Specs.lean` rather than a
    statement about the program, which is the thing the theorem claims.
    """
    if len(args) != 1:
        raise RefinesRefusal(
            f"@{REFINES_DECORATOR} takes one name — the word reading of "
            f"`lib/Specs.lean` the program should be checked against — and this "
            f"one has {len(args)} arguments{_at(where)}. To state a range, use "
            f"the two-clause form `@{REFINES_DECORATOR}(Name; N)`")
    name = dotted_name(args[0])
    if not _LEAFAN_NAME_RE.match(name):
        raise RefinesRefusal(
            f"@{REFINES_DECORATOR}({name!r}) does not name a Lean "
            f"declaration{_at(where)}. It names a `UInt64 → UInt64` word "
            f"reading of `lib/Specs.lean` and is used as a Lean term, so a "
            f"typo is an elaboration error rather than a claim nobody checks")
    return Refines(name, DEFAULT_RANGE)


def _at(where: str) -> str:
    return f" on `{where}`" if where else ""


# ---------------------------------------------------------------------------
# The emitted theorems
# ---------------------------------------------------------------------------

def _range_binders(rng: int) -> str:
    """The stated range as an explicit `n` and its membership hypothesis.

    `n ∈ List.range 64` rather than `n < 64`, because that is the form the
    FINITE check can decide: `∀ n, n ∈ List.range 64 → …` has a `Decidable`
    instance and `∀ n, n < 64 → …` does not.  There is no `Finset` in this
    toolchain's import closure, so `List.range` is the finite range this can be
    written in.
    """
    return f"(n : Nat) (h : n ∈ List.range {rng})"


def _closed_range(rng: int) -> str:
    """The same range as ONE closed proposition, which is what decides.

    `main_model_refines_spec` is stated this way and not with explicit binders
    because `native_decide` closes a goal by EVALUATING it, and a goal with a
    free `n` in it has nothing to evaluate.  `main_refines_spec` needs `n` and
    its hypothesis, so it takes them as binders and instantiates this.
    """
    return f"∀ n ∈ List.range {rng}, "


def refines_section(func_name: str, prog_name: str, ref: Refines,
                    machine_half: bool = True) -> str:
    """The Lean text of the refinement section for one annotated program.

    `prog_name` is the `runProg` name the universal theorem is about — the same
    string `<func_name>_prog`, passed in rather than rebuilt so that the two
    halves of the composition cannot disagree about it.

    `machine_half` is False when the generated file's universal theorem is not
    the value-returning form (a function that calls out of the image), in which
    case `main_refines_spec` would be a theorem about a run the model cannot
    complete.  The model-level half is still emitted, because it is true and it
    is the half a reader of the specification can check; the missing half is
    named in a comment rather than left as an absence.
    """
    spec = ref.spec
    rng = ref.rng
    model = (
        f"theorem main_model_refines_spec :\n"
        f"    {_closed_range(rng)}mojo (UInt64.ofNat n) = {spec} (UInt64.ofNat n) := by\n"
        f"  native_decide\n")
    if not machine_half:
        return (
            f"/- SPECIFICATION REFINEMENT: `{spec}`, over the {rng} inputs "
            f"`0 … {rng - 1}`.\n\n"
            f"  Only the MODEL half is emitted here.  This function calls out "
            f"of the image, so `arm64_step` returns `none` at the call and no "
            f"execution in this file completes: the universal theorem above "
            f"states reachability of the call instead of a result value.  "
            f"`main_refines_spec` would therefore be a theorem about a run "
            f"that never finishes, which is the shape a claim takes when "
            f"nobody is looking at what the model supports.\n\n"
            f"  What IS proved is that the model agrees with the "
            f"specification on every one of the {rng} inputs, which is the "
            f"half that does not need the call. -/\n"
            + model)
    return (
        f"/- SPECIFICATION REFINEMENT: `{spec}`, over the {rng} inputs "
        f"`0 … {rng - 1}`.\n\n"
        f"  Every other theorem in this file compares the machine with the "
        f"generator's own model of the source, `mojo`, and the model is "
        f"derived from the same source by the same front end — so all of them "
        f"are SELF-CONSISTENCY theorems.  These two put the machine and an "
        f"INDEPENDENT specification on opposite sides of an equation: `{spec}` "
        f"is a definition written by hand in Lean's own `Nat` in "
        f"`lib/Specs.lean`, with no reference to this file, to `ProofLib`'s "
        f"machine model, or to `mojo`.\n\n"
        f"  The claim is over a RANGE and not over all inputs, and the range is "
        f"the author's: a word reading is `UInt64.ofNat` of a mathematical "
        f"value, so the equation is false wherever that value does not fit in "
        f"a word.  Stating it for all inputs needs an induction over this "
        f"program's own loop structure, which is a different proof per program "
        f"and is not attempted here.\n\n"
        f"  The check has teeth: `native_decide` EVALUATES both sides for every "
        f"one of the {rng} inputs, so a specification that does not match the "
        f"program makes the build fail with a `false` goal instead of being "
        f"believed. -/\n"
        f"theorem main_model_refines_spec :\n"
        f"    {_closed_range(rng)}mojo (UInt64.ofNat n) = {spec} (UInt64.ofNat n) := by\n"
        f"  native_decide\n\n"
        f"/-- `main_refines_spec`: the COMPILED program returns the "
        f"specification's value, on every input in the range.\n\n"
        f"  The composition is the whole point.  "
        f"`{func_name}_compiles_correctly_universal` says the machine's result "
        f"register holds `mojo n`; `main_model_refines_spec` says `mojo n` is "
        f"what `{spec}` computes; together they say the code computes the "
        f"specification, which is a stronger claim than either half and is "
        f"the one the other theorems in this file cannot make. -/\n"
        f"theorem main_refines_spec {_range_binders(rng)}\n"
        f"    (s : Arm64State) (hr : runProg {prog_name} (UInt64.ofNat n) = some s) :\n"
        f"    s.x0 = {spec} (UInt64.ofNat n) := by\n"
        f"  have hmem : n < {rng} := List.mem_range.mp h\n"
        f"  have hn0 : (UInt64.ofNat n).toNat = n :=\n"
        f"    Specs.ofNat_toNat_small n (by omega)\n"
        f"  have h1 := {func_name}_compiles_correctly_universal (UInt64.ofNat n) (by omega)\n"
        f"  rw [hr] at h1\n"
        f"  exact h1.trans (main_model_refines_spec n h)\n")


def header_imports(needs_specs: bool) -> str:
    """The generated file's import block, with `Specs` only when it is used.

    Conditional rather than unconditional so that the 45-odd examples with no
    `@refines(…)` annotation get a byte-identical header to the one they got
    before this existed — an import nothing uses is an import every one of them
    pays to resolve.
    """
    block = "import ProofLib\nimport work\nimport Refine\n"
    if needs_specs:
        block += "import Specs\n"
    return block