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

try:
    C.pool_slot("no-such-slot")
    check("an unknown slot is refused", False)
except SystemExit:
    check("an unknown slot is refused", True)

pool = C.load_pool()
check("the pool's default slot exists", any(s["name"] == pool["default_slot"] for s in pool["slots"]))
check("the pool's total is the sum of its counts", C.pool_total() == sum(s["count"] for s in pool["slots"]))
check("every slot names exactly one model", all(isinstance(s["model"], str) for s in pool["slots"]))

print("%d passed, %d failed" % (len(PASSES), len(FAILS)))
sys.exit(1 if FAILS else 0)
