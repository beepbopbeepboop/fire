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

    @admitted("the child's exit status word: 0..255 for a normal exit, or -N "
              "for a death by signal N")
    def run(argv: str, capture: int) -> int:
        ...

That decorator is the ONLY place the assumption is written.  This module reads
it back out of the parsed source, publishes it in three places that must agree
(the generated Lean, the build's `trust:` line, and `tools/formal_sweep.py`'s
class), and counts it.  `test_formal_admitted.py` pins the count per module, so
a new admitted contract cannot land without the number moving.

The example above is the SECOND version of that sentence.  The first said "an
integer in 0..255" and was false of CPython, which reports `-N` for a child
killed by signal N; fourteen of the nineteen contracts were false in some such
way and every instrument this module had — the count, the scope rule, the
emitted declaration, the inertness check — was green on all of them, because
each decides FORM and none of them asks whether an assumption is true.  That is
what `test_formal_admitted.py`'s `truth` group is for, and
`bugs/FORMAL_trust_audit_2026-10-04.md` is the audit with the table.

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

WHAT THE WORD IS
----------------
`UInt64 -> UInt64` is not CPython's return type, and `Contract.docstring` says so
in every generated declaration.  For most of these operations CPython returns
`None`, a `Popen`, a `CompletedProcess`, a pair, a `Future` or a `bool`, so the
declaration is a claim about what THIS MODEL answers to the question the caller
asked.  That sentence is stamped in one place rather than written into nineteen
decorator texts: it is a fact about the shape of the declaration, not an
assumption, and the decorator stays the only place an assumption is written.

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

import collections
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
        for j in range(start, start + 8):
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
#
# THIS LIST IS NOT THE RULE, and it is worth saying why in the place a reader
# looks for the rule rather than only in a bug doc.  The audit of 2026-10-04
# found an admission that overclaimed and that no phrase here matched:
#
#     the loader handle is 0, meaning no library of that name is on this target
#
# "the loader handle is 0" is a claim about the WORD and "no library of that
# name is on this target" is a claim about the host's FILESYSTEM, and the word
# "meaning" is the whole of the join — which is why a list of phrases cannot
# see it.  Adding `meaning` to this table would reject the corrected text, which
# says the same thing about the word and is true, so the list is left as the
# one cheap arm it is and `value_attached_claim` below is the structural one.
_OVERCLAIM = (
    ("always", "a claim that every run behaves this way"),
    ("never", "a claim that no run ever does otherwise"),
    ("deterministic", "a claim that the host has no nondeterminism"),
    ("empty", "a claim about the CONTENT of an answer, not its shape"),
    ("no other", "a claim about host state this project cannot see"),
    ("none running", "a claim about host state this project cannot see"),
    ("safe", "a claim about a property of the host, not of the answer"),
)


