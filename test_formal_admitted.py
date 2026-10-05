#!/usr/bin/env python3
"""The ADMITTED CONTRACT ratchet, and the differential tests of everything NOT admitted.

    python3 test_formal_admitted.py [-v] [group ...]

## What this file is for, in the order the two halves matter

A trust boundary is worth nothing if nobody can see it moving.  The FIRST half
here is therefore the ratchet: `test_the_count_per_module_is_pinned` walks every
`formal/hostmods/` module and requires the number of `@admitted` declarations in
it to be the number `ADMITTED_COUNTS` records.  Both directions are failures.  A
new contract that does not move the table is a claim of trust nobody counted, and
a table entry whose module stopped declaring is a stale marker -- the same
`expect=` discipline `tools/suite.py` applies, in the direction that matters here,
because a trust boundary that only ever grows in the report is a boundary nobody
is watching.

The SECOND half is what stops the ratchet from being a way to make the number
go up.  Everything a hostmod DECIDES rather than admits is checked against
CPython's own answer: `subprocess`'s argument validation and `check_returncode`,
`ctypes`'s fourteen sizes and four conversions and its buffer refusal,
`fcntl`'s eleven constants, `concurrent.futures`' five `Future` states and three
transitions, `threading`'s `TIMEOUT_MAX`.  If a model grew a contract to avoid
being wrong about something CPython can be asked, these groups go red.

And the third thing, which is the point of the whole mechanism: an admitted
contract must be SCOPED.  `test_every_contract_only_constrains_the_answer` runs
`formal/admitted.py`'s `contract_text_is_scoped` over every declaration, so an
admission that grew a claim about the host's BEHAVIOUR -- "always", "never",
"deterministic" -- is refused.  An admission is a claim of trust; a claim that
reaches past the answer is an unproved assertion wearing a proof's clothes.
`SCOPE_PROBES` is the instrument for the rule itself, in the shape
`PRE_AUDIT_TEXT` gives the truth half: one row per rule in BOTH directions, and
one row per explanatory connective built from `formal/admitted.py`'s table, so a
connective nothing exercises is reported rather than read as a rule that blocks
nothing.

FOURTH, and the one the audit of 2026-10-04 added: an admission must be TRUE.
Scoping cannot tell a true assumption from a false one -- both are sentences
about the answer -- and fifteen of the nineteen contracts were false of the real
host while every group above was green.  The `truth` group asks CPython or the
OS what the host actually does and requires each contract's own text to cover
it; `test_the_truth_probes_reject_the_pre_audit_text` puts every pre-audit
sentence back through its own probe, so a probe that stops testing what it was
written for fails rather than passing quietly.  `TRUTH_PROBES` below is the
audit's table, one row per contract, and it is the whole of it.

## Groups

  registry   the partition, the Lean shapes, the scope rule, the ratchet
  emitted    the generated Lean carries one countable `sorry` per contract
  subprocess / ctypes / fcntl / futures / threading   the differential groups
  surface     the MEASURED call surface builds and refuses, on both backends
  runtime    an admitted call REFUSES at run time, with a status that cannot be
             mistaken for a child's
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
sys.path.insert(0, HERE)

from test_formal_dylib import TestFailure, check, run_fire  # noqa: E402
from test_formal_json import Failure  # noqa: E402  (one failure type, not two)

from formal import admitted as A  # noqa: E402
from formal import imports as I  # noqa: E402

BACKENDS = ("arm64", "x86_64")


# ── THE RATCHET ───────────────────────────────────────────────────────────────
# The number of `@admitted` declarations per module.  This IS the claim the file
# exists to keep true, and it is a table rather than a derived count precisely so
# that changing it is a DELIBERATE act somebody has to make in a diff.
#
# Read the zeros: `os` is 0 and `argparse` is 0, and those are measurements --
# `formal/hostmods/os/__init__.mojo` decides everything it can and admits nothing
# -- not absences.  `formal/admitted.py`'s `counts_by_module` reports every module
# with a model, so "not in the table" and "in the table with a zero" are
# distinguishable, and only the second is allowed to be wrong.
ADMITTED_COUNTS = {
    "argparse": 0,
    "ast": 0,
    "concurrent": 0,
    "concurrent.futures": 2,       # Executor.submit, Executor.shutdown
    "contextlib": 0,
    "ctypes": 2,                   # CDLL, a call through the handle
    "enum": 0,
    "fcntl": 0,                    # the real flock(2); nothing is admitted
    "fnmatch": 0,
    # `glob` is 0 and the reason is the same one `tempfile`'s zero is: every
    # answer this module gives is computed.  The directory entries come from
    # `readdir(3)` through `os.listdir`, the pattern language is
    # `formal/hostmods/fnmatch.mojo`'s `match_any`, and the only decisions are
    # `opendir`/`lstat` questions libSystem answers -- there is no host fact
    # left over to trust, which is what the zero measures.  All 33 corpus cases
    # in `test_formal_glob.py` are compared with CPython's own `glob` on both
    # backends.
    "glob": 0,
    "hashlib": 0,
    # `escape` is five ordered substring replacements over bytes a string already
    # is, and every one of the 1132 answers `test_formal_html.py` compares with
    # CPython is computed rather than looked up. There is no host fact left over
    # to admit, which is what the zero is measuring.
    "html": 0,
    "io": 0,
    "json": 0,
    "math": 0,
    # `operator` is 0 because every name it exports is either the machine's own
    # word arithmetic or a status this module computes: 27 functions over one
    # 64-bit word, checked name by name against CPython's live `operator` by
    # `test_formal_core_hostmods.py`'s `op` group on both backends. The three
    # places CPython raises (a zero divisor, a zero modulus, a shift distance
    # outside 0..63) answer -1 and are compared against CPython's exceptions
    # rather than against CPython's values, which is what the group does with
    # them. No host fact is left over to admit.
    "operator": 0,
    "os": 0,
    "os._syscalls": 0,
    "os.path": 0,
    "pathlib": 0,
    # Every one of its thirty functions is a one-line forward to
    # `formal/hostmods/os/path/__init__.mojo`, which is CPython's `posixpath`
    # and admits nothing itself. It is a SPELLING, and a spelling has no host
    # fact left over to admit — which is what the zero is measuring, and the
    # reason `formal/hostmods/posixpath.mojo`'s own docstring carries the
    # measurement about why each name is a `def`.
    "posixpath": 0,
    "platform": 0,
    # `random` is CPython's Mersenne Twister, written out: the state is 624
    # 32-bit words this module computes (`seed` is the init_by_array schedule,
    # `random`/`getrandbits`/`randrange` are the tempering and the rejection
    # loop), so there is no host fact left over to admit. The zero is measured
    # the way `test_formal_random.py` measures the rest — name by name against
    # CPython's live `random` on both backends, including the seeded sequences
    # that fix the state schedule.
    "random": 0,
    "re": 0,
    # `quote` is a scan over bytes a string already is plus a substitution, and
    # every one of the 1142 answers `test_formal_shlex.py` compares with
    # CPython is computed rather than looked up — so there is no host fact left
    # over to admit, which is what the zero is measuring and the same row
    # `html` and `glob` carry for the same reason. `split`/`join`/`shlex` are
    # absent from the module and refused by name, so the module's surface is
    # one function and that function decides everything.
    "shlex": 0,
    "shutil": 0,
    # `signal` is 0 and the reason is the `fcntl` one: every name it exports is
    # either this platform's `<signal.h>` number (computed from the same header
    # CPython reads, and compared with CPython's live `signal` name by name by
    # `test_formal_core_hostmods.py`'s `sig` group on both backends) or a libc
    # call (`strsignal(3)`, `kill(2)`). The dispositions — `signal()`, the
    # itimers, `getsignal` — are ABSENT rather than admitted, so there is no
    # host fact left over to trust, which is what the zero measures.
    "signal": 0,
    "stat": 0,
    "struct": 0,
    "subprocess": 12,               # run/call/check_call/check_output/getoutput/
                                   # getstatusoutput/Popen + popen_{wait,poll,
                                   # kill,terminate,communicate}
    "sys": 0,
    # `tempfile` is 0 and that is the BEST outcome for it: every name it
    # exports is a real call this image makes, so there is no host fact left
    # over to admit — `gettempdir`'s candidates are read with
    # `os.getenv`/`isdir`/`access`, `mkdtemp`'s directory is a real `mkdir(2)`
    # at 448 and its eight characters are `arc4random_buf`. It is also the
    # largest host-import row in the corpus (111 files) and it left
    # `HOST_UNREACHABLE` on 2026-10-03 for that reason — the placement was under
    # "a terminal", which is about `TMPDIR`, and `TMPDIR` is a variable.
    "tempfile": 0,
    # `textwrap` is 0 because `dedent` and `indent` are pure string
    # computation over primitives `_syscalls.mojo` already has — the
    # `fcntl` situation. Five files in this repository import it, spelling
    # `dedent` 78 times and `indent` twice, with no keywords.
    "textwrap": 0,
    # `traceback` is 0 because its only two functions COMPUTE CPython's answer
    # rather than assert one: `format_exc()` returns the text
    # `format_exception_only(None, None)` produces, which is what CPython itself
    # prints when `sys.exc_info()` is `(None, None, None)` — and on this target
    # it always is, because there is no `raise` and no unwinder. `print_exc()`
    # writes that same text to descriptor 2 through `sys.write_stderr`. Every
    # name that would need a live exception, a traceback object or a frame list
    # is absent from the module rather than admitted, so no host fact is left
    # over to trust, which is what the zero measures.
    "traceback": 0,
    "typing": 0,
    "threading": 3,               # Thread.start, Thread.join, Lock.acquire
    "textwrap": 0,                # every name it exports is arithmetic over
                                  # bytes a string already is: dedent's margin
                                  # is a lexicographic min/max walk and indent's
                                  # is a splitlines scan, both compared against
                                  # CPython's own over a corpus built so each
                                  # rule is separable. There is no host fact
                                  # left over to admit, which is what the zero
                                  # is measuring — the same claim tempfile's
                                  # zero makes, and for the same reason.
    "time": 0,
    "typing": 0,
}


def _module_source(programs, name, body, tmpdir, cas_root, backend="arm64"):
    """Build `programs` and RUN the image, returning its stdout lines.

    `run_fire` is imported from `test_formal_dylib` rather than copied, for the
    reason that file's own header gives: an independent driver is the point, and a
    second copy of it is a second thing that can be wrong.
    """
    src = os.path.join(tmpdir, f"t_{abs(hash(name))}.mojo")
    with open(src, "w") as f:
        f.write("\n".join(programs) + "\n")
    out = os.path.join(tmpdir, f"t_{abs(hash(name))}.aout")
    home = os.path.join(cas_root, backend, str(abs(hash(name))))
    os.makedirs(home, exist_ok=True)
    r = run_fire(["build", "--formal", "--no-prove", f"--backend={backend}",
                  "-o", out, src], env={"GMOJO_HOME": home})
    check(r.returncode == 0,
          f"{name}: the image did not build.\n    "
          f"{(r.stderr or r.stdout or '').strip()[:400]}")
    check(os.path.isfile(out), f"{name}: the build reported success and wrote no image")
    p = subprocess.run([out], capture_output=True, text=True, timeout=60)
    return [ln for ln in p.stdout.split("\n") if ln != ""]


# ── registry ──────────────────────────────────────────────────────────────────

def group_registry(tmpdir, cas_root, verbose):
    """The partition holds, the tier agrees with the tree, and the shapes are sane."""
    check(not I._host_tier_conflicts(),
          "a name is in both HOST_MODELLED and HOST_UNREACHABLE: "
          f"{I._host_tier_conflicts()}")
    bad = I._admitted_tier_conflicts()
    check(not bad, "HOST_ADMITTED and the tree disagree:\n    " + "\n    ".join(bad))

    mods = {m.split(".")[0] for m in I.HOST_ADMITTED}
    tiers = {n: I.host_module_tier(n) for n in sorted(I.HOST_ADMITTED)}
    wrong = {n: t for n, t in tiers.items() if t != "admitted"}
    check(not wrong,
          "every name in HOST_ADMITTED must report tier 'admitted', and these "
          f"do not: {wrong}.  A name in the set whose tier is something else is a "
          f"module the sweep's reach line will file under the wrong bucket.")

    # `HOST_MODULES` must still be the union, or `_is_host_module` stops
    # covering these names and a file importing one is refused for a DIFFERENT
    # reason -- "not a stdlib or sibling module" -- which sends a reader looking
    # for a broken module path instead of at the contract.
    missing = sorted(m for m in I.HOST_ADMITTED if m not in I.HOST_MODULES)
    check(not missing,
          f"HOST_ADMITTED names must be in HOST_MODULES; missing: {missing}")

    clash = A.contract_texts_are_unique(A.all_contracts())
    check(not clash, clash)
    if verbose:
        print(f"    {len(A.all_contracts())} contracts across "
              f"{len({c.module for c in A.all_contracts()})} modules; "
              f"tier conflicts 0; Lean names unique")
    return True, f"the admitted tier is a partition ({len(mods)} modules)"


def group_scope(tmpdir, cas_root, verbose):
    """Every contract's text constrains the ANSWER and nothing else."""
    bad = []
    for c in A.all_contracts():
        why = A.contract_text_is_scoped(c)
        if why:
            bad.append(why)
    check(not bad, "an admitted contract reaches past the host's answer:\n    "
                   + "\n    ".join(bad))
    if verbose:
        for c in A.all_contracts():
            print(f"    {c.qualified:34s} {c.assumes[:70]}")
    return True, f"{len(A.all_contracts())} contract(s) are scoped to the answer"


# ── the SCOPE probes: one sentence per rule, in BOTH directions ───────────────
#
# `contract_text_is_scoped` is a text rule, and a text rule that has only ever
# agreed with the tree proves nothing — which is how fifteen false admissions
# were green in every other group of this file on 2026-10-04, and how the
# `ctypes` sentence the audit found ("the loader handle is 0, meaning no library
# of that name is on this target") passed a rule that no row had ever been
# written for.  `PRE_AUDIT_TEXT` below is the truth side's answer to that; this
# table is the scope side's, and it is the same shape for the same reason.
#
# Both directions, and the accept rows are the half that matters: a rule
# implemented by refusing everything would pass every refuse row here and be
# useless, because the live corpus it is supposed to admit is admitted by
# `group_scope` above.  So every rule needs a sentence it must ADMIT, and two
# of the accept rows here are the instrument's DOCUMENTED LIMITS — sentences the
# rule does not catch, with the instrument that does named beside them.
#
# `(rule, refused, text, why)`.  The `why` is read by a reader who finds a row
# firing when it should not; it is not checked, because a probe that asserts its
# own justification is a probe with nothing left to test.
SCOPE_PROBES = (
    # ── `no_text`: a `sorry` with an empty statement is an absence, not a claim
    ("no_text", True, "",
     "an admission with no text says nothing, so there is no claim to trust"),
    ("no_text", True, "   \n  ",
     "whitespace is not a sentence either"),
    ("no_text", False, "the child's process id, a positive integer",
     "the shortest real admission in the tree, and the shape of every other"),

    # ── `overclaim_phrase`: one row per phrase, so removing one fails here
    ("overclaim_phrase", True, "the command always succeeds, so the word is 0",
     "the `always` phrase"),
    ("overclaim_phrase", True,
     "the child's status word, which is never negative for a normal exit",
     "the `never` phrase"),
    ("overclaim_phrase", True,
     "the number of bytes the write reports, and the write is deterministic",
     "the `deterministic` phrase"),
    ("overclaim_phrase", True,
     "the child's output on stdout, an arbitrary byte string that is empty",
     "the `empty` phrase, which is a claim about CONTENT rather than shape"),
    ("overclaim_phrase", True,
     "the lock is granted, and no other holder of it is running",
     "the `no other` phrase, which is a claim about host state"),
    ("overclaim_phrase", True,
     "the child's status word, and none running means it has been collected",
     "the `none running` phrase"),
    ("overclaim_phrase", True,
     "the pointer this returns is safe to dereference for any address",
     "the `safe` phrase, which is a claim about a property of the host"),
    ("overclaim_phrase", False,
     "the child's exit status word: 0..255 for a normal exit, or -N for a "
     "death by signal N",
     "the shape `subprocess.run` actually declares, and no phrase in it"),

    # ── `value_attached_claim`: the shape a phrase list cannot see
    ("value_attached_claim", True,
     # The audit's own sentence, verbatim from `PRE_AUDIT_TEXT`: a claim about
     # the WORD, joined to a claim about the FILESYSTEM by "meaning".
     "the loader handle is 0, meaning no library of that name is on this "
     "target, or a non-zero word this target's dynamic loader owns",
     "the one instance the audit found false, and the reason a phrase list "
     "cannot be the rule"),
    ("value_attached_claim", True,
     "the lock this returns is free, which means no thread of this process "
     "holds it",
     "a `which means` clause about host state — the threading analogue of the "
     "ctypes sentence, and the clause shape rather than the word"),
    ("value_attached_claim", False,
     # The live text, and the test below pins that the row IS the tree's.
     "the loader handle is 0 when dlopen(3) failed: the file may be absent, "
     "may not be a loadable image, or a symbol may be unresolvable, and "
     "CPython raises OSError for all three, or else a non-zero word this "
     "target's dynamic loader owns",
     "the corrected `ctypes` text: a claim about the filesystem in every word, "
     "and IN SCOPE because it constrains the answer 0.  This is the row a "
     "phrase list cannot produce — refusing it would trade a false admission "
     "for an unusable instrument"),
    ("value_attached_claim", False,
     "the loader handle is 0, meaning 0 is the word this loader answers for a "
     "failure",
     "an explanation clause carrying a numeral, which is a value "
     "specification and therefore a constraint on the word"),
    ("value_attached_claim", False,
     "the child's status word, meaning the word this kernel reports at the "
     "child's exit",
     "an explanation clause that names the answer, which is what the rule asks "
     "for"),
    ("value_attached_claim", False,
     "the child's output on stdout up to the first NUL byte, because a str "
     "on this path is a NUL-terminated char *; CPython's own answer is the "
     "whole byte string and may contain NULs",
     "a `because` clause, which is a RATIONALE for a constraint on the word "
     "and not an explanation of it — `because` is absent from the connective "
     "table on this row's account, since `subprocess.check_output` declares it"),
    # The two rows below are the rule's LIMITS, and they are here so that the
    # boundary between the two instruments is written down rather than
    # discovered.  `TRUTH['subprocess.popen_poll']` refuses the first (it is
    # the `-1` sentinel that collides with a real SIGHUP answer) and
    # `TRUTH['ctypes.cdll_open']` measures the second; a scope rule is a shape
    # question and neither of these is one.
    ("value_attached_claim", False,
     "the child's exit status word, an integer in 0..255, and -1 while the "
     "child has not been collected",
     "LIMIT: the `-1` sentinel the audit found false.  No connective, no "
     "banned phrase — it is the TRUTH probe for `popen_poll` that refuses it, "
     "because `-1` is an answer CPython really gives"),
    ("value_attached_claim", False,
     "the loader handle is 0 because no library of that name is on this target",
     "LIMIT: a world claim attached by a CAUSAL connective.  `because` is not "
     "in the table (see the `because` row above), so this passes; "
     "`TRUTH['ctypes.cdll_open']`'s measurement is what catches it"),
) + tuple(
    # ONE ROW PER CONNECTIVE, BUILT rather than written, and that is the whole
    # reason this is a comprehension: eleven of the thirteen connectives in
    # `_EXPLANATORY` had no row, so removing any of them was a no-op and the
    # table could not tell a live connective from a dead one — which is the
    # defect `tools/formal_sweep_causes.py` was fixed for in
    # `bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` §5.1, and the reason that
    # map's `check_cause_table` asserts every label is reachable from a sample.
    # Generated, a connective added to `_EXPLANATORY` brings its row with it and
    # the row fails if the connective does not fire.
    ("value_attached_claim", True,
     f"the loader handle is 0, {conn} no library of that name is on this "
     f"target",
     f"the `{conn}` connective, which introduces a clause")
    for conn in A._EXPLANATORY_CLAUSE) + tuple(
    ("value_attached_claim", True,
     f"the loader handle is 0, {conn} a claim about the filesystem of this "
     f"target",
     f"the `{conn}` connective, which introduces a phrase rather than a clause")
    for conn in A._EXPLANATORY_PHRASE)


def test_the_scope_probes_refuse_what_they_are_written_for(tmpdir=None):
    """Every scope rule refuses the sentence written for it, and admits the
    others — and every rule has a row in BOTH directions.

    The direction that keeps `contract_text_is_scoped` honest.  It is a text
    check, and text checks have two ways to be useless: passing everything (which
    is how the `ctypes` sentence survived the audit) and refusing everything
    (which would pass every refuse row here while `group_scope` went red on the
    tree's own nineteen contracts).  So the table is keyed by rule name, a rule
    with no refuse row is reported as a dead rule, a rule with no accept row is
    reported as one that can only refuse, and a row naming a rule that no longer
    exists is reported as a probe that lost its subject.
    """
    live_rules = set(A.SCOPE_RULES)
    bad = []
    # One row per rule per direction, from the table rather than from the run, so
    # the failure names the rule whose coverage is missing.
    seen = {}
    for rule, refused, text, _why in SCOPE_PROBES:
        seen.setdefault(rule, {True: 0, False: 0})[refused] += 1
        c = A.Contract("probe", "probe", text, "<scope-probe>", 0)
        why = A.contract_text_is_scoped(c)
        if refused and not why:
            bad.append(f"rule `{rule}`: the probe sentence {text!r} is ADMITTED, "
                       f"so the rule does not catch what it was written for")
        elif refused and f"rule `{rule}`" not in why:
            bad.append(f"rule `{rule}`: the probe sentence {text!r} is refused, "
                       f"but by a different rule:\n        {why}")
        elif not refused and why:
            bad.append(f"rule `{rule}`: the probe sentence {text!r} must be "
                       f"admitted and was refused:\n        {why}")
    unknown = sorted(set(seen) - live_rules)
    check(not unknown,
          f"these SCOPE_PROBES rows name a rule `contract_text_is_scoped` does "
          f"not have: {unknown}. A probe that lost its subject keeps passing "
          f"after the rule it was written for is gone.")
    gaps = [f"rule `{rule}` has no {'refuse' if not d[True] else 'accept'} row"
            for rule, d in sorted(seen.items())
            for d in ([d] if (not d[True] or not d[False]) else [])]
    missing_rules = sorted(live_rules - set(seen))
    check(not missing_rules,
          "these scope rules have no probe row at all, so nothing here checks "
          f"that they fire: {missing_rules}")
    check(not gaps, "a scope rule can only do one direction:\n    "
                    + "\n    ".join(gaps))
    check(not bad, "a scope probe does not behave as it was written:\n    "
                   + "\n    ".join(bad))
    # Anti-drift: the sentence the audit corrected has to be the ACCEPT row, so
    # a rewrite of `ctypes.cdll_open` that reintroduces an attached claim has to
    # update this table rather than quietly pass.
    cdll_open = next((c for c in A.all_contracts()
                      if c.qualified == "ctypes.cdll_open"), None)
    check(cdll_open is not None,
          "ctypes.cdll_open is not in the tree, so the scope rule's own reason "
          "for existing cannot be checked")
    accepted = {t for _r, refuted, t, _w in SCOPE_PROBES if not refuted}
    check(cdll_open.assumes in accepted,
          "the corrected `ctypes.cdll_open` text is not one of the accept rows "
          "of SCOPE_PROBES:\n        " + cdll_open.assumes
          + "\n    so the sentence the rule exists for is not pinned against "
            "the tree, and a rewrite that reintroduced an attached claim would "
            "pass rather than be reported.")
    return True, (f"{len(SCOPE_PROBES)} scope probe(s) over "
                  f"{len(live_rules)} rule(s), refuse and accept each way; the "
                  f"corrected ctypes text is pinned as an accept row")


