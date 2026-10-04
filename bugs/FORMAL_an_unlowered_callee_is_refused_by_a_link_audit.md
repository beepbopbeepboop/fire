# FORMAL_an_unlowered_callee_is_refused_by_a_link_audit: the refusal names a file and a symbol, never the call

**Area:** formal build · **found by:** `tools/formal_fuzz.py --mix limits`
(seed `sweepG`, the refusal half of the corpus) · **both architectures** ·
**filed 2026-10-03, NOT fixed**

## What I ran

    python3 tools/memslot.py --gb 8 --label limits -- \
        python3 tools/formal_fuzz.py --mix limits --seed sweepG \
            --seeds 8000-8015 -j 3 --max-min-steps 30 --work .tmp/fz4/limits2

and, to see the message whole rather than as a screen line,

    python3 tools/formal_fuzz.py --audit .tmp/fz4/lead/unknown.mojo

## What I saw

For `print(sum(xs))` on a list of ints, on BOTH backends:

    build: sum.mojo: the image would bind 1 symbol(s) that nothing provides, so
    it could not be loaded: sum. Nothing on this link line defines them: not the
    C library, and not any library this program linked. Two very different causes
    produce that, and the distinction is not lost — each name in this list is
    either a call the codegen emitted (`info['external_syms']`, so some construct
    was not lowered and the call is dangling) or a name that entered the image as
    a bare reference with no call site behind it. Deciding which is a question for
    the assembler, and it is asked nowhere in this backend, so this message stops
    at the fact both causes share.

`--audit` reports it as `construct: unnamed` / `audit: unnamed` and exits 1.

Measured the same for `max(a, b)`, `min(a, b)`, `abs(x)` and for a name nothing
declares at all (`frobnicate(1)`): **every unlowered callee reaches the link
audit**, on both architectures, with the same words. Nothing in the backend
refuses an unknown bare-name callee BY NAME — `check_module_symbols`
(`formal/build.py` ~11880) collects such a callee into `bare_callees` precisely
so the "name has no home" check does not fire on it, and from there the emitter
writes `call sum` and the bind audit is what notices.

## What I expected

A refusal that names the construct: `sum(xs) is a call this path does not
lower`, with the same shape as `d.keys() is a method call on a value, and this
backend lowers only …` — which is what the same backend says for the neighbouring
case, one statement away. The reader of a refusal needs to know whether to change
their program or their link line, and this message explicitly says it cannot tell
them which.

## Why it is filed and not fixed

Two reasons, both about blast radius rather than difficulty.

1. **The right refusal point is a design decision, not a patch.** Refusing at
   `check_module_symbols` needs the set of names that ARE provided (libc, the
   host-module dylibs, this image's own functions), which is exactly what
   `_audit_bound_symbols`/`_is_libsystem` compute at the END of the build. Moving
   the decision earlier means duplicating that knowledge in a place that cannot
   see the link line, and a false positive there refuses programs that build today
   — over 660 stdlib files' worth of blast radius.
2. **The cheap half is a wording change with wide needles.** `_unaccounted_report`
   (`formal/build.py:1002`) is the single source of that text and its sentences
   are grepped as needles by `test_formal_module_attr.py`,
   `test_formal_receiver_position.py`, `tools/formal_sweep.py`, `formal/imports.py`,
   `formal/monomorph.py`, `fire.py` and about a dozen `bugs/` docs. Appending one
   sentence is safe; rewriting is not, and appending cannot fix the fact that the
   message stops at a fact both causes share.

## The exact next step

Append to `_unaccounted_report`, without touching its existing sentences, the
branch it cannot currently take: `check_module_symbols` already knows which
unaccounted names are bare-name CALLEES (`bare_callees`), so pass that set in and
say which of the two causes each name is — `sum is a call this build emitted and
nothing provides it, so \`sum(xs)\` is not lowered on this path` — for the names
in it, keeping the shared-cause paragraph for the rest. One function, one
caller-side argument, no change to what builds. The pin is
`test_formal_x86_64_parity.py`'s `REFUSALS` group with the needle
`is not lowered on this path`, which builds BOTH backends — that file is where a
refusal's words are already required to match across the two machines.

## What the audit says about it, so the finding is reproducible

`tools/formal_fuzz.py`'s `audit_refusal` returns `unnamed` for this message and
`REFUSAL-UNNAMED` is a finding, so every `--mix limits` sweep reports it. That is
deliberate: the mix is the one place a construct the corpus cannot produce is
measured, and a family that produces a finding is a family that measures. The
tally line is `refusal audit: true=N, unnamed=M, false=0, no-predicate=K` — the
`unnamed` count IS this bug's count.
