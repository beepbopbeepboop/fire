"""Code-only, inverse, and doc-absence checks for the 'landed hunks' BUG-DOC rows.

For each row of bugs/mid/RECOVER_landed_hunks_changed_on_master.md, with the
row's tag from that doc's table:
  - code_pid: patch-id of the commit's diff excluding bugs/ paths;
  - master_code: the master commit(s) with that same code-only patch-id
    (from `git log master -p --no-merges -- . ':!bugs'`), and whether each is
    an ancestor of master;
  - inverse_on_master: a master commit whose code-only patch-id equals the
    row's inverse code diff (i.e. master later reverted it);
  - doc_absent: every bugs/ path the row deletes is absent on master.
Writes recover/landed_code_check.tsv. Run from the worktree root:
    python3 -I recover/landed_code_check.py
"""
import os
import re
import subprocess

ROOT = os.getcwd()
DOC = os.path.join(ROOT, "bugs", "mid", "RECOVER_landed_hunks_changed_on_master.md")


def sh(cmd, inp=None):
    return subprocess.run(cmd, shell=True, cwd=ROOT, input=inp,
                          capture_output=True, text=True).stdout


def pid_of(diff):
    out = sh("git patch-id --stable", inp=diff).split()
    return out[0] if out else ""


rows = []
for line in open(DOC):
    m = re.match(r"^\| (\d+) \| (recover-\w+) \| `([0-9a-f]{40})` \|", line)
    if m:
        rows.append((int(m.group(1)), m.group(2), m.group(3)))

master_code = {}
for line in sh("git log master -p --no-merges -- . ':!bugs' | git patch-id --stable").splitlines():
    p = line.split()
    if len(p) >= 2:
        master_code.setdefault(p[0], []).append(p[1])

with open(os.path.join(ROOT, "recover", "landed_code_check.tsv"), "w") as out:
    out.write("row\ttag\tsha\tcode_pid_match\tmaster_commits\tall_ancestors\t"
              "inverse_on_master\tdeleted_docs_absent\n")
    for num, tag, sha in rows:
        diff = sh(f"git show {sha} --no-merges --format= -- . ':!bugs'")
        pid = pid_of(diff)
        matches = master_code.get(pid, [])
        anc = all(sh(f"git merge-base --is-ancestor {c} master; echo $?").strip() == "0"
                  for c in matches) if matches else False
        inv = pid_of(sh(f"git show {sha} -R --no-merges --format= -- . ':!bugs'"))
        inverse_on = "yes" if inv and inv in master_code else "no"
        deleted = sh(f"git show {sha} --no-merges --format= --diff-filter=D --name-only -- bugs").split()
        absent = all(sh(f"git cat-file -e master:{d} 2>/dev/null; echo $?").strip() == "1"
                     for d in deleted) if deleted else True
        out.write(f"{num}\t{tag}\t{sha}\t{'yes' if matches else 'no'}\t"
                  f"{','.join(c[:9] for c in matches)}\t{'yes' if anc else 'no'}\t"
                  f"{inverse_on}\t{'yes' if absent else 'no'}\n")
print(f"checked {len(rows)} rows -> recover/landed_code_check.tsv")