# ── the structural arm: a claim ATTACHED to a value ───────────────────────────
#
# The shape is grammatical rather than lexical, which is what makes it checkable
# without a phrase list.  An admission is a set of constraints on one word; a
# writer who also wants to say something about the host's STATE has to attach it
# to that word, and the way English does that is an explanatory connective — "X
# is V, meaning P" / "…, i.e. P" / "…, which is to say P".  So the sentence
# itself says which clause is the claim about the word (before the connective)
# and which is the claim about the world (after it), and the rule is that the
# second has to be about the first.
#
# WHY NOT `meaning` IN THE TABLE ABOVE.  A phrase list is right about the words
# it has seen and blind to the grammar, and adding connective after connective
# produces a list that is wrong about good sentences: the corrected `ctypes`
# text — "the loader handle is 0 when dlopen(3) failed: the file may be absent,
# may not be a loadable image, or a symbol may be unresolvable" — is a claim
# about the host's filesystem in every word and is *in scope*, because it
# constrains the answer 0.  The same sentence with a connective is only refused
# when the clause it attaches to is not about the word, and that is a question
# about the two clauses rather than about a word.
#
# WHAT IT CANNOT SEE, stated here because a rule that only ever claims to work on
# the instance it was written for is the failure `PRE_AUDIT_TEXT` exists for.
# Two limits, both structural rather than fixable by more words:
#
#   * a world claim with NO connective passes — "the loader handle is 0 because
#     no library of that name is on this target" is a sentence about the
#     filesystem, and `because` is absent from the connective table on purpose
#     because `subprocess.check_output`'s corrected admission uses it to explain
#     a truncation that IS a constraint on the word.  `test_formal_admitted.py`'s
#     `SCOPE_PROBES` carries one such sentence as an ACCEPT row, next to the
#     truth row that does catch it, because that is where the boundary between
#     the two instruments is;
#   * a world claim that happens to share a word with the answer passes — the
#     overlap test asks whether the clause is ABOUT the answer, not whether
#     every clause of it is.
#
# A version that scales past both limits is the one this doc named second: give
# `Contract` a declared KIND (`status`, `byte_string`, `handle`, …) and check
# the text against that kind's shape, which is `bugs/FORMAL_contract_scope_
# rule_is_a_phrase_list.md`'s §"option 2" and is not done here because it
# duplicates every `@admitted` text in a second place — the one thing this
# module's header forbids.
_EXPLANATORY_CLAUSE = (
    # Introduces a CLAUSE, so the template the probe rows are built from can
    # carry one.  "that is to say" and "which is to say" are NOT here: "that is"
    # and "which is" already match inside them, so listing them would be two
    # entries of this table that removing changes nothing — the dead-marker
    # shape, which `test_formal_admitted.py`'s `SCOPE_PROBES` is built to
    # report rather than to accommodate.
    "meaning", "means", "i.e.", "in other words", "that is", "which is",
)
_EXPLANATORY_PHRASE = (
    # Introduces a PHRASE (`namely X`, `denoting X`, `read as X`), which is the
    # other English shape a claim like this takes and needs the other template.
    "namely", "denoting", "denotes", "signifying", "signifies", "read as",
    "stands for",
)
_EXPLANATORY = _EXPLANATORY_CLAUSE + _EXPLANATORY_PHRASE
_EXPLANATORY_RE = re.compile(
    r"(?<![A-Za-z])(?:" +
    "|".join(re.escape(c) for c in _EXPLANATORY) + r")(?![A-Za-z])",
    re.IGNORECASE)

# Where one clause of an admission ends and the next begins.  `:` is here
# because `subprocess.call`'s admission uses it to introduce the word's own
# domain ("the child's exit status word: 0..255 for a normal exit, or -N for a
# death by signal N") and a colon-separated tail is a separate claim from the
# phrase before it in exactly the way a comma-separated one is.
_CLAUSE_END_RE = re.compile(r"[;.,:]")

# A word of a clause, as opposed to a number or a delimiter.  `len >= 4` drops
# the two- and three-letter words of the corpus's prose ("a", "is", "of", "in")
# without a list of them, and the function words that survive are excluded
# explicitly: this is a CLOSED class of grammar, not a list of phrases that
# overclaim, which is the difference between the two lists in this file.
_FUNCTION_WORDS = frozenset((
    "about", "above", "after", "against", "also", "among", "another", "around",
    "because", "before", "being", "below", "between", "both", "cannot", "could",
    "does", "doing", "done", "down", "during", "each", "either", "else",
    "enough", "every", "from", "further", "have", "having", "here", "into",
    "itself", "less", "made", "make", "many", "more", "most", "much", "must",
    "near", "neither", "never", "next", "none", "only", "onto", "other",
    "others", "over", "same", "says", "shall", "should", "since", "some",
    "such", "than", "that", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "thus", "under", "until", "upon", "were",
    "what", "when", "where", "which", "while", "will", "with", "within",
    "without", "would", "your",
))
_WORD_RE = re.compile(r"[A-Za-z]+")

# A clause with a numeral in it is naming a VALUE, whatever else it says: this is
# the "or -N for a death by signal N" arm of every status contract in the tree,
# and it is why a range or a sentinel is enough for a clause to count as a
# constraint on the word without naming the word.
_HAS_DIGIT_RE = re.compile(r"\d")


