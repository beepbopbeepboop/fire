# plan/step-22: the singleton direct causes — re-measure, then one verdict per row (LOOP STEP)
**Status: DONE 2026-11-07 (measured).** Fresh sweep (`bugs/sweeps/sweep-arm-15-step22.txt`): 88 direct CODEGEN rows, 41 singleton causes; every row reproduced and given a verdict in `bugs/FORMAL_known_limits.md` section 3.2 (replacing the 2026-11-05 table, whose all-S verdicts were unreproduced). T=33 M=1 S=0 C=7. The M row (26) is fixed (commit 0efcafd25): refusal messages and the tests that quote them carried twelve repeated `(deleted)` tags; `test_formal_module_attr.py` 33/3 -> 34/2 (the 2 left expect cross-module writable-global accessors to build, which they do not: a separate gap). The seven C rows are the work list named under the table. Rows were split in four chunks; a and b by workers (plan-22a-r2, plan-22b), c and d by hand after both restarted workers wrote nothing in 90 minutes.
Class: mid      Size: L      Depends: 15a, 16f, 17, 20      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §3 (small shapes table, line ~909), §6.1 ("19 distinct singleton causes"), §6.3 lever #5 ("prefer fixing a wrong message to adding a capability"). The 19 are from 2026-09-27 and the doc does NOT list them: this step produces the list.

## Current state (measured 2026-11-05)
- No list of the 19 exists anywhere. The newest committed sweep log `bugs/sweeps/sweep-arm-14.txt` (2026-10-05) yields 24 singleton direct causes with the script below (91 direct `CODEGEN:` lines, 28 normalised causes). The number moves with the tree (families move by orders of magnitude "without anything being wrong").
- Tools: `tools/formal_sweep.py` (usage in its docstring: `python3 tools/formal_sweep.py [-j N] [-t SECONDS | -t POP=SECONDS] [--arch x86_64] [paths...]`; `DEFAULT_JOBS = max(4, min(cpus, 20))`; per-file memory cap `MEMCAP_GB = 4.0`; default scope = this repo + the stdlib `std/` found by `module_loader` = `../modular/mojo/stdlib`; one line per non-pass: `CLASS: path  (message)`); `tools/formal_sweep_causes.py LOG [--json] [--min N]` (ranks terminal causes; rows with 1 file are singletons at its coarse label).
- Prerequisites: step 15a (the tree must import) and ideally 16f, 17, 20 (they change which rows are singletons).

## Decisions already made
- A SINGLETON = a direct (`CODEGEN:`, not `CODEGEN/DEPENDENCY:`) line whose message, after normalising backticked tokens, quoted tokens and digits and truncating to 90 chars, occurs exactly once in the log. The script is below; use it verbatim.
- Allowed verdicts, nothing else:
  T = TRUE LIMIT: the refusal is true of the file; record the one-line reason it is true (name the construct and the line).
  M = MESSAGE FIX: the refusal is right but the sentence is false/weak about the file; fix the sentence (arch-free text in `formal/model/`), prove the new text true of the file, pin it.
  S = STALE: the file no longer refuses with this message (it built, or moved to a different message): record the new terminal message verbatim.
  C = CAPABILITY: the refusal is an over-refusal that needs a feature; record ONE line of what it needs and a size (S/M/L). Do NOT implement it here (this step is not allowed to add a capability).
- Where verdicts are recorded: ONE table, `bugs/FORMAL_known_limits.md` new subsection `## 3.2 The singleton direct causes (re-measured 2026-11-NN, step-22)`, columns `# | file | verdict | message (first 100 chars) | reason / fix | commit`. One row per singleton, appended as each is measured. Never record a verdict from reading; each row cites the command that reproduced it.
- Evidence rule (CLAUDE.md "Never spend a turn re-verifying"): a row must end as M (code change + pin), or C/T/S with a reproduced measurement; a row with nothing new is still a valid T/S entry because the table is the deliverable.

## Work order
0. `export PATH=/opt/homebrew/bin:$PATH`; `python3 -c "import formal.build"` must print nothing (else step 15a is not done: STOP).
1. RE-MEASURE FIRST (heavy; reserves 24 GB for 4 workers x 4 GB cap):
   `mkdir -p .tmp && python3 tools/memslot.py --gb 24 --label sweep22 -- python3 tools/formal_sweep.py -j 4 -t repo=600 -t stdlib=120 > .tmp/sweep22.log 2>&1`
   then `tail -40 .tmp/sweep22.log` (the summary: class counts, coverage). Do not run it twice. If it exceeds the machine's patience, rerun only the failing populations: `python3 tools/formal_sweep.py -j 4 -t stdlib=120 ../modular/mojo/stdlib/std/<subtree>` (tool accepts paths).
