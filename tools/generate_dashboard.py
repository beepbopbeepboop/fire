#!/usr/bin/env python3
"""
Generate a comprehensive dashboard HTML for the mojo-reference orchestration system.
Sources: doc/ORCHESTRATION.html
"""

import os
from datetime import datetime

# ---------------------------------------------------------------------------
# DATA EXTRACTED FROM doc/ORCHESTRATION.html
# ---------------------------------------------------------------------------

# --- Roles (bird's eye view) ---
ROLES = [
    {
        "name": "Controller",
        "who": "one agent (the user / opencode controller)",
        "role": "Dispatches work, keeps the fleet healthy, lands finished branches on master, runs the gate, records state. The only role that merges to master.",
        "color": "#0b57d0",
    },
    {
        "name": "Worker",
        "who": "opencode models",
        "role": "Fixes one focused set of bug docs in its own git worktree ../work-N on branch work/<name>. Light: no gate, no heavy builds. Commits; never merges.",
        "color": "#7aa7ff",
    },
    {
        "name": "Merger",
        "who": "strongest available opencode model",
        "role": "A worker whose task is 'merge these finished branches into your branch, resolve conflicts, verify'. Its output branch is then landed by the controller.",
        "color": "#9a3412",
    },
    {
        "name": "Hard-Problem Agent",
        "who": "strongest models (Claude Opus/Sonnet subagents when the controller is Claude Code; otherwise the best opencode model)",
        "role": "One agent on one hard problem (bootstrap self-host, Lean proof engineering, a deep perf bug).",
        "color": "#c2410c",
    },
]

# --- Directory layout ---
DIRECTORY_LAYOUT = """mojo-reference/           main checkout, master (the integrator's tree; control.py lives in tools/)
work-N/                       one worktree per worker/merger. work.log = everything it printed. exitcode = written when it exits.
gate-wt/                      the gate worktree: a detached checkout where suite.py gate|check runs, so merges never disturb a running gate
task-*.md                     task files given to workers (scratch, outside the repo)
keepfull.sh / keepfull.log     the keep-full loop and its log
check-*.log / gate-N.log      logs of suite runs (full detail in gate-wt/build/suite.log)
mojo-reference/.claude/worktrees/agent-*   isolated worktrees of Claude Code subagents (branch worktree-agent-*)"""

# --- Environment / Models ---
ENVIRONMENT = {
    "Python": {
        "path": "/opt/local/bin (3.14.8) — the project's interpreter",
        "note": "Use python 3.14 by absolute path. /usr/bin/python3 is 3.9, /opt/homebrew/bin/python3 is 3.15.0 (changed 2026-10-18). Put /opt/local/bin first, not /opt/homebrew/bin.",
    },
    "opencode": {
        "version": "v2.0.26",
        "spawn": "opencode run --model PROVIDER/MODEL --auto --title NAME \"...\"",
        "warning": "The OLD form `opencode --model M run --dir D` now prints a usage screen and exits. Probe with the new form.",
    },
    "Models": [
        {"id": "opencode-go/deepseek-v4.1-flash", "use": "default worker; also decent at merging", "note": "Exactly one DeepSeek worker at a time (cost). opencode/big-pickle shares its quota bucket — do not use it as an alternative."},
        {"id": "opencode/space-bunny-free", "use": "hard problems, hard merges", "note": "Free, replenishes daily. Rate limited only on explicit 429/Rate limit exceeded. A worker that stops with exit 0 and no error is NOT rate limited."},
        {"id": "omlx/Qwen3.8-27B-oQ4e-mtp", "use": "local, slow; light merging", "note": "Server http://127.0.0.1:8000. Has exited early and with 'oMLX memory guard abort'. Too slow for hard conflict merges."},
        {"id": "opencode/claude-* / openrouter/anthropic/*", "use": "—", "note": "Failed with 'Insufficient account funds' / 'Key limit exceeded'. Do not rely on them. (Claude Opus/Sonnet available only as Claude Code subagents when the controller is Claude Code.)"},
        {"id": "opencode/fledge-alpha-free", "use": "—", "note": "Hung for hours once. Do not use unless the owner says it is back."},
    ],
}

# --- Control commands ---
CONTROL_COMMANDS = [
    ("ps", "Live workers. Names show as ? for v2-launched workers. Also reports 'N other opencode processes belong to someone else' (the owner's own sessions — never touch them)."),
    ("status", "One line per task: name, work-N, state (running, exited-ok, exited-err, integrated, superseded, abandoned), commits ahead, dirty files. integrated does NOT mean the branch is on master."),
    ("spawn NAME --claim K [--claim K...] ...", "Creates the worktree and starts a worker now. Refuses if a claim conflicts. A name that already exists is refused."),
    ("enqueue NAME ... / queue / refill --target N", "Queue a task; refill starts queued tasks oldest-first while fewer than N workers run and claims are free. FIFO; priority is only for integration order, not start order."),
    ("restart NAME [--model M] [--why TEXT]", "Snapshots uncommitted work, stops worker, continues as NAME-r2 from its branch. Never restart a worker mid-merge with unresolved conflicts."),
    ("unstick", "Restarts workers whose log is idle AND whose tree uses no CPU."),
    ("claims", "All live claims. [external: ...] rows are outside sessions."),
    ("mark NAME STATE", "Set a state by hand (integrated releases the claims; abandoned)."),
    ("guard [--once]", "Watchdog: kills process trees over 55 GB each / 90 GB total, Lean past 45 min wall / 90 min CPU, runaway fire.py / test_*.py / probes past 120 min. Does not cover native test binaries or CPU-burning opencode processes."),
    ("status [--all] [-v] / prune [--dry-run]", "Lists tasks that still matter, ends with '+N finished tasks hidden'. Prune deletes hidden entries from tasks.json."),
    ("reap / cleanup [--dry-run] [--no-branches] [--no-prune] [-j N]", "Kills leftover Lean/gcc; removes clean worktrees whose HEAD is an ancestor of master. Run every monitoring loop."),
    ("claim / release", "For work not started by control.py. claim registers the claim (exit 1 + CONFLICT if held); release drops it. Lapses after --hours (default 12) or when pid dies."),
    ("refill (circuit breaker)", "A worker that dies on arrival is bounced to the queue. A limit marks that model dead for its recovery time; an outage pauses starts 30 min."),
    ("digest NAME / log NAME -n N / report", "Read a worker's verdict/report block; tail its log; regenerate CONTROL.html's table."),
]

