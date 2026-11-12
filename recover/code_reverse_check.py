"""Reverse-apply check of each code-hunk match's CODE paths against master.

For every row that recover/subject_matches.py matched on code hunks
(code_match == yes), take the row commit's diff restricted to its NON-doc
paths, and check it reverse-applies to a master index (temp index, master's
tree). PASS means the code hunks of the row are present on master.
Writes recover/code_reverse.tsv. Run from the worktree root:
    python3 -I recover/code_reverse_check.py
"""
import os
import subprocess

ROOT = os.getcwd()
IDX = os.path.join(ROOT, ".tmp", "idx")
os.makedirs(os.path.join(ROOT, ".tmp"), exist_ok=True)
ENV = dict(os.environ, GIT_INDEX_FILE=IDX)


def sh(cmd, inp=None, env=None):
    return subprocess.run(cmd, shell=True, cwd=ROOT, input=inp, env=env or os.environ,
                          capture_output=True, text=True)


def is_doc(path):
    return path.startswith("bugs/") or path.startswith("recover/")


sh("git read-tree master", env=ENV)
rows = []
with open(os.path.join(ROOT, "recover", "subject_matches.tsv")) as f:
    next(f)
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 5 and p[4] == "yes":
            rows.append((p[0], p[1]))

with open(os.path.join(ROOT, "recover", "code_reverse.tsv"), "w") as out:
    out.write("row\tsha\tcode_files\tcode_reverse_apply\n")
    for row, sha in rows:
        files = sh(f"git show {sha} --no-merges --format= --name-only").stdout.split()
        code = [x for x in files if not is_doc(x)]
        diff = sh(f"git show {sha} --no-merges --format= -- " +
                  " ".join(f"'{c}'" for c in code)).stdout
        ok = sh("git apply --cached -R --check", inp=diff, env=ENV).returncode == 0
        out.write(f"{row}\t{sha}\t{' '.join(code)}\t{'pass' if ok else 'fail'}\n")
print("wrote recover/code_reverse.tsv")
