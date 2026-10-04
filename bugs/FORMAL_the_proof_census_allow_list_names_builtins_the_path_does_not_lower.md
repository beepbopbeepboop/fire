# FORMAL_the_proof_census_allow_list_names_builtins_the_path_does_not_lower

**Area:** `tools/formal_proof_breadth.py` (`BUILTIN_NAMES`) and, for each name in
it, whichever emitter is the one that would have to lower it ·
**found by** `the link audit's naming of an unlowered callee (landed in ee704916)`
§"Measured over a real corpus", whose naming half is fixed and whose BUILTIN
half is not · **both architectures** · **filed 2026-10-04, NOT fixed**

## What this is

`tools/formal_proof_breadth.py`'s `BUILTIN_NAMES` is "the set of names a
synthesised `main` may have in reach", and it is also this backend's to lower.
It is not: of the names in it that take only ints, `max`, `min`, `bool`,
`divmod`, `chr`, `ord` and `float` are all emitted as calls to functions nothing
provides. `abs` IS lowered, which is why the deleted doc's own `abs(x)`
measurement had gone stale.

So the census reports 6 of its 78 items as refused by the link audit
(`list`, `enumerate`, `max`, `min`, `REPORT.append`,
`_DISPATCH_TABLE_GLOBAL_CTYPES.get`) — byte-identically on both machines — and a
reader of the ledger cannot tell whether the frontier is the proof layer or the
code generator. That is the census's own job being made impossible by an
allow-list that is not a measurement of anything.

## What I ran

    python3 tools/memslot.py --gb 8 --label p -- python3 fire.py build --formal \
        --no-prove -o .tmp/unc2/max .tmp/unc2/max.mojo

for each of `max` / `min` / `bool` / `divmod` / `chr` / `ord` / `float` /
`abs`, on `--backend=arm64` and `--backend=x86_64`, with the program
`def main(n: Int) -> Int: return <name>(n)`:

| name | arm64 | x86-64 |
|---|---|---|
| `max` `min` `bool` `divmod` `chr` `ord` `float` | **refused** — the link audit | **refused**, identical words |
| `abs` | builds | builds |

Seven unlowered of the eight the deleted doc names, and `abs` still lowered, so
that doc's `abs(x)` measurement is confirmed stale rather than merely reported
as such. Every refusal is the sentence landed for
`the link audit's naming of an unlowered callee (landed in ee704916)`, and every one
is refused on BOTH machines with identical words, so this is a shared-pipeline
gap and not a codegen divergence.

## Two answers, and they are different jobs

1. **Narrow `BUILTIN_NAMES` to what the path lowers.** Cheap, and the WRONG
   direction for a census: it removes these items from the ledger and with them
   the measurement of a real gap. A census whose allow-list is trimmed to match
   the implementation cannot report the implementation's frontier.
2. **Lower the int-valued ones.** `max`/`min` are a compare and a select, and
   both emitters already have that: `formal/model.py`'s `MLIR_SELECT_OP` rewrite
   turns `a if c else b` into a `TernaryExpr` that arm64 emits as one `CSEL`.
   `chr`/`ord` are a store and a load; `bool` is a compare against zero;
   `divmod` is a division and a remainder. This one also wants a
   `MojoExpr.max` / `MojoExpr.min` (etc.) arm in `lib/ProofLib.lean` before an
   item can be *proved* rather than merely built, and that invalidates every
   cached Lean verdict.

**Why no light worker landed (2).** `lib/ProofLib.lean` is the source of the
27 MB `ProofLib.olean` every proof-checking path links against, and
`formal/lean.py`'s own measured table records that build at 112 s wall and a
7.82 GB peak — over the 8 GB a light worker is given, and `formal/lean.py::run_lean`
is not to be launched by one. The eight Lean-checking formal gate tests are
disabled for the same reason. Landing the codegen half alone would leave every
existing proof RED on any program that calls one of these names, silently.

## The exact next step

Decide (1) or (2) in writing — and note that a THIRD answer exists and is
probably the right one: split the set. `BUILTIN_NAMES` is used in two places
(`tools/formal_proof_breadth.py:459` and `:479`) to decide whether a free name
disqualifies a candidate function. Keeping the un-lowered names in the set but
marking them, so the ledger reports "the generator refused this one, and here is
which builtin's lowering is missing" instead of folding it into the link audit's
bucket, measures the frontier AND keeps the census honest. Either way the
allow-list stops being an assertion about the backend that nothing checks.

A cheap first step with no Lean behind it: a `test_*.py` row asserting that
every name in `BUILTIN_NAMES` is either lowered by the formal backends or listed
in an explicit `NOT_LOWERED` set with a sentence each — so the drift the census
recorded as 6 items becomes a build failure the day it widens, and the message a
reader sees names the builtin instead of the link line.

## Reproducing

    python3 -c "import sys; sys.path.insert(0,'tools'); import formal_proof_breadth as P; \
      print(sorted(P.BUILTIN_NAMES))"
    # then one program per name, both backends, per the command above.