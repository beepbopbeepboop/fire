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
`bugs/formal/FORMAL_a_specification_layer_that_stops_at_a_finite_range.md`.
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


# ---------------------------------------------------------------------------
# The ALL-INPUTS refinement: the model half, without the range
#
# `main_model_refines_spec` is `native_decide` over `List.range N`, so it needs
# nothing about the specification beyond its name.  Its all-inputs companion
# does: the proof is an induction on the PROGRAM's own model (`<func>_go`) and
# its arithmetic step is the SPECIFICATION's own equation, so the generator has
# to be told which `Nat` function a `…64` word reading truncates and which
# equation unfolds it.  That is what a row of `ALL_INPUTS` carries, and it is
# why a specification with no row gets no all-inputs theorem rather than a
# guessed one — the same refusal-not-a-guess rule the annotation reader keeps.
#
# The row also carries the model SHAPE the induction is written for.  The shape
# is checked against the emitted model text before the theorem is written, so a
# program annotated with a registered specification but modelled some other way
# gets the finite-range theorem it always had and no false all-inputs claim.
# ---------------------------------------------------------------------------

#: How to apply the model named `<func>_go`/`<func>_model`; the reader both
#: generators share (`formal/arm64_proof_gen.py::_model_shape`) reports the same
#: two candidate names, and this reproduces the candidate ORDER only.
_MODEL_NAME_RE = r"^def %s\b"


class AllInputs:
    """What an all-inputs refinement needs beyond the finite-range one.

    `kind` is the model shape the induction is written for — ``"identity"`` for
    a `UInt64 → UInt64` model that is `n`, ``"recursive"`` for a `Nat → UInt64`
    structural recursion whose step is `(ofNat (k+1)) <op> <go> k`, and
    ``"closed"`` for a straight-line model whose body is one closed word
    expression.  `nat` is the `Nat` function the word reading truncates, `succ`
    its step equation and `lemma` the word-product fact the step rewrites
    through.  A `"closed"` row also carries the model BODY it is written for
    (`body`, compared exactly) and the tactic block that closes it (`proof`);
    the two are one row because the proof is only a proof of that body.
    """

    __slots__ = ("word", "nat", "kind", "op", "succ", "lemma", "body",
                 "proof")

    def __init__(self, word: str, nat: str, kind: str, op: str = "",
                 succ: str = "", lemma: str = "", body: str = "",
                 proof: str = ""):
        self.word = word
        self.nat = nat
        self.kind = kind
        self.op = op
        self.succ = succ
        self.lemma = lemma
        self.body = body
        self.proof = proof

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"AllInputs({self.word!r}, {self.nat!r}, {self.kind!r})"