# --- Claims ---
CLAIMS = [
    {
        "type": "Claim definition",
        "detail": "A claim is a string such as bug:FORMAL_some_doc, module:os, or a repo path.",
        "rule": "Two claims conflict when EQUAL or when one is a PATH-PREFIX of the other.",
        "action": "spawn / refill refuse a task whose claims conflict with any task not in a terminal state.",
    },
    {
        "type": "Life cycle",
        "detail": "A claim is held until the task is marked integrated / abandoned / superseded.",
        "rule": "A claim releases when: task marked integrated, abandoned, or superseded (after branch lands on master for integrated).",
        "action": "Hand-marking integrated is only right after verifying the branch is on master.",
    },
    {
        "type": "Auto-release (keepfull loop)",
        "detail": "formal_feed.release_finished now keeps the claims of an exited task whose branch still has commits master lacks (git rev-list --count master..BRANCH > 0).",
        "rule": "Claims are NOT released when a worker exits — only when its branch has landed on master (fix d20d1466).",
        "action": "This prevents duplicate work: 750 distinct docs across 758 dispatches; 522 fixed of which 341 in one dispatch, 181 needed two or more.",
    },
    {
        "type": "Released claims (current)",
        "detail": "Three formal branches are landed (owner's choice a), check is 53/53.",
        "claims": [
            "formal636-docs",
            "formal637-docs",
            "formal638-docs",
        ],
        "note": "formal637-docs added three theorems to lib/X86.lean; formal636-docs fixed wrong answers at call boundaries.",
    },
    {
        "type": "Failure mode (duplicate work)",
        "detail": "If many finished branches are unmerged, queued tasks that name the same docs are skipped ('claim ... conflicts with ... held by task X') and the fleet starves. Also: without release-at-land, branches sat unmerged for days and bugs were re-fixed.",
        "rule": "The cure is to LAND finished branches (§7), not to release claims by hand.",
        "action": "Before dispatching new work, search for overlap: git branch --no-merged master | grep work/, git log master --oneline -S<identifier>, git cherry master BRANCH.",
    },
]

# --- Workers ---
WORKERS = [
    {
        "role": "Controller",
        "type": "Control",
        "model": "you (one agent)",
        "status": "Operational",
        "description": "Dispatches work, keeps fleet healthy, lands finished branches, runs the gate, records state. Only role that merges to master.",
    },
    {
        "role": "Worker (default)",
        "type": "Formal / bug-doc",
        "model": "opencode-go/deepseek-v4.1-flash",
        "status": "Currently down (fleet by design — see Snapshot)",
        "description": "Default worker; also decent at merging. Exactly one DeepSeek worker at a time (cost). big-pickle shares its quota bucket.",
    },
    {
        "role": "Merger (hard)",
        "type": "Merger",
        "model": "opencode/space-bunny-free (strongest model)",
        "status": "Awaits work (branches merged once landed)",
        "description": "Merges finished branches into master, resolves conflicts, verifies. Handed to the strongest model. Output branch then landed by controller.",
    },
    {
        "role": "Hard-Problem Agent",
        "type": "Hard problem",
        "model": "strongest models (Claude Opus/Sonnet subagents when controller is Claude Code; otherwise best opencode model)",
        "status": "Active (worktrees may exist)",
        "description": "One agent on one hard problem: bootstrap self-host, Lean proof engineering, deep perf bug.",
    },
    {
        "role": "Local (Qwen)",
        "type": "Light merging / slow",
        "model": "omlx/Qwen3.8-27B-oQ4e-mtp",
        "status": "Not used (exited early)",
        "description": "Local, slow; light merging only. Has exited early ('waiting for a background run') and with 'oMLX memory guard abort'. Too slow for hard conflict merges.",
    },
    {
        "role": "Qwen free (hard)",
        "type": "Hard problems / hard merges",
        "model": "opencode/space-bunny-free",
        "status": "Available",
        "description": "Free, replenishes daily. Handed to space-bunny for hard problems and hard merges. Stops without error → restart, not 'rate limited'.",
    },
]

# --- keepfull loop ---
KEEPFULL = {
    "command": "/Users/mrs/net/chatgpt/claude/keepfull.sh",
    "frequency": "every 300 seconds (5 minutes loop; tick every 50 min for monitor)",
    "steps": [
        "formal_feed.py --min-ready 12 — releases landed tasks' claims, enqueues more FORMAL docs / projects",
        "control.py ps — tail total worker count",
        "refill --target N — starts workers while claims free (exactly ONE DeepSeek worker)",
        "control.py guard --once — watchdog check",
        "sleep 300 — repeat",
    ],
    "behavior": "Keeps the queue stocked from FORMAL docs nobody holds and from formal_projects.json. Starts workers only while claims are free. If it prints a Python error, restart it.",
}