def _content_words(text: str) -> set:
    """The words of `text` that could be ABOUT something: len >= 4, not a
    function word.  Stopwords are excluded because "…that is what the kernel
    returns" and a head clause that happens to contain "that" must not count as
    agreeing about the answer."""
    return {w.lower() for w in _WORD_RE.findall(text)
            if len(w) >= 4 and w.lower() not in _FUNCTION_WORDS}


def _sentence_head(text: str, at: int) -> str:
    """The part of `text` before offset `at`, back to the start of its sentence.

    The sentence rather than the clause, because the answer is named once and
    then talked about: "the child's exit status word: 0..255 for a normal exit,
    meaning it is never negative there" has its answer named four clauses before
    the connective, and the connective's clause is about the word by reference
    to a noun phrase that is not in front of it.
    """
    start = 0
    for m in re.finditer(r"[;.]", text[:at]):
        start = m.end()
    return text[start:at]


def _explanation_clause(text: str, at: int) -> str:
    """The clause the connective at `at` introduces, up to the next boundary."""
    m = _CLAUSE_END_RE.search(text, at)
    return text[at:m.start()] if m else text[at:]


def _rule_value_attached_claim(contract: Contract) -> str:
    """Why `contract`'s text attaches a claim about the world to the answer, or
    '' when every clause it explains is a constraint on the word itself.

    A clause that must mention the answer, and a clause carrying a numeral,
    passes: the second is a value specification, which is a constraint on the
    word by construction.  The message names the connective and quotes the
    clause, because a writer who is refused has to be able to see which of their
    own clauses the rule read as a claim about the host.
    """
    text = contract.assumes
    for m in _EXPLANATORY_RE.finditer(text):
        tail = _explanation_clause(text, m.end())
        if _HAS_DIGIT_RE.search(tail):
            continue
        answer = _content_words(_sentence_head(text, m.start()))
        if answer & _content_words(tail):
            continue
        return (f"admitted contract {contract.qualified} "
                f"{contract.assumes!r} attaches a claim to its answer with "
                f"{m.group(0)!r}, and the clause it introduces "
                f"({tail.strip()!r}) names none of the answer's own words "
                f"({', '.join(sorted(answer)) or 'none'}), so it is a claim "
                f"about the HOST rather than about the word the host returns. "
                f"An admitted contract may constrain what the host RETURNS; a "
                f"claim about what the host DOES is not an admission, it is an "
                f"unproved assertion with a proof attached to it. Say it about "
                f"the word — \"… {m.group(0)} …\" naming the answer, or the "
                f"answer's own domain (\"0..255\", \"a non-zero word\") — and "
                f"the rule passes.")
    return ""


def _rule_no_text(contract: Contract) -> str:
    if contract.assumes:
        return ""
    return (f"admitted contract {contract.qualified} is admitted with no text. "
            f"A contract has to say what it assumes of the host: a `sorry` "
            f"whose statement is empty is not a claim of trust, it is an absence "
            f"of one.")


def _rule_overclaim_phrase(contract: Contract) -> str:
    low = contract.assumes.lower()
    for phrase, why in _OVERCLAIM:
        if phrase in low:
            return (f"admitted contract {contract.qualified} admits "
                    f"{contract.assumes!r}, which says {why}. An admitted "
                    f"contract may constrain what the host RETURNS; a claim "
                    f"about what the host DOES is not an admission, it is an "
                    f"unproved assertion with a proof attached to it.")
    return ""


# The rules, in the order they run, as `(name, fn)`.  The NAMES are load-bearing
# in two places and neither is bookkeeping: `test_formal_admitted.py`'s
# `SCOPE_PROBES` is keyed by them, so a rule nothing exercises is reported
# rather than passing quietly, and every refusal carries the name of the rule
# that fired, so a writer who is refused can find it here.
_SCOPE_RULES = (
    ("no_text", _rule_no_text),
    ("overclaim_phrase", _rule_overclaim_phrase),
    ("value_attached_claim", _rule_value_attached_claim),
)
SCOPE_RULES = tuple(name for name, _fn in _SCOPE_RULES)


