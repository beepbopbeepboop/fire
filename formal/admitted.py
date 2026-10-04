"""ADMITTED HOST CONTRACTS: the trust boundary for host modules this target cannot answer.

WHAT THIS IS
------------
Some CPython modules cannot be *modelled* for the formal backends.  They need a
second process, a thread, the network, a dynamic loader for foreign code, or an
embedded interpreter — objects a freestanding image that links libSystem and
nothing else does not have.  `formal/imports.py` classes those modules
`HOST_UNREACHABLE` and refuses every file that imports one.

Refusing is the honest answer to "can this image compute that?" and a useless
answer to "what does the file say?", because 30 of the sweep's files import
`subprocess` and are then reported for a fact about the TARGET that no amount of
work in this tree can change.  The question this module adds is the other one:
**what would a proof have to assume about the host to accept the file?**

So each hard module gets a Mojo-side model of its API SHAPE in
`formal/hostmods/` — signatures, return types, and which exception each call
raises — and every operation whose ANSWER is an external fact is declared an
admitted contract.  The declaration is written in the Mojo source itself, as an
`@admitted("<what it assumes of the host>")` decorator:

    @admitted("the child's exit status, an integer in 0..255")
    def run(argv: str, capture: int) -> int:
        ...

That decorator is the ONLY place the assumption is written.  This module reads
it back out of the parsed source, publishes it in three places that must agree
(the generated Lean, the build's `trust:` line, and `tools/formal_sweep.py`'s
class), and counts it.  `test_formal_admitted.py` pins the count per module, so
a new admitted contract cannot land without the number moving.

WHY `sorry` AND NOT `axiom`
---------------------------
FORMAL.md §7 states the project's position: *no Lean `axiom` and no `opaque`
anywhere; everything is assumed in the `sorry` sense, which is the harder habit
to see.*  That position is load-bearing rather than stylistic, and this module
keeps it.  An `axiom` is INVISIBLE to `formal/lean.py`'s census, which counts
`declaration uses 'sorry'` as Lean reports it (`_census_from_output`) — so an
admitted contract written as an axiom would be a claim of trust that no count
ever reports, which is precisely the failure this file exists to prevent.

So each contract is emitted as

    /-- ADMITTED: <module>.<name>.  ASSUMES OF THE HOST: <the decorator text> -/
    theorem admitted_<module>_<name> (...) : ... := by
      sorry

which the existing census counts with no new machinery, and which `#print
axioms` reports as depending on `sorryAx` like every other hole in this tree.
The task's "a named `axiom` (or a theorem proved by `sorry`/`admit`)" is the
second of those, and it is the one this project's own rule selects.

WHAT IS NOT ADMITTED
--------------------
The API shape.  A signature, a return type, and *which exception a call raises*
are all facts about CPython that this tree can check and that the model can
therefore implement rather than assume: `test_formal_admitted.py` runs the same
table through CPython's own `subprocess` and requires the model's verdict to be
the exception CPython raises.  Only the host's ANSWER is admitted.  A contract
that says more than that — "and the output is empty", "and it always succeeds" —
is refused by `contract_text_is_scoped`, because an admission wider than the
answer is a claim about a host nobody checked.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fire_compiler as F  # noqa: E402

from formal import imports as _imports  # noqa: E402

# The decorator that marks an admitted contract.  Deliberately not a builtin and
# deliberately not a Python decorator this tree already means something else by:
# `dataclasses.dataclass` is applied at compile time by
# `formal/dataclass_transform.py`, and reusing that name for a marker no
# transform reads would make `@admitted` mean two things depending on which pass
# looked at it.
ADMITTED_DECORATOR = "admitted"

# `formal/hostmods/`, read through `formal/imports.py`'s own root rather than a
# second copy of the path.  Two spellings of that directory would drift, and the
# drift would be invisible: a module found by one and not the other builds here
# and is then unbuildable for every importer.
HOSTMODS_ROOT = _imports._HOSTMODS_ROOT

# One admitted contract, as read off one `@admitted(...)` in one module.
#
# `module` is the CPython name the file answers (`subprocess`), `name` is the
# function, and `assumes` is the decorator's text verbatim: the declaration the
# proof rests on is the same sentence a reader of the Mojo source reads, not a
# restatement of it here.  `source`/`line` are where to go and look, and they are
# in the dataclass rather than recomputed by every consumer for the same reason
# a message names its file.
class Contract:
    __slots__ = ("module", "name", "assumes", "source", "line")

    def __init__(self, module: str, name: str, assumes: str, source: str,
                 line: int):
        self.module = module
        self.name = name
        self.assumes = " ".join((assumes or "").split())
        self.source = source
        self.line = line

    # `subprocess.run` — how every consumer names it.  One spelling, so a `trust:`
    # line, a Lean docstring and a test failure cannot disagree about which
    # contract they are talking about.
    @property
    def qualified(self) -> str:
        return f"{self.module}.{self.name}"

    # The Lean declaration name.  `admitted_` prefix, because the word "admitted"
    # in a generated proof has to mean "this is a hole" at a glance, and a bare
    # `subprocess_run` would read as a definition.
    @property
    def lean_name(self) -> str:
        return "admitted_" + _lean_ident(f"{self.module}_{self.name}")

    def docstring(self) -> str:
        """The `/-- … -/` body for the generated Lean declaration.

        `THE WORD IS THE MODEL'S` is stamped here rather than written into
        nineteen `@admitted` texts, and the reason is that it is not an
        ASSUMPTION: it is a statement about the shape of the declaration this
        module generates, which is `UInt64 → UInt64` because a value on this path
        is one 64-bit word.  The decorator stays the only place an ASSUMPTION is
        written, which is the rule the module header states and the one a reader
        of the Mojo source relies on; a shape is not an assumption, and repeating
        it nineteen times is nineteen chances for the copies to disagree.

        It is here because it is the largest standing gap in the mechanism and
        nothing said so.  For most of these operations CPython does not return a
        word at all: `check_call`, `Thread.join` and `Executor.shutdown` return
        `None`, `Popen` and `run` return objects, `getstatusoutput` and
        `communicate` return pairs, `Executor.submit` returns a `Future`, and
        `Lock.acquire` returns `True`.  So `admitted_subprocess_check_call : UInt64 →
        UInt64` is a claim about what THIS MODEL answers, and a proof that reads
        it as CPython's return type is reading a different claim from the one the
        declaration makes.  `bugs/FORMAL_trust_audit_2026-10-04.md` §"the word is
        the model's" carries the measurement and the per-operation table.
        """
        return (f"ADMITTED: {self.qualified}.\n"
                f"    THE WORD IS THE MODEL'S: this declaration is "
                f"`UInt64 -> UInt64` because a value on this path is one 64-bit "
                f"word, so what it admits is the answer THIS MODEL gives to the "
                f"question the caller asked.  For most of these operations "
                f"CPython returns something that is not a word -- `None`, a "
                f"`Popen`, a `CompletedProcess`, a pair, a `Future`, a `bool` -- "
                f"so this is not a restatement of CPython's return type.\n"
                f"    ASSUMES OF THE HOST: {self.assumes}\n"
                f"    Nothing else about the host's answer is assumed or proved. "
                f"Declared at {self.source}:{self.line}.")

    def __repr__(self):
        return f"<Contract {self.qualified}>"

    def __eq__(self, other):
        return (isinstance(other, Contract)
                and (self.module, self.name, self.assumes)
                == (other.module, other.name, other.assumes))

    def __hash__(self):
        return hash((self.module, self.name, self.assumes))


def _lean_ident(text: str) -> str:
    """A Lean identifier for `text`: dots and dashes out, underscores in.

    `subprocess.run` and `concurrent.futures.ThreadPoolExecutor` both have to
    become identifiers, and Lean's own name mangling would not be the one a
    reader of the `trust:` line expects, so it is done here once.
    """
    out = []
    for ch in text:
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    ident = "".join(out)
    # A leading digit is not an identifier in Lean, and a module named `2to3`
    # would produce one.
    return ("_" + ident) if ident[:1].isdigit() else ident


def _decorator_text(dec) -> str:
    """The single string argument of an `@admitted("…")` decorator, or ''.

    Only `@admitted("text")` is a declaration.  A bare `@admitted` says nothing
    about what is assumed, which is the one thing a contract has to say, and a
    docstring on the function is not read here — the reason is that a contract
    has to be countable from the source by something that does not have to
    evaluate the module, and a decorator argument is that.
    """
    name = getattr(getattr(dec, "func", None), "name", None)
    if name != ADMITTED_DECORATOR:
        return None
    args = list(getattr(dec, "args", None) or [])
    if len(args) != 1 or not isinstance(args[0], F.StringLiteral):
        return ""
    return args[0].value


def contracts_in_file(path: str) -> list:
    """Every admitted contract declared in one Mojo file, in source order.

    Read through `formal/imports.py`'s parse, so a file is parsed once per
    (path, content) for this reader and for every other reader in the tree.  A
    second `F.Parser` here would be free to disagree with the build's parse about
    what the source says, and the disagreement would be a missing contract in a
    proof rather than an error.

    THE LINE IS FOUND IN THE SOURCE TEXT, not read off the AST, because the AST
    does not carry one: `fire_compiler.py`'s top-level `FunctionDef(...)` is built
    without `line=`, so `getattr(st, "line", 0) + 1` is 1 for every contract in
    every module, and every `trust:` line and every generated Lean docstring
    pointed a reader at line 1 of the file — the module docstring.  Fixing it in
    the parser would mean editing a file every branch in this project parses
    through, for a field nothing else reads, so the location is recovered where
    it is consumed instead: the `@admitted(` lines in the text, in order, which is
    the order the parse returns them in.
    """
    module = _module_name_for(path)
    admitted_lines = _admitted_decorator_lines(path)
    out = []
    for st in _imports.module_statements(path):
        if not isinstance(st, F.FunctionDef) or not st.name:
            continue
        for dec in (getattr(st, "decorators", None) or []):
            text = _decorator_text(dec)
            if text is None:
                continue
            out.append(Contract(module, st.name, text, path,
                                _line_for(path, st.name, len(out),
                                          admitted_lines)))
            break
    return out


def _admitted_decorator_lines(path: str) -> list:
    """The 1-based line of every `@admitted(` in `path`, in source order."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if line.lstrip().startswith("@" + ADMITTED_DECORATOR + "("):
                    out.append(i)
    except OSError:
        pass
    return out


def _line_for(path: str, name: str, index: int, admitted_lines: list) -> int:
    """Where `@admitted(` for `name` is, 1-based; `0` if it cannot be found.

    The ordinal `index` is the contract's position among the file's contracts, so
    the `n`th `@admitted(` in the text belongs to the `n`th contract the parse
    returned — which holds because the parse returns them in source order and
    `contracts_in_file` collects them in that order.  The ordinal is verified
    rather than assumed: the decorator is only taken when the `def` it decorates
    is the one being asked about, and otherwise the name is searched for, because
    a location that can be wrong is worse than no location.

    `0` is a real answer and not a sentinel to hide behind: `Contract.line` is
    printed in the `trust:` line and in the generated Lean, and `0` reads as "not
    known" where `1` read as "line one" and pointed at the wrong thing.
    """
    if 0 <= index < len(admitted_lines):
        start = admitted_lines[index]
        for j in range(start, min(start + 6, start + 40)):
            try:
                with open(path, encoding="utf-8") as f:
                    line = f.readlines()[j - 1]
            except (OSError, IndexError):
                break
            if _spelled(line, name):
                return start
            # A blank line or a new top-level statement ends the search: without
            # it a name that is never declared under this decorator would be
            # attributed to the NEXT contract's, which is a location that points
            # at the wrong assumption.
            if line.strip() and not line.startswith(" ") and \
                    not line.lstrip().startswith(("@" + ADMITTED_DECORATOR
                                                 + "(", ")", "#")):
                break
    for j, line in enumerate(_read_lines(path), 1):
        if _spelled(line, name):
            return j
    return 0


def _spelled(line: str, name: str) -> bool:
    """Does `line` declare `name`?  A prefix match is not enough: `run` must not
    match `run_once`, which is why the parameter list or the colon has to follow.
    """
    head = line.lstrip()
    for kw in ("def ", "fn "):
        if head.startswith(kw):
            rest = head[len(kw):]
            return rest == name or rest.startswith(name + "(") or \
                rest.startswith(name + "[") or rest.startswith(name + ":")
    return False


def _read_lines(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().split("\n")
    except OSError:
        return []


def all_contracts() -> list:
    """Every admitted contract in `formal/hostmods/`, sorted by module then name.

    Walked, not listed, for the reason `test_formal_hostmods_census.py` walks:
    a hand-maintained list is a list that is wrong the day somebody adds a
    module, and the whole value of a census is that it cannot be.  A module with
    no `@admitted` contributes nothing and is not an error — that is a hostmod
    whose operations are all computable, which several of them are.
    """
    out = []
    for rel, full in hostmod_files():
        out.extend(contracts_in_file(full))
    return sorted(out, key=lambda c: (c.module, c.name))


def hostmod_files() -> list:
    """Every `.mojo` under `formal/hostmods/`, as (relpath, abspath), sorted."""
    out = []
    for dirpath, dirs, files in os.walk(HOSTMODS_ROOT):
        dirs.sort()
        for name in sorted(files):
            if name.endswith(".mojo"):
                full = os.path.join(dirpath, name)
                out.append((os.path.relpath(full, HOSTMODS_ROOT), full))
    return sorted(out)


def _module_name_for(path: str) -> str:
    """The CPython module name a `formal/hostmods` path answers.

    `formal/hostmods/os/__init__.mojo` is `os` and
    `formal/hostmods/concurrent/futures.mojo` is `concurrent.futures`, which is
    the same rule `formal/imports.py`'s `_module_identity` applies to an import
    spelling.  A contract reported under the wrong module name would be a
    `trust:` line nobody could act on.
    """
    rel = os.path.relpath(os.path.abspath(path), HOSTMODS_ROOT)
    parts = rel.split(os.sep)
    if parts[-1] == "__init__.mojo":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-len(".mojo")]
    return ".".join(parts)


def contracts_for_module(module: str) -> list:
    """Every contract declared by one module, in source order."""
    top = (module or "").split(".")[0]
    return [c for c in all_contracts() if c.module.split(".")[0] == top]


def counts_by_module() -> dict:
    """`{module: n admitted contracts}`, for the ratchet test.

    Every module with a model appears, including the ones whose count is zero:
    a module that silently stopped declaring its trust would otherwise leave no
    trace in the count, and "absent from the table" and "zero" have to be
    distinguishable.
    """
    counts = {}
    for _rel, full in hostmod_files():
        counts.setdefault(_module_name_for(full), 0)
    for c in all_contracts():
        counts[c.module] = counts.get(c.module, 0) + 1
    return counts


# Phrases an admission may not contain, because each one is a claim about the
# host BEYOND the answer, and this tree has no evidence for any of them.
#
# The rule this enforces is stated once, in `contract_text_is_scoped`: an
# admitted contract may constrain the host's ANSWER and may not assert anything
# about the host's BEHAVIOUR.  `subprocess.run` returns an exit status in 0..255
# — that is the shape of the answer, and it is checkable by looking at what the
# caller does with the word.  "the command always succeeds", "the output is
# empty" and "no other process is running" are claims about a machine this
# project has no model of, and an admission is the wrong place to make one: it
# would be a `sorry` over a claim nobody wrote a test for, which is the exact
# failure `formal/arm64_proof_gen.py`'s `fun n => n` contract was.
_OVERCLAIM = (
    ("always", "a claim that every run behaves this way"),
    ("never", "a claim that no run ever does otherwise"),
    ("deterministic", "a claim that the host has no nondeterminism"),
    ("empty", "a claim about the CONTENT of an answer, not its shape"),
    ("no other", "a claim about host state this project cannot see"),
    ("none running", "a claim about host state this project cannot see"),
    ("safe", "a claim about a property of the host, not of the answer"),
)


def contract_text_is_scoped(contract: Contract) -> str:
    """'' when the contract only constrains the ANSWER; why not otherwise.

    A cheap text check, and deliberately so: its job is to stop an admission
    that quietly grew a behavioural claim, and the cheapest instrument for that
    is a list of the phrases such a claim is written with.  It is not a
    judgement about whether an assumption is reasonable — nobody can check that
    from here, and the assumption's whole point is that it is not checkable.  It
    is a check that the assumption is about the ANSWER, which is a shape
    question.
    """
    low = contract.assumes.lower()
    for phrase, why in _OVERCLAIM:
        if phrase in low:
            return (f"{contract.qualified} admits {contract.assumes!r}, which "
                    f"says {why}. An admitted contract may constrain what the "
                    f"host RETURNS; a claim about what the host DOES is not an "
                    f"admission, it is an unproved assertion with a proof "
                    f"attached to it.")
    if not contract.assumes:
        return (f"{contract.qualified} is admitted with no text. A contract has "
                f"to say what it assumes of the host: a `sorry` whose statement "
                f"is empty is not a claim of trust, it is an absence of one.")
    return ""


# ── the Lean side ─────────────────────────────────────────────────────────────

def lean_declarations(contracts: list) -> str:
    """The `theorem … := by sorry` block for a set of contracts.

    Emitted into EVERY generated proof whose file depends on one of them, rather
    than into a library module, for two reasons.  A library module would put the
    admission in `lib/`, where `formal/lean.py`'s `library_census` measures it as
    a hole in the MODEL every proof rests on — the count would then be a property
    of the library rather than of the file that asked for the trust, which is
    the opposite of what a per-file `trust:` line claims.  And a proof file that
    does not use `subprocess` would still be carrying the hole.

    The signature is `UInt64 → UInt64`, and the ONE argument is forced rather
    than chosen.  `MojoExpr.call` in `lib/ProofLib.lean` carries a single
    `UInt64` argument, so the AST layer of a generated proof can only evaluate a
    call with one; an admission applied to two arguments in the source model and
    one in the AST model would make `eval_eq_mojo` — the statement that the two
    layers are the same function — false rather than merely unproved.  So a
    hostmod's admitted operation is written with ONE parameter, the request, and
    `formal/arm64_proof_gen.py`'s `_call_go` refuses a call that passes another
    number rather than padding it or dropping the rest.

    `def` and NOT `theorem`, and that is a Lean rule rather than a preference: a
    `theorem`'s type must be a `Prop`, and this declaration's type is the
    contract's VALUE — the word the host returns — so `theorem` is refused with
    `type of theorem '…' is not a proposition`.  The admission is still a `sorry`
    and still counted: `formal/lean.py`'s `_SORRY_LOC_RE` matches Lean's
    `declaration uses 'sorry'` warning, which Lean emits for any declaration
    whose proof term reaches `sorryAx`, `def` included.  Measured on this tree:
    a `def … := by sorry` in a generated proof is reported as
    `declaration '…' uses 'sorry'` and lands in the census.
    """
    out = []
    for c in sorted(contracts, key=lambda k: k.qualified):
        out.append(
            f"/-- {c.docstring()}\n"
            f"    This is a claim of TRUST, not a proof: `sorry` makes this\n"
            f"    declaration ACCEPTED, and `formal/lean.py`'s census counts it. -/\n"
            f"def {c.lean_name} (req : UInt64) : UInt64 :=\n"
            f"  sorry")
    return "\n\n".join(out)


def lean_trust_header(contracts: list) -> str:
    """The `/- … -/` block that names the admissions above the `def`s.

    A `/- -/` block comment rather than `/-- -/`: the header is prose ABOUT the
    declarations that follow it, and a doc comment has to attach to a
    declaration, so putting one above `set_option` or above another doc comment
    is a parse error rather than a comment.  (Measured: the first version of
    this was `/--` and Lean reported `unexpected token '*'` at the first bullet,
    which is the error a reader would have to work backwards from.)
    """
    if not contracts:
        return ""
    lines = ["/- ADMITTED HOST CONTRACTS.  This proof trusts the following about",
             "   the host, and nothing else about it.  Each is a `sorry`: a claim",
             "   of trust, counted by `formal/lean.py`, never a proof.",
             ""]
    for c in sorted(contracts, key=lambda k: k.qualified):
        lines.append(f"   * `{c.qualified}` — {c.assumes}")
        lines.append(f"     ({c.source}:{c.line})")
    lines.append("   -/")
    return "\n".join(lines)


def contract_texts_are_unique(contracts: list) -> str:
    """'' unless two contracts share a Lean declaration name.

    Two contracts colliding on `lean_name` would be one declaration silently
    standing for two admissions, and the count would be off by one in the
    direction that hides a hole — so this is checked rather than assumed.
    """
    seen = {}
    for c in contracts:
        prev = seen.get(c.lean_name)
        if prev is not None and prev.qualified != c.qualified:
            return (f"{prev.qualified} and {c.qualified} both declare "
                    f"`{c.lean_name}`, so one Lean declaration would stand for "
                    f"two admissions and the census would count one hole for "
                    f"two contracts")
        seen[c.lean_name] = c
    return ""


# ── the Lean library's own trust ──────────────────────────────────────────────
#
# The other half of the boundary.  `formal/admitted.py` above is about the HOST:
# what a proof must assume about a second process, a thread, a loader and a
# kernel lock.  This half is about LEAN ITSELF — what the hand-written library
# every generated proof rests on is already trusting, written in a language where
# the trust has to be spelled `axiom`, `sorry`, or a tactic whose proof term
# reaches an axiom.
#
# FORMAL.md §7 states the project's position as *no Lean `axiom` and no `opaque`
# anywhere; everything is assumed in the `sorry` sense*.  Measured on `lib/` on
# 2026-10-04 (`bugs/FORMAL_trust_audit_2026-10-04.md`): the first half of that
# sentence is true of the SOURCE TEXT and false of a theorem's transitive
# closure.  There is no `axiom` declaration and no `sorry` in any of the five
# modules — and 749 proof sites are closed by `native_decide` or `bv_decide`,
# which do not go through the kernel: they compile a decision procedure and run
# it, and close the goal through Lean's `Lean.ofReduceBool` axiom.
# `#print axioms` on such a theorem reports `Lean.ofReduceBool`, and `OPUS.md` §1
# already says so about a generated theorem ("plus the project's usual
# `native_decide`/`bv_decide` step-lemma axioms") without FORMAL.md's inventory
# having a row for it.  That 749 is a CEILING rather than an equality, because it
# is a debt being paid down and `lib/ProofLib.lean` is edited by many hands at
# once; `test_formal_admitted.py` pins it, reports it, and fails when it rises.
#
# WHY THIS IS NOT A BUG AND WHY IT IS STILL COUNTED
# -------------------------------------------------
# `native_decide` cannot prove a false statement: it evaluates the goal's decision
# procedure and answers `True` only when the evaluation says so.  What it moves
# is WHERE the trust sits — from the kernel to the generated C code and the C
# compiler — and that is a legitimate trade (it is why a 1.4M-step machine
# simulation finishes at all) rather than a hole.  It is counted because a trust
# boundary nobody can see is worth nothing, and because the alternative — a
# library that quietly depends on an axiom while §7 says it depends on none — is
# the failure this module exists to prevent.  `bugs/FORMAL_native_decide_axiom.md`
# carries the replacement plan and the exact `#print axioms` measurement that
# belongs to the integrator.
#
# TEXT SCAN, AND WHAT IT IS NOT
# -----------------------------
# This is a TEXT census and `formal/lean.py` says, about `sorry` itself, that a
# text scan is the wrong instrument: whether a hole was ADMITTED is elaboration,
# so the sound instrument is what Lean reports.  It is here anyway, for three
# reasons stated rather than assumed: it needs no Lean run (so it can sit in a
# test that runs every time, which the axiom census cannot), it is exact for the
# things it counts because `lean_code_regions` strips comments and string
# literals first, and its own limits are written down rather than left for a
# reader to discover.  It reports `native_decide` SITES in the source; it does not
# report which theorems reach `Lean.ofReduceBool`, which is the transitivity the
# `#print axioms` route is for.

# Tactics whose proof term reaches an axiom instead of the kernel.  `decide`,
# `rfl`, `simp`, `norm_num` and `omega` are not here: they elaborate to terms the
# kernel checks.  `exact_decide` is not a Lean 4 tactic and `implemented_by` is
# not used in `lib/`; both are checked by the test that pins this list, so a
# library that starts using one cannot be counted correctly.
AXIOM_TACTICS = ("native_decide", "bv_decide")


def lean_code_regions(text: str) -> str:
    """`text` with every comment and string literal's CONTENTS blanked out.

    Blanked rather than deleted, so every offset — and therefore every line
    number — survives, which is what lets the callers report where a hit is.

    Lean's lexical shapes that matter here, and why each is handled:

      * `-- …` to the end of the line;
      * `/- … -/` **nested**, which Lean allows and which a regex cannot do;
      * `"…"` with `\\` escapes, and `r"…"` without them (a raw string's
        backslash does not escape its own closing quote, so treating it as an
        ordinary string mis-lexes every `r"` in the file);
      * `'…'` character literals, because a `'/'` or `'-'` inside one would
        otherwise open a comment that swallows the rest of the file.

    Lean's multi-line string delimiter (three double quotes) is deliberately
    absent from the list above: `lib/` contains none, and a scanner that guessed
    at one would be guessing.  The test that pins the census asserts there is
    none, so the omission cannot rot silently.
    """
    out = []
    i, n = 0, len(text)
    depth = 0                     # block-comment nesting
    while i < n:
        ch = text[i]
        if depth:
            if text.startswith("/-", i):
                depth += 1
                out.append("  ")
                i += 2
                continue
            if text.startswith("-/", i):
                depth -= 1
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if text.startswith("/-", i):
            depth = 1
            out.append("  ")
            i += 2
            continue
        if ch in "\"'":
            raw = (ch == '"' and i > 0 and text[i - 1] == "r"
                   and not (i > 1 and (text[i - 2].isalnum()
                                       or text[i - 2] == "_")))
            quote = text[i:i + 3] if text.startswith(ch * 3, i) else ch
            j = i + len(quote)
            while j < n:
                if not raw and text[j] == "\\":
                    j += 2
                    continue
                if text.startswith(quote, j):
                    j += len(quote)
                    break
                j += 1
            j = min(j, n)
            out.append("".join("\n" if c == "\n" else " " for c in text[i:j]))
            i = j
            continue
        out.append(ch)
        i += 1
    out.append(" " * (n - i))
    return "".join(out)


# An `axiom`/`opaque` DECLARATION, as opposed to either word inside prose.  Both
# are at the head of a line in Lean source and both take a name, so the
# declaration form is anchored at the start and the prose forms are not.
_AXIOM_DECL_RE = re.compile(r"(?m)^[ \t]*(?:@\[[^\]\n]*\][ \t\n]*)*"
                            r"(?:private\s+|protected\s+)?"
                            r"(axiom|opaque)\s+([A-Za-z_][\w'.]*)")
_SORRY_RE = re.compile(r"(?<![\w.])sorry(?![\w.])")
_TACTIC_RE = re.compile(r"(?<![\w.'])(" + "|".join(AXIOM_TACTICS) + r")(?![\w'])")


def library_trust(lean_dir: str) -> dict:
    """`{module: {kind: (count, (lines…))}}` for every `*.lean` in `lean_dir`.

    Three kinds, and they are the three ways a Lean declaration can rest on
    something unproved:

      `axiom`   an `axiom`/`opaque` declaration — none is wanted, ever (§7);
      `sorry`   a hole — countable here and, more precisely, by Lean itself;
      `axiom_tactic`  a `native_decide`/`bv_decide` site, whose proof term
                 reaches `Lean.ofReduceBool` rather than the kernel.

    Both the count and the LINES come back, because a count with no location is
    a number nobody can act on and a location with no count is a note.
    """
    out = {}
    for name in sorted(os.listdir(lean_dir)):
        if not name.endswith(".lean"):
            continue
        path = os.path.join(lean_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            continue
        code = lean_code_regions(raw)
        line_of = lambda off: raw.count("\n", 0, off) + 1     # noqa: E731
        kinds = {}
        for kind, regex in (("axiom", _AXIOM_DECL_RE),
                            ("sorry", _SORRY_RE),
                            ("axiom_tactic", _TACTIC_RE)):
            hits = sorted({line_of(m.start()) for m in regex.finditer(code)})
            kinds[kind] = (len(hits), tuple(hits))
        out[name[:-len(".lean")]] = kinds
    return out


def library_trust_lines(lean_dir: str) -> list:
    """`library_trust` as `module: kind=n at L…` lines, for a report."""
    out = []
    for mod, kinds in sorted(library_trust(lean_dir).items()):
        for kind in ("axiom", "sorry", "axiom_tactic"):
            count, lines = kinds[kind]
            if count:
                shown = ",".join(str(x) for x in lines[:6])
                more = "" if len(lines) <= 6 else f",+{len(lines) - 6}"
                out.append(f"{mod}: {kind}={count} at {shown}{more}")
    return out


def lean_dir(root: str) -> str:
    """The hand-written Lean library directory for a checkout.

    One function rather than a path spelled at each of its call sites, for the
    reason `HOSTMODS_ROOT` is defined through `formal/imports.py`'s root: two
    spellings of one directory drift, and the drift is invisible.
    """
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "lib")