# --- Integration ---
INTEGRATION = [
    "Find finished work: status | grep -E 'DONE|PARTIAL' and git for-each-ref --no-merged master --format='%(refname:short)' 'refs/heads/work/*'",
    "Try plain merge first (git merge --no-edit work/NAME). On conflict: git merge --abort and give to a merger.",
    "After any merge: python3 tools/dangling_doc_refs.py --ratchet and a compile() sweep of every tracked .py.",
    "Verify bulk merges before trusting: run python3 tools/suite.py check in gate-wt before merging a large branch.",
    "Mark landed tasks integrated only after merge (feed does this automatically once git rev-list --count master..BRANCH is 0).",
    "Formal-only changes need no gate. Anything touching core modules owes a full gate once, after the batch.",
    "Delete fixed bug docs in the same commit as the fix; run the citation ratchet.",
]

# --- Gate ---
GATE = {
    "check": "python3 tools/suite.py check — ~53 jobs, ~9-10 min",
    "full_gate": "gate = check + coro + stdlib + native + bootstrap — ~35 min, tens of GB",
    "run": "cd gate-wt && git checkout -q --detach master && nohup python3 tools/suite.py check > ../check-X.log 2>&1 &",
    "reading_notes": [
        "expect='why' = known cheap failure (PASSES are reported FAILURE: drop the marker). disabled= is a known expensive failure (doc is the switch).",
        "Two verdicts need judgement: stdlib-dylib (skip count must not rise) and stdlib-syntax (U must not rise).",
        "Fanout jobs print many FAIL job:item lines absorbed by expect= counts — look at the FAILED section.",
        "If log prints PEAK DRIFT: run tools/suite.py --apply-peaks build/suite.log and re-class the jobs.",
        "Flake: x86-examples 'toplevel_const has no home' under parallel load; passes alone.",
    ],
}

# --- Monitoring loop ---
MONITORING = {
    "frequency": "every 50 minutes",
    "purpose": "Keeps the model prompt cache warm and keeps the fleet healthy.",
    "steps": [
        "Fleet: control.py ps; compare work.log mtime, rev-list count master..HEAD, status --short count. Log untouched >30 min with ~0% CPU = stalled (§10).",
        "Finished: status | grep exited|DONE|PARTIAL and unmerged-branches list. Land what is finished (§7).",
        "Hard-problem agents: their worktree (.claude/worktrees/agent-*). Check commits ahead, dirty, behind master. If stopped on a session limit, try resuming once reset time passed.",
        "Queue & keep-full: tail keepfull.log. Starvation ('skip ... claim conflicts') means unmerged branches hold claims: land them.",
        "Verification: any pending check/gate log? Read FAILED section and act (§8).",
        "Resources: df -h / (cleanup above ~85%), load average.",
        "Report to owner in plain text: what changed, what landed, what is red and why. Never assert a cause without the log line that shows it.",
    ],
}

# --- Diagnosis ---
DIAGNOSIS = [
    {
        "symptom": "Process alive, log not growing, ~0% CPU",
        "check": "ps -o pid,etime,time,pcpu -p PID; stat -f %Sm work.log; probe the model with a one-word prompt",
        "action": "Model not answering → down/hung (wait or switch model, restart with --model). Model answers → restart NAME.",
    },
    {
        "symptom": "Log ends abruptly, exitcode 0, no error line",
        "check": "tail -c 2000 work.log; cat exitcode",
        "action": "Model ended without a tool call ('stopped early'). Restart it. This is NOT a rate limit.",
    },
    {
        "symptom": "Log has 'Rate limit exceeded' / 429 / 'Insufficient account funds'",
        "check": "grep -n -iE 'rate limit|429|insufficient|quota' work.log — read the actual line",
        "action": "Genuine limit: switch model or wait for the reset the message states.",
    },
    {
        "symptom": "Log has 'oMLX memory guard abort'",
        "check": "local Qwen server",
        "action": "Restart; if recurs, give the work to a remote model.",
    },
    {
        "symptom": "Started but only the banner (<300 bytes) after minutes",
        "check": "wrong CLI form or dead model",
        "action": "Check the spawn command (§2) and probe the model.",
    },
    {
        "symptom": "Mid-merge with conflicts, want to restart it",
        "check": "git -C ../work-N ls-files -u | wc -l; MERGE_HEAD exists",
        "action": "Restart only with --why telling the new worker to resolve committed conflict markers first (§3); never leave markers in a landed commit.",
    },
]

# --- Resources ---
RESOURCES = [
    {
        "category": "Memory",
        "detail": "96 GB memory budget shared by everything, enforced by tools/memslot.py (strict FIFO reservations).",
        "classes": "tiny 4 GB, small 8 GB, module 24 GB, program 55 GB, stage 96 GB. Each class comes from a measured peak (MEASURED_PEAK_GB in suite.py). Anything over 3-4 GB is itself a bug.",
        "tool": "python3 tools/memslot.py status",
    },
    {
        "category": "Disk",
        "detail": "df -h /. control.py cleanup above ~85%. Never clear ~/.gmojo/cas (content-addressed, self-invalidating). tools/clean-gmojo.py prunes old entries by age.",
    },
    {
        "category": "Process safety",
        "detail": "Never kill the owner's own opencode sessions (ps shows them as 'belong to someone else'). Never kill the omlx server. Kill only our worker trees; prefer restart / guard over kill -9.",
    },
    {
        "category": "Lean / compile",
        "detail": "Lean must be bounded: a proof check that runs long is a bug. tools/formal/lean.py::run_lean now bounds wall/CPU time and guard backs it up.",
        "note": "Ten Lean processes once ran for hundreds of CPU-hours; guard prevents this now.",
    },
]