# ── the TRUTH half: every contract against the real host ──────────────────────
#
# Everything above checks that an admission is SCOPED (it constrains the answer
# and not the host's behaviour) and that it is COUNTED.  Neither of those can
# tell a TRUE admission from a FALSE one, and the difference is the whole subject
# of this group: on 2026-10-04, FIFTEEN of the
# nineteen contracts asserted something the host does not do (three more were
# true only under a reading the audit had to choose), and all nineteen were green
# in every other group in this file.
#
# The shape of the check is deliberately the shape of the existing differential
# groups: ask CPython, or the OS, and compare its answer with the model's.  What
# is new is that the thing being compared is an ASSUMPTION rather than a return
# value, so each row asks what the contract has to cover and then checks that the
# contract's own text covers it.  A row is allowed to disagree with a contract;
# it is not allowed to disagree with CPython.
#
# Every contract must appear in TRUTH exactly once
# (`test_every_contract_has_a_truth_row`), which is the ratchet that matters
# here: a contract nobody probed is a contract nobody checked, and adding one
# without a row would otherwise be silent.

TRUTH: dict = {}


def _truth(name):
    """Register a probe as the truth row for one contract, and return it."""
    def deco(fn):
        TRUTH[name] = fn
        return fn
    return deco


def _low(text):
    return (text or "").lower()


def _missing(c, *markers):
    """Problems when the admission does not say what it has to say."""
    low = _low(c.assumes)
    if any(m.lower() in low for m in markers):
        return []
    return [f"{c.qualified}: the admission has to say "
            f"{' or '.join(repr(m) for m in markers)} — it is what the "
            f"measurement below turned on — and it says {c.assumes!r}"]


def _forbidden(c, *phrases):
    """Problems when the admission says something measured to be false."""
    low = _low(c.assumes)
    return [f"{c.qualified}: {c.assumes!r} says {p!r}, which is false of the "
            f"real host" for p in phrases if p.lower() in low]


# ── the probes, measured ──────────────────────────────────────────────────────

def _status_probes():
    """`(label, status)` over the ways a child's status can come out.

    Six rows and every one of them earns its place.  `0`, `3` and `255` are the
    ordinary answers, and `255` is the top of the range the old admission
    claimed, so a probe without it could not tell "the contract admits the whole
    range" from "it admits 0..3".  The three signals are the rows that make the
    answer NEGATIVE, and `SIGHUP` is in the table for a second reason: CPython
    reports a SIGHUP death as `-1`, which is the value the `popen_poll` model
    used to answer "not collected" with.
    """
    out = []
    for label, script in (("normal exit 0", "exit 0"),
                          ("normal exit 3", "exit 3"),
                          ("normal exit 255", "exit 255"),
                          ("SIGHUP", "kill -1 $$"),
                          ("SIGTERM", "kill -15 $$"),
                          ("SIGKILL", "kill -9 $$")):
        out.append((label, subprocess.run(["/bin/sh", "-c", script],
                                         capture_output=True).returncode))
    return out


def _status_probe_cache():
    global _STATUS_PROBES
    try:
        return _STATUS_PROBES
    except NameError:
        _STATUS_PROBES = _status_probes()
        return _STATUS_PROBES


def _status_uncovered(c, v):
    """Why `c`'s text does not admit the status word `v`, or ''."""
    if not re.search(r"0\.\.255", c.assumes):
        return ("CPython reports a normal exit status as the exit code itself, "
                "so the admission has to carry the `0..255` range")
    if v >= 0:
        return ""
    if re.search(r"-\s*N\b", c.assumes):
        return ""
    return (f"CPython reports a death by signal {-v} as the NEGATIVE word {v}, "
            f"which no `0..255` range admits")


@_truth("subprocess.run")
def _truth_run(c):
    return [_f for _l, v in _status_probe_cache()
            for _f in ([f"{c.qualified} [{_l}]: {_status_uncovered(c, v)}"]
                       if _status_uncovered(c, v) else [])]


@_truth("subprocess.call")
def _truth_call(c):
    bad = _truth_run(c)
    # `call` returns a failing child's status and raises nothing: the second half
    # of its admission, and the reason it is a separate contract from `run`.
    try:
        got = subprocess.call(["/bin/sh", "-c", "exit 7"])
        raised = None
    except BaseException as e:                             # noqa: BLE001
        got, raised = None, type(e).__name__
    if raised is not None:
        bad.append(f"{c.qualified}: CPython's `call` raised {raised} for a child "
                   f"that exited 7, so \"returned rather than raised\" is not "
                   f"what it does")
    elif got != 7:
        bad.append(f"{c.qualified}: CPython's `call` answered {got} for a child "
                   f"that exited 7, so the status word it returns is not the "
                   f"child's")
    bad += _missing(c, "returned rather than raised")
    return bad


@_truth("subprocess.check_call")
def _truth_check_call(c):
    """What CPython's `check_call` HANDS BACK, measured rather than remembered.

    The obvious answer is wrong on the toolchain this tree runs on: `check_call`
    does not return `None` and does not return the child's status either, it
    returns **0** on success and raises `CalledProcessError` otherwise (the
    `return 0` is in `subprocess.py`).  An admission that said "the child's exit
    status" therefore described a value no caller of CPython's `check_call` has
    ever received, which is why the row compares against the real return and not
    against an assumption about it.
    """
    bad = []
    got = subprocess.check_call(["/bin/sh", "-c", "exit 0"])
    if got != 0:
        bad.append(f"{c.qualified}: CPython's `check_call` returned {got!r} for "
                   f"a child that exited 0, so the admission's account of what "
                   f"CPython hands back is stale")
    try:
        subprocess.check_call(["/bin/sh", "-c", "exit 7"])
        raised = None
    except BaseException as e:                             # noqa: BLE001
        raised = type(e).__name__
    if raised != "CalledProcessError":
        bad.append(f"{c.qualified}: a non-zero status raised {raised or 'nothing'}, "
                   f"so the admission has to say the raise rather than imply a "
                   f"returned word")
    bad += _missing(c, "CalledProcessError")
    bad += _forbidden(c, "CPython returns nothing")
    bad += [_f for _l, v in _status_probe_cache()
            for _f in ([f"{c.qualified} [{_l}]: {_status_uncovered(c, v)}"]
                       if _status_uncovered(c, v) else [])]
    return bad


@_truth("subprocess.getstatusoutput")
def _truth_getstatusoutput(c):
    return [_f for _l, v in _status_probe_cache()
            for _f in ([f"{c.qualified} [{_l}]: {_status_uncovered(c, v)}"]
                       if _status_uncovered(c, v) else [])]


@_truth("subprocess.popen_wait")
def _truth_popen_wait(c):
    return [_f for _l, v in _status_probe_cache()
            for _f in ([f"{c.qualified} [{_l}]: {_status_uncovered(c, v)}"]
                       if _status_uncovered(c, v) else [])]


def _nul_in_output():
    """`(bytes, str)` for a child whose stdout contains a NUL, from CPython."""
    return subprocess.run(["/bin/sh", "-c", "printf 'a\\0b'"],
                          capture_output=True).stdout


@_truth("subprocess.check_output")
def _truth_check_output(c):
    out = _nul_in_output()
    bad = []
    if b"\0" not in out:
        bad.append(f"{c.qualified}: CPython's own answer came back as {out!r} "
                   f"with no NUL, so the probe is not measuring the case the "
                   f"admission is about")
    bad += _missing(c, "first NUL")
    return bad


@_truth("subprocess.getoutput")
def _truth_getoutput(c):
    out = subprocess.getoutput("printf 'a\\0b'")
    bad = []
    if "\0" not in out:
        bad.append(f"{c.qualified}: CPython's own answer came back as {out!r} "
                   f"with no NUL, so the probe is not measuring the case the "
                   f"admission is about")
    bad += _missing(c, "first NUL")
    return bad