def contract_text_is_scoped(contract: Contract) -> str:
    """'' when the contract only constrains the ANSWER; why not otherwise.

    A cheap text check, and deliberately so: its job is to stop an admission
    that quietly grew a claim about the host, and the cheapest instrument for
    that is a text rule.  It is not a judgement about whether an assumption is
    reasonable — nobody can check that from here, and the assumption's whole
    point is that it is not checkable.  It is a check that the assumption is
    about the ANSWER, which is a shape question.

    Three rules, and the second and third are different IN KIND rather than
    three entries in one table: `no_text` says a contract has to say something,
    `overclaim_phrase` is the phrase list every overclaim in this tree has been
    written with, and `value_attached_claim` is the structural rule for the
    shape a phrase list cannot see — a claim about the host's state attached to
    a value by an explanatory connective.  The third's own comment states what
    it cannot see, which is the honest limit of a text check and the reason the
    `truth` probes exist beside it.
    """
    for name, rule in _SCOPE_RULES:
        why = rule(contract)
        if why:
            return f"rule `{name}`: {why}"
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
# modules — and 751 proof sites are closed by `native_decide` or `bv_decide`,
# which do not go through the kernel: they compile a decision procedure and run
# it, and close the goal through a generated axiom.  What that axiom is CALLED
# is not what the first version of this paragraph said; see `AXIOM_TACTICS` and
# `formal/lean.py::GENERATED_AXIOM_RE`.  `#print axioms` on such a theorem
# reports an axiom named after the theorem, and `OPUS.md` §1 already says as
# much about a generated theorem ("plus the project's usual
# `native_decide`/`bv_decide` step-lemma axioms") without FORMAL.md's inventory
# having a row for it.  That 751 is a CEILING rather than an equality, because it
# is a debt being paid down and `lib/ProofLib.lean` is edited by many hands at
# once; `test_formal_admitted.py` pins it, reports it, and fails when it rises.
# It was **749 until 2026-10-04 and 749 was wrong**: the scanner's own apostrophe
# rule (`lean_code_regions`) hid two sites, so this figure is a measurement of a
# fixed instrument and not of the file it started out measuring.
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
#
# The axiom is NOT `Lean.ofReduceBool`, and that name must not be written here:
# `ofReduceBool` is DEPRECATED on the pinned 4.32.2, and each use of either
# tactic elaborates to a fresh axiom named after the DECLARATION that used it
# (`work_step_mov._native.native_decide.ax_1_1`).  Measured; see
# `formal/lean.py::GENERATED_AXIOM_RE`.  A census that matched the source
# against `ofReduceBool` would be green over a library that reaches an axiom at
# every one of these sites.
AXIOM_TACTICS = ("native_decide", "bv_decide")

