"""Find master commits that carry the same change as a 'Needs integration' row.

Two evidence paths, both written to recover/subject_matches.tsv:

1. Code hunks: for a non-merge row commit, the diff restricted to the row's
   NON-doc paths is patch-id'd. Every master commit that touched those paths
   is patch-id'd the same way, in ONE `git log -p | git patch-id` pass per row.
   A match means the code hunks are the same commit diff on master, whatever
   the subject (a re-landed change may carry a different subject or sha).
2. Doc state: for every bugs/ or recover/ path the row touches, the row's
   post-image must equal master's blob at that path, or the row deleted the
   path and master lacks it. Otherwise the doc state is named per path.

verdict = ALREADY when the code hunks match a master commit (or the row has no
code hunks) AND every doc path is in state. Otherwise DIFFERS.

Run from the worktree root:  python3 -I recover/subject_matches.py
"""
import os
import subprocess

ROOT = os.getcwd()


def sh(cmd, inp=None):
    return subprocess.run(cmd, shell=True, cwd=ROOT, input=inp,
                          capture_output=True, text=True).stdout


def is_doc(path):
    return path.startswith("bugs/") or path.startswith("recover/")


def blob(rev, path):
    return sh(f"git rev-parse -q --verify {rev}:'{path}' 2>/dev/null").strip()


def pathargs(paths):
    return " ".join(f"'{p}'" for p in paths)


rows = []
for line in open(os.path.join(ROOT, "recover", "checks.tsv")).read().splitlines()[1:]:
    f = line.split("\t")
    rows.append((f[0], f[2], f[3]))

with open(os.path.join(ROOT, "recover", "subject_matches.tsv"), "w") as out:
    out.write("row\tsha\tkind\tmaster_candidate\tcode_match\tdocs_in_state\tverdict\tcode_paths\tdoc_paths\n")
    for num, sha, kind in rows:
        if kind != "commit":
            continue
        files = sh(f"git show --format= --name-only {sha} --no-merges").split()
        code = [p for p in files if not is_doc(p)]
        docs = [p for p in files if is_doc(p)]
        doc_ok = True
        for p in docs:
            if blob(sha, p) == "":
                doc_ok &= blob("master", p) == ""
            else:
                doc_ok &= blob(sha, p) == blob("master", p)
        match_cands = []
        if code:
            row_pid = sh(f"git show {sha} --no-merges --format= -- {pathargs(code)} | git patch-id --stable").split()
            row_pid = row_pid[0] if row_pid else ""
            # every master commit that touched these paths, patch-id'd on those paths only
            # --full-history: default simplification hides side-branch commits whose
            # change is TREESAME to a parent after the merge, which is exactly a re-landed copy.
            log = sh(f"git log master --no-merges --full-history -p -- {pathargs(code)} | git patch-id --stable")
            for line in log.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[0] == row_pid:
                    match_cands.append(parts[1])
        code_ok = bool(match_cands) if code else True
        verdict = "ALREADY" if (code_ok and doc_ok and (code or docs)) else "DIFFERS"
        out.write(f"{num}\t{sha}\t{kind}\t{' '.join(match_cands) or '-'}\t"
                  f"{'yes' if code_ok and code else ('n/a' if not code else 'no')}\t"
                  f"{'yes' if doc_ok else 'no'}\t{verdict}\t{' '.join(code)}\t{' '.join(docs)}\n")
print("wrote recover/subject_matches.tsv")
