# TEST: a registered test in no bucket is in the estate's inventory and in no run

## Status

OPEN for two of the nineteen. The other seventeen are accounted for below: five
were measured and given a bucket by the change that wrote this, eleven belong to
another doc, and one is deliberate.

## What is believed

The estate check in `test_suite.py` answers "is every `test_*.py` in the repo
named by a registered spec, or declared with a reason". It reads `cmd`, and it
cannot tell a registration that is EXECUTED from one that is merely present: a
spec in no bucket is named, so the estate counts it as covered, while
`make check`, `make gate` and every other bucket walk straight past it. The
registry's own `--list` prints `[]` in the bucket column for exactly these, and
nothing else in the tree reads that column.

Measured on the merged tree, 2026-09-30, with
`python3 tools/suite.py --list | grep '\[\]'`:

    19 registered tests were in no bucket at all.

They fall into three groups, and only one of them is a mistake.

    11  `expect=`-marked and ungated — async-runtime-scaffold,
        async-void-return, async-with-lock-guard, coro-detached-async,
        coro-future-await, gimple-async-runner, mutable-async-capture,
        nested-async-generic, taskgroup, transitive-closure-capture and
        x86-containers. This is exactly the table in
        bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md, which owns this
        group and the anti-rot argument for it. NOT TOUCHED here: bucket
        membership for a known-failure row is `tools/suite.py:disabled-status`,
        another worker's claim.

     1  `prooflib` — DELIBERATE and correct. It is a dependency rather than a
        test (`formal/lean.py`'s `ensure_library` builds it under a lock, and
        every proof-checking job `deps` on it), and CLAUDE.md says outright that
        it is in no bucket on purpose so `make check`/`make gate` do not pay for
        it. Naming it here so the count reconciles and nobody "fixes" it.

     7  registered, NOT expect-marked, and ungated — the actual gap:
        metalgpu, x86-examples, cli-usage-text, md2html, arm64-encoders,
        ownership-destruct, x86-decode

## What was run, and what it showed

    $ python3 tools/suite.py --list | grep '\[\]' | awk '{print $1}'
    ... 19 names ...

    $ for t in test_cli_usage_text.py test_md2html.py test_arm64_encoders.py \
               test_ownership_destruct.py test_x86_64_decode.py; do
          python3 tools/memslot.py --gb 8 --label "$t" -- python3 .tmp/peak.py python3 "$t"
      done
    test_cli_usage_text.py    MEASURED_PEAK_GB = 0.04  elapsed 1.1s  exit 0
    test_md2html.py           MEASURED_PEAK_GB = 0.01  elapsed 0.5s  exit 0
    test_arm64_encoders.py    MEASURED_PEAK_GB = 0.04  elapsed 15.1s exit 0
    test_ownership_destruct.py MEASURED_PEAK_GB = 0.01  elapsed 0.5s  exit 0
    test_x86_64_decode.py     MEASURED_PEAK_GB = 0.01  elapsed 0.5s  exit 0

    # …and that they are not vacuous runs, which the numbers alone do not show:
    $ python3 test_ownership_destruct.py   # 113/113 ownership_destruct fixture cases passed
    $ python3 test_x86_64_decode.py        # ok: every x86-64 encoder round-trips through the decoder
    $ python3 test_md2html.py              # Ran 14 tests — OK

Five of the six were therefore measured, given `mem='tiny'` (which is what the
ratchet assigns at those peaks), and NAMED in a bucket: `cli-usage-text`,
`ownership-destruct`, `md2html` and `arm64-encoders` in `check`, `x86-decode` in
`x86`. That is the fix, and it is why this doc's status is OPEN for two rather
than six.

## The two that are left, and why

**`metalgpu`** — `test_metal_codegen.py`: MSL emitted by
`mojo/backend_gimple/emit_metal.py`, compiled by Apple's real Metal compiler and
run ON THE GPU against a CPU reference. It is `cache=True`, so a recorded PASS
replays and the bucket question is the only open one, but whether it is green at
all needs a GPU and a whole codegen path, which no registration may assume. Its
natural home is `check`, beside the `llm-reference` CPU reference it is paired
with — and the honest first step is to run it once, alone:

    python3 tools/memslot.py --gb 8 --label metalgpu -- python3 tools/suite.py metalgpu

**`x86-examples`** — `test_x86_64_examples.py` builds every `formal/examples/*.mojo`
for x86-64 and compares each answer with the source. Its natural home is `x86`,
beside `formal-x86`/`formal-x86-endtoend`/`formal-x86-model`, and it is a
whole-sweep run rather than a single test; the measurement has to come from a
`formal-x86`-shaped run, not from a guess.

## Why this is the same bug as the estate one

`bugs/UNTESTED_estate_check_is_red_and_outside_the_gate.md` (closed and deleted
2026-09-30) was about the inventory of what runs being outside every gate. This
is the same defect one level down: the inventory now sees these tests, so the
estate is GREEN, and green here has been indistinguishable from run. Five of the
seven arrived that way — `cli-usage-text` was registered by the integrator with
a comment saying so, and the registration satisfied the check that was supposed
to notice.

## The next step, exactly

1. Run `metalgpu` alone, once, on a machine with a GPU. If it is green, add it to
   `check` and give it a measured row; if it is red, register the red with an
   `expect=` and a bug doc, which is the discipline CLAUDE.md states for a
   subject that really is broken.
2. Run `x86-examples` the way `formal-x86` runs (or add it to the `x86` bucket
   and let the bucket report it), then bucket it on the result.
3. Not this: sweeping the twelve `expect=`-marked ones in from here. That is
   `tools/suite.py:disabled-status`, and the argument for it — a marker nobody
   can observe going stale — is written down in the doc that owns it.

## Related

- `--list` is the tool that finds these: the bucket column is `[]` and nothing
  else in the tree reads it. `tools/suite.py` refuses a name used for both a
  bucket and a test, but nothing requires every registered test to be in one.
- A cheap guard, not written, and named here so the next person does not have to
  re-derive it: `test_suite.py` already reads every registry field for its own
  estate (`expect`, `memwhy`, `cmd`), and "every non-`expect` registered test is
  in at least one bucket" is one more `check()` over the same table. It is NOT
  written because `prooflib` is a legitimate exception and a check that needs an
  exception list is the excuse table this doc is arguing against; the honest
  form is a per-spec opt-out (`dep=True`) beside the registration, which is a
  change to `Spec` that deserves its own commit.
