#!/usr/bin/env python3
"""The gate ledger: when the full gate must run, what it found, and when each red job last worked.

Four jobs, each a pure function over git and text so each can be tested without a gate run:

  needs_gate(files)        does a change touch anything a gate can see? Docs and the orchestration tools cannot.
  pending(last_sha, tip)   the first-parent commits since the last full gate whose files need one. The full gate runs
                           as long as there is at least one; it is no longer a timer.
  first_bad(commits, bad)  binary search: of COMMITS (oldest first, the last one known bad) the first that is bad.
                           The job before it is the last that worked.
  set_disabled / drop_disabled  edit the `disabled=` marker of one registration in tools/suite.py (an ast splice, so a
                           comment or a neighbouring job is never touched). A red job is disabled with its gate doc as the
                           switch, so it costs the gate no time; the fixer who fixes it deletes the doc and the marker.
                           Only a marker naming bugs/gate-<job>.md is ever dropped: a person's marker is theirs.

State is one file, <git common dir>/control/gate_ledger.json: per job, whether it is red, the last sha it worked on,
the first sha it was seen failing on (None when no earlier run covered it), and the run that saw it."""
import ast, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

MARK = "gate-ledger:"            # every marker this module writes starts with it, so it can find its own

# Files whose change cannot alter any gate job's verdict: prose, the bug queue, and the orchestration machinery.
EXEMPT_PREFIXES = ("bugs/", "doc/", "docs/")
EXEMPT_TOOLS = {"swarm.py", "control.py", "integrate.py", "autointegrate.py", "verify_landed.py", "gate_ledger.py",
                "fleet_ledger.py", "task_text.py", "formal_feed.py", "pool.json", "gates.json", "priority.json",
                "control_prompt.md", "dangling_doc_refs.py", "dangling_refs_baseline.py"}


def needs_gate(files):
    """True if any of FILES is something a gate job reads. The orchestration tools (and their own tests) are exempt;
    everything else is not, because the compiled path is invisible to a reading of the diff (CLAUDE.md)."""
    for f in files:
        if f.endswith(".md") or f.startswith(EXEMPT_PREFIXES):
            continue
        base = os.path.basename(f)
        if f.startswith("tools/") and (base in EXEMPT_TOOLS or re.fullmatch(r"test_(swarm|orch|chain_cap|fleet|gate_ledger)\w*\.py", base)):
            continue
        return True
    return False


def _git(*a, cwd=None):
    r = subprocess.run(["git", *a], cwd=cwd or C.MAIN, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def pending(last_sha, tip="master", cwd=None):
    """[(sha, subject)] of the first-parent commits in last_sha..tip that need a gate, oldest first. With no
    last_sha (no full gate has ever run) every first-parent commit is unverified: that is one entry, the tip."""
    if not last_sha:
        s = _git("log", "-1", "--format=%H %s", tip, cwd=cwd)
        return [tuple(s.split(" ", 1))] if s else []
    out = []
    for line in _git("log", "--first-parent", "--reverse", "--format=%H %s", "%s..%s" % (last_sha, tip), cwd=cwd).splitlines():
        sha, _, subj = line.partition(" ")
        files = _git("diff", "--name-only", sha + "^", sha, cwd=cwd).splitlines()
        if needs_gate(files):
            out.append((sha, subj))
    return out


def commits_between(good, bad, cwd=None):
    """First-parent commits after GOOD up to and including BAD, oldest first."""
    return _git("rev-list", "--first-parent", "--reverse", "%s..%s" % (good, bad), cwd=cwd).split()


def first_bad(commits, is_bad):
    """The first commit in COMMITS (oldest first; the last is known bad) for which is_bad(sha) holds, assuming the job
    stays red once it breaks. Returns (first_bad, probes) where probes is how many times is_bad ran."""
    lo, hi, probes = 0, len(commits) - 1, 0          # commits[hi] is bad
    while lo < hi:
        mid = (lo + hi) // 2
        probes += 1
        if is_bad(commits[mid]):
            hi = mid
        else:
            lo = mid + 1
    return commits[hi], probes


# ---- the marker edit ------------------------------------------------------------------------------------------

def _registrations(src, job):
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("test", "fanout")
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == job):
            yield n


def _offsets(src):
    b = src.encode()
    starts, pos = [0], 0
    for line in b.split(b"\n"):
        pos += len(line) + 1
        starts.append(pos)
    return b, starts


def _span(node, starts):
    return starts[node.lineno - 1] + node.col_offset, starts[node.end_lineno - 1] + node.end_col_offset


def _splice(b, lo, hi, text):
    return (b[:lo] + text.encode() + b[hi:]).decode()


def get_marker(src, job, kw_name):
    """The registration's text for keyword KW_NAME (`expect` or `disabled`), or None when empty or absent."""
    for call in _registrations(src, job):
        for kw in call.keywords:
            if kw.arg == kw_name and isinstance(kw.value, ast.Constant) and kw.value.value:
                return kw.value.value
        return None
    return None


