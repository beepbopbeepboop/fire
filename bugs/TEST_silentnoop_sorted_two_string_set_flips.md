# TEST: `silentnoop`'s `parameter_rebound_to_one_container_kind_is_not_multi_kind` is a ~5% coin flip

Found 2026-10-02 while gating a compiled-path change, so `silentnoop` went red
on a case nobody was working on. It is NOT caused by the change under test (see
the baseline measurement below), and it is not the case's subject: the case is
about container-kind tracking for a reassigned parameter, and what fails is the
ORDER of a two-element string set after `sorted`.

## Status (2026-10-04 — NOT reproduced in 16 further harness runs; the doc's own hypothesis is now MEASURED and ELIMINATED, and the missing evidence is now kept automatically)

### What was re-measured, and what it rules out

Sixteen faithful single-case runs of the harness (the case's own
`_case`/`_compiled_stdout` path, fresh temp dir each time, so a fresh compile
each time) on this tree: **16/16 correct**. Plus, on the same tree:

| what | result |
|---|---|
| `fire.py --dump` of the case's source, 14 runs | the `.ci` is **byte-identical** every time |
| the same, from three source paths of different length (2, 10, 70 chars) | byte-identical, and `mojo_set_sorted` emitted in all three |
| `fire.py build` of the same source to two different `-o` paths | the two **binaries are byte-identical** (`cmp`) |
| what `_mojo_sorted_str_ok`'s window admits, measured on this host | every address class: `strdup` `0x1052e9930`, a `static char *` literal `0x104c9864c`, `malloc(1 MiB)` `0x7ff480000`, `malloc(256 MiB)` `0xc28000000` — all inside `[0x1000, 2^47)` |

**So the hypothesis this doc ranked first cannot be the mechanism.** The chain
is: `mojo_set_sorted` finds a `tag == 1` slot, so `is_str` is set, so the list
goes to `mojo_list_sorted_str(out)` with `MOJO_KIND_STR`, whose comparator is
`_mojo_sorted_str_cmp` → `strcmp` on the set's own `strdup` copies. The
comparator's "two slots that both fail the plausibility test compare EQUAL" arm
needs a slot outside `[0x1000, 2^47)`, and **no user-space address this target
can produce is outside it** — arm64 macOS user space ends at `2^47`, and the four
classes measured above are four different ways of allocating inside it. For any
two in-window slots the comparator is `strcmp`, which cannot call `"q"` and
`"r"` equal. Whatever failed, it was not this.

### What that leaves, and it is now a one-command question

The observed output is exactly slot order for `{"q", "r"}`, so the last
lexicographic pass did not happen or did not swap — from a *different runtime
call* than the one above. The single discriminating measurement is
`grep mojo_set_sorted <the failing build's own .ci>`: `mojo_sorted` (the generic
int64-payload sort, which orders a list of strings by ADDRESS) instead of
`mojo_set_sorted` produces this symptom and is decided by codegen's element-type
evidence for `box` — a `MojoSet *` parameter reached through a set
comprehension, which is the one shape in the case no other line exercises.

**That measurement used to be impossible**, and that is the other half of what
landed: every case built in a `TemporaryDirectory` and took its evidence with it
— both stdouts, the compiler's own output, the generated C and the binary.
`test_silent_noop_iter.py` now copies all of it into
`.tmp/silentnoop-failures/<case>/` on ANY failure (source, both stdouts, the
compiled stderr, the binary, and a `--dump` of the same source) and names the
directory in the failure line. The next occurrence is self-diagnosing: the `.ci`
is on disk next to the failure.

Verified here by calling that path directly — it keeps
`program.{py,ci,ast,tok,pyi}` and `stdout.txt`, and the kept `.ci` contains
`mojo_set_sorted`. The two cases named above still pass.

### Still open

Which call the failing compile emitted, and why that compile differed from the
ones measured above — given that the `.ci` is byte-identical per source on this
tree, the variation is upstream of codegen (a stale cached module dylib or object
served from `~/.gmojo/cas`, which is shared by every worktree on this box, is
the obvious candidate and is exactly the question a kept `.ci` plus the CAS key
answers). Nothing further is asserted here: it has not been reproduced, and the
instrumentation to catch it now exists.