#: The word readings the all-inputs emitter can prove, keyed by the name the
#: annotation writes.  A row exists only where the induction has been written
#: and checked; every other `@refines(…)` spec gets the finite-range theorem and
#: no more.  See `bugs/formal/FORMAL_a_specification_layer_that_stops_at_a_finite_range.md`.
#:
#: `lemma=` is the BARE `u64_ofNat_mul`, and used to be `Specs.u64_ofNat_mul`:
#: `lib/Specs.lean` restated the theorem so the name would be in scope without
#: rebuilding `ProofLib`'s `.olean`, which is past a bounded change's memory
#: ceiling.  That was a merge artefact -- `lib/ProofLib.lean` already stated it
#: beside `u64_ofNat_add`/`u64_ofNat_sub` -- and it cost two proofs to keep true
#: and a second row in `AXIOM_CLOSURE` for one theorem.
#:
#: **It is bare and not `ProofLib.u64_ofNat_mul` because `lib/ProofLib.lean` has
#: no `ProofLib` namespace**: its declarations sit at the root, so the prefix is
#: an unknown identifier (measured with `lean` on a file that imports all four
#: modules and `open Specs`).  That is the same spelling `arm64_reg`,
#: `mem_read_u64` and every other library fact already uses in generated text.
#: A generated proof does `import ProofLib` and `import Specs` with `open Specs`,
#: so the bare name resolves to ProofLib's, and with the Specs copy gone there is
#: nothing for `open Specs` to shadow it with.
ALL_INPUTS = {
    "Specs.id64": AllInputs(word="Specs.id64", nat="Specs.idNat",
                            kind="identity"),
    "Specs.factorial64": AllInputs(
        word="Specs.factorial64", nat="Specs.factorial", kind="recursive",
        op="*", succ="Specs.factorial_succ", lemma="u64_ofNat_mul"),
    # ── the STRAIGHT-LINE shapes ────────────────────────────────────────────
    #
    # A straight-line program's model is one closed word expression, so the
    # all-inputs theorem is not an induction at all: unfold both sides and the
    # goal is a word identity.  Each row is the model body it was written for
    # (compared exactly, like the recursive shape) and the tactic block that
    # closes THAT body, because the two are one claim.
    #
    # They are not interchangeable with a `bv_decide` and that is measured:
    # `bv_decide` on `w * w + w = w * (w + 1)` times out (the SAT solver does
    # not have associativity/commutativity for free), while two rewrites
    # `simplify` leaves in the goal close it.  So the proof is per row and a
    # row that cannot be written is a spec with no all-inputs theorem rather
    # than a guessed one.
    "Specs.consecutiveProduct64": AllInputs(
        word="Specs.consecutiveProduct64", nat="Specs.consecutiveProduct",
        kind="closed", body="((n * n) + n)",
        proof=("simp [mojo, {go}, {word}, {nat}]\n"
               "rw [UInt64.mul_add, UInt64.mul_one]")),
    "Specs.succSquare64": AllInputs(
        word="Specs.succSquare64", nat="Specs.succSquare", kind="closed",
        body="((n + (UInt64.ofNat 1)) * (n + (UInt64.ofNat 1)))",
        proof="simp [mojo, {go}, {word}, {nat}]"),
    "Specs.doubleSuccOne64": AllInputs(
        word="Specs.doubleSuccOne64", nat="Specs.doubleSuccOne",
        kind="closed",
        body="((n * (UInt64.ofNat 2)) + (UInt64.ofNat 1))",
        proof=("simp [mojo, {go}, {word}, {nat}]\n"
               "rw [UInt64.mul_comm w 2]")),
    "Specs.maskedMix64": AllInputs(
        word="Specs.maskedMix64", nat="Specs.maskedMix", kind="closed",
        body=("(((n &&& (UInt64.ofNat 255)) + (n ||| (UInt64.ofNat 240))) + "
              "(n ^^^ (UInt64.ofNat 85)))"),
        proof="simp [mojo, {go}, {word}, {nat}]"),
    "Specs.isNonzero64": AllInputs(
        word="Specs.isNonzero64", nat="Specs.isNonzero", kind="closed",
        body=("(if (n ≠ (UInt64.ofNat 0)) then (UInt64.ofNat 1) else "
              "(UInt64.ofNat 0))"),
        proof=("by_cases h : w.toNat = 0\n"
               "· have hw : w = 0 := UInt64.toNat_inj.mp (by simpa using h)\n"
               "  simp [mojo, {go}, {word}, {nat}, hw]\n"
               "· have hw : w ≠ 0 := fun e => h (by simpa [e])\n"
               "  simp [mojo, {go}, {word}, {nat}, hw, h]")),
}


def _model_def_name(func_name: str, go_defs: str) -> str:
    """`<func>_model` if the model text declares one, else `<func>_go`, else "".

    The two candidate names and their order are `_model_shape`'s; a tree model
    is `<func>_model` and an applied one `<func>_go`, and a model that is
    neither is a shape this emitter cannot read, so it says so with "".
    """
    src = go_defs or ""
    for cand in (func_name + "_model", func_name + "_go"):
        if re.search(_MODEL_NAME_RE % re.escape(cand), src, re.M):
            return cand
    return ""


def _identity_shape(go_defs: str, go: str) -> bool:
    """Is `<go>` the applied identity — `def <go> (n : UInt64) : UInt64 := n`?"""
    return bool(re.search(
        r"^def %s \(n : UInt64\) : UInt64 :=\n  n$" % re.escape(go),
        go_defs or "", re.M))