@_truth("subprocess.popen_communicate")
def _truth_popen_communicate(c):
    """Two facts, both measured: the answer is a PAIR, and either half can hold a NUL."""
    p = subprocess.Popen(["/bin/sh", "-c", "printf 'x\\0y'"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    bad = []
    if b"\0" not in out:
        bad.append(f"{c.qualified}: CPython's own answer came back as {out!r} "
                   f"with no NUL, so the probe is not measuring the case the "
                   f"admission is about")
    if not isinstance(err, bytes):
        bad.append(f"{c.qualified}: `communicate` answered {err!r} for stderr, "
                   f"which is not the byte string the admission concatenates")
    bad += _missing(c, "first NUL", "pair")
    return bad


@_truth("subprocess.popen_poll")
def _truth_poll(c):
    """The sentinel must be a MODEL's choice and not an answer the host gives.

    Two halves, and both were false of the model this replaced.  CPython answers
    `None` while a child is running, so `-65` is a convention and has to be
    named as one; and `-1` is an answer CPython really gives (a SIGHUP death), so
    a sentinel equal to it would make two different situations one word.
    """
    bad = []
    p = subprocess.Popen(["/bin/sh", "-c", "sleep 0.5"])
    try:
        while_running = p.poll()
        bad += _missing(c, "None")
        if while_running is not None:
            bad.append(f"{c.qualified}: CPython's `poll()` answered "
                       f"{while_running!r} for a running child, so the sentinel "
                       f"is CPython's value rather than the model's own")
        sentinel = model_const("subprocess", "POLL_NOT_COLLECTED")
    finally:
        p.kill()
        p.wait()
    # Every status the host can produce, and the sentinel must not be one of them.
    for label, v in _status_probe_cache():
        if sentinel == v:
            bad.append(f"{c.qualified}: POLL_NOT_COLLECTED is {v}, which is "
                       f"exactly what CPython reports for [{label}] — the "
                       f"model's \"not collected\" marker has to be outside "
                       f"every answer the host can give")
    if f"-{abs(sentinel)}" not in c.assumes and str(sentinel) not in c.assumes:
        bad.append(f"{c.qualified}: the admission does not state the sentinel "
                   f"({sentinel}) it answers with, so the range a proof may "
                   f"assume is not the range the model uses")
    return bad


@_truth("subprocess.popen_kill")
def _truth_kill(c):
    return _truth_signal(c)


@_truth("subprocess.popen_terminate")
def _truth_terminate(c):
    return _truth_signal(c)


def _truth_signal(c):
    """Delivery is bounded by the child still running, and that is measured.

    `Popen.send_signal` calls `poll()` and RETURNS when the child has already
    been collected, so a `kill()` on a child this process waited for delivers
    nothing and raises nothing.  The evidence is CPython's own source rather than
    an inference about it: a test that asserted "no exception" would also pass on
    a host where the signal was delivered.
    """
    import inspect
    src = inspect.getsource(subprocess.Popen.send_signal)
    early = "returncode is not None" in src and "Skip signalling" in src
    bad = []
    p = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    p.wait()
    if p.returncode is None:
        return [f"{c.qualified}: the probe's child was not collected, so it is "
                f"not measuring the case the admission is about"]
    try:
        p.kill()
        raised = None
    except BaseException as e:                             # noqa: BLE001
        raised = type(e).__name__
    if raised is not None:
        bad.append(f"{c.qualified}: CPython's `kill()` on a collected child "
                   f"raised {raised}, so nothing here is bounded by the child "
                   f"still running")
    if not early:
        bad.append(f"{c.qualified}: CPython's `Popen.send_signal` no longer has "
                   f"the `returncode is not None` early return this row rests "
                   f"on, so re-measure whether a collected child is signalled "
                   f"before trusting the admission's bound")
    bad += _missing(c, "still running", "collected")
    return bad


@_truth("subprocess.Popen")
def _truth_pid(c):
    bad = []
    p = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    try:
        pid = p.pid
    finally:
        p.wait()
    if not (isinstance(pid, int) and pid > 0):
        bad.append(f"{c.qualified}: CPython reported the child's process id as "
                   f"{pid!r}, so \"a positive integer\" is not what it gives")
    if pid == os.getpid():
        bad.append(f"{c.qualified}: the id CPython reports is THIS process's "
                   f"own, so it is not the child's pid the admission claims")
    bad += _forbidden(c, "a negative integer")
    return bad


@_truth("ctypes.cdll_open")
def _truth_loader(c, tmpdir=None):
    """Handle 0 does NOT mean the library is absent, and this is the counterexample.

    The admission this replaces said "0, meaning no library of that name is on
    this target".  A file that EXISTS and is not a loadable image makes `dlopen`
    fail, so the implication is false on the host the tree runs on; the text now
    names the three reasons `dlopen` can fail instead.
    """
    import ctypes
    path = os.path.join(tmpdir or tempfile.gettempdir(), "admitted_truth.so")
    with open(path, "w") as f:
        f.write("not a Mach-O file at all\n")
    bad = _forbidden(c, "no library of that name", "meaning no library")
    try:
        ctypes.CDLL(path)
        failed = False
    except OSError:
        failed = True
    if not failed:
        bad.append(f"{c.qualified}: dlopen accepted a file that is not a "
                   f"library, so the probe is not measuring the case")
    bad += _missing(c, "dlopen")
    return bad


@_truth("ctypes.cdll_call")
def _truth_foreign(c):
    """\"One word\" is true of `ctypes`' default `restype` and of nothing else.

    Two measurements, because either alone is a half-answer: with the default
    `restype` CPython converts to `c_int`, which is a word, and with
    `restype = None` it returns `None`, which is not one.
    """
    import ctypes
    bad = []
    lib = ctypes.CDLL(None)
    default = lib.getpid()
    if not isinstance(default, int):
        bad.append(f"{c.qualified}: with the default restype CPython answered "
                   f"{default!r}, which is not a word either")
    lib.getpid.restype = None
    as_none = lib.getpid()
    if as_none is not None:
        bad.append(f"{c.qualified}: with `restype = None` CPython answered "
                   f"{as_none!r}, and the admission has to exclude that case "
                   f"rather than admit it")
    bad += _missing(c, "restype")
    return bad


@_truth("concurrent.futures.executor_submit")
def _truth_submit(c):
    """`ProcessPoolExecutor` runs the callable in a PROCESS, not on a thread.

    Measured by having the callable report its own pid: the whole reason the
    admission mentions processes is that this row can tell the two executors
    apart, and an admission that said \"some thread\" was claiming a thread for
    an executor that never makes one.
    """
    import concurrent.futures as CF
    bad = []
    try:
        with CF.ProcessPoolExecutor(max_workers=1) as pool:
            where = pool.submit(os.getpid).result(timeout=60)
    except Exception as e:                                 # noqa: BLE001
        return [f"{c.qualified}: a ProcessPoolExecutor could not be measured "
                f"({type(e).__name__}: {e}), so this row is not checking the "
                f"claim it exists for"]
    if where == os.getpid():
        bad.append(f"{c.qualified}: a ProcessPoolExecutor ran the callable in "
                   f"THIS process, so \"some process of this machine\" is not "
                   f"what it does either")
    bad += _missing(c, "process")
    return bad


@_truth("concurrent.futures.executor_shutdown")
def _truth_shutdown(c):
    """Quiescent means the pool's OWN workers, and this is the counterexample.

    A submitted callable that started its own thread had that thread still
    running when `shutdown(wait=True)` returned, because the pool joins the
    workers it started and nothing else.  \"Every thread the pool started\" was
    true under its narrowest reading and false under the reading a caller has.
    """
    import concurrent.futures as CF
    import threading as T
    started = T.Event()
    still_running = []

    def _inner():
        started.set()
        T.Event().wait(0.4)
        still_running.append(1)

    def _outer():
        th = T.Thread(target=_inner)
        th.start()
        return th

    with CF.ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(_outer).result(timeout=60)
    bad = []
    if not started.is_set():
        bad.append(f"{c.qualified}: the callable's own thread never started, so "
                   f"this row is not measuring the case the admission is about")
    if still_running:
        bad.append(f"{c.qualified}: `shutdown(wait=True)` waited for the thread "
                   f"a submitted callable started, so the admission's bound is "
                   f"not what was measured")
    bad += _missing(c, "OWN")
    return bad


@_truth("threading.thread_start")
def _truth_start(c):
    """`start()` returns when the callable has BEGUN, not when it has finished."""
    import threading as T
    import time
    done = []

    def _slow():
        time.sleep(0.4)
        done.append(1)

    th = T.Thread(target=_slow)
    th.start()
    bad = []
    if done:
        bad.append(f"{c.qualified}: the callable had finished when `start()` "
                   f"returned, so the row is not measuring the distinction")
    th.join()
    bad += _missing(c, "BEGUN")
    bad += _forbidden(c, "has run the target callable,")
    return bad


@_truth("threading.thread_join")
def _truth_join(c):
    """`join()` with no timeout returns after the callable has finished."""
    import threading as T
    import time
    done = []

    def _slow():
        time.sleep(0.2)
        done.append(1)

    th = T.Thread(target=_slow)
    th.start()
    th.join()
    bad = []
    if not done:
        bad.append(f"{c.qualified}: `join()` returned before the callable had "
                   f"finished, so \"the thread has stopped\" needs re-measuring")
    bad += _missing(c, "timeout")
    return bad


@_truth("threading.lock_acquire")
def _truth_lock(c, tmpdir=None):
    """A `threading.Lock` is not a kernel lock on a descriptor, and this is it.

    Two measurements.  The object has no `fileno` and no `_handle`, so there is
    no descriptor to hold; and a CHILD PROCESS took `flock(LOCK_EX)` on a file
    while this process held a `threading.Lock`, so the two do not exclude each
    other at all.  The admission this replaces said "the lock is held by the
    kernel on a descriptor".
    """
    import fcntl
    import threading as T
    bad = _forbidden(c, "the kernel on a descriptor")
    lk = T.Lock()
    if hasattr(lk, "fileno") or hasattr(lk, "_handle"):
        bad.append(f"{c.qualified}: this `threading.Lock` grew a descriptor "
                   f"({[a for a in ('fileno', '_handle') if hasattr(lk, a)]}), "
                   f"so re-measure before trusting the admission's wording")
    path = os.path.join(tmpdir or tempfile.gettempdir(), "admitted_truth.lock")
    with open(path, "w") as f:
        f.write("")
    lk.acquire()
    try:
        child = subprocess.run(
            [sys.executable, "-c",
             "import fcntl,sys\n"
             "fd = open(sys.argv[1], 'r+')\n"
             "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
             "print('taken')\n", path],
            capture_output=True, text=True, timeout=60)
    finally:
        lk.release()
    if "taken" not in child.stdout:
        bad.append(f"{c.qualified}: a child process could NOT take flock while "
                   f"this one held a threading.Lock ({child.stdout.strip()!r} "
                   f"{child.stderr.strip()[:120]!r}), so the two may interact "
                   f"and the admission needs re-measuring")
    bad += _missing(c, "THIS process", "this process")
    return bad


# The contracts whose probe needs a scratch file, so they are called with the
# run's temp directory rather than with a directory of their own.
TRUTH_NEEDS_TMPDIR = frozenset({"ctypes.cdll_open", "threading.lock_acquire"})


def test_every_contract_has_a_truth_row(tmpdir=None):
    """Every contract is probed, and every probe is a real function.

    Both directions, for the reason the count ratchet gives: a contract with no
    row is a claim of trust nobody checked, and a row with no contract is a probe
    that lost its subject and will keep passing after the admission it was
    written for is gone.
    """
    have = {c.qualified for c in A.all_contracts()}
    missing = sorted(have - set(TRUTH))
    extra = sorted(set(TRUTH) - have)
    check(not missing,
          "these admitted contracts have no truth row, so nothing in this file "
          "asks the real host whether they are true:\n    "
          + "\n    ".join(missing))
    check(not extra,
          "these truth rows name a contract that does not exist:\n    "
          + "\n    ".join(extra))
    bad = [f"{name}: {fn!r} is not callable"
           for name, fn in sorted(TRUTH.items()) if not callable(fn)]
    check(not bad, "a truth row is not a function:\n    " + "\n    ".join(bad))
    return True, (f"{len(TRUTH)} row(s) for {len(have)} contract(s), one each")


def group_truth(tmpdir, cas_root, verbose):
    """Every admitted contract, checked against CPython or the OS.

    The group that found the eight false admissions of 2026-10-04, and the one
    that keeps them from coming back: a contract whose text has to say `0..255`
    AND the `-N` of a signal death, a byte-string contract whose text has to say
    where the word stops, a poll sentinel that is not an answer the host gives.
    """
    cs = {c.qualified: c for c in A.all_contracts()}
    probes, bad = 0, []
    for name in sorted(TRUTH):
        c = cs.get(name)
        if c is None:
            continue
        probes += 1
        try:
            out = TRUTH[name](c, tmpdir) if name in TRUTH_NEEDS_TMPDIR \
                else TRUTH[name](c)
        except Exception as e:                             # noqa: BLE001
            bad.append(f"{name}: the probe itself failed — {type(e).__name__}: "
                       f"{e}")
            continue
        bad += [str(x) for x in (out or [])]
    # The refusal marker, whose claim was the most-read false statement in the
    # mechanism: 125 is inside 0..255, and no exit code is outside it.
    bad += _exit_status_claims()
    check(not bad,
          "an admitted contract does not say what the real host does:\n    "
          + "\n    ".join(bad))
    if verbose:
        for line in sorted(_status_probe_cache()):
            print(f"    a child that {line[0]:16s} is reported by CPython as "
                  f"{line[1]}")
    return True, (f"{probes} contract(s) checked against CPython/the OS; "
                  f"the refusal marker is RESERVED, not out of range")


# Words that make a sentence about `0..255` a CORRECTION rather than the claim.
# The mechanism needs them because the corrected text has to be able to QUOTE
# the false one — a ratchet that forbade the phrase outright would forbid the
# sentence that says it was wrong, which is the sentence a reader needs.
_CORRECTION_NEGATORS = ("not ", "no ", "never", "false", "earlier", "was",
                        "corrected", "instead", "rather", "inside")


def _exit_status_claims():
    """Problems with any hostmod's claim about what `ADMITTED_EXIT_STATUS` does.

    Read off the SOURCE window after the declaration, SENTENCE by sentence,
    because the thing being checked is a sentence rather than a substring.  The
    measurement: a child can exit 125 (`sh -c 'exit 125'` is reported as 125), so
    the status is INSIDE `0..255`; and no exit code can be outside it at all,
    because the kernel masks one (`sh -c 'exit 300'` is reported as 44).  A
    sentence that puts `outside` and `0..255` together without a word that makes
    it a correction is the false claim, whichever way it is punctuated.
    """
    bad = []
    for _rel, full in A.hostmod_files():
        with open(full, encoding="utf-8") as f:
            lines = f.read().split("\n")
        for i, line in enumerate(lines):
            if not re.match(r"\s*ADMITTED_EXIT_STATUS\s*=", line):
                continue
            window = "\n".join(lines[i:i + 14])
            low = _low(window)
            for sentence in re.split(r"(?<=[.;])\s+", window):
                slow = _low(sentence)
                if "outside" in slow and "0..255" in slow:
                    if not any(n in slow for n in _CORRECTION_NEGATORS):
                        bad.append(f"{os.path.relpath(full)}:{i + 1}: "
                                   f"{sentence.strip()!r} claims the refusal "
                                   f"status is outside 0..255. 125 is INSIDE it "
                                   f"(`sh -c 'exit 125'` is reported as 125) and "
                                   f"no exit code is outside it at all (`exit "
                                   f"300` is reported as 44), so the number "
                                   f"RESERVES rather than escapes and the "
                                   f"diagnostic on stdout is what says "
                                   f"\"refused\"")
            if "reserved" not in low:
                bad.append(f"{os.path.relpath(full)}:{i + 1}: does not say the "
                           f"status is RESERVED by this tree, which is what it "
                           f"is for now that it cannot be out of range")
            if "inside" not in low:
                bad.append(f"{os.path.relpath(full)}:{i + 1}: does not state "
                           f"that 125 is inside 0..255, so the measurement that "
                           f"corrected the claim is not next to it")
    return bad


# ── the Lean LIBRARY's own trust ──────────────────────────────────────────────
#
# `ADMITTED_COUNTS` above is the census of what this tree admits about the HOST.
# This is the census of what the hand-written library every generated proof rests
# on already trusts, and it was not counted anywhere: FORMAL.md §7's "no axiom and
# no opaque anywhere" is true of the SOURCE TEXT and not of a theorem's
# transitive closure, because `native_decide` and `bv_decide` close a goal
# through a generated axiom rather than through the kernel.
#
# **The axiom is not `Lean.ofReduceBool`, and the earlier version of this comment
# said it was.**  On the pinned 4.32.2 `ofReduceBool` is deprecated ("in-kernel
# native reduction is deprecated; assert native evaluations with axioms
# instead") and each USE of either tactic elaborates to a fresh axiom named after
# the declaration that used it — `work_step_mov._native.native_decide.ax_1_1`.
# Measured, with the before/after sets in `bugs/FORMAL_native_decide_axiom.md`.
# So `bugs/FORMAL_native_decide_axiom.md`'s "Expected output: …
# `Lean.ofReduceBool` appearing is the confirmation" would have read a library
# that reaches an axiom at every one of these sites as CLEAN, and the census
# below is what replaced it.  `formal/lean.py::GENERATED_AXIOM_RE` is the shape
# that is actually matched.


# transitive closure, because `native_decide` and `bv_decide` close a goal by
# running a decision procedure.
#
# **The axiom is not the one this file used to name.**  Lean 4.32.2 gives each
# use its OWN axiom — `t32s_t8s._native.bv_decide.ax_1_5` — and
# `#print axioms` over all 375 theorems in `lib/` reports `Lean.ofReduceBool`
# for NONE of them; measured, in `AXIOM_CLOSURE` below and by
# `test_the_closure_census_says_what_the_text_census_cannot`.  A reader grepping
# a proof's axiom list for `Lean.ofReduceBool` finds nothing and concludes the
# proof is kernel-checked, which is how a wrong name becomes a wrong conclusion.
#
# The first two rows are equalities and the third is a CEILING, and the asymmetry
# is the point rather than an inconsistency.  An `axiom` or a `sorry` appearing
# in `lib/` is a NEW EVENT — there are none, FORMAL.md §7's position depends on
# there being none, and nothing in this tree is working to add one.  A tactic
# site count is a DEBT being paid down, in a file several branches edit at once,
# so pinning it as an equality would turn every unrelated merge into a failure
# while teaching nobody anything; a ceiling fails when the number RISES, which is
# the direction that matters, and reports the figure on every run so the debt is
# visible while it is being paid.
#
# **The figure is 707 on this tree, and it is a LEDGER rather than a sum.**
# `FORMAL.md` §7 row 10 publishes total **770**, replaced **63**, remaining
# **707**: 751 sites when the pay-down started, 63 of them replaced, and **19
# that arrived afterwards** with `lib/IEEE754.lean` — the binary64 arithmetic
# theorems, which `NATIVE_DECIDE_ALLOWED` names with the measured reason that
# `decide` cannot reduce `Float.ofBits`. A total that can only fall cannot
# record new debt, and a ledger that cannot record new debt is a number nobody
# can re-derive, which is what this test exists to stop. The four `X86` sites
# this commit removed were four of the 707 rather than four of the 688 the row
# used to publish, which is the whole difference between an honest ledger and a
# stale one.
#
# **The 63 that went** are named in `NATIVE_DECIDE_REPLACED` below rather than
# only in a commit message.  All 63 were CLOSED propositions over literals — `¬
# (0xd65f03c0 && & 0xffe00000 = 0x2a00fa00)`, `(1 : UInt64).toNat = 1` — which
# `decide` discharges in microseconds and the KERNEL checks; `native_decide` was
# compiling a decision procedure to C and asserting the result, which on this
# toolchain means a generated axiom per use rather than `Lean.ofReduceBool`.
# **What is left is 1518 in `ProofLib`, 3 in `X86` (the `∀ w, …`
# bit-pattern lemmas, which is the right tool), 19 in `IEEE754` and none in
# `Contracts`/`Refine`/`work` — per-module figures, all `native_decide`/
# `bv_decide` together** — **1540, not the 749 this table pinned until
# 2026-10-04.** The 22 `native_decide` that evaluate a ground binary64 value are
# inside the 19 `IEEE754` sites plus the three named ones in `NATIVE_DECIDE_ALLOWED`.
#
# TWO upward movements, and they are not the same kind of movement, which is the
# reason both are written down rather than just the total:
#
#   * **+2, the instrument got better** (2026-10-04). The census's own scanner
#     mis-read an identifier's apostrophe as a character literal and hid two
#     sites — see `lean_code_regions`. A ceiling going UP because the instrument
#     can see more is not a regression.
#   * **+833, real debt ARRIVED** (2026-10-05, this merge). `work/formal28-2`
#     modelled arm64's twelve narrower/unscaled memory forms and its two
#     flag-setting compares, and each new `arm64_step` arm carries its own
#     `work_step_*` lemma proved by `bv_decide` over a quantified word — which
#     is the right tool for that shape and still an axiom in the closure of
#     every theorem proved with it. `lib/ProofLib.lean` went from 697 lines
#     mentioning a decide tactic to 1545.
#
# The second is the one this ledger exists to make visible, and the branch that
# landed it did not move the total: the pay-down identity
# `total - remaining == replaced` still holds (1540 + 67 = 1607), but only
# because the arrivals are counted in `total`. A ledger that recorded the
# arrivals as new debt is what makes the number trustworthy; one that let the
# ceiling sit at 685 while the tree carried 1518 is what this row is. The
# pay-down itself has moved in NOBODY's favour: `NATIVE_DECIDE_REPLACED` is
# still 67 and `REPLACEABLE_THEOREMS` is still 0.
LIBRARY_TRUST = {
    # module    axiom  sorry  axiom_tactic ceiling (see the note above)
    "Contracts": (0, 0, 0, 0),
    # The two casualties of the apostrophe fix, measured, because they are what
    # makes the earlier 749 an UNDERCOUNT rather than a total: the `'` in
    # `clang's` at `lib/ProofLib.lean:1392` was read as a character-literal
    # opener and blanked 187 lines of real code — including the `bv_decide` in
    # `t32s_t8s` (:1579) and the one in `t32s_t16s` (:1582) — and five
    # declarations whose names end in `'` (`mem_read_two_writes_adjacent'`,
    # `mem_read_after_write_u64_slot'`, `u64_toNat_sub_one'`,
    # `MF.fieldTag_inj'`, `work.s64_to_u64_toNat'`) were invisible to any
    # per-theorem census until the fix.  A ceiling going UP because the
    # instrument got better is the one movement of it that is not a regression.
    # What is pinned here is the figure AFTER the 63 replacements, so `Contracts`
    # is 0 rather than the 1 this table held while its single site was still a
    # `native_decide`.
    "ProofLib": (0, 0, 1518, 1518),
    "Refine": (0, 0, 0, 0),
    # **3, and it was 3 before this commit read 7**: four `native_decide` sites
    # landed here (`@[simp] theorem x86_mask_{one,two,four,eight}`, all four on
    # four lines at `lib/X86.lean:503..506`) without the ceiling moving, which is
    # how a gate job goes red for a reason nobody wrote down.  All four were
    # CLOSED facts over literals — `x86_mask 1 = 0xff` and its three siblings —
    # and `decide` discharges them with the KERNEL checking the answer, so they
    # are gone and this row is a measurement again.  The 3 that remain are the
    # `bv_decide` bit-pattern lemmas at `:2946`, `:2948` and `:2970`.
    "X86": (0, 0, 3, 3),
    "work": (0, 0, 0, 0),
    # The binary64 semantics, added 2026-10-04 with `lib/IEEE754.lean`.  Zero
    # `sorry` and zero `axiom` is the load-bearing column and it is the whole
    # reason this module is separate from `ProofLib.lean`: the COMPARISONS are
    # `UInt64`/`Bool` functions and every theorem about them is closed under
    # `decide`, which is why they can be counted at 0 axiom-tactic sites.  The
    # fourth column is a CEILING and not a measurement because the arithmetic
    # theorems are `native_decide` over ground values and the number of them is
    # whatever the next person adds — raise it in the same commit as the theorem
    # rather than letting it fail, which is what a ceiling is for.
    # The 19 is a MEASUREMENT and not a guess: it is `AXIOM_CLOSURE`'s `reaches`
    # column for this module, read out of a real `#print axioms` run over all 24
    # of its declarations.  The 5 that are kernel-checked are the comparison
    # section, which is `UInt64`/`Bool` only — the split between the two halves
    # of this module is the finding, and it is why the arithmetic's cost is
    # bounded while the comparisons' is zero.
    "IEEE754": (0, 0, 19, 19),
    # `lib/Peephole.lean`, added 2026-10-05: the three peephole rules
    # `formal/peephole.py` may perform, each proved against the machine
    # model with its side conditions stated. `0` in the axiom column is
    # the point of the module — the rules reason about `Arm64State`
    # with `omega` and `bv_decide` and reach no axiom, so a rewrite the
    # pass performs is one whose soundness does not rest on a decision
    # procedure's fidelity. Nine `bv_decide` sites, no `sorry`.
    "Peephole": (0, 0, 9, 9),
    # `lib/Specs.lean`, added 2026-10-05: the INDEPENDENT specification layer
    # (reference definitions for the classic example programs, written by hand
    # in `Nat`/`Int`/`List`).  Zero at 0 and zero at 1, and the zero at column 2
    # is a MEASUREMENT rather than an absence of measurement: every theorem in
    # it is closed under `decide`/`omega`/`rfl`, which is what a specification
    # layer can afford to be — a spec whose own proof needed a reflection axiom
    # would be resting on the same unverified evaluation the layer exists to
    # check.  `AXIOM_CLOSURE`'s row below is what decided that, read out of a
    # real `#print axioms` run over all 55 declarations.
    "Specs": (0, 0, 0, 0),
}

#: What the CLOSURE census measured, per module: how many theorems were asked,
#: how many reached a decide axiom, and the two disagreements with the text
#: census. Read out of a real `#print axioms` run over all of `lib/` through
#: `formal/admitted.py::theorem_axiom_census`, and pinned because the number §7
#: publishes is this one and there was nothing measuring it. **All 520 answered**
#: but one — `ProofLib.ifUpdate_congr`, the `private theorem` at
#: `lib/ProofLib.lean:7364`, whose name Lean mangles and which carries no tactic
#: site (checked, not assumed) — and the four columns partition each module
#: exactly, which is asserted rather than hoped for: an unanswered theorem is
#: counted in none of them.
#:
#: `reaches` is the honest fact: of the theorems in `lib/`, **81** rest on a
#: decide axiom and the rest are kernel-checked. `text_only` are theorems whose
#: source names one of the tactics and whose closure has none — a losing tactic
#: alternative is still text, so the site census overcounts, and each row is a
#: place where a replacement would have changed nothing. `closure_only` are
#: theorems whose source names none and whose closure has one, because they
#: reach it THROUGH another theorem: the site census cannot see these at all, and
#: they are the argument for measuring the closure rather than the text. The
#: clearest is `ProofLib.arm64_cset_{eq,le,lt_s,ne}`, which carry
#: `arm64_flag_eq._native.bv_decide.ax_1_N` through it and name no tactic.
#:
#: **Every figure in this table moved on 2026-10-04, and both instruments that
#: produced it were wrong first.** `AXIOM_SITE_RE`'s declaration group was
#: `[^.]+`, so a NAMESPACED declaration's axiom read as "not one of ours" and
#: `IEEE754` measured `reaches 0 / text_only 19` — the opposite of the truth; and
#: `library_theorems` carried its own declaration-head pattern with no `@[...]`
#: prefix, so 98 attributed declarations were never asked about at all (31 in
#: `ProofLib`, 66 in `X86`, 1 in `work`) and every one of them was filed as
#: `clean`. The old numbers were `375 asked / 53 reaches` over five modules, and
#: the module set was missing `IEEE754` entirely. See
#: `bugs/FORMAL_native_decide_axiom.md`.
#:
#: `of_reduce_bool` is 0 everywhere, and is the row that corrects the name.
#:
#: **A SEPARATE table from `LIBRARY_TRUST` above, and the separation is the
#: point**: that one counts SITES in the source text and is a ceiling somebody
#: pays down, this one counts THEOREMS by what their proof term actually reaches
#: and is a measurement nothing can move without a Lean run. The merge of the two
#: into one dict would make a site count and a theorem count differ by a row
#: rather than by a table, which is how a reader ends up comparing them.
#:
#: **The whole table was re-derived on 2026-10-04 and the previous one was wrong
#: in a DIRECTION, not only out of date.**  `AXIOM_SITE_RE`'s `decl` group was
#: `[^.]+`, which cannot match a namespace-qualified declaration name — and five
#: of the six `lib/` modules open a `namespace`, so Lean's per-use axiom name for
#: every theorem inside one is `DylibExport.Semantics_refutable._native.…`,
#: which that pattern rejected.  Every such theorem was therefore filed
#: `text_only` ("its source names a tactic and its closure reaches none"), which
#: is the one column whose purpose is to catch a closure the census cannot see.
#: Consequences, all now corrected: `IEEE754` read `reaches 0` for 19 theorems
#: that each carry their own `native_decide` axiom — while the comment on
#: `LIBRARY_TRUST`'s IEEE754 row above asserted this very column said 19 — and
#: `ProofLib`'s three `DylibExport` `native_decide` theorems were `text_only`.
#: The fix is `AXIOM_SITE_RE`'s and is pinned by qualified-spelling samples in
#: `test_the_axiom_names_are_classified_not_guessed`.
AXIOM_CLOSURE = {
    #            asked  reaches  clean  text_only  closure_only  ofReduceBool
    "Contracts": (7, 0, 7, 0, 0, 0),
    # +14 asked and +14 reaching, and it is the SAME arrival `LIBRARY_TRUST`'s
    # ceiling above records: arm64's twelve narrower/unscaled memory forms and
    # its two flag-setting compares each add a `work_step_*` lemma proved by
    # `bv_decide`, so 14 new declarations reach an axiom and `clean` does not
    # move at all. The partition still closes exactly (311 = 60 + 243 + 0 + 8),
    # which is the assertion that makes this a measurement rather than a number
    # somebody typed.
    "ProofLib": (311, 60, 243, 0, 8, 0),
    "Refine": (29, 0, 29, 0, 0, 0),
    "X86": (144, 2, 141, 0, 1, 0),
    "work": (19, 0, 17, 0, 2, 0),
    # Read out of a real `#print axioms` run over all 24 declarations of
    # `lib/IEEE754.lean`, on the pinned toolchain.  19 reach a decide axiom and
    # 5 are kernel-checked, and the 5 are exactly the COMPARISON section — the
    # half that is `UInt64`/`Bool` and therefore closed under `decide`.  Zero
    # `text_only` and zero `closure_only` because every `native_decide` site is
    # also in its own closure and no theorem reaches an axiom through another
    # one, which is the opposite of `ProofLib`'s `arm64_cset_*` row and is
    # recorded as a contrast rather than left for a reader to infer.
    #
    # **This row is the one the regex defect was hiding**, and it is why the
    # numbers above are re-measured rather than adjusted: the whole of
    # `lib/IEEE754.lean` is inside `namespace IEEE754` (lines 49-415), so all 24
    # of its axiom names are module-qualified and none of them matched
    # `[^.]+`.  It read `reaches 0 / text_only 19` and the comment on
    # `LIBRARY_TRUST`'s IEEE754 row — which says this column is where the 19
    # comes from — was describing a measurement the code could not make. The fix
    # is `AXIOM_SITE_RE`'s and is pinned by qualified-spelling samples in
    # `test_the_axiom_names_are_classified_not_guessed`; `library_theorems` had
    # the mirror defect, carrying its own declaration-head pattern with no `@[...]`
    # prefix, so 98 attributed declarations were never asked about at all.
    "IEEE754": (24, 19, 5, 0, 0, 0),
    # All 55 declarations of `lib/Specs.lean` answered, none reaching a decide
    # axiom, none dropped as `private`, and no `of_reduce_bool`.  Read out of
    # `formal/admitted.py::theorem_axiom_census(..., modules=['Specs'])` on the
    # pinned toolchain — which is the same instrument the five rows above were
    # read out of, so the comparison is like for like.
    "Specs": (55, 0, 55, 0, 0, 0),
}


# The three `native_decide` sites left in `lib/`, each with the reason it cannot
# be a `decide`.
#
# This table is a RATCHET in the same direction `LIBRARY_TRUST` is, and it is
# tighter than that one in the way that matters: `LIBRARY_TRUST` is a per-MODULE
# ceiling, so it would take 685 new `native_decide` sites to notice anything, and
# every one of them could be a closed fact `decide` closes in microseconds.  This
# one says WHICH DECLARATION may carry one, so a `native_decide` added anywhere
# else — including to one of the 43 declarations that used to carry several and
# now carry none — fails by name.
#
# All three are in `namespace DylibExport` and all three evaluate the machine
# model at a GROUND image: `runExport … = none` with a concrete `DylibImage`, and
# `InImage` over one.  That is the one shape `decide` cannot take, because the
# decision is `arm64_step`'s whole decode chain over a `Arm64State`, and the
# kernel has to reduce it; `decide` would be correct and enormously slower than
# the compiled path.  The three file's own docstrings say so at 5587 (`it cannot
# decide with `n` free`, i.e. what is wanted here is that it CAN).
NATIVE_DECIDE_ALLOWED = {
    "ProofLib": {
        "DylibExport.Semantics_refutable":
            "`runExport` over the empty 0-byte image is `none`; the goal is "
            "one `arm64_step` over a ground `Arm64State`, which `decide` would "
            "have to reduce in the kernel.",
        "DylibExport.backward_branch_in_image":
            "`InImage backward_branch_image backward_branch_export` is a "
            "decidable test over a ground export table.",
        "DylibExport.backward_branch_run_none":
            "`runExport backward_branch_image … 0 = none`, and the file's own "
            "docstring (5587) records that this is the ground case "
            "`native_decide` is there for.",
    },
    # The binary64 ARITHMETIC theorems, 19 of them, and the reason is a
    # measurement rather than a preference: `Float.ofBits` and `Float.toBits`
    # are COMPILED PRIMITIVES, so `decide` cannot reduce them.  Measured on
    # `lib/IEEE754.lean` before this row existed: `decide` on
    # `Float.toBits (Float.ofBits p) = p` gets stuck at the `UInt64.decEq`
    # instance and reports "reduction got stuck", while the same proposition
    # closes under `native_decide`.  So the alternatives were a `decide` that
    # does not run, or a from-scratch bit-level IEEE implementation to have
    # something decidable to check — a second implementation of arithmetic both
    # machines already perform, with its own rounding bugs.
    #
    # They are all GROUND VALUES and that is what keeps the count at 19 rather
    # than at a number nobody can bound: `AXIOM_CLOSURE`'s IEEE754 row is the
    # measured per-theorem split (24 asked, 19 reach a decide axiom, 5
    # kernel-checked — the 5 are the pure `UInt64`/`Bool` COMPARISONS, which is
    # why the comparisons are modelled bit-level and the arithmetic is not).
    "IEEE754": {
        "IEEE754." + name: (
            "a ground binary64 value statement over `Float.ofBits`/`toBits`, "
            "which `decide` cannot reduce because they are compiled primitives "
            "(measured on this file); the kernel-checkable half of the model is "
            "the COMPARISON section, which is `UInt64`/`Bool` only"
        )
        for name in (
            "ofBits_toBits_normalises_a_nan_payload",
            "ofBits_toBits_round_trips_the_zeroes_and_the_ordinaries",
            "signed_zeros_are_equal",
            "the_two_zeros_are_equal_and_neither_orders",
            "a_nan_is_not_equal_to_itself",
            "negative_zero_plus_negative_zero_is_negative_zero",
            "negative_zero_plus_positive_zero_is_positive_zero",
            "additive_identity_on_an_ordinary",
            "one_and_a_half_plus_two_and_a_quarter",
            "a_tenth_plus_a_fifth_rounds",
            "zero_over_zero_is_a_nan",
            "one_over_zero_is_an_infinity",
            "overflow_is_an_infinity",
            "underflow_is_a_subnormal",
            "fneg_of_positive_zero_is_negative_zero",
            "fneg_is_an_involution",
            "fromIntBits_of_2_pow_53_plus_1",
            "fromIntBits_of_a_tie_rounds_up",
            "fromIntBits_agrees_with_the_machine_on_a_tie",
        )
    },
}


# What the 67 replaced sites were, in ONE place, so the ceiling's fall is
# attributable rather than merely smaller.  A number with no list is the failure
# mode `tools/suite.py`'s count-checked `expect=` markers were built against.
#
# Both halves are the same shape and the same fix: `decide` for a bit-pattern
# fact over `UInt32` literals (61 of 63), `rfl` for `(1 : UInt64).toNat = 1` and
# its `2` sibling, which are definitional and which `decide` also closes — `rfl`
# because it reaches NO axiom at all where `decide` reaches `propext` and
# `Quot.sound`.  Measured per shape in `bugs/FORMAL_native_decide_axiom.md`.
NATIVE_DECIDE_REPLACED = {
    "ProofLib": 61,      # 34 `absurd h`, 17 `absurd t`, 3 `absurd h_opc`,
                         # 5 closed `have`s, 2 `.toNat` facts
    "Contracts": 1,      # `spec_triple_ne_identity`: `¬ (n * 3) 7 = 7`
    "X86": 5,            # `lowMask_eight`: eight `|||`/`<<<` on `UInt64`; and
                         # `x86_mask_{one,two,four,eight}` (`lib/X86.lean:503..506`),
                         # the four `native_decide` that landed here without the
                         # ceiling moving and made this file red on 2026-10-04.
                         # `x86_mask n` is `if n ≥ 8 then … else UInt64.ofNat
                         # (2^(8n) - 1)` over a LITERAL argument, so `decide`
                         # discharges all four and `#print axioms` answers "does
                         # not depend on any axioms" for each — not even
                         # `propext`/`Quot.sound`. They were worth FIVE theorems
                         # and four sites: `x86_step_movsx_r64_r8` reached
                         # `x86_mask_eight`'s axiom through it and is
                         # kernel-checked now that the theorem is
    # No `IEEE754` row, and the omission is the finding rather than an oversight:
    # its 19 `native_decide` sites are ground binary64 facts over `Float.ofBits`
    # / `Float.toBits`, which are COMPILED PRIMITIVES, so `decide` cannot reduce
    # them (measured: "reduction got stuck"). They are debt that ARRIVED, named
    # one by one in `NATIVE_DECIDE_ALLOWED`, and they are the reason §7 row 10's
    # total is 770 rather than 751.
}


# The text each contract carried BEFORE the audit of 2026-10-04, for the
# eighteen it changed, and the point of keeping them HERE rather than in a bug
# doc: an instrument that has only ever agreed with the tree proves nothing.  Each
# row is the pre-audit sentence, and each must make its own probe complain — so a
# future rewrite of a contract, or of a probe, that quietly stops testing what it
# was written for fails this check rather than passing silently.
#
# `subprocess.Popen` is absent on purpose: "the child's process id, a positive
# integer" is the one contract the audit found TRUE, and a row asserting a
# complaint about it would be asserting something false about the toolchain.
PRE_AUDIT_TEXT = {
    "concurrent.futures.executor_shutdown":
        "every thread the pool started has stopped by the time this returns",
    "concurrent.futures.executor_submit":
        "the submitted callable runs on some thread and its result is one word, "
        "and nothing is assumed about which or when",
    "ctypes.cdll_call":
        "the value the foreign function returns is one word, and nothing is "
        "assumed about which value it is",
    "ctypes.cdll_open":
        "the loader handle is 0, meaning no library of that name is on this "
        "target, or a non-zero word this target's dynamic loader owns",
    "subprocess.call":
        "the child's exit status, an integer in 0..255, and nothing is raised "
        "for a non-zero status",
    "subprocess.check_call":
        "the child's exit status, an integer in 0..255",
    "subprocess.check_output":
        "the child's output on stdout, an arbitrary byte string",
    "subprocess.getoutput":
        "the child's output on stdout, an arbitrary byte string",
    "subprocess.getstatusoutput":
        "the shell command's exit status, an integer in 0..255, and its output "
        "is an arbitrary byte string",
    "subprocess.popen_communicate":
        "the child's output on stdout and stderr, an arbitrary byte string",
    "subprocess.popen_kill":
        "the signal reaches the child this handle names",
    "subprocess.popen_poll":
        "the child's exit status word, an integer in 0..255, and -1 while the "
        "child has not been collected",
    "subprocess.popen_terminate":
        "the signal reaches the child this handle names",
    "subprocess.popen_wait":
        "the child's exit status, an integer in 0..255",
    "subprocess.run":
        "the child's exit status, an integer in 0..255, and the captured output "
        "bytes are an arbitrary byte string",
    "threading.lock_acquire":
        "the lock is held by the kernel on a descriptor, and whether it is "
        "granted depends on every other holder",
    "threading.thread_join":
        "the thread has stopped, and nothing is assumed about what it computed",
    "threading.thread_start":
        "the thread exists and has run the target callable, and nothing is "
        "assumed about what the callable computed or when",
}


def test_the_truth_probes_reject_the_pre_audit_text(tmpdir=None):
    """Every probe still rejects the claim the audit found false.

    The direction that keeps the `truth` group honest.  A checker that only ever
    passes is indistinguishable from no checker, and this file's own history is
    the argument: the contracts were SCOPED, COUNTED, EMITTED and inert where
    they did not apply for a long time while fifteen of them were false of the
    host.  So each pre-audit sentence goes back through its own probe, and a
    probe that stopped complaining about the text it was written for is the
    failure this asserts on.
    """
    live = {c.qualified for c in A.all_contracts()}
    stale = sorted(set(PRE_AUDIT_TEXT) - live)
    check(not stale,
          "PRE_AUDIT_TEXT names contracts that no longer exist:\n    "
          + "\n    ".join(stale)
          + "\n    A row about a contract that is gone tests nothing.")
    quiet = []
    for name in sorted(PRE_AUDIT_TEXT):
        if name not in live or name not in TRUTH:
            continue
        # `rsplit`, not `split`: `concurrent.futures.executor_submit` is a
        # DOTTED module name, and splitting on the first dot would build a
        # contract whose own `qualified` says `concurrent.submit` -- a different
        # name from the key, so every message it produced would name something
        # that does not exist.
        module, _, fn = name.rpartition(".")
        c = A.Contract(module, fn, PRE_AUDIT_TEXT[name], "<pre-audit>", 0)
        try:
            out = TRUTH[name](c, tmpdir) if name in TRUTH_NEEDS_TMPDIR \
                else TRUTH[name](c)
        except Exception as e:                             # noqa: BLE001
            quiet.append(f"{name}: the probe raised {type(e).__name__}: {e}")
            continue
        if not out:
            quiet.append(f"{name}: the probe accepts the pre-audit text "
                         f"{PRE_AUDIT_TEXT[name]!r}, so it is not testing the "
                         f"thing it was written for")
    check(not quiet,
          "a truth probe no longer rejects the claim it was written to reject:\n    "
          + "\n    ".join(quiet))
    unchanged = sorted(live - set(PRE_AUDIT_TEXT))
    return True, (f"{len(PRE_AUDIT_TEXT)} pre-audit sentence(s) all rejected "
                  f"by their own probe; {len(unchanged)} contract(s) audited "
                  f"and left as they were ({unchanged})")


def test_every_contract_points_at_its_own_declaration(tmpdir=None):
    """`Contract.line` is the line the assumption is ON, verified against the text.

    The audit found this broken: `fire_compiler.py` builds its top-level
    `FunctionDef` without `line=`, so `getattr(st, "line", 0) + 1` was 1 for every
    contract in every module, and all nineteen `trust:` lines and all nineteen
    generated Lean docstrings pointed a reader at line 1 of the module — the
    module docstring.  A `source:line` that is always `:1` is worse than none,
    because it looks like a location.

    Both halves are checked against the file rather than against the reader that
    produced it: the line named must be an `@admitted(` line, and the `def` it
    decorates must be the one this contract declares.  A line that drifts to the
    next contract's decorator would satisfy the first check alone.
    """
    bad = []
    for c in A.all_contracts():
        try:
            with open(c.source, encoding="utf-8") as f:
                lines = f.read().split("\n")
        except OSError as e:
            bad.append(f"{c.qualified}: cannot read {c.source}: {e}")
            continue
        if not (0 < c.line <= len(lines)):
            bad.append(f"{c.qualified}: line {c.line} is not inside "
                       f"{os.path.relpath(c.source, HERE)} ({len(lines)} lines)")
            continue
        here = lines[c.line - 1].strip()
        nxt = lines[c.line].strip() if c.line < len(lines) else ""
        if not here.startswith("@" + A.ADMITTED_DECORATOR + "("):
            bad.append(f"{c.qualified}: {os.path.relpath(c.source, HERE)}:"
                       f"{c.line} is {here[:50]!r}, not an `@admitted(` line")
        elif not nxt.startswith("def " + c.name):
            bad.append(f"{c.qualified}: "
                       f"{os.path.relpath(c.source, HERE)}:{c.line} is followed "
                       f"by {nxt[:50]!r}, so the line points at another "
                       f"contract's assumption")
    check(not bad, "an admitted contract's location does not name its own "
                   "declaration:\n    " + "\n    ".join(bad))
    return True, (f"{len(A.all_contracts())} contract(s), each pointing at its "
                  f"own `@admitted(` line")


def check_the_stripper_sees_every_declaration(mod, raw):
    """No declaration header at the start of a line may be BLANKED by the stripper.

    `lean_code_regions` is what makes the census a census — it removes comments
    and string contents so a count is of code and not of prose — and a stripper
    that removes CODE is worse than no stripper, because every number downstream
    is then quietly short.  That happened, and the instrument's own arithmetic
    could not see it: reading an identifier's apostrophe (`fieldTag_inj'`, and
    about forty more in `lib/`) as the opening of a `Char` literal blanks
    everything to the next apostrophe in the FILE, which lands inside an
    unrelated docstring, and from there the scanner is inside a string it
    invented.  Measured on `lib/` before the fix: **74 declaration headers that
    start at the beginning of a line were blanked as if they were prose** — 62 in
    `ProofLib`, 11 in `Refine`, 1 in `Contracts` — among them
    `private def stmtsSize` and the `end` that closes a `mutual`, and the
    `axiom_tactic` count was 749 where it is 751.

    A column-0 declaration header cannot be inside a comment in practice — `-`
    and `/-` are not identifier characters, so the only way is a `/-! -/` block
    whose interior happens to start at column 0 — and where it does happen this
    reports it by name rather than absorbing it, because "the scanner hides real
    code" is the claim this file exists to make impossible.
    """
    stripped = A.lean_code_regions(raw).split("\n")
    raw_lines = raw.split("\n")
    lost = [i + 1 for i, line in enumerate(raw_lines)
            if _DECL_HEADER_RE.match(line) and not _DECL_HEADER_RE.match(stripped[i])]
    check(not lost,
          f"lib/{mod}.lean: the comment/string stripper blanked "
          f"{len(lost)} declaration header(s) that start at the beginning of a "
          f"line — at {lost[:10]} — so `lean_code_regions` is inside a comment "
          f"or a string literal it invented and the census above is an "
          f"under-count:\n    "
          + "\n    ".join(f"{ln}: {raw_lines[ln - 1].strip()[:70]}"
                          for ln in lost[:6]))


# A declaration header at the start of a line: the attributes and modifiers that
# may precede it, then the keyword and whitespace.  `A._DECL_RE` is the same
# shape; this one is anchored so it can be applied line by line, which is what
# the stripper comparison needs.
_DECL_HEADER_RE = re.compile(
    r"^(?:@\[[^\]\n]*\][ \t]*(?:\n|\Z))?"
    r"(?:private\s+|protected\s+|noncomputable\s+)*"
    r"(?:theorem|lemma|def|abbrev|instance|example)\s")


def test_the_library_trust_counts_are_pinned(tmpdir=None):
    """`lib/`: no `axiom`, no `sorry`, and an axiom-carrying tactic count.

    The Lean half of the audit of 2026-10-04, and the assertion that makes §7's
    position checkable rather than asserted: this tree's stated trust boundary is
    "no `axiom` and no `opaque` anywhere, everything assumed in the `sorry`
    sense", and two of those three words are decided by a text census.
    """
    lib = A.lean_dir(HERE)
    census = A.library_trust(lib)
    got = sorted(census)
    want = sorted(LIBRARY_TRUST)
    check(got == want,
          f"lib/ modules {got} and the pinned table {want} disagree — add the "
          f"module with its counts, or delete the row for one that is gone")
    grown, shrank, errors = [], [], []
    for mod in want:
        if mod not in census:
            continue
        want_axiom, want_sorry, _have, ceiling = LIBRARY_TRUST[mod]
        kinds = census[mod]
        got_axiom, axiom_lines = kinds["axiom"]
        got_sorry, sorry_lines = kinds["sorry"]
        got_tactic, tactic_lines = kinds["axiom_tactic"]
        if got_axiom != want_axiom:
            errors.append(f"{mod}: {got_axiom} axiom/opaque declaration(s) at "
                          f"{list(axiom_lines)}, the table says {want_axiom}. "
                          f"An `axiom` in `lib/` is invisible to the hole census, "
                          f"which is the entire reason FORMAL.md §7 forbids "
                          f"them.")
        if got_sorry != want_sorry:
            errors.append(f"{mod}: {got_sorry} `sorry` site(s) at "
                          f"{list(sorry_lines)}, the table says {want_sorry}. "
                          f"`formal/lean.py`'s census measures the elaborated "
                          f"form of this; a text count that disagrees with it is "
                          f"a scanner that has stopped being honest.")
        if got_tactic > ceiling:
            grown.append(f"{mod}: {got_tactic} native_decide/bv_decide site(s), "
                         f"the ceiling is {ceiling} (+{got_tactic - ceiling}). "
                         f"Each one is an axiom in the transitive closure of "
                         f"every theorem proved with it "
                         f"(bugs/FORMAL_native_decide_axiom.md).")
        elif got_tactic < ceiling:
            shrank.append(f"{mod}: {got_tactic} native_decide/bv_decide site(s) "
                          f"and the ceiling says {ceiling}. Sites were replaced "
                          f"by kernel-checked proofs, which is the BEST outcome "
                          f"here: lower the ceiling with the change and say in "
                          f"the commit which ones.")
    check(not errors,
          "the Lean library's trust census moved in a way that is not a debt "
          "being paid:\n    " + "\n    ".join(errors))
    check(not grown and not shrank,
          "the axiom-carrying tactic count moved:\n  MORE THAN THE CEILING:\n    "
          + "\n    ".join(grown) + "\n  FEWER THAN THE CEILING:\n    "
          + "\n    ".join(shrank))
    # The scanner's own limits, asserted rather than assumed: the delimiter it
    # does not handle, the axiom-carrying tactic it would not count, and — the
    # one that was WRONG until 2026-10-04 — how much of the file it is looking
    # at.
    for mod in census:
        with open(os.path.join(lib, mod + ".lean"), encoding="utf-8") as f:
            raw = f.read()
        check('"""' not in raw,
              f"lib/{mod}.lean contains a three-quote string delimiter, which "
              f"`formal/admitted.py`'s `lean_code_regions` does not lex — the "
              f"census would be counting inside a string literal")
        check(not re.search(r"(?<![\w'])(exact_decide|implemented_by|unsafe)"
                            r"(?![\w'])", A.lean_code_regions(raw)),
              f"lib/{mod}.lean uses a construct the trust census does not "
              f"count (`exact_decide`, `implemented_by` or `unsafe`); extend "
              f"`AXIOM_TACTICS`/the regexes in formal/admitted.py first")
        check_the_stripper_sees_every_declaration(mod, raw)
    # A `Char` literal in `lib/`, which is what makes the scanner's
    # character-literal branch reachable at all.  It is not a ban on the literal;
    # it is the statement that the branch is UNREACHABLE today, so the rule the
    # bug fixed (`a `'` after an identifier character is a prime, not an opening
    # quote`) is the whole of the behaviour there is.  The day somebody writes
    # `'x'` this fails and the ambiguity has to be thought about rather than
    # inherited.
    chared = []
    for mod in sorted(census):
        with open(os.path.join(lib, mod + ".lean"), encoding="utf-8") as f:
            for i, line in enumerate(f.read().split("\n"), start=1):
                for m in re.finditer(r"(?<![A-Za-z0-9_'])'(\\.|[^\\'])'", line):
                    chared.append(f"lib/{mod}.lean:{i} {m.group(0)!r}")
    check(not chared,
          "lib/ now contains a `Char` literal, which makes "
          "`formal/admitted.py::lean_code_regions`'s character-literal branch "
          "reachable for the first time and gives an apostrophe in an "
          "identifier (`fieldTag_inj'`, forty-odd of them) two possible "
          "meanings:\n    " + "\n    ".join(chared)
          + "\n    The scanner resolves it by requiring the preceding character "
            "to be a non-identifier, which is Lean's own rule; check the "
            "resolution against this file before trusting the census again.")
    # VACUITY, which is the third way a Lean declaration can assert nothing and
    # the only one of the three that a text scan decides.  `formal/lean.py::
    # vacuous_declarations` finds the two shapes it knows: a `def` whose declared
    # return type is `Prop` and whose body is `True`, and a `∀ …, … → True` -- a
    # statement no inhabitant can contradict.  Both are read over the
    # comment-stripped text, for the same reason this census is.  The two shapes
    # are the detector's, not this file's, and a third vacuous shape would need
    # `vacuous_declarations` to learn it.
    #
    # The EMITTED contracts are checked here too, not only `lib/`: a `sorry` is
    # the one thing this project admits on purpose, and a contract whose
    # STATEMENT were vacuous would be a hole over nothing at all.
    from formal import lean as _L
    vacuous_lib = []
    for mod in sorted(census):
        with open(os.path.join(lib, mod + ".lean"), encoding="utf-8") as f:
            raw = f.read()
        vacuous_lib += [f"lib/{mod}.lean:{ln} {name} ({shape})"
                        for name, shape, ln in
                        _L.vacuous_declarations(A.lean_code_regions(raw))]
    vacuous_admitted = []
    for c in A.all_contracts():
        emitted = A.lean_trust_header([c]) + "\n" + A.lean_declarations([c])
        vacuous_admitted += [
            f"the declaration for {c.qualified} at {c.source}:{c.line} ({shape})"
            for name, shape, _ln in _L.vacuous_declarations(emitted)]
    check(not vacuous_lib and not vacuous_admitted,
          "a declaration that asserts nothing:\n    "
          + "\n    ".join(vacuous_lib + vacuous_admitted)
          + "\n    `True` as a statement, or `∀ …, … → True`, is a shape no "
            "proof of it can repair -- and over an ADMITTED contract it is a "
            "`sorry` over nothing.")
    total = sum(kinds["axiom_tactic"][0] for kinds in census.values())
    return True, (f"0 axiom, 0 sorry and 0 vacuous across {len(census)} lib/ "
                  f"module(s) and {len(A.all_contracts())} emitted contract(s); "
                  f"{total} native_decide/bv_decide site(s), within the ceiling")


def test_the_library_trust_is_attributed_to_a_declaration(tmpdir=None):
    """Every tactic site belongs to a named theorem, and no site is lost.

    The census above counts SITES per MODULE, which is the right granularity for
    a ceiling — a merge moves a module's number — and the wrong one for a
    REPLACEMENT, because a module is not something anybody fixes.  This is the
    other direction, and it is what makes "these theorems are kernel-checked
    now" a claim the tree can check: `library_trust_by_declaration` attributes
    every site to the declaration whose proof it is in, namespaced the way Lean
    spells it, so a `#print axioms` line can be generated from the census
    (`test_formal_axioms.py` does).

    Both directions are asserted because both failure modes are silent.  A site
    that finds no declaration above it lands under `A.UNATTRIBUTED` — a named
    sentinel rather than a dropped count, since a dropped count is
    indistinguishable in the output from a right one — and an attribution whose
    total disagrees with `library_trust`'s is a scanner that has started
    skipping proofs.
    """
    lib = A.lean_dir(HERE)
    per_mod = A.library_trust(lib)
    per_decl = A.library_trust_by_declaration(lib)
    lost = []
    for mod in sorted(per_mod):
        by_line = per_decl.get(mod, {})
        summed = sum(count for count, _lines in by_line.values())
        counted = per_mod[mod]["axiom_tactic"][0]
        if summed != counted:
            lost.append(f"{mod}: {counted} site(s) in the module census and "
                        f"{summed} attributed to declarations")
        if A.UNATTRIBUTED in by_line:
            lost.append(f"{mod}: {by_line[A.UNATTRIBUTED][1]} site(s) have no "
                        f"declaration above them")
    check(not lost,
          "the tactic-site census and its per-declaration attribution "
          "disagree:\n    " + "\n    ".join(lost))
    named = sum(len(v) for v in per_decl.values())
    return True, (f"{sum(k['axiom_tactic'][0] for k in per_mod.values())} "
                  f"site(s) attributed to {named} declaration(s) across "
                  f"{len(per_decl)} module(s), none unattributed")


def test_native_decide_is_only_where_decide_cannot_go(tmpdir=None):
    """`native_decide` may appear in exactly the three theorems that evaluate
    the model, and in no others — anywhere, ever.

    This is the ratchet `LIBRARY_TRUST` cannot be.  That table is per MODULE, so
    it would take 685 new `native_decide` sites before it noticed anything, and
    it cannot tell a closed bit-pattern fact — which `decide` discharges in
    microseconds and the kernel checks — from a `runExport` over a ground image,
    which is the one thing here `decide` cannot do.  Both were `native_decide` in
    `lib/` until 2026-10-04: 63 of the 64 in `ProofLib` plus `Contracts`' one and
    `X86`'s one were closed facts, and they are now `decide`/`rfl`, which reach
    no generated axiom at all.  A 64th closed fact arriving as `native_decide`
    would push `LIBRARY_TRUST`'s module counts UP and fail — but only after it had
    also been merged, and the message would say a module grew rather than which
    theorem did.

    So the declaration is named, and both directions are failures: a site in a
    table row the tree cannot find is a stale marker (the same failure
    `tools/suite.py` reports for an `expect=` that starts passing), and a site
    outside the table is the thing this exists to catch.  Every remaining
    `bv_decide` is deliberately NOT in here — `bv_decide`'s subject is a
    `∀ w, …` over a 32-bit word, where bit-blasting is the only tool there is.
    """
    lib = A.lean_dir(HERE)
    live = A.native_decide_declarations(lib)
    bad = []
    for mod in sorted(NATIVE_DECIDE_ALLOWED):
        for name, why in sorted(NATIVE_DECIDE_ALLOWED[mod].items()):
            at = live.get(mod, {}).get(name)
            if at is None:
                bad.append(f"{mod}.{name}: {why} — and the declaration now has "
                           f"no `native_decide` site, so this row is a marker "
                           f"for a debt that is PAID. Delete the row and say so "
                           f"in the commit.")
            elif len(at) != 1:
                bad.append(f"{mod}.{name}: {why} — and it now has {len(at)} "
                           f"`native_decide` sites at {at}, so the row's reason "
                           f"is being asked to cover more than the one site it "
                           f"was written for")
    for mod in sorted(live):
        for name, at in sorted(live[mod].items()):
            if name not in NATIVE_DECIDE_ALLOWED.get(mod, {}):
                bad.append(
                    f"{mod}.{name} at {at}: a `native_decide` site in a "
                    f"declaration NATIVE_DECIDE_ALLOWED does not name. If it is "
                    f"a closed fact over literals, `decide` closes it and the "
                    f"KERNEL checks it — measured, `decide` on "
                    f"`¬ (0xd65f03c0 &&& 0xffe00000 = 0x2a00fa00)` reaches only "
                    f"propext and Quot.sound, and `(1 : UInt64).toNat = 1` by "
                    f"`rfl` reaches none at all. If it is not, say why here and "
                    f"why `decide` cannot.")
    check(not bad,
          "the `native_decide` ratchet does not match lib/:\n    "
          + "\n    ".join(bad))
    total = sum(len(v) for m in live.values() for v in m.values())
    return True, (f"{total} native_decide site(s), all in "
                  f"{sum(len(v) for v in live.values())} named model-evaluation "
                  f"theorem(s); the other "
                  f"{sum(k['axiom_tactic'][0] for k in A.library_trust(lib).values()) - total}"
                  f" site(s) are bv_decide over a quantified word")


def test_the_replaced_native_decide_count_is_what_it_claims(tmpdir=None):
    """FOUR copies of the same number, and every one of them has to agree.

    The 751 `native_decide`/`bv_decide` sites `lib/` carried on 2026-10-03 are
    in four places — FORMAL.md §7's row 10 (as published prose), this file's
    `LIBRARY_TRUST` ceiling, this file's `NATIVE_DECIDE_REPLACED`, and the live
    census — and the debt being paid down is only visible if they move together.
    `_formal_md_inventory` below exists for exactly the same reason about §7a's
    nineteen contracts, and it exists because §7a's table once said `subprocess`
    admits 7 and `fcntl` 1 against a tree that admits 12 and 0, with nothing in
    the tree able to notice.  So row 10 publishes BOTH figures — the number it
    started from and the number it is at — and this requires

        published_before - published_now == sum(NATIVE_DECIDE_REPLACED)
        published_now                       == the live census
        per-module LIBRARY_TRUST ceilings    == the live per-module census

    A replacement cannot be landed without the document moving, and the document
    cannot claim a replacement the tree does not have.  That is the whole point:
    a smaller number with nothing saying where it went is a number nobody can
    re-derive, which is what the original audit of this row found.
    """
    before, replaced_doc, after, why = _formal_md_row10_axiom_tactic()
    check(not why, why)
    census = A.library_trust(A.lean_dir(HERE))
    replaced = sum(NATIVE_DECIDE_REPLACED.values())
    bad = []
    if replaced_doc != replaced:
        bad.append(f"FORMAL.md §7 row 10 publishes {replaced_doc} replacement(s) "
                   f"and NATIVE_DECIDE_REPLACED claims {replaced}")
    if before - after != replaced:
        bad.append(f"FORMAL.md §7 row 10 publishes total {before} and remaining "
                   f"{after}, a fall of {before - after}, and "
                   f"NATIVE_DECIDE_REPLACED claims {replaced} replacement(s)")
    live = sum(k["axiom_tactic"][0] for k in census.values())
    if live != after:
        bad.append(f"FORMAL.md §7 row 10 publishes {after} site(s) remaining "
                   f"and lib/ has {live}")
    for mod in sorted(LIBRARY_TRUST):
        want = LIBRARY_TRUST[mod][3]
        got = census[mod]["axiom_tactic"][0]
        if got != want:
            bad.append(f"{mod}: the pinned ceiling is {want} and lib/ has {got}")
    check(not bad,
          "the axiom-carrying tactic count is in four places and they "
          "disagree:\n    " + "\n    ".join(bad))
    return True, (f"FORMAL.md row 10, LIBRARY_TRUST, NATIVE_DECIDE_REPLACED and "
                  f"lib/ all say total {before}, replaced {replaced}, remaining "
                  f"{after}, across {len(LIBRARY_TRUST)} module(s)")


def _formal_md_row10_axiom_tactic():
    """`(total, replaced, remaining, why)` as FORMAL.md §7's row 10 publishes.

    Read out of the document for the reason `_formal_md_inventory` gives, and
    the shape is found by STRUCTURE rather than by a line number, because §7
    grows rows above row 10 and a row number is not a stable handle.  All THREE
    figures have to be present and LABELLED, and `why` is returned rather than a
    guess made when they are not: a row that published only what it is at could
    not say what it fell from, which is the whole reason this reads the document
    rather than comparing against a copy of it.
    """
    path = os.path.join(HERE, "FORMAL.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    row = re.search(r"^\|\s*10\s*\|.*$", text, re.M)
    if not row:
        return 0, 0, 0, ("FORMAL.md §7 has no row 10, so the published "
                        "axiom-tactic figure cannot be checked against the "
                        "tree")
    line = row.group(0)
    found = re.search(r"total \*\*(\d+)\*\*, replaced \*\*(\d+)\*\*, "
                      r"remaining \*\*(\d+)\*\*", line)
    if not found:
        return 0, 0, 0, (
            "FORMAL.md §7's row 10 does not publish its three figures as "
            "`total **N**, replaced **N**, remaining **N**`, so what the "
            f"axiom-tactic debt fell by cannot be checked against the tree.  "
            f"The row currently reads {line[:200]!r}.")
    g = found.groups()
    return int(g[0]), int(g[1]), int(g[2]), ""


def test_the_census_is_attributed_to_theorems_not_only_to_lines(tmpdir=None):
    """`lib/`'s axiom-carrying sites, per THEOREM, and the completeness of that.

    `LIBRARY_TRUST` above pins a count per FILE, and a file-level ceiling is the
    right shape for a debt several branches pay down at once — but it is not the
    shape the WORK has. `bugs/FORMAL_native_decide_axiom.md` item 2 asks for
    "for each top-level `theorem`/`lemma` in `lib/`, the number of
    axiom-carrying tactic sites in its own proof, so the ceiling can be lowered
    per theorem rather than per file", and that is
    `formal/admitted.py::declaration_tally`.

    Three things are asserted, in the order they can fail:

      * **COMPLETENESS, both directions.** The per-declaration counts for a module
        must SUM to that module's file-level count. An attribution that lost a
        site would report a smaller, plausible number, and one that invented one
        would report a bigger one; neither is visible without this.
      * **No hit is in no theorem.** A site above the first declaration head in a
        file is `UNATTRIBUTED`, the named sentinel the scanner reports rather
        than dropping the count — a shape somebody has to look at rather than a
        theorem to work on. There are none, and that is a fact about the corpus
        rather than an assumption: a future top-level tactic script would land
        here.
      * **The shortlist is a ceiling, not a snapshot.** The theorems carrying
        exactly ONE site are the cheapest to replace (`decide` or `rfl` closes a
        closed arithmetic goal; `bv_decide` is the right tool for the `∀ w, … ≠
        …` bit-pattern lemmas and those are the ones to leave), so their NUMBER
        is pinned as a ceiling and their names are printed. A name list as an
        equality would fail on every proof somebody improves, which is the
        failure mode `LIBRARY_TRUST`'s own note describes for a per-file
        equality.
    """
    lib = A.lean_dir(HERE)
    census = A.library_trust(lib)
    by_decl = A.declaration_tally(lib)
    errors = []
    for mod in sorted(census):
        rows = by_decl.get(mod)
        if rows is None:
            errors.append(f"{mod}: the per-declaration census has no row for a "
                          f"module the file-level census has")
            continue
        for kind in ("sorry", "axiom_tactic"):
            attributed = sum(r[2][kind] for r in rows)
            whole = census[mod][kind][0]
            if attributed != whole:
                errors.append(
                    f"{mod}: {kind} — {attributed} attributed to declarations "
                    f"against {whole} in the file. An attribution that loses a "
                    f"site reports a smaller plausible number and one that "
                    f"invents a site reports a bigger one; neither is visible "
                    f"without this comparison")
        for name, line, _kinds in rows:
            if name == A.UNATTRIBUTED:
                errors.append(
                    f"{mod}: a {census[mod]['axiom_tactic'][0]} site(s) with no "
                    f"theorem above it, at line {line}. That is a top-level "
                    f"tactic script or a declaration head "
                    f"`_DECL_RE` does not match, and both are shapes a "
                    f"reader has to look at rather than a theorem to work on")
    check(not errors,
          "the per-theorem attribution of lib/'s trust census:\n    "
          + "\n    ".join(errors))

    # The two tactics SUM to the count, per declaration.  They are counted with
    # their own regexes rather than derived from `_TACTIC_RE`, so this is the
    # check that says the split did not drift from the total — and the split is
    # what decides which of a theorem's sites is worth attempting.
    mixed = []
    for mod in sorted(by_decl):
        for name, _line, kinds in by_decl[mod]:
            split = sum(kinds.get(t, 0) for t in A.AXIOM_TACTICS)
            if split != kinds["axiom_tactic"]:
                mixed.append(f"{mod}: {name} — {split} counted as "
                             f"{'/'.join(A.AXIOM_TACTICS)} against "
                             f"{kinds['axiom_tactic']} sites")
    check(not mixed,
          "the per-tactic split of a theorem's sites does not add up:\n    "
          + "\n    ".join(mixed))

    shortlist = sorted((r[2]["axiom_tactic"], r[0], mod)
                       for mod, rows in by_decl.items()
                       for r in rows if r[2]["axiom_tactic"] == 1)
    check(len(shortlist) <= ONE_SITE_THEOREMS,
          f"{len(shortlist)} theorems in lib/ carry exactly one axiom-carrying "
          f"site and the ceiling says {ONE_SITE_THEOREMS}. That count is a "
          f"WORK LIST — each of those is one site away from a kernel-checked "
          f"proof — so it moving DOWN is the outcome and moving UP means new "
          f"debt landed. Either way the ceiling and the commit move together.")
    # …and the sharper one.  Of the 36, ten are the `arm64_flag_*` family, whose
    # sites are `simp only […]; bv_decide` over bit patterns — the right tool
    # with no kernel-checked spelling short of writing the arithmetic out.  A
    # theorem whose ONLY site is a `native_decide` is the other kind: closed
    # `UInt64`/`Nat` arithmetic, which `decide`, `rfl`, `norm_num` or `omega`
    # very often closes.  **A declaration `NATIVE_DECIDE_ALLOWED` already names
    # with a reason is NOT on this list**, and that exclusion is what keeps it a
    # work list: all 19 `IEEE754` arithmetic theorems and the three
    # `DylibExport` ground-image theorems carry exactly one `native_decide` and
    # every one of them has a measured reason `decide` cannot go, so counting
    # them made the list report 22 items of which 22 were justified and the next
    # reader would have had to re-derive that.  This is the list
    # `bugs/FORMAL_native_decide_axiom.md` item 3 asks for by another name, and
    # it is short enough to read — which is the point of a work list.
    replaceable = sorted(r[0] for mod, rows in by_decl.items() for r in rows
                         if r[2]["axiom_tactic"] == 1
                         and r[2].get("native_decide", 0) == 1
                         and r[0] not in NATIVE_DECIDE_ALLOWED.get(mod, {}))
    check(len(replaceable) <= REPLACEABLE_THEOREMS,
          f"{len(replaceable)} theorems in lib/ carry exactly one site and that "
          f"site is a `native_decide` that NATIVE_DECIDE_ALLOWED does not already "
          f"justify ({', '.join(replaceable)}), and the ceiling says "
          f"{REPLACEABLE_THEOREMS}. Those are the sites with a "
          f"kernel-checked spelling standing next to them, so the count "
          f"falling is the whole of item 3's first step.")
    hot = sorted(((r[2]["axiom_tactic"], r[0], mod)
                  for mod, rows in by_decl.items() for r in rows),
                 reverse=True)[:3]
    total = sum(census[m]["axiom_tactic"][0] for m in census)
    holders = sum(1 for mod, rows in by_decl.items() for r in rows
                  if r[2]["axiom_tactic"])
    return True, (f"{total} site(s) over {holders} theorem(s), all attributed; "
                  f"{len(shortlist)} carry a single site and {len(replaceable)} "
                  f"of those a single native_decide ({', '.join(replaceable)}); "
                  f"the three heaviest are "
                  + ", ".join(f"{n} ({k})" for k, n, _m in hot))


# How many theorems in `lib/` may carry EXACTLY ONE axiom-carrying tactic site.
# A ceiling, for the reason `LIBRARY_TRUST`'s note gives: each of those is one
# site away from a kernel-checked proof, so the count moving DOWN is the outcome
# and moving UP means new debt landed.  **36 on this tree**, and the jump from the
# 19 this table held is not new work: it is 19 declarations that were never in
# the list because their site is in a file that arrived after the ceiling was
# written (`lib/IEEE754.lean`, 19 one-site `native_decide` theorems) plus the
# one-site rows the per-theorem attribution already counted and this ceiling had
# not caught up with.  `test_the_census_is_attributed_to_theorems_not_only_to_lines`
# prints their names; ten are the `arm64_flag_*` family and 19 are IEEE754's
# arithmetic, which `NATIVE_DECIDE_ALLOWED` justifies by declaration.
ONE_SITE_THEOREMS = 36

# How many theorems may carry exactly one site AND that site be a `native_decide`
# that `NATIVE_DECIDE_ALLOWED` does not already name with a reason.  This is
# `bugs/FORMAL_native_decide_axiom.md` item 3's list by another name, and it is
# the sharpest version.  **0 on this tree, and that is the outcome item 3 asked
# for**: the last four were `@[simp] theorem x86_mask_{one,two,four,eight}` and
# `decide` closed them, so every one-site `native_decide` in `lib/` is now either
# kernel-checked or justified by name — `IEEE754`'s 19 ground binary64
# arithmetic theorems (measured: `decide` cannot reduce `Float.ofBits`, which is
# a compiled primitive) and `ProofLib`'s three `DylibExport` theorems over a
# ground image.  The 11 of the 36 that are `bv_decide` over bit patterns are the
# right tool and are not on this list at all.  A ceiling of **0** is the strongest
# form of the ratchet `NATIVE_DECIDE_ALLOWED` already is: a new one-site
# `native_decide` anywhere in `lib/` fails this row BY NAME, and a site in a
# theorem that already had another is caught by that table instead.
REPLACEABLE_THEOREMS = 0


def test_the_source_half_of_the_closure_census_is_readable(tmpdir=None):
    """`library_theorems` — the half of the axiom census that needs no Lean.

    The closure census (`AXIOM_CLOSURE`) asks Lean what a theorem rests on; this
    asks the SOURCE what it is made of, and the join is the finding. Three
    properties, each of which was a way the source half could be quietly wrong
    and leave the closure half reporting nonsense:

    * **namespaces are resolved.** `lib/Contracts.lean` and `lib/Refine.lean` open
      a namespace of their own name and `lib/ProofLib.lean` opens three more, so
      a bare name is not a name Lean answers to. An unqualified scan reports 0 of
      7 and 0 of 22 for those modules and reads as a clean result rather than as
      a broken instrument.
    * **every declared name is QUALIFIED the way Lean would spell it**, and the
      two that end in a PRIME are the check: `lib/ProofLib.lean:665` and
      `lib/work.lean:141` both declare one, and `lean_code_regions` used to read
      that `'` as a character-literal opener and blank the declaration away.
      Lean answers `#print axioms u64_toNat_sub_one'` with `[propext,
      Quot.sound]`, so the declaration is real and the scanner was wrong.
    * **every module is represented and every row has a line**, because a count
      with no location is the sentence `library_trust`'s docstring argues
      against.
    """
    lib = A.lean_dir(HERE)
    rows = A.library_theorems(lib)
    check(sorted(rows) == sorted(A.library_trust(lib)),
          f"the source census sees modules {sorted(rows)} and the trust census "
          f"{sorted(A.library_trust(lib))}; two scans of one directory must "
          f"agree on what is in it")
    check(all(r["line"] >= 1 for m in rows.values() for r in m.values()),
          "a theorem with no line is a number nobody can act on")
    primes = [f"{mod}.{q}" for mod, m in rows.items() for q in m
              if q.endswith("'")]
    check(primes == ["ProofLib.mem_read_two_writes_adjacent'",
                     "ProofLib.mem_read_after_write_u64_slot'",
                     "ProofLib.u64_toNat_sub_one'",
                     "ProofLib.MF.fieldTag_inj'",
                     "work.s64_to_u64_toNat'"],
          f"the declarations whose names end in a prime are {primes}; a scanner "
          f"that cannot see a prime cannot see these, and two of them were "
          f"invisible to the site census until this fix")
    # The qualified spelling is what makes `#print axioms <name>` work at all, so
    # check it structurally rather than against a copy of the tree: every name is
    # either bare (a file with no namespaces) or dotted, and a dotted one starts
    # with a name the file either OPENS as a namespace or DECLARES as a type —
    # because Lean lets a declaration introduce a namespace implicitly by a
    # qualified name, and `lib/ProofLib.lean` does exactly that:
    # `@[ext] theorem Arm64State.mem_pc` (`:3481`) puts `mem_pc` in
    # `Arm64State`'s namespace without a `namespace Arm64State` anywhere, so a
    # check that demanded the file to OPEN it reported a real, answerable name as
    # one Lean would refuse.
    for mod, m in rows.items():
        raw = open(os.path.join(lib, mod + ".lean"), encoding="utf-8").read()
        opens = set(re.findall(r"(?m)^namespace\s+([A-Za-z_][\w'.]*)", raw))
        types = set(re.findall(r"(?m)^\s*(?:@\[[^\]\n]*\]\s*)*(?:private\s+|"
                               r"protected\s+)*(?:structure|class|inductive)\s+"
                               r"([A-Za-z_][\w'.]*)", A.lean_code_regions(raw)))
        for q in m:
            if "." in q:
                check(q.split(".")[0] in opens | types,
                      f"{mod}.{q} is namespaced under {q.split('.')[0]!r}, which "
                      f"{mod}.lean neither opens as a namespace nor declares as a "
                      f"type — Lean would answer `Unknown constant` and this row "
                      f"would read as a theorem that reaches no axiom")
    # **Every attributed THEOREM is one this census can ask about.**  The two
    # used to be separate scanners with separate answers: this function's own
    # `heads` pattern had no `@[...]` prefix, so 98 attributed declarations
    # (`ProofLib` 31, `X86` 66, `work` 1 — four of the X86 ones being
    # `@[simp] theorem x86_mask_*` on four lines side by side) were never asked
    # about, and `axiom_census_summary` filed every one of them as a theorem
    # that reaches no axiom: a clean row for a proof nobody asked Lean about.
    #
    # `def`/`abbrev`/`instance` are deliberately not required — they carry no
    # proof, so `#print axioms` has nothing to ask about them — so the keyword is
    # read off the declaration's OWN first line rather than assumed, and the
    # attributed names are the ones the other scanner produced.
    for mod in sorted(rows):
        for name, line, _kinds in A.declaration_tally(lib).get(mod, []):
            head = open(os.path.join(lib, mod + ".lean"),
                        encoding="utf-8").read().splitlines()[line - 1]
            kind = re.match(r"^[ \t]*(?:@\[[^\]\n]*\][ \t\n]*)*"
                            r"(?:private\s+|protected\s+|noncomputable\s+|"
                            r"nonrec\s+)*(theorem|lemma|def|abbrev|instance|"
                            r"example)\s", head)
            if kind and kind.group(1) in A.THEOREM_HEAD_KINDS:
                check(name in rows[mod],
                      f"{mod}.{name} is a theorem the attribution walk found at "
                      f"line {line} ({head.strip()[:60]!r}) and the closure "
                      f"census cannot see it, so `#print axioms` is never asked "
                      f"about it and it reads as a proof that reaches no axiom")
    # The four that started this, named rather than counted, because a count
    # moves when the corpus grows and a NAME is what a reader goes and looks at.
    for name in ("x86_mask_one", "x86_mask_two", "x86_mask_four",
                 "x86_mask_eight"):
        check(name in rows["X86"],
              f"X86.{name} is invisible to the source half of the closure "
              f"census. All four are written `@[simp] theorem …`, and the "
              f"scanner's own declaration-head pattern had no `@[...]` prefix, "
              f"so a `#print axioms` line was never emitted for any of them")
    # **The declarations the census cannot ASK about are the ones with no site
    # to hide**, and that is what makes the drop safe rather than a hole: a
    # `private` theorem's name is mangled, so `theorem_axiom_census` leaves it
    # out and REPORTS it, and a `bv_decide` inside one would be an axiom that
    # exists and cannot be named — which is the arithmetic in
    # `test_formal_axioms.py` being unable to close. `lib/` has exactly one such
    # declaration (`ProofLib.ifUpdate_congr`) and it has no site. Checked here
    # because this file is the one that runs without Lean.
    private = {f"{mod}.{name}"
               for mod, m in rows.items() for name, row in m.items()
               if not row.get("public", True)}
    holders = {f"{mod}.{name}"
               for mod, rs in A.declaration_tally(lib).items()
               for name, _line, kinds in rs if kinds["axiom_tactic"]}
    check(not (private & holders),
          f"a declaration the closure census cannot ask about carries an "
          f"axiom-carrying site: {sorted(private & holders)}. Its name is "
          f"mangled, so the axioms it introduces exist and cannot be named, and "
          f"every count built on `#print axioms` would then be short by an "
          f"amount nobody could point at")
    return True, (f"{sum(len(m) for m in rows.values())} top-level theorem(s) "
                  f"across {len(rows)} module(s), namespaced and located; "
                  f"{len(primes)} of them end in a prime; "
                  f"{len(private)} unaskable (private) and none carries a site; "
                  f"every attributed theorem is visible to the census")


def test_the_axiom_names_are_classified_not_guessed(tmpdir=None):
    """`axiom_site_tactic` and `parse_print_axioms`, on MEASURED text.

    The corpus's largest admitted assumption in the model is 751
    `native_decide`/`bv_decide` sites, and what they put in a proof term is an
    axiom whose NAME this project published wrongly for a year: `AXIOM_TACTICS`'s
    own comment and FORMAL.md §7 row 10 both said `Lean.ofReduceBool`, and on
    Lean 4.32.2 the measured answer is a fresh axiom per use,
    `<decl>._native.<tactic>.ax_<n>_<m>`. So the classifier is the thing a reader
    needs and it has to be pinned against what Lean PRINTS, not against what a
    docstring claims.

    The three rows are the three shapes that matter:

    * the real per-use name, classified to its tactic;
    * a standard Lean axiom, classified to nothing — and `OF_REDUCE_BOOL` is one
      of those names today, which is why it is a constant a measurement can be
      compared against rather than a thing to grep for and be misled by;
    * `'name' does not depend on any axioms`, the form a parser written for the
      `depends on axioms: [...]` shape silently drops. Every dropped row is a
      theorem reported as unknown, so the FIRST measured run of this census
      parsed 193 of ProofLib's 255 and the shortfall was almost entirely
      theorems that reach nothing — the best outcome there is.

    **A NAMESPACE-QUALIFIED `decl`, which is what four of the rows above do not
    have and five of `lib/`'s six modules produce.**  `AXIOM_SITE_RE`'s `decl`
    group was `[^.]+` and could not match one, so `axiom_site_tactic` answered
    None for every theorem inside a `namespace` block and
    `axiom_census_summary` filed each of them `text_only` — the column that
    exists to catch a closure the census cannot see.  The names below are the
    MEASURED `#print axioms` output of three theorems, one per shape of
    qualification: a namespace (`DylibExport.Semantics_refutable`), a
    module-named namespace wrapping the entire file
    (`IEEE754.signed_zeros_are_equal`, and `lib/IEEE754.lean` is one `namespace`
    from line 49 to 415), and a namespaced `bv_decide`
    (`MF.fieldTag_inj`).
    """
    check(A.axiom_site_tactic("t32s_t8s._native.bv_decide.ax_1_5")
          == "bv_decide",
          "the measured per-use name is not classified to its tactic")
    check(A.axiom_site_tactic("work_step_ldr_uoff._native.native_decide.ax_1_1")
          == "native_decide",
          "and neither is the native_decide spelling")
    for qualified, tactic in (
            ("DylibExport.Semantics_refutable._native.native_decide.ax_1_1",
             "native_decide"),
            ("IEEE754.signed_zeros_are_equal._native.native_decide.ax_1_1",
             "native_decide"),
            ("MF.fieldTag_inj._native.bv_decide.ax_1_1", "bv_decide"),
            ("DylibExport.Semantics_refutable._native.bv_decide.ax_3_7",
             "bv_decide"),
    ):
        check(A.axiom_site_tactic(qualified) == tactic,
              f"the NAMESPACE-QUALIFIED measured name {qualified!r} is not "
              f"classified to {tactic!r}. `AXIOM_SITE_RE`'s decl group must "
              f"accept a dotted name, because every theorem inside a "
              f"`namespace` — five of lib/'s six modules open one — carries "
              f"one, and a classifier that answers None for those files every "
              f"such theorem as `text_only`, which is the one column whose "
              f"purpose is to catch a closure the census cannot see.")
    check(A.AXIOM_SITE_RE.match(
        "DylibExport.Semantics_refutable._native.native_decide.ax_1_1")
        .group("decl") == "DylibExport.Semantics_refutable",
        "the decl group must capture the WHOLE qualified name, so a reader can "
        "tell which declaration the axiom belongs to; a pattern that stops at "
        "the first dot classifies the right tactic for the wrong declaration")
    for standard in ("propext", "Classical.choice", "Quot.sound",
                     A.OF_REDUCE_BOOL):
        check(A.axiom_site_tactic(standard) is None,
              f"{standard!r} is classified as a decide site; it is a standard "
              f"Lean axiom and classifying it as ours would put a site in the "
              f"census that does not exist")
    check(A.axiom_site_tactic("t32s_t8s._native.exact_decide.ax_1_1") is None,
          "a `._native.` name for a tactic outside AXIOM_TACTICS is classified "
          "as ours; the test below asserts lib/ contains none, which is what "
          "keeps the limit from being a silent gap")
    # **A NAMESPACED declaration's axiom, which is what `lib/` mostly prints.**
    # `AXIOM_SITE_RE`'s declaration group was `[^.]+` — it cannot match a dotted
    # name at all — while its only other spelling of this shape,
    # `formal/lean.py::GENERATED_AXIOM_RE`, uses a greedy `.+` and carries a
    # comment saying a lazy one "would hand `DylibExport` to `decl` and fail to
    # match at all". Measured consequence: `axiom_census_summary` read every
    # namespaced axiom as "this closure has no site", so `IEEE754` reported
    # `reaches 0 / text_only 19` against a truth of `reaches 19 / text_only 0`,
    # and `ProofLib` reported 43 where the answer is 46. A false `clean` is the
    # one thing a trust census may not produce, and both names here are MEASURED
    # output (`formal/lean.py::print_axioms`, 2026-10-04).
    for measured_name, want in (
            ("IEEE754.signed_zeros_are_equal._native.native_decide.ax_1_1",
             "native_decide"),
            ("DylibExport.backward_branch_run_none._native.bv_decide.ax_1_3",
             "bv_decide"),
            ("MF.fieldTag_inj'_one._native.bv_decide.ax_2_9", "bv_decide")):
        check(A.axiom_site_tactic(measured_name) == want,
              f"{measured_name!r} classifies to "
              f"{A.axiom_site_tactic(measured_name)!r} rather than {want!r}. "
              f"The declaration group must be GREEDY, for the reason "
              f"`formal/lean.py::GENERATED_AXIOM_RE` gives: a namespaced "
              f"declaration's axiom does not match at all otherwise, and the "
              f"census then files a proof that reaches one as reaching none")
    check(A.axiom_site_tactic("IEEE754.signed_zeros_are_equal._native.foo."
                              "ax_1_1") is None,
          "a namespaced name for a tactic outside AXIOM_TACTICS is classified "
          "as ours; the limit is the same one the bare name has")
    measured = ("'x86_step_ret' depends on axioms: [propext, Quot.sound]\n"
                "'nat64' does not depend on any axioms\n"
                "'IEEE754.signed_zeros_are_equal' depends on axioms: [propext, "
                "Quot.sound, "
                "IEEE754.signed_zeros_are_equal._native.native_decide.ax_1_1]\n"
                "'mem_read_bytes_write_same' depends on axioms: [propext, "
                "Classical.choice, Quot.sound, "
                "mem_read_bytes_write_same._native.bv_decide.ax_1_15, "
                "mem_read_bytes_write_same._native.bv_decide.ax_1_20]\n")
    got = A.parse_print_axioms(measured)
    check(got.get("x86_step_ret") == ["propext", "Quot.sound"],
          f"a measured `depends on axioms: [...]` line parsed as "
          f"{got.get('x86_step_ret')!r}")
    check(got.get("nat64") == [],
          f"the `does not depend on any axioms` form was dropped rather than "
          f"answered empty: {got!r}. An empty list is the result a replacement "
          f"proof is after, so it cannot be confused with an absence.")
    # The qualified row through the PARSER as well as the classifier: the name
    # carries a dot, so a name pattern written as `[^\x27]+` up to the next
    # quote handles it while one written as `[^.]+` does not, and only the whole
    # row exercises the two halves together.
    check([a for a in got.get("IEEE754.signed_zeros_are_equal", [])
           if A.axiom_site_tactic(a)]
          == ["IEEE754.signed_zeros_are_equal._native.native_decide.ax_1_1"],
          f"the measured namespace-qualified row did not parse and classify "
          f"to one site: {got.get('IEEE754.signed_zeros_are_equal')!r}")
    sites = [a for a in got.get("mem_read_bytes_write_same", [])
             if A.axiom_site_tactic(a)]
    check(len(sites) == 2,
          f"the measured X86 row's two per-site axioms classified to {sites!r}")
    check(A.axiom_site_tactic("") is None and A.parse_print_axioms("") == {},
          "empty input must not raise and must not invent a row")
    return True, ("4 axiom-name shapes (3 namespaced, 1 out-of-list) and 4 "
                  "`#print axioms` output shapes, all from a measured run")


def test_every_native_axiom_in_lib_is_one_this_file_knows(tmpdir=None):
    """The classifier's limit, asserted over the SOURCE rather than assumed.

    `axiom_site_tactic` answers None for a `._native.` name whose tactic is not
    in `AXIOM_TACTICS`, which is a hole by construction — a tactic this tree
    starts using that also introduces an axiom would be counted as "not ours"
    and the per-theorem census would under-report. Nothing can close that hole
    without running Lean, so what this does is the half that needs no Lean: every
    `AXIOM_TACTICS` entry must actually appear in `lib/`, so the list cannot be
    padded with a tactic nothing uses (which would make `uses_axiom_tactic`
    over-report) and the census's own comment is checked rather than trusted.
    The Lean half — that lib/ introduces no `._native.` axiom for any OTHER
    tactic — is `test_the_closure_census_says_what_the_text_census_cannot` in
    `test_formal_sweep_truth.py`, which skips without Lean.
    """
    lib = A.lean_dir(HERE)
    census = A.library_trust(lib)
    used = set()
    for mod in census:
        raw = open(os.path.join(lib, mod + ".lean"), encoding="utf-8").read()
        used |= set(re.findall(
            r"(?<![\w.'])(" + "|".join(A.AXIOM_TACTICS) + r")(?![\w'])",
            A.lean_code_regions(raw)))
    check(used == set(A.AXIOM_TACTICS),
          f"lib/ uses {sorted(used)} and AXIOM_TACTICS lists "
          f"{sorted(A.AXIOM_TACTICS)}; a tactic in the list that nothing uses "
          f"makes `uses_axiom_tactic` over-report and one that is missing makes "
          f"the census silent")
    return True, (f"every one of {sorted(used)} appears in lib/, and no other "
                  f"tactic carries that name")
# ── the inventory FORMAL.md publishes ─────────────────────────────────────────

def _formal_md_inventory():
    """`(total, modules, {module: n})` as §7 and §7a of FORMAL.md publish them.

    Read out of the document rather than compared against a copy of it, and the
    reason is the one the audit ran into: §7a's table said `subprocess` admits 7
    and `fcntl` 1, and it admits 12 and 0, and row 8 said 15 contracts across
    five modules when there are 19 across four.  Nothing checked any of it, so a
    paragraph about the trust boundary was free to describe a boundary that no
    longer existed.  A census that is published in prose is a census with two
    copies, and the instrument has to be the one that can fail — so this reads
    the document and the caller compares.

    The three shapes come from three places in it: row 8's figure and module
    list, and §7a's per-module table.  Each is found by the structure it has
    rather than by a line number, because §7 grows rows above it.
    """
    path = os.path.join(HERE, "FORMAL.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    row8 = re.search(r"^\|\s*8\s*\|.*?(\d+)\s+of them across\s+(.*)$",
                     text, re.M)
    if not row8:
        return None, None, None, (
            "FORMAL.md §7's row 8 no longer states how many admitted contracts "
            "there are, so the inventory cannot be checked against the tree; "
            "either put the figure back or delete the row and say why")
    total = int(row8.group(1))
    # The list is the RUN of backticked names right after the figure, and nothing
    # else: a follow-up clause naming a module that admits nothing (`fcntl`) is
    # not part of it.  `fcntl` WAS inside the list until the audit, which is how
    # a stale row 8 passed every other check in the tree.  (Splitting the tail on
    # a `.` to end the sentence does NOT work: `concurrent.futures` has one.)
    listed = re.match(r"((?:`[\w.]+`)(?:\s*(?:,|and)\s*(?:`[\w.]+`))*)",
                      row8.group(2))
    if not listed:
        return None, None, None, (
            f"FORMAL.md §7 row 8 reads {row8.group(2)[:60]!r} after its figure, "
            f"which is not a list of modules, so the modules it claims cannot "
            f"be compared with the ones that admit contracts")
    mods = sorted(re.findall(r"`([\w.]+)`", listed.group(1)))
    counts = {m: int(n) for m, n in
              re.findall(r"^\|\s*`([\w.]+)`\s*\|\s*(\d+)\s*\|", text, re.M)}
    if not counts:
        return None, None, None, (
            "FORMAL.md §7a's per-module table no longer has rows this can read, "
            "so the published counts cannot be checked against the modules")
    return total, mods, counts, ""


def test_the_formal_md_inventory_agrees(tmpdir=None):
    """FORMAL.md's published inventory IS the census, in both directions."""
    want_total, want_mods, want_counts, why = _formal_md_inventory()
    check(not why, why)
    counts = A.counts_by_module()
    live_total = sum(counts.values())
    live_counts = {m: n for m, n in counts.items() if n}
    check(want_total == live_total,
          f"FORMAL.md §7 says {want_total} admitted contract(s) and there are "
          f"{live_total}. A published census that does not match the tree "
          f"describes a trust boundary nobody has.")
    check(want_mods == sorted(live_counts),
          f"FORMAL.md §7 row 8 names {want_mods} as the modules that admit "
          f"contracts and the modules that declare any are "
          f"{sorted(live_counts)}")
    bad = []
    for mod in sorted(set(want_counts) | set(live_counts)):
        got, want = live_counts.get(mod), want_counts.get(mod)
        if got != want:
            bad.append(f"{mod}: FORMAL.md §7a publishes {want}, the modules "
                       f"declare {got}")
    check(not bad,
          "FORMAL.md §7a's per-module table has drifted from "
          "formal/hostmods/:\n    " + "\n    ".join(bad))
    return True, (f"FORMAL.md publishes {want_total} contract(s) across "
                  f"{len(want_counts)} module(s), as declared")
def test_the_count_per_module_is_pinned():
    """THE RATCHET.  The per-module count, in both directions.

    This is the assertion the task's "a test must assert the count of
    `sorry`/`admit`/axioms per module so a new one cannot appear unnoticed" asks
    for, and it is deliberately a hard equality rather than a bound.

    Upward (a module declares more than the table says): someone has widened what
    this backend trusts.  That may be right -- `ctypes` answering one more
    operation honestly would be a real improvement -- but it is a change to what
    the `trust:` line claims, and the table is where a reader looks to see it.
    Land the fix with the number.

    Downward (the table says more than the module declares): a stale marker, and
    the same failure `tools/suite.py` reports for an `expect=`-marked test that
    starts passing.  A module that became fully computable is the BEST outcome
    this project can have for it, so the table entry is now a lie and the fix is
    to delete the row and say so in the commit.
    """
    counts = A.counts_by_module()
    grew, shrank = [], []
    for mod in sorted(set(counts) | set(ADMITTED_COUNTS)):
        got = counts.get(mod)
        want = ADMITTED_COUNTS.get(mod)
        if got is None:
            grew.append(f"{mod}: ADMITTED_COUNTS records {want} but there is no "
                        f"formal/hostmods module for it")
        elif want is None:
            grew.append(f"{mod}: declares {got} admitted contract(s) and is not "
                        f"in ADMITTED_COUNTS — add the row with its count")
        elif got > want:
            grew.append(f"{mod}: declares {got} admitted contract(s), the table "
                        f"says {want}. A module that trusts more than it records "
                        f"is a trust line that under-reports. Either the new "
                        f"contract is wrong or the count is stale; land the fix "
                        f"with the number.")
        elif got < want:
            shrank.append(f"{mod}: the table records {want} admitted contract(s) "
                          f"and it now declares {got}. The extra admission is "
                          f"GONE, which is the best outcome this project can "
                          f"have for the module, so the row is now a lie: delete "
                          f"it and say in the commit what became computable.")
    check(not grew and not shrank,
          "the admitted-contract count moved:\n  MORE THAN RECORDED:\n    "
          + "\n    ".join(grew) + "\n  FEWER THAN RECORDED:\n    "
          + "\n    ".join(shrank))
    total = sum(ADMITTED_COUNTS.values())
    return True, (f"{total} admitted contract(s) across "
                  f"{sum(1 for v in ADMITTED_COUNTS.values() if v)} module(s), "
                  f"as recorded")


def group_counts(tmpdir, cas_root, verbose):
    ok, note = test_the_count_per_module_is_pinned()
    return ok, note


# ── emitted ───────────────────────────────────────────────────────────────────

def group_emitted(tmpdir, cas_root, verbose):
    """The generated Lean carries one COUNTED hole per contract, and names them.

    Asserted on the TEXT rather than on a Lean run, for the reason
    `formal/lean.py` gives about counting holes: whether a `sorry` was ADMITTED is
    elaboration, so the sound instrument is what Lean reports.  This file is not
    that instrument -- it checks that each contract produced a `def … := by sorry`
    with its own name and docstring, which is the part a text scan CAN decide, and
    `formal/lean.py`'s census then counts them for real.  Asserting the COUNT here
    too is what makes the two agree: if the generator ever stopped emitting one,
    the census would silently report a smaller number and nothing would notice.
    """
    cs = A.all_contracts()
    text = A.lean_declarations(cs)
    missing, unnamed = [], []
    for c in cs:
        if f"def {c.lean_name} " not in text:
            missing.append(c.qualified)
        elif f"ASSUMES OF THE HOST: {c.assumes}" not in text:
            unnamed.append(c.qualified)
    check(not missing,
          "a contract produced no Lean declaration: " + ", ".join(missing))
    check(not unnamed,
          "a Lean declaration does not carry its contract's own assumption text: "
          + ", ".join(unnamed)
          + ". The docstring IS the claim; a hole whose text is somewhere else "
            "is a hole nobody can check.")
    n_sorry = text.count("\n  sorry")
    check(n_sorry == len(cs),
          f"the emitted block has {n_sorry} `sorry` for {len(cs)} contracts — "
          f"one per contract, or the census would be counting something else")
    header = A.lean_trust_header(cs)
    check("ADMITTED HOST CONTRACTS" in header and header.rstrip().endswith("-/"),
          "the trust header must be a closed `/- -/` block that names every "
          f"contract; got {header[:80]!r}...")
    if verbose:
        print(f"    {len(cs)} declaration(s), {n_sorry} sorry, header closed")
    return True, f"{len(cs)} contract(s) each became one named, countable sorry"


def test_a_file_that_reaches_none_generates_no_hole(tmpdir):
    """The change is INERT where it does not apply — the strongest of the ratchets.

    `formal/arm64_proof_gen.py` and `formal/x86_64_proof_gen.py` were changed to
    carry admitted contracts, and the failure mode of that change is not a wrong
    proof -- it is a RE-WRAPPED one: the same theorems with different whitespace,
    which still typechecks, still passes, and invalidates every cached verdict in
    `~/.gmojo` without anyone being able to say what changed.  So this compares the
    generator's output against HEAD's, byte for byte, on the corpus in
    `formal/examples/`.
    """
    import types
    import glob
    from formal import build as BB
    from types import SimpleNamespace

    def _head_gen(path, name):
        src = subprocess.run(["git", "show", f"HEAD:{path}"],
                             capture_output=True, text=True, check=True).stdout
        mod = types.ModuleType(name)
        mod.__file__ = os.path.join(HERE, path)
        exec(compile(src, path, "exec"), mod.__dict__)
        return mod

    try:
        old_arm = _head_gen("formal/arm64_proof_gen.py", "old_arm64_proof_gen")
        old_x86 = _head_gen("formal/x86_64_proof_gen.py", "old_x86_64_proof_gen")
    except Exception as e:                                  # noqa: BLE001
        return True, f"SKIPPED: no git HEAD to compare against ({type(e).__name__})"
    import formal.arm64_proof_gen as new_arm
    import formal.x86_64_proof_gen as new_x86

    checked, diffs, skipped = 0, [], []
    for path in sorted(glob.glob(os.path.join(HERE, "formal", "examples",
                                              "*.mojo"))):
        rel = os.path.relpath(path, HERE)
        try:
            fns = [s for s in BB.parse_module(open(path).read(), filename=rel)
                   if type(s).__name__ == "FunctionDef"]
        except Exception as e:                               # noqa: BLE001
            skipped.append(f"{rel}: {type(e).__name__}: {e}")
            continue
        if not fns:
            skipped.append(f"{rel}: no FunctionDef to generate a proof for")
            continue
        for arch, old_g, new_g, call in (
                ("arm64", old_arm, new_arm, "generate_arm64_proof"),
                ("x86_64", old_x86, new_x86, "generate_x86_64_proof")):
            # A DIFFERENT output path per architecture: `compile_formal` writes
            # the image, and one shared name would have the second architecture's
            # build overwrite the first's -- so this check would be comparing a
            # freshly written file against a stale one.
            out = os.path.join(tmpdir, f"idem_{arch}.aout")
            try:
                res = BB.compile_formal(rel, output=out, prove=False,
                                        check=False, arch=arch)
                prog = SimpleNamespace(functions=fns, externs=[],
                                       admitted=[], admitted_calls={})
                a = getattr(old_g, call)(prog, res["code"], res["info"])
                b = getattr(new_g, call)(prog, res["code"], res["info"])
            except Exception as e:                           # noqa: BLE001
                # REPORTED, never a silent `continue`.  The first version of this
                # check skipped on any exception and reported "0 generated
                # proofs" as a PASS, which is the worst shape a test can have:
                # it is green, it asserts nothing, and the reason it asserts
                # nothing is a `continue` nobody reads.
                skipped.append(f"{rel} [{arch}]: {type(e).__name__}: "
                               f"{str(e)[:120]}")
                continue
            checked += 1
            if a != b:
                diffs.append(f"{rel} [{arch}]")
    check(checked >= 20,
          "the byte-identity check compared only "
          f"{checked} proof(s) over {len(skipped)} skip(s), so it is not "
          "measuring what it claims:\n    " + "\n    ".join(skipped[:10]))
    check(not diffs,
          "a program that reaches NO admitted contract must generate a "
          "BYTE-IDENTICAL proof, and these do not:\n    "
          + "\n    ".join(diffs)
          + "\n  A whitespace-only difference still invalidates every cached "
            "proof verdict in ~/.gmojo without anyone being able to say what "
            "changed, which is why this is compared byte for byte.")
    return True, (f"{checked} generated proof(s) byte-identical to HEAD's, "
                  f"{len(skipped)} skipped")


def model_const(module, name):
    """The value of a hostmod's module-level integer constant, read from SOURCE.

    Read rather than written here, and that is the point: the alternative is a
    copy of `ARG_EMPTY = 2` in this file, and a copy is a second place for the
    model's numbering to be wrong in without anything noticing -- which is how a
    differential test stops being differential and starts comparing two tables
    that were both typed by the same person on the same afternoon.

    A module-level name on this path is FOLDED at every read
    (`bugs/FORMAL_module_state_no_storage.md`), so there is no way to ask the
    image for it; the declaration in the source is the only place the number
    exists, and reading it is what a caller would do too.
    """
    from formal import imports as I
    import fire_compiler as F
    for st in I.module_statements(os.path.join(A.HOSTMODS_ROOT,
                                               module.replace(".", os.sep)
                                               + ".mojo")):
        if isinstance(st, F.AssignStmt):
            tgt = getattr(st.target, "name", None)
            if tgt == name:
                return _folded_int(st.value, f"{module}.{name}")
    raise TestFailure(f"{module}.{name} is not a module-level integer constant "
                      f"in formal/hostmods/{module}.mojo")


def _folded_int(node, what):
    """`node` as an int, folding a unary minus; raise if it is not one.

    A NEGATIVE module constant is a `UnaryOp` over an `IntLiteral` and not an
    `IntLiteral` with a negative `value`, which is worth knowing because
    `POLL_NOT_COLLECTED = -65` is negative and `int(getattr(node, "value"))` is
    `None` for it -- so the first version of this reader reported `None` for a
    sentinel whose whole job is to be a number outside every answer the host
    gives.  Folding here rather than in a second reader is the point: there is
    one place that turns a hostmod's literal into a Python int.
    """
    import fire_compiler as F
    if isinstance(node, F.IntLiteral):
        return int(node.value)
    if isinstance(node, F.UnaryOp) and getattr(node, "op", None) in ("-", "−"):
        return -_folded_int(node.operand, what)
    raise TestFailure(f"{what} is not a module-level integer constant; its value "
                      f"is a {type(node).__name__}, which this reader does not "
                      f"fold")


# ── the differential groups ───────────────────────────────────────────────────

def _exc(name):
    """The exception CLASS named `name`, for an `issubclass` test on a verdict.

    A verdict is a class NAME, because that is what the model's table compares
    against and what a diagnostic can print; turning it back into the class is
    needed for the one check that is about a kind rather than a name, and going
    through `getattr` on the builtin module rather than a registry means it works
    for any class CPython raised, including ones this file never mentions.
    """
    import builtins
    cls = getattr(builtins, name, None)
    if not (isinstance(cls, type) and issubclass(cls, BaseException)):
        raise TestFailure(f"{name!r} is not an exception class, so a verdict "
                          f"naming it cannot be checked")
    return cls


def group_subprocess(tmpdir, cas_root, verbose):
    """`subprocess`: the DECIDED half, against CPython's own verdicts.

    Two assertions per row, and the split between them is the interesting part of
    this group.  The model's `validate_args` returns FOUR DIFFERENT codes for four
    different shapes that CPython reports as the SAME exception class -- it
    distinguishes "no `args` at all" from "`args` is not iterable" from "an
    element is not path-like" from "an unknown keyword", and CPython raises
    `TypeError` for all four with four different messages.  So:

      * the model's code must equal the code its own table says for that shape
        (self-consistency, and the thing a copy of the numbering in this file
        would break -- which is why the codes are READ from the module source by
        `model_const` rather than written here);
      * and CPython must raise the exception CLASS the model documents for that
        code.  THAT is the differential half: it is what says the model's
        refinement of CPython's taxonomy is a refinement and not a divergence.
    """
    import subprocess as S
    A_OK = model_const("subprocess", "ARG_OK")
    codes = {n: model_const("subprocess", n) for n in
             ("ARG_OK", "ARG_NO_ARGS", "ARG_NOT_ITERABLE", "ARG_EMPTY",
              "ARG_ELEMENT_NOT_PATH", "ARG_UNKNOWN_KEYWORD")}
    NONZERO = model_const("subprocess", "ARG_NONZERO_STATUS")

    # (name, (args_kind, element_kind, keywords), expected code, the exception
    #  class CPython raises for a real argument of that shape, and a lambda that
    #  makes CPython raise it).  The lambda is PER ROW: the first version of this
    #  table called one shared `_construct_ok()` for every row, so five of the six
    #  rows compared CPython's answer for "/bin/true" against a shape meant to
    #  raise -- and FileNotFoundError is what it raised, for all five.
    #
    # `cls` is the exact class CPython raises for a shape it REFUSES, and `None`
    # for a shape it ACCEPTS -- where "accepts" means it went on to touch the
    # host and failed THERE, which is a `FileNotFoundError` in this sandbox and
    # would be a `PermissionError` on another.  That is not a loosened assertion:
    # a refusal is a `TypeError`/`IndexError` from the argument check and a host
    # failure is an `OSError` subclass, so the two are separated by kind and the
    # test is still exact about which one happened.  Asserting "no exception" for
    # the accepted row would instead have depended on whether `/bin/true` exists
    # on the machine running the test.
    cases = [
        ("no args",        (codes["ARG_NO_ARGS"], codes["ARG_OK"], 0),
         codes["ARG_NO_ARGS"], "TypeError", lambda: S.Popen()),
        ("not iterable",   (codes["ARG_NOT_ITERABLE"], codes["ARG_OK"], 0),
         codes["ARG_NOT_ITERABLE"], "TypeError", lambda: S.Popen(5)),
        ("empty",          (codes["ARG_EMPTY"], codes["ARG_OK"], 0),
         codes["ARG_EMPTY"], "IndexError", lambda: S.Popen([])),
        ("bad element",    (codes["ARG_OK"], codes["ARG_ELEMENT_NOT_PATH"], 0),
         codes["ARG_ELEMENT_NOT_PATH"], "TypeError",
         lambda: S.Popen(["a", 1])),
        ("unknown kwarg",  (codes["ARG_OK"], codes["ARG_OK"], 1),
         codes["ARG_UNKNOWN_KEYWORD"], "TypeError",
         lambda: S.Popen([sys.executable], bogus=1)),
        ("all fine",       (codes["ARG_OK"], codes["ARG_OK"], 0),
         codes["ARG_OK"], None, _construct_ok),
    ]
    want = []
    for _name, _m, _code, _cls, probe in cases:
        try:
            probe()
            want.append(None)
        except BaseException as e:  # noqa: BLE001
            want.append(type(e).__name__)

    got = _run("sp", ["import subprocess", "", "def main():"] +
               [f'    printf("%lld\\n", subprocess.validate_args({a}, {b}, {c}))'
                for _n, (a, b, c), _c, _e, _p in cases], tmpdir, cas_root)
    check(len(got) == len(cases),
          f"subprocess: image reported {len(got)} of {len(cases)} verdicts")
    bad = []
    for (name, _m, expect, cls, _p), g, wcls in zip(cases, got, want):
        if int(g) != expect:
            bad.append(f"{name}: image {g}, the model's own table says {expect}")
            continue
        if cls is None:
            # ACCEPTED: CPython must have got past the argument check.  An
            # `OSError` subclass is that -- the HOST refused, not the validator.
            if wcls is not None and not issubclass(_exc(wcls), OSError):
                bad.append(f"{name}: the model accepts this shape, and CPython "
                           f"raised {wcls}, which is a REFUSAL rather than a "
                           f"host failure")
        elif wcls != cls:
            bad.append(f"{name}: the model's code {expect} is documented as "
                       f"{cls}, and CPython raised {wcls or 'nothing'}")
    check(not bad, "subprocess.validate_args disagrees with CPython:\n    "
                   + "\n    ".join(bad))

    consts = _run("spc", ["import subprocess", "", "def main():",
                          '    printf("%lld %lld %lld\\n", subprocess.PIPE(), '
                          'subprocess.STDOUT(), subprocess.DEVNULL())'],
                  tmpdir, cas_root)
    want_c = f"{S.PIPE} {S.STDOUT} {S.DEVNULL}"
    check(consts == [want_c],
          f"subprocess constants: image {consts}, CPython [{want_c!r}]")

    rc = _run("sprc", ["import subprocess", "", "def main():",
                       '    printf("%lld %lld %lld\\n", '
                       'subprocess.check_returncode(0), '
                       'subprocess.check_returncode(1), '
                       'subprocess.check_returncode(7))'], tmpdir, cas_root)

    def _cp_rc(v):
        try:
            S.CompletedProcess(["x"], v).check_returncode()
            return A_OK
        except S.CalledProcessError:
            return NONZERO
    want_rc = " ".join(str(_cp_rc(v)) for v in (0, 1, 7))
    check(rc == [want_rc],
          f"subprocess.check_returncode: image {rc}, CPython [{want_rc!r}]")

    bs = _run("spbs", ["import subprocess", "", "def main():",
                       '    printf("%lld %lld\\n", '
                       'subprocess.validate_bufsize(-1), '
                       'subprocess.validate_bufsize(0))'], tmpdir, cas_root)
    A_BUFSIZE = model_const("subprocess", "ARG_BUFSIZE_NOT_INT")

    def _cp_bs(v):
        try:
            p = S.Popen([sys.executable], bufsize=v)
            p.kill()
            return A_OK
        except TypeError:
            return A_BUFSIZE
    want_bs = " ".join(str(_cp_bs(v)) for v in (-1, 0))
    check(bs == [want_bs],
          f"subprocess.validate_bufsize: image {bs}, CPython [{want_bs!r}]")

    # ── the wrappers' own keyword rules ───────────────────────────────────────
    # `run` and `check_output` are not `Popen`; they are three lines of argument
    # checking wrapped around it, and all 508 of this repository's
    # `capture_output=` call sites sit inside those three lines.  These rows are
    # the second half of the differential claim: the codes are read out of the
    # module source (`model_const`, never written here) AND each row's
    # expectation is CPython's own exception for the same real keyword
    # combination.  The `capture_output=False` row is in the table on purpose —
    # it is the row that shows the rule is about PRESENCE and not truth, which a
    # table of only `capture_output=True` would not distinguish from
    # `capture_output` being ignored entirely.
    KW = {n: model_const("subprocess", n) for n in
          ("ARG_OK", "ARG_STDIN_AND_INPUT", "ARG_STDOUT_AND_CAPTURE",
           "ARG_STDOUT_NOT_ALLOWED", "ARG_CHECK_NOT_ALLOWED")}

    def _verdict(fn, **kw):
        """CPython's exception CLASS for `fn(**kw)`, or None when it accepted it.

        `accepted` is separated from the rest by KIND the same way the `args`
        table above separates an `OSError` from a `TypeError`: a refusal is
        `ValueError` or `TypeError` and a host failure is an `OSError` subclass,
        so a row that says "accepted" asserts CPython got past the argument check
        and failed where this table cannot see.
        """
        try:
            fn([sys.executable, "-c", "pass"], **kw)
            return None
        except (ValueError, TypeError, OSError) as e:
            return type(e).__name__

    def _kw_row_agrees(expect, w):
        """Does CPython's verdict match the code the model returned?

        `expect` says whether the model claims CPython refused.  When it does,
        CPython must have raised a `ValueError` and nothing else — a `TypeError`
        is a different refusal and an `OSError` is not a refusal at all.  When
        the model says "accepted", CPython must NOT have raised a `ValueError`
        or a `TypeError`; an `OSError` or no exception at all both mean it got
        past the wrapper's checks, which is all this table claims.
        """
        if expect != KW["ARG_OK"]:
            return w == "ValueError"
        return w not in ("ValueError", "TypeError")

    run_rows = [
        # (name, model's (has_input, has_stdin, capture_output, has_stdout,
        #  has_stderr), expected code, the keyword combination CPython gets)
        ("nothing",         (0, 0, 0, 0, 0), KW["ARG_OK"], {}),
        ("input+stdin",     (1, 1, 0, 0, 0), KW["ARG_STDIN_AND_INPUT"],
         dict(input=b"x", stdin=S.PIPE)),
        ("capture+stdout",  (0, 0, 1, 1, 0), KW["ARG_STDOUT_AND_CAPTURE"],
         dict(capture_output=True, stdout=S.PIPE)),
        ("capture+stderr",  (0, 0, 1, 0, 1), KW["ARG_STDOUT_AND_CAPTURE"],
         dict(capture_output=True, stderr=S.PIPE)),
        # THE ORDER ROW.  CPython checks `input`/`stdin` first, so this
        # combination raises that message and not the `capture_output` one; a
        # model that checked them the other way round would agree on four rows
        # out of five and be wrong about the one a caller hits when it passes
        # both.
        ("input+stdin+capture", (1, 1, 1, 1, 0), KW["ARG_STDIN_AND_INPUT"],
         dict(input=b"x", stdin=S.PIPE, capture_output=True)),
        ("capture=False+stdout", (0, 0, 0, 1, 0), KW["ARG_OK"],
         dict(capture_output=False, stdout=S.PIPE)),
    ]
    got = _run("sprun", ["import subprocess", "", "def main():"] +
               [f'    printf("%lld\\n", subprocess.validate_run('
                f'{", ".join(str(v) for v in row[1])}))'
                for row in run_rows], tmpdir, cas_root)
    bad = []
    for (name, model_args, expect, kw), g in zip(run_rows, got):
        if int(g) != expect:
            bad.append(f"run/{name}: image {g}, the model's own table says "
                       f"{expect}")
            continue
        w = _verdict(S.run, **kw)
        if not _kw_row_agrees(expect, w):
            bad.append(f"run/{name}: the model says {expect} and CPython "
                       f"raised {w or 'nothing'}")
    check(not bad, "subprocess.validate_run disagrees with CPython:\n    "
                   + "\n    ".join(bad))

    co_rows = [
        ("stdout kwarg",  (1, 0, 0, 0, 0), KW["ARG_STDOUT_NOT_ALLOWED"],
         dict(stdout=S.PIPE)),
        ("check kwarg",   (0, 1, 0, 0, 0), KW["ARG_CHECK_NOT_ALLOWED"],
         dict(check=True)),
        # `check_output` forwards to `run`, so `capture_output` raises run's
        # message and not `check_output`'s own — measured, and the reason this
        # is ONE function in the model.
        ("capture",       (0, 0, 0, 0, 1), KW["ARG_STDOUT_AND_CAPTURE"],
         dict(capture_output=True)),
        ("clean",         (0, 0, 0, 0, 0), KW["ARG_OK"], {}),
    ]
    got = _run("spco", ["import subprocess", "", "def main():"] +
               [f'    printf("%lld\\n", subprocess.validate_check_output('
                f'{", ".join(str(v) for v in row[1])}))'
                for row in co_rows], tmpdir, cas_root)
    bad = []
    for (name, model_args, expect, kw), g in zip(co_rows, got):
        if int(g) != expect:
            bad.append(f"check_output/{name}: image {g}, the model's own table "
                       f"says {expect}")
            continue
        w = _verdict(S.check_output, **kw)
        if not _kw_row_agrees(expect, w):
            bad.append(f"check_output/{name}: the model says {expect} and "
                       f"CPython raised {w or 'nothing'}")
    check(not bad, "subprocess.validate_check_output disagrees with CPython:\n    "
                   + "\n    ".join(bad))

    # ── the constructors whose FIELD is a word ────────────────────────────────
    # 88 call sites in this tree spell `TimeoutExpired` (81), `CalledProcessError`
    # (4) and `CompletedProcess` (3), and none of the three is a type on this
    # path.  What is answerable about all three is one integer field, so the
    # model returns it and the expectation is read off a real CPython object.
    ctor_src = ["import subprocess", "", "def main():",
                '    printf("%lld %lld %lld\\n", '
                'subprocess.CompletedProcess(["a"], 7, stdout=1, stderr=2), '
                'subprocess.CalledProcessError(3, "cmd"), '
                'subprocess.TimeoutExpired("cmd", 30))']
    got = _run("spctor", ctor_src, tmpdir, cas_root)
    want_ctor = " ".join(str(v) for v in (
        S.CompletedProcess(["a"], 7, stdout=b"x", stderr=b"y").returncode,
        S.CalledProcessError(3, "cmd").returncode,
        S.TimeoutExpired("cmd", 30).timeout))
    check(got == [want_ctor],
          f"subprocess field constructors: image {got}, CPython [{want_ctor!r}]")

    if verbose:
        print(f"    {len(cases)} argument shapes (each against CPython's own "
              f"exception class), 3 constants, 3 returncodes, 2 bufsizes, "
              f"{len(run_rows)} run keyword rules, {len(co_rows)} check_output "
              f"keyword rules, 3 field constructors")
    return True, (f"subprocess: {len(cases) + len(run_rows) + len(co_rows)} "
                  f"refusal shapes and 11 other decisions agree with CPython")


def group_subprocess_surface(tmpdir, cas_root, verbose):
    """The MEASURED call surface BUILDS, and every admitted call REFUSES.

    This is the half of `subprocess` the differential table above cannot see.  A
    differential test compares verdicts, and every verdict in it comes from a
    function that is already callable — so the table is green whether or not a
    caller can CALL the module at all, and it was: before `run` declared
    `capture_output`, every one of this tree's 547 `subprocess.run` call sites
    failed the build with `unexpected keyword argument`, and the module was
    "modelled" for nobody.

    So this walks the surface the tree actually spells — measured by
    `test_formal_subprocess.py`, which fails if a name appears without being
    modelled — and asserts two things per program on BOTH backends: it builds,
    and running it stops with `ADMITTED_EXIT_STATUS` and names the contract that
    stopped it.  (The status is a RESERVED value inside `0..255`, not a value
    outside it; `group_runtime` measures why and `group_truth` keeps the tree
    from claiming otherwise.)  A model that accepted a keyword and then answered differently
    would fail the second half, which is the failure `formal/admitted.py`'s scope
    rule exists to prevent.

    Both backends because a hostmod is a dylib and a dylib is emitted twice, and
    "it builds on the one I happened to run" is not a claim about the module.
    """
    for backend in BACKENDS:
        for label, body in _SUBPROCESS_SURFACE:
            lines = ["import subprocess", "", "def main() -> int:"] + body
            name = f"spsurf-{backend}-{label.replace(' ', '_').replace('.', '_')}"
            # `_run` builds AND runs, and raises on a failed build, so reaching
            # the next line already says the surface compiles on this backend.
            out = _run(name, lines, tmpdir, cas_root, backend)
            if label == DECIDED_LABEL:
                check(out == ["-1 -2 -3"],
                      f"{name}: the DECIDED half must ANSWER, and the constants "
                      f"are the only thing it can answer here; the image "
                      f"printed {out}")
                continue
            aout = os.path.join(tmpdir, f"t_{abs(hash(name))}.aout")
            check(os.path.isfile(aout), f"{name}: no image to run")
            p = subprocess.run([aout], capture_output=True, text=True, timeout=60)
            check("ADMITTED contract" in p.stdout,
                  f"{name}: an admitted call must name its contract on stdout; "
                  f"stdout was {p.stdout[:200]!r}")
            check(p.returncode == A_ADMITTED_EXIT_STATUS,
                  f"{name}: exited {p.returncode}, and an admitted call must "
                  f"exit {A_ADMITTED_EXIT_STATUS} — this tree's reserved "
                  f"nonzero refusal status, which is inside 0..255 and so is "
                  f"NOT what identifies the refusal; the contract name on "
                  f"stdout is (see `group_runtime`)")
            # WHICH operation it came from.  A row that nests two admissions
            # (`popen_wait(Popen(...))`) is stopped by the inner one, so the row
            # names every operation whose refusal is a correct answer for it —
            # asserting the outer one would be asserting which call happens
            # first, which is a fact about the source and not about the model.
            named = [n for n in _SUBPROCESS_ACCEPTS[label] if n in p.stdout]
            check(named, f"{name}: the refusal must name one of "
                         f"{_SUBPROCESS_ACCEPTS[label]}; stdout was "
                         f"{p.stdout[:200]!r}")
    if verbose:
        for backend in BACKENDS:
            print(f"    {backend}: {len(_SUBPROCESS_SURFACE) - 1} admitted "
                  f"operations refuse, 1 decided surface answers")
    return True, (f"the measured call surface builds on "
                  f"{len(BACKENDS)} backends and every admitted call refuses "
                  f"with status {A_ADMITTED_EXIT_STATUS}")


# The surface `group_subprocess_surface` builds, one program per operation, in the
# SPELLING this repository uses — the keywords are the point, so each row is the
# call as the tree writes it rather than a tidied version of it.  `decided` is the
# one row that is not an admission: it is the decidable half, which must ANSWER.
DECIDED_LABEL = "decided"

_SUBPROCESS_SURFACE = [
    (DECIDED_LABEL, [
        '    printf("%lld %lld %lld\\n", subprocess.PIPE(), '
        'subprocess.STDOUT(), subprocess.DEVNULL())']),
    ("run", [
        '    return subprocess.run(["./x"], capture_output=True, text=True, '
        'timeout=120, cwd="/tmp", check=True)']),
    ("run", [
        '    return subprocess.run(["./x"], env="A=1", shell=0, errors="strict",'
        ' input="", stdout=0, stderr=0, stdin=0)']),
    ("call", ['    return subprocess.call(["./x"], timeout=30, cwd=".")']),
    ("check_call", ['    return subprocess.check_call(["./x"], cwd=".", env="")']),
    ("check_output", [
        '    printf("%s\\n", subprocess.check_output(["./x"], timeout=30, '
        'stderr=0, text=True))']),
    ("getoutput", ['    printf("%s\\n", subprocess.getoutput("ls -l"))']),
    ("getstatusoutput", ['    return subprocess.getstatusoutput("ls -l")']),
    ("Popen", [
        '    return subprocess.Popen(["./x"], stdout=subprocess.PIPE(), '
        'stderr=subprocess.STDOUT(), cwd=".", start_new_session=True)']),
    ("Popen", [
        '    return subprocess.Popen(["./x"], bufsize=0, stdin=0, text=True, '
        'pass_fds=0, errors="", preexec_fn=0)']),
    ("Popen.wait", [
        '    return subprocess.popen_wait(subprocess.Popen(["./x"]), '
        'timeout=30)']),
    ("Popen.poll", [
        '    return subprocess.popen_poll(subprocess.Popen(["./x"]))']),
    ("Popen.kill", [
        '    return subprocess.popen_kill(subprocess.Popen(["./x"]))']),
    ("Popen.terminate", [
        '    return subprocess.popen_terminate(subprocess.Popen(["./x"]))']),
    ("Popen.communicate", [
        '    printf("%s\\n", subprocess.popen_communicate('
        'subprocess.Popen(["./x"]), input=0, timeout=5))']),
]

# Which refusal each row of `_SUBPROCESS_SURFACE` may report, by the string the
# model prints.  A row that makes ONE admitted call names that one; the five
# `popen_*` rows nest a `Popen` inside, so the inner refusal is the one that fires
# and both are correct answers for the row.
_SUBPROCESS_ACCEPTS = {
    "run": ("subprocess.run",),
    "call": ("subprocess.call",),
    "check_call": ("subprocess.check_call",),
    "check_output": ("subprocess.check_output",),
    "getoutput": ("subprocess.getoutput",),
    "getstatusoutput": ("subprocess.getstatusoutput",),
    "Popen": ("subprocess.Popen",),
    "Popen.wait": ("Popen.wait", "subprocess.Popen"),
    "Popen.poll": ("Popen.poll", "subprocess.Popen"),
    "Popen.kill": ("Popen.kill", "subprocess.Popen"),
    "Popen.terminate": ("Popen.terminate", "subprocess.Popen"),
    "Popen.communicate": ("Popen.communicate", "subprocess.Popen"),
}

# `ADMITTED_EXIT_STATUS`, read out of the module rather than written here, so a
# change to the number the model exits with is a change to the model and this
# file follows it instead of asserting a stale copy.
def _admitted_exit_status():
    from formal import imports as _I
    import fire_compiler as _F
    for st in _I.module_statements(os.path.join(A.HOSTMODS_ROOT,
                                                "subprocess.mojo")):
        if isinstance(st, _F.AssignStmt) and \
                getattr(st.target, "name", None) == "ADMITTED_EXIT_STATUS":
            return int(getattr(st.value, "value", None))
    raise TestFailure("subprocess.mojo declares no ADMITTED_EXIT_STATUS")

A_ADMITTED_EXIT_STATUS = _admitted_exit_status()


def _construct_ok():
    """CPython's verdict for an argument shape that is entirely valid.

    The real `subprocess` module, imported HERE rather than through a closure
    variable: the first version took it from the enclosing function's `S`, which
    is a `NameError` the moment this is called from anywhere else -- and it was
    called from a table walk, so the group failed on `NameError` rather than on
    anything about `subprocess`.
    """
    import subprocess
    p = subprocess.Popen([sys.executable])
    try:
        p.kill()
    except Exception:  # noqa: BLE001
        pass


def group_ctypes(tmpdir, cas_root, verbose):
    """`ctypes`: the type table and the buffer refusal, against CPython's own."""
    import ctypes as C
    names = [("c_int8", 1), ("c_uint8", 1), ("c_int16", 2), ("c_uint16", 2),
             ("c_int32", 4), ("c_uint32", 4), ("c_int64", 8), ("c_uint64", 8),
             ("c_float", 4), ("c_double", 8), ("c_bool", 1), ("c_char_p", 8),
             ("c_void_p", 8)]
    want = []
    src = ["import ctypes", "", "def main():",
           '    printf("%lld\\n", ' +
           " + ".join(f"ctypes.size_{n}()" for n, _s in names) + " + 0)"]
    # One sum is not a per-name check, so ask for them one at a time.
    src = ["import ctypes", "", "def main():"]
    for n, _s in names:
        src.append(f'    printf("%lld\\n", ctypes.size_{n}())')
    got = _run("ctsz", src, tmpdir, cas_root)
    check(len(got) == len(names),
          f"ctypes: image reported {len(got)} of {len(names)} sizes")
    bad = []
    for (n, _s), g in zip(names, got):
        want_s = C.sizeof(getattr(C, n))
        if int(g) != want_s:
            bad.append(f"{n}: image {g}, CPython sizeof {want_s}")
    check(not bad, "ctypes size table disagrees with CPython:\n    "
                   + "\n    ".join(bad))

    conv_src = ["import ctypes", "", "def main():",
                '    printf("%lld\\n", ctypes.c_int(2147483648))',
                '    printf("%lld\\n", ctypes.c_uint(2147483648))',
                '    printf("%lld\\n", ctypes.c_int(7))',
                '    printf("%lld\\n", ctypes.c_uint(4294967295))',
                '    printf("%lld\\n", ctypes.c_int64_value(0))']
    got = _run("ctcv", conv_src, tmpdir, cas_root)
    want = [C.c_int32(2147483648).value, C.c_uint32(2147483648).value,
            C.c_int32(7).value, C.c_uint32(4294967295).value,
            C.c_int64(0).value]
    bad = [(f"conv {w}", g) for w, g in zip(want, got) if int(g) != w]
    check(not bad,
          "ctypes conversions disagree with CPython: "
          + ", ".join(f"image {g} CPython {w}" for w, g in bad))

    buf = _run("ctbuf", ["import ctypes", "", "def main():",
                         '    printf("%lld %lld %lld\\n", '
                         'ctypes.validate_buffer(2, 5), '
                         'ctypes.validate_buffer(6, 5), '
                         'ctypes.validate_buffer(1, 1))'],
               tmpdir, cas_root)
    def _cp_buf(init_len, size):
        try:
            C.create_string_buffer(b"x" * init_len, size)
            return 0                       # ARG_OK
        except ValueError:
            return 1                       # ARG_BUF_TOO_LONG
    want_buf = " ".join(str(_cp_buf(a, b)) for a, b in ((2, 5), (6, 5), (1, 1)))
    check(buf == [want_buf],
          f"ctypes.validate_buffer: image {buf}, CPython [{want_buf!r}]")

    if verbose:
        print(f"    {len(names)} sizes, 5 conversions, 3 buffer refusals")
    return True, f"ctypes: {len(names)} sizes and 8 decisions agree with CPython"


def group_fcntl(tmpdir, cas_root, verbose):
    """`fcntl`: the whole flag table, against CPython's own module."""
    import fcntl as F
    names = ["LOCK_SH", "LOCK_EX", "LOCK_NB", "LOCK_UN", "F_DUPFD", "F_GETFD",
             "F_SETFD", "F_GETFL", "F_SETFL", "FD_CLOEXEC", "F_DUPFD_CLOEXEC"]
    src = ["import fcntl", "", "def main():"]
    for n in names:
        src.append(f'    printf("%lld\\n", fcntl.{n}())')
    got = _run("fc", src, tmpdir, cas_root)
    bad = []
    for n, g in zip(names, got):
        w = getattr(F, n)
        if int(g) != w:
            bad.append(f"{n}: image {g}, CPython {w}")
    check(not bad, "fcntl flag table disagrees with CPython:\n    "
                   + "\n    ".join(bad))
    if verbose:
        print(f"    {len(names)} flags, each against getattr(fcntl, name)")
    return True, f"fcntl: {len(names)} flags agree with CPython"


def group_futures(tmpdir, cas_root, verbose):
    """`concurrent.futures`: `Future`'s five states, against a live Future.

    CPython's five states are SENTINEL OBJECTS (`concurrent.futures._base.PENDING`
    and friends), not integers, and `Future._state` is one of those objects by
    identity.  So this compares the model's integer against the model's OWN
    mapping of that integer to a state, and separately asserts that the mapping
    is right by driving CPython's own `Future` through its own transitions and
    reading `_state` back.  Asserting the integers were equal -- which the first
    version of this group did, and which is why it failed on
    `type object 'Future' has no attribute 'PENDING'` -- would have been
    comparing a number to a class.
    """
    import concurrent.futures as CF
    from concurrent.futures import _base

    model = {n: model_const("concurrent.futures", n) for n in
             ("FUTURE_PENDING", "FUTURE_RUNNING", "FUTURE_CANCELLED",
              "FUTURE_CANCELLED_AND_NOTIFIED", "FUTURE_FINISHED")}

    # CPython's state -> the model's code for it.  Built from the two dicts above
    # rather than from a literal, so adding a state to either side is a compile
    # error here instead of a silent mismatch.
    pairs = [
        ("FUTURE_PENDING", _base.PENDING),
        ("FUTURE_RUNNING", _base.RUNNING),
        ("FUTURE_CANCELLED", _base.CANCELLED),
        ("FUTURE_CANCELLED_AND_NOTIFIED", _base.CANCELLED_AND_NOTIFIED),
        ("FUTURE_FINISHED", _base.FINISHED),
    ]
    check(sorted(model.values()) == list(range(len(model))),
          f"the model's five state codes must be 0..4 so that a code and an "
          f"index into the state list agree; they are "
          f"{sorted(model.values())}")

    # `from … import *` does NOT bring this module's module-level CONSTANTS into
    # the caller -- measured: the build refuses `FUTURE_PENDING` with "has no
    # home", because the importer materialises a folded constant only for a name
    # the import statement spells.  So they are spelled out.
    NAMES = ["FUTURE_PENDING", "FUTURE_RUNNING", "FUTURE_CANCELLED",
             "FUTURE_CANCELLED_AND_NOTIFIED", "FUTURE_FINISHED",
             "future_state_after_submit", "future_state_after_set_result",
             "future_state_after_cancel", "future_done", "future_running",
             "future_cancelled"]
    src = ["from concurrent.futures import " + ", ".join(NAMES),
           "", "def main():"]
    for name, _cp in pairs:
        src.append(f'    printf("%lld\\n", {name})')

    # Four transitions, each driven on a real Future so the expectation is
    # CPython's answer rather than a reading of the model's docstring.
    f_running = CF.Future()
    f_running.set_running_or_notify_cancel()
    f_done = CF.Future()
    f_done.set_result(1)
    f_cancel = CF.Future()
    f_cancel.cancel()
    f_after = CF.Future()
    f_after.set_running_or_notify_cancel()
    f_after.cancel()          # CPython: cancelling a RUNNING Future is False

    def _code(st):
        for name, cp in pairs:
            if st is cp:
                return model[name]
        raise TestFailure(f"CPython's Future reached a state this table does "
                          f"not name: {st!r}")

    want = [model[n] for n, _cp in pairs] + [
        _code(f_running._state),      # after_submit(PENDING)
        _code(f_done._state),         # after_set_result(RUNNING)
        _code(f_cancel._state),       # after_cancel(PENDING)
        _code(f_after._state),        # after_cancel(RUNNING) -- unchanged
        model["FUTURE_CANCELLED"],    # after_cancel(CANCELLED) -- unchanged
        1,                            # done(FINISHED)
        1,                            # running(RUNNING)
        1,                            # cancelled(CANCELLED)
        1,                            # cancelled(CANCELLED_AND_NOTIFIED)
        0,                            # running(FINISHED)
        0,                            # cancelled(FINISHED)
    ]
    src += ['    printf("%lld\\n", future_state_after_submit(FUTURE_PENDING))',
            '    printf("%lld\\n", future_state_after_set_result('
            'FUTURE_RUNNING))',
            '    printf("%lld\\n", future_state_after_cancel(FUTURE_PENDING))',
            '    printf("%lld\\n", future_state_after_cancel(FUTURE_RUNNING))',
            '    printf("%lld\\n", future_state_after_cancel(FUTURE_CANCELLED))',
            '    printf("%lld\\n", future_done(FUTURE_FINISHED))',
            '    printf("%lld\\n", future_running(FUTURE_RUNNING))',
            '    printf("%lld\\n", future_cancelled(FUTURE_CANCELLED))',
            '    printf("%lld\\n", future_cancelled('
            'FUTURE_CANCELLED_AND_NOTIFIED))',
            '    printf("%lld\\n", future_running(FUTURE_FINISHED))',
            '    printf("%lld\\n", future_cancelled(FUTURE_FINISHED))']
    got = _run("cf", src, tmpdir, cas_root)
    check(len(got) == len(want),
          f"concurrent.futures: image reported {len(got)} of {len(want)}")
    bad = [(i, g, w) for i, (g, w) in enumerate(zip(got, want))
           if int(g) != w]
    check(not bad,
          "concurrent.futures disagrees with a live Future:\n    "
          + "\n    ".join(f"row {i}: image {g}, CPython {w}"
                           for i, g, w in bad))
    check(f_after.cancel() is False,
          "the premise of the `cancel` on RUNNING row: CPython must refuse it, "
          "or the row is testing something else")
    if verbose:
        print(f"    5 states, 4 transitions, 5 predicates — every expectation "
              f"read off a live concurrent.futures.Future")
    return True, ("concurrent.futures: 15 decisions agree with a live Future")


def group_threading(tmpdir, cas_root, verbose):
    """`threading`: `TIMEOUT_MAX` and the timeout check, against CPython's own."""
    import threading as T
    got = _run("th", ["import threading", "", "def main():",
                      '    printf("%lld\\n", threading.TIMEOUT_MAX())',
                      '    printf("%lld\\n", threading.validate_timeout(-1))',
                      '    printf("%lld\\n", threading.validate_timeout(0))',
                      '    printf("%lld\\n", threading.validate_timeout(1))'],
               tmpdir, cas_root)
    check(int(got[0]) == T.TIMEOUT_MAX,
          f"threading.TIMEOUT_MAX: image {got[0]}, CPython {T.TIMEOUT_MAX} — "
          f"and it is a platform fact, not a typo, which is why it is a table "
          f"row rather than a -1")
    def _cp(v):
        try:
            lock = T.Lock()
            if v == 0:
                lock.acquire(timeout=0)
                lock.release()
            else:
                lock.acquire(timeout=v)
                lock.release()
            return 0
        except ValueError:
            return 1
    want = " ".join(str(_cp(v)) for v in (-1, 0, 1))
    check(got[1:] == want.split(),
          f"threading.validate_timeout: image {got[1:]}, CPython [{want!r}]")
    if verbose:
        print(f"    TIMEOUT_MAX and 3 timeout refusals, against CPython's Lock")
    return True, "threading: 4 decisions agree with CPython"


def group_runtime(tmpdir, cas_root, verbose):
    """An admitted call REFUSES, and says WHICH contract refused.

    The runtime half of the policy, and the one that stops `admit` from being a
    licence to invent.  `subprocess.run` on this target cannot answer, so the
    image prints which contract stopped it and exits 125; a refusal that exited 0
    would be a fabricated success wearing a diagnostic's clothes.

    **125 is RESERVED, not out of range**, and this used to assert the opposite.
    The claim it made — that 125 is outside `0..255` and so cannot be read as a
    child's exit status — is false twice over, and both halves are measured right
    here rather than in a comment: a child CAN exit 125, and no exit code is
    outside `0..255` at all.  So the assertions are the two that hold: the
    refusal exits with this tree's reserved nonzero status, and it NAMES the
    contract — which is the channel that actually distinguishes a refusal from an
    answer.  `group_truth`'s `_exit_status_claims` keeps the tree from putting the
    false sentence back.
    """
    src = os.path.join(tmpdir, "sp_run.mojo")
    with open(src, "w") as f:
        f.write('import subprocess\n\ndef main() -> int:\n'
                '    return subprocess.run("ls -l")\n')
    out = os.path.join(tmpdir, "sp_run.aout")
    home = os.path.join(cas_root, "rt")
    os.makedirs(home, exist_ok=True)
    r = run_fire(["build", "--formal", "--no-prove", "--backend=arm64",
                  "-o", out, src], env={"GMOJO_HOME": home})
    check(r.returncode == 0, "the admitted-call image did not build:\n    "
          f"{(r.stderr or r.stdout or '').strip()[:300]}")
    p = subprocess.run([out], capture_output=True, text=True, timeout=60)
    check(p.returncode == A_ADMITTED_EXIT_STATUS,
          f"subprocess.run exited {p.returncode}; it must exit "
          f"{A_ADMITTED_EXIT_STATUS}, this tree's reserved refusal status. It is "
          f"NOT outside 0..255 and cannot be: the kernel masks every exit code "
          f"into that range, and a child can exit "
          f"{A_ADMITTED_EXIT_STATUS} like any other — which is why the check "
          f"below, that the refusal NAMES its contract, is the one that "
          f"distinguishes it from an answer.")
    # The two measurements the corrected claim rests on.  Asserted rather than
    # assumed: a comment that says "125 is a legal child status" is worth
    # exactly as much as the next run, and this is the next run.
    child_125 = subprocess.run(["/bin/sh", "-c", "exit 125"],
                               capture_output=True).returncode
    check(child_125 == 125,
          f"a child that exits 125 is reported by CPython as {child_125}, so "
          f"the reserved status is inside the legal range after all and "
          f"whatever this file says about it is wrong")
    child_300 = subprocess.run(["/bin/sh", "-c", "exit 300"],
                               capture_output=True).returncode
    check(0 <= child_300 <= 255,
          f"a child that exits 300 is reported as {child_300}; the kernel is "
          f"supposed to mask it into 0..255, and if it does not then a status "
          f"outside the range IS available and this tree should use one")
    check("ADMITTED contract" in p.stdout,
          f"the refusal must NAME the contract that stopped it; stdout was "
          f"{p.stdout[:200]!r}")
    if verbose:
        print(f"    exit {p.returncode}, stdout names the contract")
    return True, (f"an admitted call refuses with the reserved status "
                  f"{p.returncode} and names its contract; a child can exit "
                  f"{A_ADMITTED_EXIT_STATUS} too, so the name is what "
                  f"identifies the refusal")


def _run(name, src_lines, tmpdir, cas_root, backend="arm64"):
    return _module_source(src_lines, name, None, tmpdir, cas_root, backend)


GROUPS = {
    "registry": group_registry,
    "scope": group_scope,
    "truth": group_truth,
    "counts": group_counts,
    "emitted": group_emitted,
    "subprocess": group_subprocess,
    "subprocess-surface": group_subprocess_surface,
    "ctypes": group_ctypes,
    "fcntl": group_fcntl,
    "futures": group_futures,
    "threading": group_threading,
    "runtime": group_runtime,
}

# The pure-Python checks, run in `main` alongside the groups so a run with no
# group still ratchets.
def _spelled_surface():
    """`({name: {keywords}}, {names read as a VALUE})` over every `subprocess.*`.

    TWO SETS, and the split is the point rather than bookkeeping.  A name
    CALLED is answered by a function the model declares, and its keywords have to
    be that function's parameters.  A name READ AS A VALUE — `stdout=subprocess.
    PIPE`, `except subprocess.SubprocessError:` — is answered by nothing the
    model can declare: a function is not a word and a class is a frame blob, so
    those sites need
    `bugs/FORMAL_module_state_no_storage.md` rather than a parameter.  Counting
    both as "the tree spells this name" hid half the gap, which is the mistake
    this rewrite exists to remove.

    Read with `ast` over every `.py` under the repository, because the number it
    produces is the number `formal/hostmods/subprocess.mojo`'s docstring quotes
    and `test_the_modelled_surface_covers_what_the_tree_spells` checks against.
    One walk, one implementation, two consumers — a second `ast` pass in the
    ratchet would be free to disagree with the one that wrote the docstring, and
    the disagreement would be a call site nobody modelled.

    `build/`, `cas/` and `.tmp/` are skipped because they are OUTPUT: a compiled
    artifact or a leftover work directory spelling `subprocess` measures nothing
    about the source.
    """
    import ast
    skip = {"build", "cas", ".git", ".tmp", "__pycache__", "node_modules"}
    calls = {}
    value_reads = set()
    for dirpath, dirs, files in os.walk(HERE):
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                tree = ast.parse(open(path, encoding="utf-8",
                                      errors="replace").read())
            except SyntaxError:
                continue
            called = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fnode = node.func
                if not (isinstance(fnode, ast.Attribute)
                        and isinstance(fnode.value, ast.Name)
                        and fnode.value.id == "subprocess"):
                    continue
                called.add(fnode.attr)
                calls.setdefault(fnode.attr, set()).update(
                    k.arg for k in node.keywords if k.arg)
            # Every `subprocess.<name>` that is NOT the callee of a call is a
            # value read, and `ast.walk` visits the `Attribute` either way.
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "subprocess"):
                    continue
                if node.attr not in called:
                    value_reads.add(node.attr)
    return calls, value_reads


def _modelled_subprocess_names():
    """The names `formal/hostmods/subprocess.mojo` actually declares.

    From the PARSED module rather than a list here, for the reason `model_const`
    gives: a list in this file is a second place for the model's surface to be
    wrong in without anything noticing, which is how a differential test stops
    being differential.
    """
    from formal import imports as I
    import fire_compiler as F
    path = os.path.join(A.HOSTMODS_ROOT, "subprocess.mojo")
    names = set()
    for st in I.module_statements(path):
        if isinstance(st, F.FunctionDef) and st.name:
            names.add(st.name)
    return names


# The `subprocess.` names this tree READS AS A VALUE, which
# `formal/hostmods/subprocess.mojo` deliberately does not answer, each with the
# reason.  The model declares all three constants as zero-argument FUNCTIONS —
# `subprocess.PIPE()` binds and `stdout=subprocess.PIPE` does not, because a
# function is not a word and a module-level name is folded at every read on this
# path.  A name reaching this table is a DELIBERATE absence somebody wrote
# down; a value-read in neither the model nor this table is a FAILURE.
_SUBPROCESS_VALUE_ABSENT = {
    "PIPE": "the constant is a FUNCTION here (`PIPE()` binds); reading it as a "
            "value needs a module-level name that is a folded literal — "
            "bugs/FORMAL_module_state_no_storage.md",
    "STDOUT": "as PIPE",
    "DEVNULL": "as PIPE",
    "SubprocessError": "a catchable TYPE, and a class on this path is a frame "
                       "blob (formal/hostmods/struct.mojo is what a struct "
                       "looks like)",
    # `except subprocess.TimeoutExpired:` needs the CLASS.  An arm whose body is
    # `raise`/`pass`/`continue`/`break` still builds today — the arm is not
    # lowered, and the refusal `formal/build.py` prints is about the ARM's body
    # (FORMAL.md phase 7, no exception unwinder), not about this name — so the
    # 81 sites in this tree are blocked on the unwinder, not on the name.  The
    # model's `TimeoutExpired` FUNCTION covers the `subprocess.TimeoutExpired(…)`
    # construction sites; this row covers the 81 that want the type.
    "TimeoutExpired": "the EXCEPTION CLASS an `except` arm names; the model's "
                      "TimeoutExpired function covers construction, not "
                      "catchability (FORMAL.md phase 7)",
}


def test_the_modelled_surface_covers_what_the_tree_spells(tmpdir=None):
    """Every `subprocess.*` this tree writes is either modelled or written down.

    The ratchet that keeps `subprocess.mojo` from drifting away from its callers,
    and it is the only one of these checks that would notice a NEW call site.  The
    differential tables above test the model's verdicts and the surface group
    tests that a hand-written selection of calls bind; neither can notice that
    somebody started calling `subprocess.run(..., newflag=True)` tomorrow, because
    nothing here knows what the tree spells.

    The failure it is aimed at is the one the `subprocess` row of the host-import
    ranking records (`bugs/FORMAL_subprocess_row_measured_b7.md`, measured over
    all 143 importing files): a module that is "modelled" for nobody, green in
    every differential test, and callable by zero of its callers.  A keyword the callers
    use and the model does not declare is exactly that, and it is invisible until
    somebody counts the call sites — which is what this does.
    """
    spelled, value_reads = _spelled_surface()
    modelled = _modelled_subprocess_names()
    check(spelled,
          "the walk found no `subprocess.*` call at all, so it is not "
          "measuring what it claims — the skip list or the AST walk is wrong")
    undeclared = sorted(n for n in spelled if n not in modelled)
    check(not undeclared,
          "this tree CALLS `subprocess.` names that formal/hostmods/subprocess."
          "mojo does not declare: " + ", ".join(undeclared) + "\n"
          "    A name here is a call site nothing answers: the build refuses it "
          "with `exports no <name>` and a differential test stays green, which "
          "is the failure the subprocess row of that ranking names. "
          "Declare it, or record why not.")
    # The KEYWORDS are the half that bit: `run` was declared with one parameter
    # and 508 of these call sites pass `capture_output`.  Checked per function,
    # because the model's `run` and its `call` take different keywords and CPython
    # refuses the ones they do not have.
    bad_kw = []
    for fn_name, kws in sorted(spelled.items()):
        declared = _modelled_subprocess_params(fn_name)
        if declared is None:
            continue
        for kw in sorted(kws):
            if kw not in declared:
                bad_kw.append(f"subprocess.{fn_name}(..., {kw}=...): the model "
                              f"declares no `{kw}`")
    check(not bad_kw,
          "keywords this tree passes that the model does not declare:\n    "
          + "\n    ".join(bad_kw)
          + "\n    Each is a build refusal at every call site that uses it. The "
            "parameters are read out of the module source, so this cannot "
            "disagree with what the model publishes.")
    # The value reads are the second half and they are NOT satisfied by a
    # function of the same name: `stdout=subprocess.PIPE` needs a WORD and
    # `subprocess.PIPE` is a function, so the call site is refused while
    # `subprocess.PIPE()` beside it builds.  That is the whole
    # `FORMAL_module_state_no_storage.md` gap, and a ratchet that treated the
    # name as covered would be green over six refused call sites.
    unexplained = sorted(n for n in value_reads
                         if n not in _SUBPROCESS_VALUE_ABSENT)
    check(not unexplained,
          "this tree READS `subprocess.` names as VALUES that nothing answers: "
          + ", ".join(unexplained) + "\n"
          "    A value read needs a folded module-level literal, not a "
          "function (bugs/FORMAL_module_state_no_storage.md), so declaring one "
          "does not cover it. Record it in _SUBPROCESS_VALUE_ABSENT with the "
          "reason, or fix the module-state gap.")
    stale = sorted(n for n in _SUBPROCESS_VALUE_ABSENT if n not in value_reads)
    check(not stale,
          "_SUBPROCESS_VALUE_ABSENT records names the tree no longer reads as a "
          f"value: {stale}. A row nobody reads is a claim about the callers "
          "that stopped being true, which is the same failure `expect=` on a "
          "test that starts passing is there to report.")
    return True, (f"{len(spelled)} called `subprocess.` name(s) with "
                  f"{sum(len(v) for v in spelled.values())} keyword(s), all "
                  f"modelled with matching parameters; "
                  f"{len(value_reads)} value-read name(s), all recorded absent "
                  f"({sorted(value_reads)})")


def _modelled_subprocess_params(name):
    """The parameter names `formal/hostmods/subprocess.mojo` gives `name`, or None.

    None means the name is not a modelled FUNCTION (a constant read as a value,
    or a type), and there is no parameter list to compare against — the caller
    handles that case in `_SUBPROCESS_ABSENT`.
    """
    from formal import imports as I
    import fire_compiler as F
    path = os.path.join(A.HOSTMODS_ROOT, "subprocess.mojo")
    for st in I.module_statements(path):
        if not (isinstance(st, F.FunctionDef) and st.name == name):
            continue
        out = set()
        for p in (getattr(st, "params", None) or []):
            if isinstance(p, (tuple, list)) and p and isinstance(p[0], str):
                out.add(p[0])
        return out
    return None


PURE = [("the emitted Lean is inert where nothing is admitted",
         test_a_file_that_reaches_none_generates_no_hole),
        ("the modelled surface covers what the tree spells",
         test_the_modelled_surface_covers_what_the_tree_spells),
        ("every scope rule refuses and admits what it was written for",
         test_the_scope_probes_refuse_what_they_are_written_for),
        ("every admitted contract has a truth row",
         test_every_contract_has_a_truth_row),
        ("every truth probe rejects the pre-audit text",
         test_the_truth_probes_reject_the_pre_audit_text),
        ("every contract points at its own declaration",
         test_every_contract_points_at_its_own_declaration),
        ("the Lean library's trust counts are pinned",
         test_the_library_trust_counts_are_pinned),
        ("every tactic site belongs to a named theorem",
         test_the_library_trust_is_attributed_to_a_declaration),
        ("native_decide is only where decide cannot go",
         test_native_decide_is_only_where_decide_cannot_go),
        ("the replaced native_decide count is what it claims",
         test_the_replaced_native_decide_count_is_what_it_claims),
        ("the census is attributed to theorems, not only to lines",
         test_the_census_is_attributed_to_theorems_not_only_to_lines),


        ("the source half of the closure census is readable",
         test_the_source_half_of_the_closure_census_is_readable),
        ("the axiom names are classified, not guessed",
         test_the_axiom_names_are_classified_not_guessed),
        ("every native axiom in lib/ is one this file knows",
         test_every_native_axiom_in_lib_is_one_this_file_knows),
        ("FORMAL.md's inventory is the census",
         test_the_formal_md_inventory_agrees)]


def _pure_call(fn, tmpdir):
    """A PURE check is called with the temp dir the GROUPS get.

    It needs one: `compile_formal` writes an image, and a check that compared two
    generators' output has to build the program first.  Passing it explicitly is
    better than the check making its own temp directory, because then every image
    this file writes lands in the one place the run cleans up.
    """


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="run only these groups")
    args = ap.parse_args()
    if args.groups:
        unknown = [g for g in args.groups if g not in GROUPS]
        if unknown:
            print(f"unknown group(s): {unknown}; have {sorted(GROUPS)}")
            return 2

    cas_root = tempfile.mkdtemp(prefix="admitted_",
                                dir=os.environ.get("TMPDIR") or None)
    passed = failed = skipped = 0
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, fn in PURE:
                try:
                    _ok, note = fn(tmpdir)
                except TestFailure as e:
                    failed += 1
                    print(f"  FAIL  {name}\n        {e}")
                    continue
                except Exception as e:  # noqa: BLE001
                    note = str(e)
                    if note.startswith("SKIPPED"):
                        skipped += 1
                        print(f"  SKIP  {name}\n        {note}")
                        continue
                    failed += 1
                    print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                    continue
                passed += 1
                print(f"  PASS  {name}\n        {note}")

            selected = args.groups or list(GROUPS)
            for gname in selected:
                fn = GROUPS[gname]
                try:
                    _ok, note = fn(tmpdir, cas_root, args.verbose)
                except (TestFailure, Failure) as e:
                    failed += 1
                    print(f"  FAIL  {gname}\n        {e}")
                    continue
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"  ERROR {gname}\n        {type(e).__name__}: {e}")
                    if args.verbose:
                        import traceback
                        traceback.print_exc()
                    continue
                passed += 1
                print(f"  PASS  {gname}\n        {note}")
    finally:
        import shutil
        shutil.rmtree(cas_root, ignore_errors=True)

    total = sum(A.counts_by_module().values())
    print(f"\nadmitted contracts: PASS={passed} FAIL={failed} SKIP={skipped}  "
          f"({total} declared across {len(A.hostmod_files())} hostmod modules)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