2. Save this script as `.tmp/singletons.py` and run `python3 .tmp/singletons.py .tmp/sweep22.log > .tmp/singletons22.txt`:
```
import re, sys, collections
rows = []
for ln in open(sys.argv[1], errors="replace"):
    m = re.match(r"CODEGEN: (\S+)\s+\((.*)\)\s*$", ln.rstrip("\n"))
    if m: rows.append((m.group(1), m.group(2)))
def norm(msg):
    msg = re.sub(r"`[^`]*`", "`X`", msg); msg = re.sub(r"'[^']*'", "'X'", msg)
    return re.sub(r"\d+", "N", msg)[:90]
cnt = collections.Counter(norm(m) for _, m in rows)
print(f"direct CODEGEN rows: {len(rows)}; distinct normalised causes: {len(cnt)}")
n = 0
for f, m in rows:
    if cnt[norm(m)] == 1:
        n += 1; print(f"{n}\t{f}\t{m[:160]}")
print(f"singletons: {n}")
```
3. Create the §3.2 table in `bugs/FORMAL_known_limits.md` with one EMPTY row per line of `.tmp/singletons22.txt` (row number, file, message prefix). Commit this alone: "step-22: singleton census N rows" — this is the checkpoint; the loop below can resume from it.
4. LOOP — for each row in order, apply exactly this procedure, fill the row, and commit per row (or per 3 rows):
   a. Reproduce: `python3 tools/memslot.py --gb 8 --label r -- python3 fire.py build --formal --no-prove -o .tmp/row.aout <file>`; copy the FULL message. If it differs from the log's, the verdict is S (record the new message) and go to (e).
   b. Read the source line the message names (open the file at that line) and the producer of the message (`grep -rn "<first 8 words of the message>" formal/ | head`; messages live in `formal/model/*.py` or `formal/build.py`).
   c. Decide T / M / C using the definitions above. M only if you can name the FALSE or MISLEADING clause and the true replacement; otherwise T or C.
   d. If M: edit the message text in the producer (arch-free: `formal/model/`); rebuild the file; the new text must appear verbatim; add a pin: find the existing pin with `grep -rln "<distinctive phrase from the old message>" test_*.py` and update it, or if none, add a `refuse:` row to `test_formal_run.py` (copy the shape of a neighbouring `refuse:` row; read how it lists the needle); run the owning test file wrapped `python3 tools/memslot.py --gb 8 --label t -- python3 <test>.py`. Also run `python3 tools/memslot.py --gb 8 --label t -- python3 test_refusal_taxonomy.py` (a reword can move a cause marker).
   e. Fill the table row and the commit hash. Commit.
5. After the last row: re-run step 1's sweep? NO (heavy); instead re-run only the M rows' files (command in 4a) and record they show the new text. Fill the totals line under the table: `T=a M=b S=c C=d`.
6. `python3 tools/dangling_doc_refs.py --ratchet` — must add nothing; `python3 tools/formal_doc_index.py --check` if that tool exists (`ls tools/formal_doc_index.py`; if absent, skip and say so).

## Do NOT
- Do not implement a capability (verdict C only records it).
- Do not edit a message you have not proved false/weak about THE FILE (invariant 2 of the plan: a refusal must be true of the file it is reported against, and so must its replacement).
- Do not re-run the full sweep to "confirm" at the end.
- Do not bulk-regenerate sweep baselines (`--write-baseline`).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_refusal_taxonomy.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep.py
python3 tools/dangling_doc_refs.py --ratchet
python3 tools/plan_index.py --check
```

## Done when
- [ ] §3.2 has one filled row per singleton in `.tmp/singletons22.txt` (row count equals the script's `singletons: N`)
- [ ] every M row has a pin that fails with the old text (state which test) and the re-run file shows the new text
- [ ] the owning test files and `test_refusal_taxonomy.py` tallies are no worse than their pre-step tallies (record both)

## If stuck
If the sweep cannot complete, run the script on `bugs/sweeps/sweep-arm-14.txt` (24 singletons), say in §3.2 that the table is from that older log, and proceed row by row (step 4a re-reproduces each, so staleness is detected per row).