def _recursive_shape(go_defs: str, go: str, op: str) -> bool:
    """Is `<go>` a `Nat → UInt64` recursion with the `<op>` step this row wants?

    Exact rather than approximate on purpose: the induction below rewrites the
    step, so a different step body is a different proof, and a row that claimed
    one it did not have would emit a theorem that does not elaborate.  Anything
    that does not match is no row — the finite-range theorem stands unchanged.
    """
    return bool(re.search(
        r"^def %s : Nat → UInt64\n"
        r"  \| 0 => [^\n]*\n"
        r"  \| k \+ 1 => \(\(UInt64\.ofNat \(k \+ 1\)\) %s %s k\)$"
        % (re.escape(go), re.escape(op), re.escape(go)),
        go_defs or "", re.M))


def _closed_shape(go_defs: str, go: str, body: str) -> bool:
    """Is `<go>` a `UInt64 → UInt64` model whose body is EXACTLY `body`?

    The straight-line twin of `_recursive_shape`, with the same rule: the
    emitted tactic block is written for one expression, so a row that accepted
    "looks straight-line" would emit a theorem about a different function and
    Lean would reject the whole proof file.  The comparison is on the def's
    single body line, so a model that is not one closed expression (an `if`,
    an application, a second line) does not match unless the row says so.
    """
    if not body:
        return False
    return bool(re.search(
        r"^def %s \(n : UInt64\) : UInt64 :=\n  %s$"
        % (re.escape(go), re.escape(body)),
        go_defs or "", re.M))


def all_inputs_section(func_name: str, ref: Refines, go_defs: str) -> str:
    """The Lean text of the all-inputs refinement, or "" when it cannot be made.

    "" is the ordinary case and is not a failure: only a registered
    specification whose model has the registered shape gets the theorem, and for
    everything else the finite-range section is the whole of what this layer
    claims.  That boundary is stated in the emitted file's own comment.
    """
    row = ALL_INPUTS.get(ref.spec)
    if row is None:
        return ""
    go = _model_def_name(func_name, go_defs)
    if not go:
        return ""
    _load_bearing = (
        f"\n\n  The no-wrap hypothesis is not decoration: outside it the "
        f"equation is false, which is what makes `{row.word}` a truncation of a "
        f"mathematical value rather than that value."
        if row.kind == "recursive" else "")
    head = (
        f"/-- `main_refines_all_inputs`: the MODEL computes `{row.word}` for "
        f"EVERY input, not only the {ref.rng} the finite check enumerates.\n\n"
        f"  The finite theorem beside this one is `native_decide` over "
        f"`List.range {ref.rng}`, which EVALUATES both sides for each input and "
        f"so says nothing about an input nobody enumerated.  This one reasons "
        f"about the model's own definition instead of enumerating it."
        + _load_bearing + f" -/\n")
    if row.kind == "identity":
        if not _identity_shape(go_defs, go):
            return ""
        return (
            head
            + f"theorem main_refines_all_inputs (w : UInt64) :\n"
            + f"    mojo w = {row.word} w := by\n"
            + f"  show {go} w = {row.word} w\n"
            + f"  simp [{go}, {row.word}]\n")
    if row.kind == "closed":
        if not _closed_shape(go_defs, go, row.body):
            return ""
        proof = "\n".join("  " + line for line in row.proof.format(
            go=go, word=row.word, nat=row.nat).splitlines())
        return (
            head
            + f"theorem main_refines_all_inputs (w : UInt64) :\n"
            + f"    mojo w = {row.word} w := by\n"
            + proof + "\n")
    if row.kind == "recursive":
        if not _recursive_shape(go_defs, go, row.op):
            return ""
        return (
            head
            + f"theorem main_refines_all_inputs (w : UInt64)\n"
            + f"    (hfits : {row.nat} w.toNat < 2 ^ 64) :\n"
            + f"    mojo w = {row.word} w := by\n"
            + f"  have hall : ∀ n, {row.nat} n < 2 ^ 64 →\n"
            + f"      {go} n = UInt64.ofNat ({row.nat} n) := by\n"
            + f"    intro n\n"
            + f"    induction n with\n"
            + f"    | zero => simp [{go}, {row.nat}]\n"
            + f"    | succ k ih =>\n"
            + f"      intro h\n"
            + f"      have hk : {row.nat} k < 2 ^ 64 := by\n"
            + f"        have hle : {row.nat} k ≤ (k + 1) * {row.nat} k :=\n"
            + f"          Nat.le_mul_of_pos_left _ (by omega)\n"
            + f"        have hs := {row.succ} k\n"
            + f"        omega\n"
            + f"      simp only [{go}]\n"
            + f"      rw [ih hk, {row.lemma}, {row.succ} k]\n"
            + f"  show {go} w.toNat = UInt64.ofNat ({row.nat} w.toNat)\n"
            + f"  exact hall w.toNat hfits\n")
    return ""