# --- Incidents ---
INCIDENTS = [
    ("2026-10-03..04", "Ten Lean processes ran for hundreds of CPU-hours; formal tests had no time bound.", "Lean only via run_lean; guard kills Lean past 45 min wall / 90 min CPU; formal gate rows can be disabled= until a proof terminates."),
    ("2026-10-05", "A gate run on python 3.9 gave 17 false failures.", "Always use the correct python path; verify 3.14."),
    ("2026-10-05", "A gate was started on a half-merged tree.", "Gate in gate-wt on a clean detached checkout; never while a merge is in progress."),
    ("2026-10-06", "Two controllers merged the same inputs in parallel (merge-final3 vs merge-gate29).", "One owner of merges and gates. Before killing a duplicate, prove inputs are ancestors of master and keep a rescue/* branch."),
    ("2026-10-09..12", "opencode auto-upgraded to v2; old CLI form printed usage and exited; workers sat idle ~2 days.", "Use opencode run --model M --auto; probe with the new form; read raw probe output."),
    ("2026-10-12", "Brew update removed /opt/homebrew/bin/python3; keepfull script kept dead cached path.", "Restart long-running scripts after environment changes; check keepfull.log every tick."),
    ("2026-10-14", "Qwen merger quit early ('I'll resume when the notification arrives') with a half-finished merge.", "Workers must not 'wait for notifications'; they run to completion or report. Controller restarts early stops."),
    ("2026-10-15", "Wrongly reported a worker as rate limited from grep -c rate.", "§10: read the log end; never infer causes from keyword counts."),
    ("2026-10-15..16", "Two bulk merges (374 and 444 commits) resolved conflicts to master's side, dropping branch definitions; 6 jobs red.", "§7: keep both halves, compile() not ast.parse, verify with check before landing a big branch."),
    ("2026-10-16", "Feed released claims at worker exit; same bugs fixed repeatedly.", "§4: claims are held until the branch lands (d20d1466)."),
    ("2026-10-07", "make bootstrap found red; bootstrap-stage2-dumps regressed after unrelated merges.", "One agent owns bootstrap; gate after every large merge catches regressions."),
    ("2026-10-18", ".olean staleness: a different branch leaves old .olean in place, so Lean under-counts and reports 'unknownIdentifier'.", "Before trusting a closure-census number, run formal/lean.py::ensure_library in the tree you are measuring."),
    ("2026-10-18", "suite.log is APPENDED across runs; §8's per-job reader returns the first matching block (a previous run).", "Trust the summary and FAILED section of check-N.log. Read the LAST matching block of build/suite.log."),
    ("2026-10-18", "Brew upgrade made /opt/homebrew/bin/python3 3.15.0; wrong interpreter selected, causing 32 failures under 3.15.", "Name the project's interpreter (/opt/local/bin, 3.14) by absolute path; never treat /opt/homebrew/bin as stable."),
    ("2026-10-20", "Landing work/formal637-docs: branch added theorems but never re-pinned a Lean table row, so formal-sweep-truth ran red.", "When landing a branch touching lib/*.lean, re-pin the table and run the Lean-dependent check after the merge."),
]

# --- Standing instructions ---
STANDING = [
    "Never lose work. Never discard uncommitted work; no git checkout / restore / stash (stash is shared by all worktrees).",
    "Workers are light (no gate, no heavy builds). The controller runs the gate once per batch. Formal work needs no gate.",
    "No time-boxing of bug work. A fixed bug's doc is deleted in the same commit; run the citation ratchet.",
    "Model policy: exactly one DeepSeek worker; space-bunny for hard problems and hard merges; Qwen local is slow; big-pickle shares DeepSeek's bucket; a bunny that stops without an error line is restarted, not 'rate limited'. Bootstrap belongs to one hard-problem agent.",
    "Check workers every 50 minutes. Record the facts, not guesses. Do not claim a cause you have not seen in a log.",
    "Prefer production-quality fixes over quick ones; consolidate duplicates; keep leftover processes and disk under control.",
]

