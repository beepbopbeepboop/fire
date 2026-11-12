"""Verify the 'Needs integration' table in recover/save.md mechanically.

Checks, for all rows of the table (run from the worktree root):
  1. The table has 114 rows, each with 7 cells, and a Disposition cell whose
     first word is one of ALREADY-ON-MASTER, OBSOLETE, APPLIED, BUG-DOC.
  2. Every bugs/mid/RECOVER_*.md named in a Disposition cell exists, and every
     BUG-DOC cell names one.
  3. Every hex sha cited in an ALREADY-ON-MASTER, OBSOLETE or APPLIED cell is
     one of: an ancestor of master or HEAD; a blob; a patch-id value (the cell
     writes 'patch-id' just before it); or the dangling sha of a row in the
     table (its own commit, or a sibling row's). Anything else is reported.
  4. The recount by disposition, printed once.

Exit 0 when nothing is reported, 1 otherwise. Reads only; runs git read-only
commands. Usage:
    python3 -I recover/verify_table.py
"""
import os
import re
import subprocess
import sys

ROOT = os.getcwd()
HEADER = "| # | Tag | Date | Kind | Files | Subject | Disposition |"
DISPOSITIONS = ("ALREADY-ON-MASTER", "OBSOLETE", "APPLIED", "BUG-DOC")


def sh(cmd):
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)


def read_table():
    rows = []
    in_table = False
    with open(os.path.join(ROOT, "recover", "save.md"), encoding="utf-8") as f:
        for line in f:
            if line.startswith(HEADER):
                in_table = True
                continue
            if not in_table:
                continue
            if not line.startswith("|"):
                if rows:
                    break
                continue
            if line.startswith("|---"):
                continue
            cells = re.split(r"(?<!\\)\|", line.strip())[1:-1]
            rows.append([c.strip() for c in cells])
    return rows


def first_word(cell):
    return re.split(r"[:\s]", cell, maxsplit=1)[0]


def row_shas():
    """Dangling sha of each row, from the checks file written by run_checks.py."""
    shas = set()
    path = os.path.join(ROOT, ".tmp", "checks.tsv")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            next(f)
            for line in f:
                shas.add(line.split("\t")[2])
    return shas


def main():
    problems = []
    rows = read_table()
    if len(rows) != 114:
        problems.append(("table", f"expected 114 rows, found {len(rows)}"))
    known = row_shas()
    if not known:
        # Without the checks file every sha citation would be reported as
        # "not a row sha" too. Stop at the real cause instead.
        print("PROBLEM table: no .tmp/checks.tsv; run recover/run_checks.py first")
        print("problems 1")
        return 1

    counts = {d: 0 for d in DISPOSITIONS}
    for cells in rows:
        if len(cells) != 7:
            problems.append((cells[0] if cells else "?", f"{len(cells)} cells, expected 7"))
            continue
        num, disp = cells[0], cells[6]
        word = first_word(disp)
        if word not in DISPOSITIONS:
            problems.append((num, f"disposition word {word!r} is not allowed"))
            continue
        counts[word] += 1
        docs = set(re.findall(r"bugs/mid/RECOVER_\w+\.md", disp))
        if word == "BUG-DOC" and not docs:
            problems.append((num, "BUG-DOC cell names no bugs/mid/RECOVER_*.md"))
        for doc in sorted(docs):
            if not os.path.exists(os.path.join(ROOT, doc)):
                problems.append((num, f"named doc {doc} does not exist"))
        if word == "BUG-DOC":
            continue
        for m in sorted(set(re.finditer(r"`([0-9a-f]{7,40})`", disp)), key=lambda x: x.group(1)):
            sha = m.group(1)
            if "patch-id" in disp[max(0, m.start() - 60):m.start()].lower():
                continue
            if sh(f"git merge-base --is-ancestor {sha} master").returncode == 0:
                continue
            if sh(f"git merge-base --is-ancestor {sha} HEAD").returncode == 0:
                continue
            if sh(f"git cat-file -t {sha}").stdout.strip() == "blob":
                continue
            if any(k.startswith(sha) for k in known):
                continue
            problems.append((num, f"cited {sha} is not on master/HEAD, not a blob, not a row sha"))

    print("rows", len(rows))
    print("counts " + " ".join(f"{k}={v}" for k, v in counts.items()))
    for num, msg in problems:
        print(f"PROBLEM row {num}: {msg}")
    print("problems", len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
