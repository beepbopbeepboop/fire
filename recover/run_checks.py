"""Recompute the 114 'Needs integration' row checks against master.

Reads the table in recover/save.md, and for each row computes patch-id match
(against `git log master -p --no-merges`), reverse-apply and forward-apply
(temp index read from master), and `git merge-tree --write-tree` vs master
(non-merge rows only). Writes .tmp/checks.tsv. Run from the worktree root:
    python3 -I recover/run_checks.py
"""
import csv
import os
import re
import subprocess

ROOT = os.getcwd()
IDX = os.path.join(ROOT, ".tmp", "idx")
os.makedirs(os.path.join(ROOT, ".tmp"), exist_ok=True)


def sh(cmd, inp=None, index=False):
    env = dict(os.environ)
    if index:
        env["GIT_INDEX_FILE"] = IDX
    return subprocess.run(cmd, shell=True, cwd=ROOT, env=env, input=inp,
                          capture_output=True, text=True)


rows = []
for line in open(os.path.join(ROOT, "recover", "save.md")):
    m = re.match(r"^\| (\d+) \| (recover-\w+) \| [^|]*\| (commit|merge) \|", line)
    if m:
        rows.append((int(m.group(1)), m.group(2), m.group(3)))
assert len(rows) == 114, len(rows)

master_ids = {}
for line in sh("git log master -p --no-merges | git patch-id --stable").stdout.splitlines():
    p = line.split()
    if len(p) >= 2:
        master_ids.setdefault(p[0], p[1])
sh("git read-tree master", index=True)

with open(os.path.join(ROOT, ".tmp", "checks.tsv"), "w") as out:
    out.write("row\ttag\tsha\tkind\tpatch_id_match\tmaster_commit\treverse_apply\tforward_apply\tmerge_tree_vs_master\n")
    for num, tag, kind in rows:
        sha = sh(f"git rev-parse {tag}^{{commit}}").stdout.strip()
        if kind == "merge":
            diff = sh(f"git diff {sha}^1 {sha}").stdout
            mt = "n/a-merge"
        else:
            diff = sh(f"git show {sha} --no-merges --format=").stdout
            r = sh(f"git merge-tree --write-tree master {sha}")
            mt = "clean" if r.returncode == 0 else "conflict"
        pid = sh("git patch-id --stable", inp=diff).stdout.split()
        pid = pid[0] if pid else ""
        mc = master_ids.get(pid, "") if pid else ""
        rev = sh("git apply --cached -R --check", inp=diff, index=True).returncode == 0
        fwd = sh("git apply --cached --check", inp=diff, index=True).returncode == 0
        out.write(f"{num}\t{tag}\t{sha}\t{kind}\t{'yes' if mc else 'no'}\t{mc}\t"
                  f"{'pass' if rev else 'fail'}\t{'pass' if fwd else 'fail'}\t{mt}\n")
print("wrote .tmp/checks.tsv")
