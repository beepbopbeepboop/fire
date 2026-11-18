#!/usr/bin/env python3
"""Pool rules of tools/control.py: a slot takes work only up to its count, never runs on another slot's model, and a
banned model takes nothing; a second limit inside a day escalates the ban to the long window.

Uses a temporary ledger directory, so it never reads or writes the live registry."""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

_tmp = tempfile.mkdtemp(prefix="pooltest_")
C.ctl_dir = lambda: _tmp
FAILS = []


PASSES = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    (PASSES if cond else FAILS).append(name)


haiku = {"name": "haiku", "model": "claude-haiku-5-5", "count": 1, "kind": "claude", "recover_hours": 24}
paid = {"name": "opencode-paid", "model": "opencode-go/deepseek-v4.1-flash", "count": 1, "kind": "opencode",
        "recover_hours": 2.5, "long_recover_days": 15}

check("a free slot takes work", C.slot_free(haiku, {}))
check("a full slot takes nothing", not C.slot_free(haiku, {"haiku": 1}))
check("a slot counts only its own running tasks", C.slot_free(haiku, {"qwen-local": 2}))

h = C.mark_dead(paid["model"], paid)
check("first limit waits the short block (2.5 h)", abs(h - 2.5) < 1e-9)
check("a banned model's slot takes nothing", not C.slot_free(paid, {}))
check("a banned model shows in dead_models", paid["model"] in C.dead_models())

# the 5-hour block lifts; the next limit inside a day is the long block
d = json.load(open(os.path.join(_tmp, C.LEDGER)))
d[paid["model"]]["until"] = time.time() - 1
json.dump(d, open(os.path.join(_tmp, C.LEDGER), "w"))
check("the lifted ban frees the slot", C.slot_free(paid, {}))
h2 = C.mark_dead(paid["model"], paid)
check("a second limit inside a day waits the 15-day block", abs(h2 - 15 * 24) < 1e-9)

