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

## Measured over a real corpus, 2026-10-04: 6 of 78 functions, and the
## builtins that cause them are half the census's `BUILTIN_NAMES`

`bugs/FORMAL_proof_coverage_census_2026-10-03.md` §0.6's second round (78
functions from this repository's own source, both architectures, phase A) puts a
number on this doc's subject:

    python3 tools/memslot.py --gb 8 --label proofbreadth2 -- \
      python3 -u tools/formal_proof_breadth.py --no-check --arch both -j 4 -t 400 \
        --repo 60 --examples 45 --example-offset 1 --admit-returns \
        --exclude-seen bugs/sweeps/proof_breadth_2026-10-03.jsonl \
        --ledger bugs/sweeps/proof_breadth_2026-10-04_round2-phaseA.jsonl

**6 of the 78 items are refused by this message**, byte-identically on both
machines, and the symbols are `list`, `enumerate`, `max`, `min`,
`REPORT.append` and `_DISPATCH_TABLE_GLOBAL_CTYPES.get`. That is 7.7 % of the
corpus, and it is the fifth row of §0.6.3's family table.

**What is new here is the overlap with the census instrument's own allow-list.**
`tools/formal_proof_breadth.py`'s `BUILTIN_NAMES` is the set of names a
synthesised `main` may have in reach, and the same list is also this
backend's to lower — but it is not: of the names in it that take only ints,
`max`, `min`, `bool`, `divmod`, `chr`, `ord` and `float` are all emitted as calls
to functions nothing provides (`abs` is lowered, which is why
`FORMAL_an_unlowered_callee_is_refused_by_a_link_audit.md`'s own `abs(x)`
measurement is stale). Measured on both architectures, two-line programs:

    def main(x):
        a = x + 3
        b = x * 2
        return max(a, b)          # the image binds `max`

So the census's allow-list and the backend's implemented set are two lists that
have drifted, and the drift is invisible until a corpus meets it. Two ways to
answer it, and they are different jobs: **narrow `BUILTIN_NAMES` to what the
path lowers** (which would remove these items from the census and with them the
measurement of a real gap — the wrong direction for a census, whose job is to
report the frontier), or **lower the int-valued ones** (`max`/`min` are a compare
and a select, and both emitters already have that: `formal/model.py`'s
`MLIR_SELECT_OP` rewrite turns `a if c else b` into a `TernaryExpr` that arm64
emits as one `CSEL`). The second also wants a `MojoExpr.max` arm in
`lib/ProofLib.lean` before the item can be *proved* rather than merely built, and
that invalidates every cached Lean verdict — so it is a change with the formal
suite behind it, not one item.

**The naming half of this doc's next step is unaffected by all of that and is
still the cheapest thing on it.** Six items in a real corpus is a measurement
that would have been a measurement months ago with one program; the message is
still the only one in the backend that names a file and a symbol and never the
call.