# --- State snapshot ---
SNAPSHOT = {
    "date": "2026-10-20 ~03:30 (goes stale: re-derive with §12)",
    "formal_branches_landed": [
        ("formal636-docs", "three wrong answers at a call boundary, fixed at roots (formal/model.py + arm64/x86 codegen; 3 docs deleted / 2 added)"),
        ("formal637-docs", "one call walk, five straight-line specs, x86-64 shift projections; three theorems in lib/X86.lean"),
        ("formal638-docs", "a typed bracket parameter is a parameter; delete the two already-fixed tuple docs"),
    ],
    "check_result": "53/53 passed",
    "first_check_after_merge": "52/53 — one red was a stale pin, not a merge bug. Re-pin 45673977 → check 53/53 (measured 2026-10-20, 741 s wall, peak 1.2 GB).",
    "gate_triage": "Gate-side triage against pre-merge baseline (c4cf116e): zero merge regressions. Red jobs were all pre-existing with byte-identical failure sets.",
    "fleet_state": "0 workers, by design. CODEGEN turns finished 2026-10-19; the DeepSeek formal worker stays down — owner's tokens out for ~19 days, NOT to be restarted.",
    "next_steps": [
        "Stdlib-100% push: 18 files / 2 root causes (peekable/next generic family, getsize/stat out-parameter modelling).",
        "Routine: suite reports 3 drifted measured peaks (linkmode, nonlocal, runtimedylib) — tools/suite.py --apply-peaks rewrites the table when convenient.",
        "20 pre-2026-10-05 archaeology branches await the owner's triage decision.",
    ],
    "open_reds": [
        "Bootstrap stage2/3 family behind bugs/CODEGEN_bootstrap_stage2_dump_is_empty.md (Opus agent's worktree).",
        "Gate-bucket formal reds itemised above (formal-os-backing, formal-monomorph, formal-run).",
    ],
}

# ---------------------------------------------------------------------------
# HTML TEMPLATE
# ---------------------------------------------------------------------------

CSS = """
:root {
  --bg: #ffffff;
  --fg: #1b1f24;
  --mut: #59636e;
  --line: #d0d7de;
  --code: #f3f4f6;
  --acc: #0b57d0;
  --acc2: #1f6feb;
  --warn: #9a3412;
  --warnbg: #fff4ec;
  --ok: #1a7f37;
  --okbg: #ecf7ef;
  --mutedge: #d0d7de;
  --panel: #f6f8fa;
  --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14181d;
    --fg: #e6e9ee;
    --mut: #9aa4b0;
    --line: #2d353f;
    --code: #1d232b;
    --acc: #7aa7ff;
    --acc2: #5e93ff;
    --warn: #ffb784;
    --warnbg: #2a2018;
    --ok: #4ade80;
    --okbg: #1e2e22;
    --mutedge: #2d353f;
    --panel: #1e232a;
    --shadow: 0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
  }
}
* { box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--fg);
  font: 15px/1.6 system-ui, -apple-system, Segoe UI, sans-serif;
  margin: 0;
  -webkit-font-smoothing: antialiased;
}
.dashboard { max-width: 1280px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }
header {
  border-bottom: 2px solid var(--line);
  padding-bottom: 1.25rem;
  margin-bottom: 1.5rem;
}
header h1 { font-size: 1.85rem; margin: 0 0 .3rem; }
header .subtitle { color: var(--mut); font-size: 1rem; margin: 0; }
header .meta { color: var(--mut); font-size: 0.82rem; margin-top: .4rem; }
.grid { display: grid; gap: 1rem; }
.grid-2 { grid-template-columns: 1fr 1fr; }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
@media (max-width: 980px) {
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 1.1rem 1.2rem;
  box-shadow: var(--shadow);
}
.panel h2 {
  font-size: 1.12rem;
  margin: 0 0 .75rem;
  padding-bottom: .4rem;
  border-bottom: 1px solid var(--line);
  display: flex; align-items: center; gap: .5rem;
}
.panel h2 .badge {
  font-size: .72rem; font-weight: 600;
  padding: .12rem .5rem; border-radius: 999px;
  background: var(--code); color: var(--acc);
  border: 1px solid var(--line);
}
.panel h3 { font-size: 1rem; margin: 1rem 0 .4rem; }
.grid-header { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 760px) { .grid-header { grid-template-columns: 1fr; } }
.row { display: flex; gap: .8rem; margin: .5rem 0; }
.row .cell { flex: 1; }
.tile {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: .8rem 1rem;
  background: var(--code);
}
.tile.primary { border-left: 4px solid var(--acc); }
.tile.accent { border-left: 4px solid var(--acc2); }
.tile.warn { border-left: 4px solid var(--warn); }
.tile.ok { border-left: 4px solid var(--ok); }
.tile h4 { margin: 0 0 .3rem; font-size: .95rem; }
.tile p { margin: 0; color: var(--fg); font-size: .9rem; }
.tile .who { font-size: .8rem; color: var(--mut); margin-bottom: .3rem; }
.list-item { margin: .4rem 0; }
.list-item .label { font-weight: 600; font-size: .88rem; display: inline-block; min-width: 11rem; }
.list-item .val { color: var(--mut); font-size: .9rem; }
.badge-status {
  display: inline-block; font-size: .72rem; font-weight: 600;
  padding: .1rem .45rem; border-radius: 999px;
  border: 1px solid var(--line);
}
.badge-status.Operational { color: var(--ok); border-color: var(--ok); background: var(--okbg); }
.badge-status.Available { color: var(--acc); border-color: var(--acc); background: var(--code); }
.badge-status.Waiting { color: var(--acc2); border-color: var(--acc2); background: #eef2fe; }
.badge-status.Down { color: var(--warn); border-color: var(--warn); background: var(--warnbg); }
table { border-collapse: collapse; width: 100%; margin: .5rem 0; font-size: .88rem; }
th, td { border: 1px solid var(--line); padding: .4rem .55rem; text-align: left; vertical-align: top; }
th { background: var(--code); font-weight: 600; }
td { font-size: .86rem; }
.tag {
  display: inline-block; font-size: .72rem; font-weight: 600;
  padding: .08rem .4rem; border-radius: 4px;
  background: var(--code); color: var(--acc);
}
.tag.warn { background: var(--warnbg); color: var(--warn); }
.tag.ok { background: var(--okbg); color: var(--ok); }
.note {
  border-left: 4px solid var(--acc); padding: .4rem .8rem; margin: .6rem 0;
  background: var(--code); border-radius: 0 4px 4px 0;
}
.note.warn { border-left-color: var(--warn); background: var(--warnbg); }
.note.ok { border-left-color: var(--ok); background: var(--okbg); }
ul.clean, ol.clean { list-style: none; padding: 0; margin: 0; }
ul.clean li, ol.clean li { margin: .2rem 0; padding-left: 1.1rem; position: relative; }
ul.clean li::before { content: "▸"; position: absolute; left: 0; color: var(--acc); font-weight: 700; }
.callout {
  background: var(--warnbg); border-left: 4px solid var(--warn);
  padding: .55rem .8rem; border-radius: 4px; margin: .7rem 0; font-size: .88rem;
}
.callout.ok { background: var(--okbg); border-left-color: var(--ok); }
.snapshot-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .6rem; }
@media (max-width: 640px) { .snapshot-grid { grid-template-columns: 1fr; } }
.snap-item { background: var(--code); border-radius: 6px; padding: .5rem .7rem; font-size: .84rem; }
.snap-item strong { color: var(--acc); }
.src { font-size: .82rem; color: var(--mut); }
hr { border: none; border-top: 1px solid var(--line); margin: 1.2rem 0; }
.kv { display: grid; grid-template-columns: 130px 1fr; gap: .5rem .8rem; font-size: .88rem; margin: .3rem 0; }
.kv .k { color: var(--mut); font-weight: 600; }
"""

