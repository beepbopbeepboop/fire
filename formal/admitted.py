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
        """The `/-- … -/` body for the generated Lean declaration."""
        return (f"ADMITTED: {self.qualified}.\n"
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
    """
    module = _module_name_for(path)
    out = []
    for st in _imports.module_statements(path):
        if not isinstance(st, F.FunctionDef) or not st.name:
            continue
        for dec in (getattr(st, "decorators", None) or []):
            text = _decorator_text(dec)
            if text is None:
                continue
            out.append(Contract(module, st.name, text, path,
                                getattr(st, "line", 0) + 1))
            break
    return out


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
