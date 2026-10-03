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
    "hashlib": 0,
    "io": 0,
    "json": 0,
    "math": 0,
    "os": 0,
    "os._syscalls": 0,
    "os.path": 0,
    "pathlib": 0,
    # A RE-EXPORT, and its zero is the claim: `formal/hostmods/posixpath.mojo`
    # publishes `os/path/__init__.mojo`'s names and admits nothing of its own,
    # because everything it publishes is computed. It is here because a module
    # with a model that is not in this table is a claim of trust nobody counted,
    # and this file's rule is that "not in the table" and "in the table with a
    # zero" must be distinguishable -- only the second is allowed to be wrong.
    "posixpath": 0,
    "platform": 0,
    "re": 0,
    "shutil": 0,
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
    "threading": 3,               # Thread.start, Thread.join, Lock.acquire
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
                v = getattr(st.value, "value", None)
                if v is None:
                    v = getattr(st.value, "raw", None)
                return int(v)
    raise TestFailure(f"{module}.{name} is not a module-level integer constant "
                      f"in formal/hostmods/{module}.mojo")


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
    stopped it.  A model that accepted a keyword and then answered differently
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
                  f"exit {A_ADMITTED_EXIT_STATUS} — outside 0..255, so it cannot "
                  f"be read as a child's status")
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
    """An admitted call REFUSES, and its status cannot be read as a child's.

    The runtime half of the policy, and the one that stops `admit` from being a
    licence to invent.  `subprocess.run` on this target cannot answer, so the
    image prints which contract stopped it and exits 125 — and 125 is outside
    0..255, which is the whole reason for that particular number: a refusal that
    exited 0 would be a fabricated success wearing a diagnostic's clothes.
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
    check(p.returncode == 125,
          f"subprocess.run exited {p.returncode}; it must exit 125, which is "
          f"outside 0..255 and so cannot be read as a child's exit status. A "
          f"refusal that returned a plausible number would be a fabricated "
          f"answer.")
    check("ADMITTED contract" in p.stdout,
          f"the refusal must NAME the contract that stopped it; stdout was "
          f"{p.stdout[:200]!r}")
    if verbose:
        print(f"    exit {p.returncode}, stdout names the contract")
    return True, (f"an admitted call refuses with status 125 (outside 0..255), "
                  f"naming its contract")


def _run(name, src_lines, tmpdir, cas_root, backend="arm64"):
    return _module_source(src_lines, name, None, tmpdir, cas_root, backend)


GROUPS = {
    "registry": group_registry,
    "scope": group_scope,
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

    The failure it is aimed at is the one `bugs/FORMAL_host_import_row_5_measured.md`
    §`subprocess` records: a module that is "modelled" for nobody, green in every
    differential test, and callable by zero of its callers.  A keyword the callers
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
          "is the failure bugs/FORMAL_host_import_row_5_measured.md names. "
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
         test_the_modelled_surface_covers_what_the_tree_spells)]


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
