# `test_formal_sweep_truth.py`'s `math` case is stale: `formal/hostmods/math.mojo` exists

**What I ran.** `python3 -m unittest test_formal_sweep_truth.TestSystemModuleCall`
(also hit by `python3 test_formal_sweep_truth.py`, which is the suite's
`formal-sweep-truth` job).

**What I saw.** 1 failure:

```
FAIL: test_a_message_naming_a_host_member_is_a_target_fact
AssertionError: '' != 'math'
```

**What I expected.** Green. The test asserts that the diagnostic
`"build: math.floor() cannot be lowered: math is not available here"` is
classified as a target fact (`CLASS_SYSCALL`), on the stated ground that "`math`
has no Mojo source in this tree" — the class comment, five lines above the
assertion.

**Why it is red.** `formal/hostmods/math.mojo` landed in `9c7ec795`
("math: the seven integer-valued functions, plus the five float constants as bit
patterns"), so the premise is no longer true and
`formal_sweep._system_module_call` — which consults the real import tiers —
correctly returns `""`. The test is asserting a fact about the tree that the
tree stopped being true of, and it is asserting it through a *classifier's*
answer rather than through the classifier's input.

**Exact next step** (not done here: this is `formal/hostmods` territory, and
this change's area is `lean:launcher`): replace the `math` case with a host
module that genuinely has no Mojo source — `subprocess`, `ctypes`, `asyncio`,
`threading`, `socket` are the ones `IN_REACH_HOST_MODULES` must never contain
and the next class down asserts exactly that list. The class comment needs the
same edit, and the honest form of the rule is "a message naming a host module
**that this tree cannot resolve** is a target fact", which needs the tier list
rather than a hard-coded name — the same shape as the `json` case that comment
already records having been fixed once.

**Note for whoever runs the gate:** this is one of the six failures in that file,
and it is pre-existing — it reproduces with `formal/lean.py` reverted, since
nothing it touches (`formal_sweep.py`, `formal/hostmods/`) is in this change's
write set. The class asserts only through `formal_sweep._system_module_call`
and `IN_REACH_HOST_MODULES`, neither of which the launcher change alters.