def esc(s):
    """Escape HTML special chars."""
    return (s
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

def role_tile(role):
    cls = "tile primary"
    return f"""
    <div class="{cls}">
      <h4>{esc(role['name'])}</h4>
      <div class="who">{esc(role['who'])}</div>
      <p>{esc(role['role'])}</p>
    </div>"""

def model_table(environment):
    rows = ""
    for m in environment["Models"]:
        note_html = f'<div class="src">{esc(m["note"])}</div>' if m["note"] else ""
        rows += f"""
        <tr>
          <td><code>{esc(m['id'])}</code></td>
          <td>{esc(m['use'])}</td>
          <td>{note_html}</td>
        </tr>"""
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Model id</th><th>Use</th><th>Notes</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

def _render_rule_action(c):
    """Render rule and action as bold text (may be empty for some claim types)."""
    rule = c.get("rule", "")
    action = c.get("action", "")
    r_html = f"<strong>{esc(rule)}</strong>" if rule else esc(rule)
    a_html = f"<strong>{esc(action)}</strong>" if action else esc(action)
    return f"{r_html}<br>{a_html}"


def claim_table():
    rows = []
    for c in CLAIMS:
        detail = ""
        if "detail" in c or "claims" in c:
            detail = f'<div class="src">{esc(c["detail"])}</div>'

        if "claims" in c:
            # Released claims (current) entry
            claims_html = "".join(
                f'<span class="tag">{esc(x)}</span>' for x in c["claims"]
            )
            rows.append(f"""
            <tr>
              <td><span class="tag ok">{esc(c['type'])}</span></td>
              <td>{detail}</td>
              <td class="cell">{esc(c['detail'])}<br><strong>{esc(c['note'])}</strong></td>
            </tr>""")
        else:
            # Standard claim entry (type, detail, rule, action)
            tag_cls = "warn"
            rows.append(f"""
            <tr>
              <td><span class="tag {tag_cls}">{esc(c['type'])}</span></td>
              <td>{detail}</td>
              <td class="cell">{_render_rule_action(c)}</td>
            </tr>""")
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Claim type</th><th>Detail</th><th>Rule & Action</th></tr>
        </thead>
        <tbody>
        {''.join(rows)}
        </tbody>
      </table>
    </div>"""

def workers_table():
    rows = ""
    for w in WORKERS:
        status_cls = "Down" if "Down" in w["status"] else ("Available" if "Available" in w["status"] else "Waiting")
        status_badge = f'<span class="badge-status {status_cls}">{esc(w["status"])}</span>'
        rows += f"""
        <tr>
          <td><strong>{esc(w['role'])}</strong></td>
          <td>{status_badge}</td>
          <td>{esc(w['model'])}</td>
          <td>{esc(w['description'])}</td>
        </tr>"""
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Role</th><th>Status</th><th>Model</th><th>Description</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

def control_commands_table():
    rows = ""
    for cmd, desc in CONTROL_COMMANDS:
        rows += f"""
        <tr>
          <td><code>{esc(cmd)}</code></td>
          <td>{esc(desc)}</td>
        </tr>"""
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Command</th><th>Purpose / Gotchas</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

def incidents_table():
    rows = ""
    for when, what, rule in INCIDENTS:
        rows += f"""
        <tr>
          <td><span class="tag warn">{esc(when)}</span></td>
          <td>{esc(what)}</td>
          <td>{esc(rule)}</td>
        </tr>"""
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>When</th><th>What happened</th><th>Rule produced</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

def snapshot_section():
    parts = []
    parts.append(f"""
    <div class="snapshot-grid">
      <div class="snap-item"><strong>Date:</strong> {esc(SNAPSHOT['date'])}</div>
      <div class="snap-item"><strong>Check result:</strong> {esc(SNAPSHOT['check_result'])}</div>
      <div class="snap-item"><strong>Fleet:</strong> {esc(SNAPSHOT['fleet_state'][:60])}...</div>
      <div class="snap-item"><strong>Next:</strong> {esc(SNAPSHOT['next_steps'][0][:50])}...</div>
    </div>""")
    parts.append(f"""
    <div class="snapshot-grid">
      <div class="snap-item"><strong>First check post-merge:</strong> {esc(SNAPSHOT['first_check_after_merge'])}</div>
      <div class="snap-item"><strong>Gate triage:</strong> {esc(SNAPSHOT['gate_triage'][:80])}...</div>
    </div>""")
    # Formal branches
    br_rows = ""
    for name, desc in SNAPSHOT["formal_branches_landed"]:
        br_rows += f"""<tr>
            <td><strong>{esc(name)}</strong></td>
            <td>{esc(desc)}</td>
          </tr>"""
    parts.append(f"""
    <div class="snapshot-grid">
      <div class="snap-item"><strong>Formal branches landed:</strong></div>
      <div class="table-wrap" style="margin-top:.4rem">
        <table>
          <thead><tr><th>Branch</th><th>Summary</th></tr></thead>
          <tbody>{br_rows}</tbody>
        </table>
      </div>
    </div>""")
    # Open reds
    rd_rows = ""
    for r in SNAPSHOT["open_reds"]:
        rd_rows += f'<div class="src">• {esc(r)}</div>'
    parts.append(f"""
    <div class="callout">
      <strong>Open reds (unchanged, outside the 53-job check bucket):</strong>
      <ul class="clean" style="margin:.3rem 0 0; padding-left:1.2rem">
        {rd_rows}
      </ul>
    </div>""")
    return "".join(parts)

def standing_section():
    lis = "".join(f'<li>{esc(s)}</li>' for s in STANDING)
    return f"""
    <div class="note ok">
      <strong>Standing instructions (in force as of 2026-10-17):</strong>
      <ul class="clean" style="margin:.3rem 0 0; padding-left:1.2rem">{lis}</ul>
    </div>"""

def keepfull_section():
    steps_html = "".join(f"<li>{esc(s)}</li>" for s in KEEPFULL["steps"])
    return f"""
    <div class="note">
      <strong>keepfull.sh loop</strong> (run detached: <code>nohup ./keepfull.sh &gt; keepfull.log 2&gt;&amp;1 &amp;</code>)
      <div class="src">Frequency: {esc(KEEPFULL['frequency'])}</div>
      <div class="src">Command: {esc(KEEPFULL['command'])}</div>
      <strong>Steps:</strong>
      <ul class="clean" style="margin:.3rem 0 0; padding-left:1.2rem">{steps_html}</ul>
      <div class="src">{esc(KEEPFULL['behavior'])}</div>
    </div>"""

def diagnose_section():
    rows = ""
    for d in DIAGNOSIS:
        rows += f"""
        <tr>
          <td><strong>{esc(d['symptom'])}</strong></td>
          <td>{esc(d['check'])}</td>
          <td>{esc(d['action'])}</td>
        </tr>"""
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Symptom</th><th>Check</th><th>Action</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

def system_overview():
    """Bird's eye view of the whole system."""
    parts = []
    # Roles
    roles_html = ""
    for r in ROLES:
        roles_html += role_tile(r)
    parts.append(f"""
    <div class="grid-header">
      <div>
        <h2>System Architecture <span class="badge">Bird's Eye View</span></h2>
        <p class="src">The mojo-reference fleet is a Python (Mojo) compiler/interpreter with formal-verification backends (arm64 + x86-64 Mach-O, Lean proofs).
        A large backlog of bug docs in <code>bugs/</code> is worked by many parallel AI workers.</p>
      </div>
      <div>
        <h3>Roles &amp; responsibilities</h3>
        {roles_html}
      </div>
    </div>""")

    # Directory layout
    parts.append(f"""
    <h3>Directory layout</h3>
    <div class="tile primary">
      <h4>Layout</h4>
      <p>{esc(DIRECTORY_LAYOUT)}</p>
    </div>
    <div class="note">
      The registry is <code>&lt;git-common-dir&gt;/control/tasks.json</code> (shared by every worktree); queued tasks live in <code>&lt;git-common-dir&gt;/control/queue/NAME.json</code>.
      <code>CONTROL.html</code> in the repo root is a generated human-readable record (<code>control.py report</code> regenerates its task table).
    </div>""")

    # Environment
    env_parts = []
    env_parts.append(f"""
    <div class="tile">
      <h4>Environment</h4>
      <div class="kv">
        <div class="k">Python</div>
        <div>{esc(ENVIRONMENT['Python']['path'])}<br><div class="src">{esc(ENVIRONMENT['Python']['note'])}</div></div>
      </div>
      <div class="kv">
        <div class="k">opencode</div>
        <div>{esc(ENVIRONMENT['opencode']['version'])}<br><div class="src">{esc(ENVIRONMENT['opencode']['spawn'])}</div></div>
      </div>
    </div>""")
    env_parts.append(f"""
    <div class="tile accent">
      <h4>Models available</h4>
      {model_table(ENVIRONMENT)}
    </div>""")
    parts.append(f"""
    <div class="grid-header">
      <div>{env_parts[0]}</div>
      <div>{env_parts[1]}</div>
    </div>""")
    return "".join(parts)

def main():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>mojo-reference Fleet Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<div class="dashboard">

  <header>
    <h1>mojo-reference Fleet Dashboard</h1>
    <p class="subtitle">Orchestration system overview — claims, workers, architecture, and system state</p>
    <div class="meta">Generated from <code>doc/ORCHESTRATION.html</code> · Orchestration guide for the mojo-reference fleet · {esc(datetime.now().strftime('%Y-%m-%d %H:%M'))}</div>
  </header>

  <div class="grid">

    <!-- SYSTEM OVERVIEW -->
    <section class="panel" id="overview">
      <h2>System Overview <span class="badge">Bird's Eye View</span></h2>
      {system_overview()}
    </section>

    <!-- CLAIMS -->
    <section class="panel" id="claims">
      <h2>Claims System <span class="badge">Duplicate-work prevention</span></h2>
      <p class="src">Claims are strings (e.g. <code>bug:FORMAL_some_doc</code>, <code>module:os</code>, repo path). Two claims conflict when equal or path-prefix of each other. Held until <strong>integrated / abandoned / superseded</strong>.</p>
      {claim_table()}
      <div class="note warn">
        <strong>Failure mode (duplicate work):</strong> Historically, claims were released at worker exit rather than when the branch landed. Branches sat unmerged for days, bugs were re-fixed.
        <strong>Fix:</strong> claims are kept until the branch lands (commit d20d1466). The cure is to <strong>land finished branches</strong>, not release claims by hand.
      </div>
    </section>

    <!-- WORKERS -->
    <section class="panel" id="workers">
      <h2>Workers &amp; Fleet <span class="badge">All roles & models</span></h2>
      {workers_table()}
      <div class="callout">
        <strong>Current fleet state (from state snapshot):</strong> 0 workers, by design. CODEGEN turns finished 2026-10-19; the DeepSeek formal worker stays down (owner's tokens out ~19 days) — <span class="tag ok">NOT to be restarted</span>.
        Merger (strongest model) is available when finished branches need merging.
      </div>
    </section>

    <!-- KEEPFULL + INTEGRATION -->
    <section class="panel" id="keepfull">
      <h2>keep-full Loop &amp; Integration</h2>
      {keepfull_section()}
      <h3>Integration: landing branches on master</h3>
      <ul class="clean">
        {"".join(f"<li>{esc(s)}</li>" for s in INTEGRATION)}
      </ul>
    </section>

    <!-- CONTROL + GATE + MONITORING -->
    <section class="panel" id="control">
      <h2>Control System &amp; Gate</h2>
      <div class="grid-header">
        <div>
          <h3>control.py commands</h3>
          {control_commands_table()}
        </div>
        <div>
          <h3>The gate (<code>suite.py</code>)</h3>
          <div class="kv">
            <div class="k">check</div>
            <div>{esc(GATE['check'])}</div>
          </div>
          <div class="kv">
            <div class="k">full gate</div>
            <div>{esc(GATE['full_gate'])}</div>
          </div>
          <div class="kv">
            <div class="k">how to run</div>
            <div>{esc(GATE['run'])}</div>
          </div>
          <h3>Reading notes</h3>
          <ul class="clean" style="padding-left:1.2rem">{"".join(f"<li>{esc(n)}</li>" for n in GATE["reading_notes"])}</ul>
        </div>
      </div>
    </section>

  </div>

  <div class="grid grid-2">

    <!-- INCIDENTS -->
    <section class="panel" id="incidents">
      <h2>Incidents &amp; Rules <span class="badge">History → rules</span></h2>
      {incidents_table()}
    </section>

    <!-- STATE SNAPSHOT -->
    <section class="panel" id="snapshot">
      <h2>State Snapshot <span class="badge">2026-10-20 ~03:30</span></h2>
      {snapshot_section()}
    </section>

    <!-- STANDING + RESOURCES + DIAGNOSIS -->
    <section class="panel" id="diagnose">
      <h2>Diagnosis &amp; Resources</h2>
      <h3>Diagnosing a worker</h3>
      {diagnose_section()}
      <hr>
      <h3>Resources (memory, disk, processes)</h3>
      <div class="grid grid-3">
        {"".join(
            f'<div class="tile"><h4>{esc(r["category"])}</h4><div class="src">{esc(r["detail"])}</div>{"" if r.get("classes", "") else ""}</div>'
            for r in RESOURCES
        )}
        {"".join(
            f'<div class="tile accent"><h4>{esc(r["category"])}</h4><div class="src">{esc(r["detail"])}</div></div>'
            for r in RESOURCES if r.get("classes", "")
        )}
      </div>
    </section>

    <section class="panel" id="standing">
      {standing_section()}
    </section>

  </div>

  <div class="panel" style="margin-top:1rem">
    <h2>Monitoring loop (every 50 minutes)</h2>
    <div class="note ok">
      <strong>Frequency:</strong> every 50 minutes — keeps the model prompt cache warm and keeps the fleet healthy.
      <div class="src">Purpose: Check workers, finished work, hard-problem agents, queue &amp; keep-full, verification, and resources.</div>
      <ul class="clean" style="margin:.3rem 0 0; padding-left:1.2rem">{"".join(f"<li>{esc(s)}</li>" for s in MONITORING["steps"])}</ul>
    </div>
  </div>

</div>
</body>
</html>"""

    # Under the repo's gitignored build/ rather than a shared /tmp name, so two
    # runs (or two worktrees) never write the same file.
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                           "build")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.normpath(os.path.join(out_dir, "dashboard.html"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard written to: {out_path}")
    print(f"File size: {os.path.getsize(out_path)} bytes")

if __name__ == "__main__":
    main()