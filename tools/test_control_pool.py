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
C.mark_dead("free-model", _free)
check("a limit on a daily tier bans until the next replenish", abs(C.dead_models()["free-model"] - _rp) < 1)

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

print("%d passed, %d failed" % (len(PASSES), len(FAILS)))
sys.exit(1 if FAILS else 0)
