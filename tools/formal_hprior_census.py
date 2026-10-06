#!/usr/bin/env python3
"""Where the EMISSION goes in a whole-program arm64 certificate, per family.

One measurement, and it is a walk over a generated `.lean`: nothing here runs
Lean, and nothing here compiles anything. That is the point — the question this
tool answers ("how many times does the generator emit a fact, and how many of
those are identical?") is about the generator's OUTPUT, so the output is the
artefact and reading it is cheaper and more exact than reasoning about the
generator.

**Why it exists.** `bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`
measured the growth and named ONE family as the cause: "`hprior` is the only row
that grows faster than 2x per branch". That is true and it is not sufficient,
which is what this tool shows. Every per-path block local grows 2x per branch
too — `hsid`, `hexit`, `h_adv`, `hrun_ex`, `hcert` are all emitted once per PATH
that reaches their block — so the exponential is structural and `hprior` is one
consumer of it. At five conditional branches `hprior` is 384 of 7 329 `have`
lines: 5%. Hoisting the `hprior` facts alone, which is what the doc's step 1
proposes, would remove 5% of the emission and leave the kernel OOM where it is.

The DUPLICATE column is the other half, and it is the strongest single argument
for hoisting rather than for anything cleverer: it counts how many of each
family's facts carry a statement another one also carries. Those copies are not
merely similar, they are the same fact proved again.

Run it over proofs you already have, or generate some without running Lean at
all — the check is stubbed, so nothing is handed to the kernel:

    python3 tools/formal_hprior_census.py .tmp/tb/b3_proof.lean
    # …or generate the family, which is four five-line programs:
    python3 - <<'PY'
    import formal.lean as L; L.check_proof_cached = lambda *a, **k: (True, "gen", False, 0)
    import fire, sys; sys.argv = ["fire.py", "build", "--formal", "-o", ".tmp/tb/b3.out",
                                  "--backend=arm64", ".tmp/tb/b3.mojo"]
    fire.main()
    PY
    python3 tools/formal_hprior_census.py .tmp/tb/b3_proof.lean

Prints one table per file and a growth summary when several are given.
"""
import collections
import os
import re
import sys

# A `have NAME :` line. The NAME is taken whole — the generator's facts are
# `hprior_4_2_n`, `h_adv_4`, `hrun_ex_4` and `hsid_4`, so no single regex
# splits a family prefix off them, and the family is matched against a list
# below instead.
HAVE_RE = re.compile(r"^\s*have\s+(?P<name>\S+?)\s*:", re.M)
# The STATEMENT of a fact, for the duplicate count: everything from the `:` to
# the `:=` that ends a `have`, read across lines because a long statement wraps.
STMT_RE = re.compile(r"^\s*have\s+(?P<name>\S+)\s*:(?P<stmt>.*?)\s*:=", re.S | re.M)

# The families this tool reports on. Matched LONGEST-FIRST against a fact's
# name, and a name matches a family only when the next character is `_`, a digit
# or the end — so `h` (the `_hvar_…`-style scratch names) cannot claim
# `hprior`/`hsid` and `hp` cannot claim `hpc`. The list is this file's to keep
# because the generator's prefixes are its own; a family the generator adds is
# counted under `other` until it is named here, which is visible in the output
# rather than silent.
PER_PATH_FAMILIES = (
    "hrun_ex", "h_adv", "hprior", "hsid", "hcert", "hexit", "hpc_s", "hx30",
    "hcbz", "hcond", "hinsn", "hjump", "hself", "heq", "hpc", "hs", "hg",
    "hw", "hsrc",
)


def family_of(name):
    """The family prefix of a fact name, or the name itself when it is none."""
    for fam in sorted(PER_PATH_FAMILIES, key=len, reverse=True):
        if name == fam or name.startswith(fam + "_") \
                or (name.startswith(fam) and name[len(fam):len(fam) + 1].isdigit()):
            return fam
    return name


def census(path):
    """`(lines, {family: count}, {family: duplicate count})` for one proof."""
    with open(path) as f:
        text = f.read()
    lines = text.splitlines()
    counts = collections.Counter()
    for m in HAVE_RE.finditer(text):
        counts[family_of(m.group("name"))] += 1
    # Statements are read across the whole text, so a `have` whose statement
    # wraps is still ONE statement. `by` and `where` bodies are excluded by
    # stopping at the first `:=`, which is where a fact's statement ends.
    # A LIST and not a set: the duplicates this tool exists to count are
    # INTRA-family (the same fact emitted again on another path), so collapsing
    # the names of one statement into a set would delete every one of them.
    statements = collections.defaultdict(list)
    for m in STMT_RE.finditer(text):
        stmt = " ".join(m.group("stmt").split())
        if stmt:
            statements[stmt].append(family_of(m.group("name")))
    # A duplicate is a statement that appears more than once, counted per extra
    # occurrence, which is what a hoist would remove.
    dup_total = sum(max(0, len(v) - 1) for v in statements.values())
    return len(lines), counts, statements, dup_total


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 0
    for path in args:
        if not os.path.exists(path):
            print(f"no such proof file: {path}", file=sys.stderr)
            return 2
    tables = []
    for path in args:
        lines, counts, statements, dup_total = census(path)
        distinct = len(statements)
        # Each duplicate is charged ONCE, to the family of the first
        # occurrence. Charging it to every family that spells the same statement
        # would make the column sum to more than the total (measured: `hsrc`'s
        # 120 facts charged 2 600), which is a table that cannot be read.
        dup_by_family = collections.Counter()
        for _stmt, fams in statements.items():
            if len(fams) > 1:
                dup_by_family[fams[0]] += len(fams) - 1
        have_total = sum(counts.values())
        print(f"\n{os.path.basename(path)}: {lines} lines, "
              f"{have_total} `have` lines, {distinct} distinct statements, "
              f"{dup_total} duplicated statements")
        print(f"  {'family':12s} {'count':>7s} {'dup':>7s} {'share':>7s}")
        for fam in PER_PATH_FAMILIES:
            if counts.get(fam):
                print(f"  {fam:12s} {counts[fam]:7d} {dup_by_family.get(fam, 0):7d} "
                      f"{counts[fam] / have_total * 100:6.1f}%")
        rest = {k: v for k, v in counts.items() if k not in PER_PATH_FAMILIES}
        if rest:
            top = sorted(rest.items(), key=lambda kv: -kv[1])[:8]
            print("  other: " + ", ".join(f"{k}={v}" for k, v in top))
        if dup_total:
            print(f"  a HOIST of every duplicated statement would remove "
                  f"{dup_total} of {have_total} `have` lines "
                  f"({dup_total / have_total * 100:.0f}%)")
        tables.append((os.path.basename(path), counts, have_total))
    if len(tables) > 1:
        print("\ngrowth (count per file):")
        print(f"  {'family':12s} " + " ".join(f"{n:>12s}" for n, _c, _t in tables))
        for fam in PER_PATH_FAMILIES:
            row = [counts.get(fam, 0) for _n, counts, _t in tables]
            if any(row):
                print(f"  {fam:12s} " + " ".join(f"{v:12d}" for v in row))
        print(f"  {'ALL have':12s} " + " ".join(f"{t:12d}" for _n, _c, t in tables))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))