# a limit that prints its reset ends the ban at that reset (plus the margin), not at the recovery time
from datetime import datetime
from zoneinfo import ZoneInfo
_now = datetime(2026, 11, 1, 9, 22, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
_r = C.reset_at("You've hit your 5-hour limit \u00b7 resets 11am (America/Los_Angeles)", _now)
check("the printed 11am reset is the next 11am Pacific", datetime.fromtimestamp(_r, ZoneInfo("America/Los_Angeles")).hour == 11 and _r - _now < 3600 * 2)
check("a reset already passed today rolls to tomorrow", C.reset_at("resets 8am (America/Los_Angeles)", _now) - _now > 3600 * 20)
check("no reset in the text, no reset time", C.reset_at("nothing printed", _now) is None)
_fut = time.time() + 3600
h3 = C.mark_dead("claude-test-model", {"name": "t", "model": "claude-test-model", "recover_hours": 4.23}, _fut)
check("a ban with a printed reset ends at it plus the margin", abs(h3 - (3600 + C.RESET_MARGIN_S) / 3600) < 0.01)
check("a reset already past falls back to the recovery time", abs(C.mark_dead("claude-test-model", {"name": "t", "model": "claude-test-model", "recover_hours": 4.23}, time.time() - 60) - 4.23) < 1e-9)

# a daily free tier bans until its replenish time, plus the margin, not for a fixed block
_utc = datetime(2026, 11, 1, 9, 0, tzinfo=ZoneInfo("UTC")).timestamp()
_free = {"name": "free", "model": "free-model", "recover_hours": 2.5,
         "replenish": {"tz": "UTC", "at": "00:00", "margin_min": 1}}
_rp = C.replenish_at(_free, _utc)
check("a daily tier replenishes at its time plus the margin", datetime.fromtimestamp(_rp, ZoneInfo("UTC")).strftime("%F %H:%M") == "2026-11-02 00:01")
check("a slot without a replenish time has none", C.replenish_at({"name": "x", "model": "x", "recover_hours": 1}, _utc) is None)
C.mark_dead("free-model", _free, now=_utc)
check("a limit on a daily tier bans until the next replenish", abs(C._ledger()["free-model"]["until"] - _rp) < 1)

# holds: only work holds a claim; a dead entry with no commits holds nothing and cannot block a retry
_real_ahead = C.ahead
C.ahead = lambda t: t["_ahead"]
try:
    check("a dead entry with no commits does not hold its claim", not C.holds_claims({"state": "integration-failed", "pid": 0, "worktree": "/x", "_ahead": 0}))
    check("a dead entry with commits holds its claim", C.holds_claims({"state": "exited-err", "pid": 0, "worktree": "/x", "_ahead": 1}))
finally:
    C.ahead = _real_ahead

try:
    C.pool_slot("no-such-slot")
    check("an unknown slot is refused", False)
except SystemExit:
    check("an unknown slot is refused", True)

check("find_slot returns None for a removed slot", C.find_slot("no-such-slot") is None)
check("a pinned task whose slot was removed waits instead of exiting",
      C.pick_slot({"only": True, "pool": "no-such-slot"}, {}) is None)
_real_load_pool = C.load_pool
C.load_pool = lambda: {"slots": [dict(name="a", model="ma", count=1, kind="opencode")]}
check("a dead task whose slot was removed is not restarted",
      C.no_restart_reason({"model": "gone", "pool": "gone"}, C.load_pool(), {}) is not None)
check("a hand-run model with no slot is left to its own retries",
      C.no_restart_reason({"model": "gone"}, C.load_pool(), {}) is None)
C.load_pool = _real_load_pool

pool = C.load_pool()
check("the pool's default slot exists", any(s["name"] == pool["default_slot"] for s in pool["slots"]))
check("the pool's total is the sum of its counts", C.pool_total() == sum(s["count"] for s in pool["slots"]))
check("every slot names exactly one model", all(isinstance(s["model"], str) for s in pool["slots"]))

# dispatch: a queued task is not tied to a slot. Its preferred slot if free, else the first free slot, else it waits.
_real_load_pool = C.load_pool
C.load_pool = lambda: {"slots": [dict(name="a", model="ma", count=1, kind="opencode"),
                                 dict(name="b", model="mb", count=1, kind="opencode")]}
check("a task with no preferred slot takes the first free slot", C.pick_slot({"pool": None}, {"a": 1})["name"] == "b")
check("a task takes its preferred slot when that is free", C.pick_slot({"pool": "b"}, {})["name"] == "b")
check("a task whose preferred slot is busy moves to a free one", C.pick_slot({"pool": "a"}, {"a": 1})["name"] == "b")
check("with every slot full the task waits", C.pick_slot({"pool": "a"}, {"a": 1, "b": 1}) is None)
C.load_pool = _real_load_pool

# free-tier probe: a daily free tier's ban ends when the tier answers a one-word prompt, not at a guessed reset.
_real_load_pool = C.load_pool
C.load_pool = lambda: {"slots": [dict(name="free", model="mfree", count=1, kind="opencode", replenish={"tz": "UTC", "at": "00:00", "margin_min": 1}),
                                 dict(name="paid", model="mpaid", count=1, kind="opencode")]}
_now = time.time()
C.mark_dead("mfree", {"name": "free", "replenish": {"tz": "UTC", "at": "00:00", "margin_min": 1}}, until=_now + 2 * C.PROBE_EVERY_S, now=_now)
C.mark_dead("mpaid", {"name": "paid", "recover_hours": 2.5}, until=_now + 3600, now=_now)
C.mark_dead("removed-model", {"name": "gone", "recover_hours": 24}, now=_now)   # no slot uses it
asked = []
C.probe_free_bans(now=_now, probe=lambda m: asked.append(m) or False)
check("a ban for a model no longer in the pool is pruned", "removed-model" not in C._ledger())
check("a refusing free tier is asked", asked == ["mfree"])
check("a refusing free tier stays banned", C._ledger()["mfree"]["until"] > _now)
check("a paid model is never probed", "mpaid" not in asked)
C.probe_free_bans(now=_now + 60, probe=lambda m: asked.append(m) or False)
check("a free tier is not re-asked inside the probe interval", asked == ["mfree"])
lifted = C.probe_free_bans(now=_now + C.PROBE_EVERY_S + 1, probe=lambda m: True)
check("a free tier that answers is lifted", lifted == ["mfree"] and C._ledger()["mfree"]["until"] <= _now + C.PROBE_EVERY_S + 1)
C.load_pool = _real_load_pool

# a worker's tree: every process a shell under it started, however deep, is among its descendants
import subprocess as _sp
_tree = _sp.Popen(["sh", "-c", "sleep 60 & sh -c 'sleep 61' & wait"])
time.sleep(0.5)
_kids = C.descendants(_tree.pid)
check("the descendants of a worker's shell include every job it started", len(_kids) >= 2)
check("a process is not its own descendant", _tree.pid not in _kids)
for _k in _kids:
    try: os.kill(_k, 9)
    except OSError: pass
_tree.kill()

# Per-model worker rules (a slot's `instructions` in pool.json): added to the prompt of a worker on that model only.
import re
RULE = "Do not use git config to change configuration data for git."
_real_load_pool = C.load_pool
C.load_pool = lambda: {"slots": [
    {"name": "or", "model": "m/free", "instructions": [RULE]},
    {"name": "or2", "model": "m/free", "instructions": [RULE, "second rule"]},   # same model, deduplicated
    {"name": "plain", "model": "m/plain"}]}
check("a model's slot instructions are returned, deduplicated, in order",
      C.model_instructions("m/free") == [RULE, "second rule"])
check("a model with no instructions gets none", C.model_instructions("m/plain") == [])
check("an unknown model gets none", C.model_instructions("m/other") == [])

_tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "control_prompt.md")).read().format(
    name="n", worktree="/w", branch="b", main="/m", task="THE TASK TEXT", claims="c", control="/c")
_ruled = C.with_model_rules(_tpl, "m/free")
check("the rule is in the prompt for that model", RULE in _ruled and "## Rules for this model" in _ruled)
check("the rule is NOT in the prompt for another model", C.with_model_rules(_tpl, "m/plain") == _tpl)
check("the rule sits after the rules and before the report section",
      _ruled.index("## Rules") < _ruled.index(RULE) < _ruled.index("## When you finish"))
check("the section is added once", _ruled.count("## Rules for this model") == 1)
_m = re.search(r"## The task\n\n(.*?)\n\n## Rules", _ruled, re.S)      # what control._task_text does on a restart
check("restart still recovers exactly the original task", _m is not None and _m.group(1) == "THE TASK TEXT")
check("without a '## When you finish' heading the rules are appended",
      RULE in C.with_model_rules("# x\n\n## The task\n\nT\n\n## Rules\n\nr\n", "m/free"))
C.load_pool = _real_load_pool
_real = {sl["name"]: sl for sl in C.load_pool()["slots"]}
check("pool.json: the free OpenRouter slot forbids `git config` for its workers",
      RULE in _real["openrouter-free"].get("instructions", []))
check("pool.json: the model-keyed lookup finds it for the OpenRouter free router",
      RULE in C.model_instructions("openrouter/openrouter/free"))

print("%d passed, %d failed" % (len(PASSES), len(FAILS)))
sys.exit(1 if FAILS else 0)
