#!/usr/bin/env python3
"""What CPython says each standard-library module IS, and what that is worth.

    export PATH=/opt/homebrew/bin:$PATH
    python3 tools/memslot.py --gb 8 --label reach -- \
      python3 tools/formal_stdlib_reach.py
    python3 tools/memslot.py --gb 8 --label reach -- \
      python3 tools/formal_stdlib_reach.py --unclassified
    python3 tools/memslot.py --gb 8 --label reach -- \
      python3 tools/formal_stdlib_reach.py --name sqlite3 --name _hashlib
    python3 tools/memslot.py --gb 8 --label reach -- \
      python3 tools/formal_stdlib_reach.py --check     # non-zero if a row is stale

**This is the measurement `bugs/formal/FORMAL_stdlib_module_names_are_not_classified.md`
§0.3 promised for the 216-name queue, run and recorded.** That section's next
step says a name whose spec CPython cannot find here is `unreachable` by the
rule, "and a name whose spec it can is `modelled` unless the content is not
code". The first half is right and is now in `formal/imports.py` (five names).
**The second half is wrong, and this tool is why** — it is the measurement that
falsifies it, so nobody re-derives it from `find_spec` a second time:

| the name | `find_spec` says | the dylib it links | the rule at the top of `formal/imports.py` |
|---|---|---|---|
| `sqlite3` | a spec EXISTS, pure python | `libsqlite3.dylib` via `_sqlite3` | needs a library outside libSystem → `unreachable` |
| `ssl` | a spec EXISTS | `libssl.3.dylib`, `libcrypto.3.dylib` | → `unreachable` |
| `bz2` | a spec EXISTS | `libbz2.1.0.dylib` | → `unreachable` |
| `lzma` | a spec EXISTS | `liblzma.5.dylib` | → `unreachable` |
| `_hashlib` | a spec EXISTS | `libcrypto.3.dylib` | …and yet `hashlib` is ANSWERED by `formal/hostmods/hashlib.mojo`, so the capability needs no object: `modelled` |

So `find_spec` cannot decide `modelled`, and the dynamic dependencies cannot
decide it either — the last row is a library outside libSystem whose capability
this tree has already implemented. **A library outside libSystem is a fact about
CPython's packaging; an object the target does not have is a fact about the
target, and only the second is a tier.** That is why
`formal/imports.py::capability_sibling_tier` derives from the tables and asks
the interpreter nothing.

What this tool IS, then, is the evidence printer for the part that is still
undecided: for every name CPython ships, what `find_spec` says, what kind of
implementation CPython gives it, which dynamic libraries it binds outside
libSystem, and what `formal/imports.py` answers. The residue between the
evidence and the tables is the queue, printed rather than described — which is
the difference §0.1 asks for when it says "the queue for the 222 is a bounded
piece of per-name work with the readings §'The next step' already lists".

**What it deliberately does not do is classify anything.** A row this tool
prints is evidence, and the tier a name lands in is a claim made by the rule in
`formal/imports.py` and by nothing else — including this tool. `--check` is the
anti-rot half: it re-derives the evidence and fails when a name's ANSWER is not
one the table and the rule can both produce, which is what stops the tables and
this file from coming apart as CPython moves a module between a `.py` and a
`.so`.

Mach-O only: the dynamic-library reading is `otool -L`, and where `otool` is
absent the reading is reported as unavailable rather than guessed. Nothing here
is needed to build anything — the tiers are hand-checked in
`formal/imports.py`, and this is what a change to them is checked against.
"""

import argparse
import importlib.util
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import formal.imports as I                                        # noqa: E402

# What the target links, and what a row is compared against. `formal/build.py`'s
# `macho_linker.LIBSYSTEM_PATH` is the same file; the basename is compared
# because that is what a load command carries.
LIBSYSTEM = "libSystem.B.dylib"


def find_spec_origin(name):
    """`(kind, detail)` — what CPython on THIS host can find for `name`.

    | kind | meaning |
    |---|---|
    | `absent` | `importlib.util.find_spec` found nothing: CPython cannot provide the module here either, so neither can a target that is a subset of this host |
    | `builtin` / `frozen` | compiled into the interpreter or frozen into its stdlib zip |
    | `source` | a `.py` file — pure computation plus whatever its imports reach |
    | `binary` | a C extension, and the dynamic libraries below are the interesting part |

    The interpreter raises for a name it considers malformed rather than
    answering, so an exception is `absent`: the caller asked whether this host
    can provide it and the answer is no.
    """
    try:
        spec = importlib.util.find_spec(name)
    except Exception:
        return ("absent", "find_spec raised")
    if spec is None:
        return ("absent", "no spec")
    origin = spec.origin
    if origin in ("built-in", "frozen"):
        return ("builtin", origin)
    if not origin:
        return ("absent", f"spec with no origin ({spec!r})")
    if origin.endswith(".py"):
        return ("source", origin)
    return ("binary", origin)