## Status (2026-10-02 — reproduced at a low rate on an unmodified tree; mechanism NOT established)

## The symptom

```
FAIL  parameter_rebound_to_one_container_kind_is_not_multi_kind
      compiled "['a']\n['x']\n['r', 'q']\nfirst\n"
      != reference "['a']\n['x']\n['q', 'r']\nfirst\n"
```

The third line is `print(pick({"q", "r"}, None))`, and `pick` ends in
`return sorted(box)`. CPython prints `['q', 'r']`. The compiled path printed
`['r', 'q']` — i.e. `sorted()` over the compiled set returned UNSORTED. The
other three lines agree, and `rc` is 0, so nothing else in the program is
wrong.

## Measurements (all on macOS/arm64)

| what | result |
|---|---|
| baseline commit `c8c273ff`, single-case runs | 1 failure in 11, then 1 in 20 |
| same commit, 12 further single-case runs | 1 failure in 12 |
| working tree with the change under test, 12 single-case runs | 0 failures |
| working tree, 40 FRESH compiles of the case, run once each | 40/40 correct |
| one compiled binary, run 200 times | 200/200 correct |
| a synthetic program with 300 distinct `sorted({'bNNNN','aNNNN'})` calls | 300/300 correct |

So it is real, it is rare, it is not tied to the change under test, and — the
part that makes it awkward — it did not reproduce on demand in any of the
attempts above.

## What has been ruled out

- **`PYTHONHASHSEED` on the reference side.** `sorted()` is
  order-independent, so the reference cannot be the side that varies, and the
  failing message names `compiled` as the wrong one.
- **Non-determinism in the compiled BINARY.** 200 runs of one binary gave the
  correct order every time; the variation tracks the COMPILE, not the run.
- **A general string-sort failure.** 300 distinct two-string sets in one
  program all sorted correctly.
- **The change under test.** Measured at the baseline commit above.

## Where to instrument next

The compiled program's third line is reached through
`mojo_set_sorted(box)` (`runtime/fire_runtime.c`), which appends the set's
slots in SLOT order and then hands the list to `mojo_list_sorted_str`. If the
final sort does not run, the printed order is exactly slot order, i.e.
`_str_hash(v) % cap` order — which for `{"q", "r"}` is `['r', 'q']`, matching
the observed failure. So the question is precisely: **why would
`mojo_list_sorted_str` not order these two?**

The one address-dependent step on that path is the comparator's pointer
plausibility test:

```c
static int _mojo_sorted_str_ok(int64_t raw) {
    uint64_t v = (uint64_t)raw;
    return v >= 0x1000ULL && v < 0x0000800000000000ULL;
}
static int _mojo_sorted_str_cmp(int64_t a_raw, int64_t b_raw) {
    ...
    if (!a_ok && !b_ok) return 0;      /* EQUAL — so no swap happens */
    ...
}
```

Two slots that both fail the check compare EQUAL, and `_mojo_permute_by` then
leaves them in the order it found them, which is slot order. That is exactly
the observed wrong answer. Its own comment says the range is a heuristic
chosen to be "high enough that no int64_t payload lands there", i.e. it is
known to be a guess.

The gap between this hypothesis and the measurements above is that the 300-set
probe did not trip it, which suggests the trip condition is rarer than "any
string outside a range" — possibly a specific compiled-artifact layout, a
specific `cap`, or something outside this path entirely. Instrument
`_mojo_sorted_str_cmp` (or add a counter for `!a_ok && !b_ok`) and loop the
single case until it fails; that is the cheapest way to tell this hypothesis
from another one.

## Until then

`silentnoop` carries a real red at a low rate, so a green run of it is not
evidence and a red one is not a regression signal. Do not mark it `expect=`:
that would forgive `FAIL` wholesale for a case that is otherwise a genuine
regression detector, and the flake is in an unrelated comparison inside it,
not in what the case is about.
