"""Model triage for a landing probe that keeps producing no verdict (swarm.resolve_stuck_batch).

`swarm.land()` probes a batch of finished branches behind the gate. When that probe gives no verdict twice in a row
(EMPTY: the process ended without reporting; ERROR: it died with an exception; RED-INCONCLUSIVE: the culprit search
could not run), retrying it blindly is the loop that ran all night. This module asks a Sonnet reviewer, once, what to
do, and parses its answer.

The reviewer returns ONE JSON object and nothing else. The action set is closed:

    land_doc  file the named branch's LAND doc (the branch is capped and left for a worker to assess)
    retry     allow one more probe of the same batch
    park      stop probing this exact batch until a branch tip changes

It can NOT land anything, edit tools/gates.json, add expect=/disabled= markers, or push. Those are not in the action
set, and parse_decision rejects anything that is not one of the three.
"""
import json
import re
import subprocess

MODEL = "claude-sonnet-5-5"
ACTIONS = ("land_doc", "retry", "park")
TIMEOUT_S = 900
TAIL_CHARS = 6000


def build_prompt(batch, out, verdict):
    return (
        "You are triaging a stuck landing probe in a compiler repository's integrator. The integrator merges finished "
        "branches into a scratch tree and runs a gate once; a probe that prints no PROBE verdict is not evidence about "
        "the branches, and retrying it unchanged wastes the machine.\n\n"
        "Probe verdict: %s\nBatch (branch task names): %s\n\n"
        "Last %d characters of the probe's output:\n-----\n%s\n-----\n\n"
        "Choose exactly one action:\n"
        "- land_doc: one branch in the batch is the cause (its merge breaks the probe, or it keeps conflicting). Name it.\n"
        "- retry: the output shows a transient cause (a lock, a timeout, a memory wait). Only one retry is allowed.\n"
        "- park: the cause is not clear from the output. The batch waits until a branch changes.\n\n"
        "Reply with ONLY one JSON object, no prose, in this form:\n"
        '{"action": "land_doc" | "retry" | "park", "branch": "<task name or null>", "reason": "<one sentence>"}'
        % (verdict, " ".join(batch), TAIL_CHARS, out[-TAIL_CHARS:])
    )


def parse_decision(text, batch):
    """The one decision in TEXT, validated: a closed action, and a branch that is in BATCH for land_doc. Raises
    ValueError on anything else, so a malformed or out-of-set answer parks the batch instead of acting on it."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in the reviewer's reply")
    d = json.loads(m.group(0))
    action = d.get("action")
    branch = d.get("branch")
    reason = str(d.get("reason") or "")[:400]
    if action not in ACTIONS:
        raise ValueError("action %r is not one of %s" % (action, ", ".join(ACTIONS)))
    if action == "land_doc" and branch not in batch:
        raise ValueError("land_doc names %r, which is not in the batch" % (branch,))
    return {"action": action, "branch": branch if action == "land_doc" else None, "reason": reason}


def ask(batch, out, verdict, run=subprocess.run):
    """One decision for a stuck probe. Raises on a failed call or an unusable answer; the caller parks on that."""
    r = run(["claude", "-p", build_prompt(batch, out, verdict), "--model", MODEL],
            capture_output=True, text=True, timeout=TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError("claude -p exited %d: %s" % (r.returncode, (r.stderr or "")[-200:]))
    return parse_decision(r.stdout, batch)