def refines_section(func_name: str, prog_name: str, ref: Refines,
                    machine_half: bool = True,
                    missing_reason: str = "",
                    go_defs: str = "") -> str:
    """The Lean text of the refinement section for one annotated program.

    `prog_name` is the `runProg` name the universal theorem is about — the same
    string `<func_name>_prog`, passed in rather than rebuilt so that the two
    halves of the composition cannot disagree about it.

    `machine_half` is False when the generated file's universal theorem cannot
    be used to say what the machine RETURNS, in which case `main_refines_spec`
    would be a theorem about a run the file has not characterised.  Two backends
    are in that position and for different reasons, so `missing_reason` is the
    caller's sentence and not one hard-coded here: on arm64 it is a function
    that calls out of the image (`arm64_step` returns `none` at the call), and
    on x86-64 it is an end-to-end theorem that is a `sorry`.  The model-level
    half is still emitted in both cases, because it is true and it is the half a
    reader of the specification can check; the missing half is NAMED in a
    comment rather than left as an absence, because an absent half and a
    forgotten half read the same in a diff.

    `go_defs` is the emitted model text, and it is optional only because a
    caller that has none is a caller that cannot write an all-inputs refinement:
    the induction is an induction on the PROGRAM's model, so its body has to be
    read from what was emitted (`all_inputs_section`).  An absent `go_defs`
    therefore drops that theorem and changes nothing else.
    """
    spec = ref.spec
    rng = ref.rng
    model = (
        f"theorem main_model_refines_spec :\n"
        f"    {_closed_range(rng)}mojo (UInt64.ofNat n) = {spec} (UInt64.ofNat n) := by\n"
        f"  native_decide\n")
    # The all-inputs strengthening, when this specification has a row and the
    # program's model has the shape that row names.  Emitted beside the finite
    # one so the two readings of the same specification sit together; "" is the
    # ordinary case and leaves the file exactly as it was.
    _all_inputs = all_inputs_section(func_name, ref, go_defs)
    if _all_inputs:
        model = model + "\n" + _all_inputs
    if not machine_half:
        return (
            f"/- SPECIFICATION REFINEMENT: `{spec}`, over the {rng} inputs "
            f"`0 … {rng - 1}`.\n\n"
            f"  Only the MODEL half is emitted here, and the reason is this "
            f"file's: {missing_reason.strip()}\n\n"
            f"  Composing with a claim this file has not established would "
            f"make Lean ACCEPT a statement about the machine while "
            f"establishing nothing about it, which is the shape a believed "
            f"falsehood takes.  What IS proved is that the model agrees with "
            f"the specification on every one of the {rng} inputs — the half "
            f"that does not need the machine. -/\n"
            + model)
    _range_para = (
        f"  The claim is over a RANGE and not over all inputs, and the range is "
        f"the author's: a word reading is `UInt64.ofNat` of a mathematical "
        f"value, so the equation is false wherever that value does not fit in "
        f"a word."
        + (
            f"  `main_refines_all_inputs`, beside `main_model_refines_spec`, is "
            f"that same claim for EVERY input in the no-wrap region, so the "
            f"range below is where the finite instrument stops rather than the "
            f"edge of what is proved."
            if _all_inputs else
            f"  Stating it for all inputs needs an induction over this "
            f"program's own loop structure, which is a different proof per "
            f"program and is not attempted here."))
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
        + _range_para + "\n\n"
        f"  The check has teeth: `native_decide` EVALUATES both sides for every "
        f"one of the {rng} inputs, so a specification that does not match the "
        f"program makes the build fail with a `false` goal instead of being "
        f"believed. -/\n"
        + model + "\n"
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