def set_marker(src, job, kw_name, value):
    """SRC with `KW_NAME=<value>` on JOB's registration; unchanged when the job already carries any non-empty
    expect/disabled marker (a marker is somebody's statement; this never overwrites one) or has no registration."""
    for call in _registrations(src, job):
        b, starts = _offsets(src)
        for kw in call.keywords:
            if kw.arg in ("expect", "disabled") and getattr(kw.value, "value", "x"):
                return src
        for kw in call.keywords:
            if kw.arg == kw_name:
                lo, hi = _span(kw.value, starts)           # `expect=''`: fill it in
                return _splice(b, lo, hi, repr(value))
        last = (call.keywords[-1].value if call.keywords else call.args[-1])
        _, hi = _span(last, starts)
        indent = " " * (call.args[0].col_offset if call.lineno != call.args[0].lineno else call.col_offset + 5)
        if call.lineno == call.end_lineno:
            return _splice(b, hi, hi, ", %s=%r" % (kw_name, value))
        return _splice(b, hi, hi, ",\n%s%s=%r" % (indent, kw_name, value))
    return src


def drop_marker(src, job, kw_name, prefix):
    """SRC without JOB's KW_NAME marker, but only when its text starts with PREFIX (ours)."""
    for call in _registrations(src, job):
        b, starts = _offsets(src)
        items = sorted(list(call.args) + [kw.value for kw in call.keywords], key=lambda n: (n.lineno, n.col_offset))
        for kw in call.keywords:
            if kw.arg == kw_name and isinstance(kw.value, ast.Constant) and str(kw.value.value).startswith(prefix):
                i = items.index(kw.value)
                _, prev_end = _span(items[i - 1], starts)
                _, end = _span(kw.value, starts)
                return _splice(b, prev_end, end, "")
    return src


def doc_path(job):
    return "bugs/gate-%s.md" % job


# A red job is DISABLED, not expect-marked: `disabled=<doc>` means the job is registered and never run (no process, no
# memory, no wall time), so a known failure costs the gate nothing. The doc is the switch (tools/suite.py refuses to
# load while a disabled test's doc is gone), so the fixer's commit that deletes the doc must also take the marker off.
def set_disabled(src, job):
    return set_marker(src, job, "disabled", doc_path(job))


def drop_disabled(src, job):
    return drop_marker(src, job, "disabled", doc_path(job))


def get_disabled(src, job):
    return get_marker(src, job, "disabled")


def get_expect(src, job):
    return get_marker(src, job, "expect")


def set_expect(src, job, reason):
    return set_marker(src, job, "expect", reason)


def drop_expect(src, job, prefix=MARK):
    return drop_marker(src, job, "expect", prefix)


# ---- the state ------------------------------------------------------------------------------------------------

def path():
    return os.path.join(C.ctl_dir(), "gate_ledger.json")


def load():
    try:
        return json.load(open(path()))
    except (OSError, ValueError):
        return {"jobs": {}}


def save(st):
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1, sort_keys=True)
    os.replace(tmp, path())


def reconcile(st, run_sha, failed, passed, prev):
    """Fold one full-gate run into the ledger. FAILED are the red jobs, PASSED the ones the run saw pass, PREV the
    previous run's {"sha":..., "failed": [...]} (the last_good of a job that was green then). Returns
    (newly_red, recovered): the jobs whose first_bad must now be found, and those that came back."""
    jobs, newly, recovered = st.setdefault("jobs", {}), [], []
    for j in failed:
        e = jobs.get(j)
        if e and e.get("red"):
            e["last_seen_bad"] = run_sha
            continue
        good = (e or {}).get("last_good")
        if not good and prev.get("sha") and j not in prev.get("failed", []) and not prev.get("unknown"):
            good = prev["sha"]
        jobs[j] = {"red": True, "last_good": good, "first_bad": None, "last_seen_bad": run_sha, "marked": False}
        newly.append(j)
    for j in passed:
        e = jobs.get(j)
        if e and e.get("red"):
            recovered.append(j)
            jobs[j] = {"red": False, "last_good": run_sha}
        elif j not in jobs:
            jobs[j] = {"red": False, "last_good": run_sha}
        else:
            jobs[j]["last_good"] = run_sha
    return newly, recovered


def report_text(job, e, run_sha, log, subj_of):
    """The body of the ledger section filed in bugs/gate-<job>.md."""
    def show(sha):
        return "none recorded (no earlier full-gate run covered this job)" if not sha else "`%s` %s" % (sha[:10], subj_of(sha))
    fb = e.get("first_bad")
    return ("## Gate ledger\n\n"
            "- **Last known working:** %s\n"
            "- **First known not working:** %s\n"
            "- **Seen red in the full gate at:** `%s` (log `%s`)\n"
            "- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='%s'`, so the gate spends no time on it. "
            "To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.\n"
            % (show(e.get("last_good")), show(fb) if fb else "not bisected: " + (e.get("bisect_note") or "unknown"),
               run_sha[:10], log, doc_path(job)))