# What a tactic site costs depends on WHICH one, and the difference is not a
# matter of degree: `bv_decide`'s subject is a `∀ w, …` over a 32-bit word, where
# no kernel decision procedure is going to enumerate 2^32 cases, and
# `native_decide`'s subject in `lib/` was a CLOSED proposition over literals —
# which `decide` discharges in microseconds and the kernel checks.  So the two
# are named apart here and the test can require the expensive one only where it
# is the only tool.
CHEAP_AXIOM_TACTICS = ("decide", "rfl", "simp", "omega", "norm_num")


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

    **A `'` after an identifier character is an identifier's PRIME, not the
    opening of a character literal**, and getting that wrong cost this census two
    sites out of 751 — the reason is worth keeping because the failure is silent
    and large.  Lean 4 identifiers may contain `'`, and `lib/ProofLib.lean` has
    `fieldTag_inj'`, `fieldTag_inj''` and about forty more.  Treating the first
    of those as a literal opener blanks everything to the next apostrophe in the
    file, which lands in the middle of an unrelated docstring; from there the
    scanner is inside a string it invented, so it blanks REAL CODE — measured on
    `lib/` before the fix: **74 declaration headers that start at the beginning
    of a line were blanked as if they were prose** (62 in `ProofLib`, 11 in
    `Refine`, 1 in `Contracts`), among them `private def stmtsSize` and the `end`
    that closes a `mutual`, and two `bv_decide` sites at `lib/ProofLib.lean:1579`
    and `:1582` were not counted at all.  So the published figure was 749 where
    the truth is 751.  `test_formal_admitted.py::check_the_stripper_sees_every_
    declaration` is the assertion that would have caught it.  The rule is
    local and total: the `'` is a prime iff the character before it is
    alphanumeric, `_` or `'`.

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
        if ch == "'" and i > 0 and (text[i - 1].isalnum()
                                    or text[i - 1] in "_'"):
            out.append(ch)          # an identifier's prime, not a literal
            i += 1
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
                 reaches a generated axiom rather than the kernel (see
                 `AXIOM_TACTICS` for the name it has and is not).

    Both the count and the LINES come back, because a count with no location is
    a number nobody can act on and a location with no count is a note.

    This is a count of SITES, which is what the source text can decide and
    therefore what can sit in a test that runs every time.
    `library_trust_by_declaration` below is the same census attributed to the
    declaration each site is in, and `formal/lean.py::print_axioms` is the
    measurement no text scan can do: which axioms a theorem's TRANSITIVE closure
    reaches.
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

        def line_of(off, _raw=raw):
            return _raw.count("\n", 0, off) + 1

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


# A top-level DECLARATION and the NAME LEAN GAVE IT, which is not the same
# string: `lib/ProofLib.lean` declares `backward_branch_run_none` inside
# `namespace DylibExport`, so a `#print axioms` line has to spell
# `DylibExport.backward_branch_run_none` and a census that reported the bare
# name would produce a file full of `Unknown constant` errors and look like a
# disagreement rather than a namespace.  `def`/`abbrev`/`instance`/`example` are
# in the shape because a tactic can sit in any of them's bodies.
_DECL_RE = re.compile(r"(?m)^[ \t]*(?:@\[[^\]\n]*\][ \t\n]*)*"
                      r"(?P<mods>(?:private\s+|protected\s+|noncomputable\s+)*)"
                      r"(?:theorem|lemma|def|abbrev|instance|example)\s+"
                      r"(?P<name>[A-Za-z_][\w'.]*)")
# Every construct that opens a LeAN SCOPE, in one regex, because a scope this
# scanner does not know about is a scope it will attribute wrongly.
#
# `[ \t]+` after the keyword, never `\s+`: `\s` spans newlines, so `^end\s+(n)`
# matched the BARE `end` at `lib/ProofLib.lean:6462` followed by the blanked-out
# body of the next declaration's docstring and took `def` for a namespace name.
# Measured — the symptom was a scanner reporting a perfectly balanced file as
# mis-nested, which is what sent this to raising in the first place.
#
# `section` and `mutual` are here for a measured reason rather than a
# general one: `lib/ProofLib.lean:6445` opens a `mutual` and closes it with a
# BARE `end` at `:6462`, and `:6708`/`:6724` is a second pair. A scanner that
# knew only `namespace` put the second `end` where a namespace should have been,
# and every declaration after `:6462` got a name one level too shallow.
_SCOPE_OPEN_RE = re.compile(r"(?m)^(namespace|section|mutual)(?:[ \t]+"
                            r"([A-Za-z_][\w'.]*))?[ \t]*$")
# `_kind` 0 opens a scope, 1 closes one; `_name` is the namespace or None.
_SCOPE_RE = re.compile(r"(?m)^(end)(?:[ \t]+([A-Za-z_][\w'.]*))?[ \t]*$")

#: The key a site lands under when no declaration starts above it.  A named
#: sentinel rather than a silently dropped site: the alternative loses a count,
#: and a count that is short because a site found no owner is indistinguishable
#: in the output from a count that is right.  It is also a FINDING — a hit with
#: no theorem above it is a top-level tactic script, or a declaration head
#: `_DECL_RE` does not match, and both are shapes somebody has to read rather
#: than a theorem to work on.  (This was `<file scope>` when the floor sweep
#: wrote it; one name for one condition, and the longer one says what the
#: condition is.)
UNATTRIBUTED = "<no declaration above the site>"