def libraries_outside_libsystem(path):
    """The `LC_LOAD_DYLIB` names of a Mach-O file that are not libSystem.

    `otool -L` rather than a Mach-O reader of this repository's own, because
    `formal/macho.py` is a BUILDER (its module docstring says so) and
    `formal/elf.py` reads ELF; a 30-line load-command walk would be a third
    reader of a format this repository already delegates. `None` means the
    reading was UNAVAILABLE, which is a third answer and not an empty list: a
    reader that cannot read must not report "no library outside libSystem",
    which is the reading that would put a name in `modelled`.
    """
    try:
        out = subprocess.run(["otool", "-L", path], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    names = []
    for line in out.stdout.splitlines()[1:]:
        token = line.strip().split(" ")[0]
        if not token:
            continue
        base = os.path.basename(token)
        if base != LIBSYSTEM and base not in names:
            names.append(base)
    return sorted(names)


def evidence(name):
    """Every reading of one name, as a dict — the row this tool prints.

    `tier` and `derived` are the two halves of `formal/imports.py`'s answer:
    `tier` is the hand-kept table membership and `derived` is what
    `capability_sibling_tier` concluded on top of it, so a reader can see which
    of the two settled a name without having to know which function ran.
    """
    kind, detail = find_spec_origin(name)
    libs = libraries_outside_libsystem(detail) if kind == "binary" else []
    public = name.lstrip("_")
    sibling = public if public and public != name else ""
    return {
        "name": name,
        "kind": kind,
        "origin": detail,
        "libs": libs,
        "sibling": sibling,
        "sibling_tier": I.host_module_tier(sibling) if sibling else "",
        "sibling_source": (I.resolve_module_path(sibling) or "") if sibling else "",
        "tier": I._hand_kept_tier(name),
        "derived": I.capability_sibling_tier(name),
        "answer": I.host_module_tier(name),
        "verdict": I.host_module_verdict(name)[0],
    }


def _fmt(row):
    libs = (",".join(row["libs"]) if row["libs"] is not None
            else ("unavailable" if row["kind"] == "binary" else ""))
    why = row["tier"] or (f"derived from {row['sibling']}"
                          if row["derived"] else "")
    return (f"{row['name']:<24} {row['verdict']:<13} {row['kind']:<8} "
            f"{libs:<38} {why}")


def unclassified_names():
    """The queue: CPython ships it and nothing here says which tier it is.

    Read through `host_module_verdict`, which is the ONE classification of a
    name — including the `written` arm, so a name this tree has a source for is
    not counted as a gap (the doc's §0.2 records that getting this wrong was the
    first version of its own census test's bug).
    """
    names = getattr(sys, "stdlib_module_names", None)
    if not names:
        return []
    return [n for n in sorted(names)
            if I.host_module_verdict(n)[0] == "unclassified"]


def check():
    """The anti-rot half. Returns a list of complaints (empty is correct).

    Two invariants, both about the tables and this file not drifting apart:

    1. **A name with no spec must be in `HOST_UNREACHABLE`.** This is the rule
       the eleven names of 2026-10-05 and the five of 2026-10-05 were placed
       by, and it is the only reading in the table that is both measured and
       sound in the direction it claims: the target is a subset of this host, so
       a name this host's own CPython cannot provide is a name nothing here
       could have implemented. If CPython stops shipping one, the entry is
       harmless; if CPython starts shipping one, the table needs the name and
       this fails.
    2. **A name whose public sibling is classified must answer with a tier.**
       That is `capability_sibling_tier` being wired into `host_module_tier` at
       all, and it is checked over every name rather than over a list, so a rule
       that stopped firing would fail here instead of quietly lengthening the
       queue.

    What is deliberately NOT checked: whether a name with a spec and no library
    outside libSystem should be `modelled`. That is the judgement
    `bugs/formal/FORMAL_stdlib_module_names_are_not_classified.md` leaves open, and the
    reason it is not machine-decidable is in that doc's §0.5 — measured over the
    whole stdlib with three named mechanisms, none of which is a bug in this
    tool.
    """
    problems = []
    for name in sorted(getattr(sys, "stdlib_module_names", ()) or ()):
        row = evidence(name)
        if row["kind"] == "absent" and row["answer"] != "unreachable":
            problems.append(
                f"{name}: CPython cannot provide it on this host (find_spec "
                f"-> {row['origin']}) and the tier answer is "
                f"{row['answer']!r}; the rule at the top of formal/imports.py "
                f"puts such a name in HOST_UNREACHABLE, and a target is a "
                f"subset of this host")
        if row["sibling"] and (row["sibling_tier"] or row["sibling_source"]) \
                and not row["answer"]:
            problems.append(
                f"{name}: its public sibling {row['sibling']} is classified "
                f"({row['sibling_tier'] or 'written'}) and this name answers "
                f"no tier, so capability_sibling_tier did not fire")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", action="append", default=[], metavar="N",
                    help="report only this name (repeatable)")
    ap.add_argument("--unclassified", action="store_true",
                    help="report only the queue — the names in no tier")
    ap.add_argument("--check", action="store_true",
                    help="assert the two invariants and exit non-zero if not")
    args = ap.parse_args(argv)

    if args.check:
        problems = check()
        for p in problems:
            print(f"FAIL  {p}")
        print(f"{'OK' if not problems else 'FAIL'}: "
              f"{len(problems)} problem(s); "
              f"{len(unclassified_names())} name(s) in no tier")
        return 1 if problems else 0

    if args.name:
        rows = [evidence(n) for n in args.name]
    elif args.unclassified:
        rows = [evidence(n) for n in unclassified_names()]
    else:
        rows = [evidence(n)
                for n in sorted(getattr(sys, "stdlib_module_names", ()) or ())]
    print(f"{'name':<24} {'answer':<13} {'kind':<8} "
          f"{'libraries outside libSystem':<38} why")
    for row in rows:
        print(_fmt(row))
    if not args.name:
        print(f"\n{len(rows)} name(s); {len(unclassified_names())} in no tier")
    return 0


if __name__ == "__main__":
    sys.exit(main())