def _declarations(code: str) -> list:
    """`(line, qualified_name, is_public)` for every declaration in `code`.

    `code` is the comment-stripped text, so a `theorem` inside a docstring is
    not a declaration.  `is_public` is False for `private`, and it is reported
    rather than filtered because the two consumers need opposite things:
    `library_trust_by_declaration` counts a `private` declaration's sites (they
    are sites), and `#print axioms` cannot NAME one — Lean mangles it, so
    `test_formal_axioms.py` can only ask about the public ones and has to
    assert that no `private` declaration carries a tactic site.

    The scope stack holds one entry per open scope: a NAMESPACE by its name, and
    a `section`/`mutual` as `(None, keyword)`. Only namespaces contribute a name
    to the declarations inside them, but both have to be on the stack, because a
    BARE `end` closes the innermost scope whatever it is: `lib/ProofLib.lean:6445`
    opens a `mutual` and `:6462` closes it with a bare `end`, and a stack that
    did not hold the `mutual` would pop `namespace MF` instead and name every
    declaration in the next 160 lines one level too shallow. `:6708`/`:6724` is
    a second pair of the same shape.

    An `end NAME` that does not match, or an `end` with nothing open, raises
    rather than guessing: a mis-nested name attributes every site after it to
    the wrong theorem, and a wrong attribution is worse than no census because
    it is still a census.
    """
    events = []
    for m in _SCOPE_OPEN_RE.finditer(code):
        events.append((m.start(), 0, m.group(1), m.group(2)))
    for m in _SCOPE_RE.finditer(code):
        events.append((m.start(), 1, m.group(1), m.group(2)))
    events.sort()
    out, stack, pos = [], [], 0

    def emit(upto):
        for m in _DECL_RE.finditer(code, pos, upto):
            out.append((code.count("\n", 0, m.start()) + 1,
                        ".".join([s[0] for s in stack if s[0]]
                                 + [m.group("name")]),
                        "private" not in m.group("mods")))

    for off, kind, kw, name in events:
        # Every declaration that STARTED before this event is emitted here and
        # named by the stack as it stood WHERE IT STARTED, which is why the pop
        # happens after the emit rather than before it.
        emit(off)
        pos = off
        line = code.count("\n", 0, off) + 1
        if kind == 0:
            if name is None and kw == "namespace":
                raise ValueError(
                    f"lib/{line}: a bare `namespace`, which this scanner will "
                    f"not guess the name of. Name it.")
            stack.append((name, kw))
            continue
        if not stack:
            raise ValueError(
                f"lib/{line}: `end {name or ''}` closes nothing, so this "
                f"scanner and the file disagree about the scopes.")
        if name is not None and stack[-1][0] != name:
            raise ValueError(
                f"lib/{line}: `end {name}` closes the {stack[-1][1]} "
                f"{stack[-1][0] or '(unnamed)'!r}, so this scanner and the "
                f"file disagree about the scopes. Fix the nesting rather than "
                f"the scanner: a mis-nested name attributes every site after it "
                f"to the wrong theorem.")
        stack.pop()
    emit(len(code))
    left = [s for s in stack if s[0]]
    if left:
        raise ValueError(f"lib/: namespace {left[-1][0]!r} is never closed")
    out.sort()
    return out


def _attribution(lean_dir: str) -> dict:
    """`{module: {declaration: record}}` — the ONE attribution walk.

    A record, not a tuple, because the three consumers want three different
    projections of the same fact and each of them used to grow its own walk:

      * `count` and `lines` are what `library_trust_by_declaration` publishes —
        the count a completeness check compares against `library_trust`'s, and
        the site lines `native_decide_declarations` and `#print axioms` need;
      * `line` is where the declaration starts, which is what makes the
        attribution a WORK LIST rather than another count;
      * `kinds` is the per-kind and per-TACTIC split (`native_decide` against
        `bv_decide`), which is what decides which of a theorem's sites is worth
        attempting: a closed arithmetic goal has a kernel-checked spelling
        standing next to it and a `∀ w, … ≠ …` bit-pattern lemma does not.

    `is_public` is carried for the reason `_declarations` reports it: a
    `private` declaration's sites are sites, and only `#print axioms` cannot
    name one.

    The attribution RULE is "the last declaration that started at or before the
    site", which is the declaration a site is inside for well-formed source
    because Lean declarations do not nest. Its two limits are reported rather
    than absorbed: a site before the first declaration is `UNATTRIBUTED`, and a
    site in a `where` clause is attributed to the head it hangs off (in this
    project a `where` body is a field or a lemma over the same statement, so
    counting it against the head is the honest reading; in a file where `where`
    held an unrelated proof it would not be, and the file would be worth
    reading).

    Raises rather than guessing if the namespace nesting does not balance — see
    `_declarations`.
    """
    census = library_trust(lean_dir)
    out = {}
    for mod, kinds in census.items():
        path = os.path.join(lean_dir, mod + ".lean")
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            continue
        code = lean_code_regions(raw)
        lines = code.split("\n")
        decls = _declarations(code)
        # `(start_line, name)` in file order, so the owner of a site is a walk
        # with a POINTER rather than a fresh scan per site: the rule is "the last
        # declaration at or before this line", the sites arrive in order, and a
        # rescan per site is a census whose cost is the square of the corpus.
        heads = [(dline, name) for dline, name, _public in decls]
        per = {}
        for kind, (_count, sites) in kinds.items():
            at = 0          # each kind's own lines start at the top again
            for site in sites:
                while at + 1 < len(heads) and heads[at + 1][0] <= site:
                    at += 1
                owner = heads[at][1] if at < len(heads) \
                    and heads[at][0] <= site else UNATTRIBUTED
                rec = per.setdefault(
                    owner, {"count": 0, "lines": (), "line":
                            heads[at][0] if owner != UNATTRIBUTED else 1,
                            "kinds": {"axiom": 0, "sorry": 0,
                                      "axiom_tactic": 0}})
                rec["kinds"][kind] += 1
                if kind == "axiom_tactic":
                    rec["count"] += 1
                    rec["lines"] = rec["lines"] + (site,)
        # The per-TACTIC split, counted with each tactic's own pattern rather
        # than derived from `_TACTIC_RE`, so the split is a measurement and the
        # check that the two sum to the total has something to disagree with.
        for name, rec in per.items():
            for tactic in AXIOM_TACTICS:
                hits = [ln for ln in rec["lines"]
                        if re.search(r"(?<![\w.'])" + tactic + r"(?![\w'])",
                                     lines[ln - 1])]
                if hits:
                    rec["kinds"][tactic] = len(hits)
        out[mod] = per
    return out


def library_trust_by_declaration(lean_dir: str) -> dict:
    """`{module: {qualified_name: (count, (lines…))}}` — the census attributed.

    **The other direction from `library_trust`, and the one that makes its number
    actionable.** `library_trust` reports SITES because a count with no location
    is a number nobody can act on; this reports how many of them each THEOREM
    owns, because the ceiling `test_formal_admitted.py` pins is per MODULE and
    the work is per proof.  `bugs/FORMAL_native_decide_axiom.md` item 2 is this
    function: "the ceiling can be lowered per theorem rather than per file",
    which needs the theorem to be named before anything can be lowered.

    A PROJECTION of `_attribution`, and kept in this shape for the two consumers
    that read a two-tuple: `test_formal_axioms.py`'s per-declaration arithmetic
    and `native_decide_declarations`' site lines. `declaration_tally` below is
    the same record in the shape a work list wants.

    Names are QUALIFIED (`DylibExport.backward_branch_run_none`), because the
    consumer of this is a `#print axioms` line and Lean's spelling is the
    qualified one.
    """
    return {mod: {name: (rec["count"], rec["lines"])
                  for name, rec in per.items()}
            for mod, per in _attribution(lean_dir).items()}


def declaration_tally(lean_dir: str) -> dict:
    """`{module: [(name, line, kinds)]}` — the attribution as a WORK LIST.

    `library_trust_by_declaration` in the shape a CEILING wants: a count and
    where its sites are.  This is the shape `bugs/FORMAL_native_decide_axiom.md`
    items 2 and 3 want — where the theorem starts, and how its sites split by
    tactic — because "these four theorems are now kernel-checked" is a claim
    somebody has to be able to act on, and the difference between a `native_decide`
    on a closed `UInt64` goal and a `bv_decide` on a `∀ w, …` bit-pattern lemma
    is the difference between a replacement with a spelling and one without.

    Only declarations that OWN at least one site are listed, and the sort is by
    site count descending then by line, so the head of the list is what to work
    on. A module with no sites is an empty list rather than absent, so a caller
    can tell "nothing here" from "the module is not in the census".

    The same `_attribution` record as `library_trust_by_declaration`, projected
    again rather than walked again — the completeness check in
    `test_formal_admitted.py` compares both projections against the same
    `library_trust` counts, which is what would fail if they ever stopped being
    the same walk.
    """
    out = {}
    for mod, per in _attribution(lean_dir).items():
        rows = [(name, rec["line"], rec["kinds"]) for name, rec in per.items()]
        rows.sort(key=lambda r: (-r[2]["axiom_tactic"], -r[2]["sorry"], r[1]))
        out[mod] = rows
    return out


def library_trust_by_declaration_lines(lean_dir: str, top: int = 6) -> list:
    """`declaration_tally` as report lines, biggest first, `top` per module.

    What makes the per-theorem number a WORK LIST rather than another count: each
    line names a theorem, where it starts, and how many axiom-carrying sites its
    own proof has. `top` is a parameter rather than a constant because the reader
    is a report and the writer is a ceiling — the full table is always available
    from `declaration_tally`, and a truncated one must never be the only way to
    see a site.
    """
    out = []
    for mod, rows in sorted(declaration_tally(lean_dir).items()):
        if not rows:
            continue
        shown = rows[:top]
        parts = []
        for name, line, kinds in shown:
            bits = ",".join(f"{k}={kinds[k]}" for k in
                            ("axiom_tactic", "sorry", "axiom") if kinds[k])
            mix = ",".join(f"{t}={kinds[t]}" for t in AXIOM_TACTICS
                           if kinds.get(t))
            if mix:
                bits += " (" + mix + ")"
            parts.append(f"{name}@{line} [{bits}]")
        more = "" if len(rows) <= top else f", +{len(rows) - top} more"
        out.append(f"{mod}: {len(rows)} declaration(s) with a hit; "
                   + "; ".join(parts) + more)
    return out


def native_decide_declarations(lean_dir: str) -> dict:
    """`{module: {qualified_name: lines…}}` for `native_decide` sites only.

    Split out from `bv_decide` because the two are not interchangeable and the
    difference is worth a name.  Every `bv_decide` in `lib/` closes a `∀ w, …`
    over a 32-bit word, where bit-blasting is the only tool; a `native_decide`
    in this tree has been a CLOSED proposition over literals, which `decide`
    discharges and the KERNEL checks.  So this is the census a reader can act on
    where `library_trust_by_declaration` is the census a reader can only count.

    It reads the per-TACTIC split off the same record as the other two
    projections rather than re-reading the file and re-searching for the string,
    so a site this reports and a site `declaration_tally` counts are the same
    site by construction.
    """
    out = {}
    for mod, per in _attribution(lean_dir).items():
        hits = {name: rec["lines"] for name, rec in per.items()
                if rec["kinds"].get("native_decide")}
        if hits:
            out[mod] = hits
    return out

def lean_dir(root: str) -> str:
    """The hand-written Lean library directory for a checkout.

    One function rather than a path spelled at each of its call sites, for the
    reason `HOSTMODS_ROOT` is defined through `formal/imports.py`'s root: two
    spellings of one directory drift, and the drift is invisible.
    """
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "lib")
