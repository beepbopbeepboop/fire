# FORMAL_bracketed_call_to_a_private_name_is_refused_as_a_dangling_symbol

## Status

OPEN — found 2026-09-30 while registering `test_formal_module_attr.py` (it was
named by no spec and in no bucket; see the commit that registers it). Not
caused by that work and not fixed by it: the fix is in the formal backend's
call-target classification, which is a different area.

This is the ONE red case of 11 in that file, and it is what
`formal-module-attr`'s `expect=` marker cites. Two things are wrong with it and
they are on different backends, so they are two findings under one test.

## What is believed

`f[x](y)` is a CALL — a comptime specialisation of `f` — but its callee is a
`SubscriptExpr`, so a backend that classifies call targets by node type sees a
subscript where it expected a name. The file's case is

```mojo
from priv import _helper

def main():
  return _helper[1](2)
```

where `priv.mojo` defines `_helper` (private, so `doc/ABI.md`'s export rule
keeps it off the boundary) and `pub`. The build must REFUSE it, and it does —
on both architectures — but neither backend says the right thing, and the two
do not even agree with each other.

## What was run, and what it said

    $ python3 test_formal_module_attr.py
    FAIL  `priv._helper[1](x)` is refused as an export gap, not a storage one
    ...
    formal module attributes: PASS=10 FAIL=1

Both halves, isolated (`.tmp/repro_bracket.py` in that worktree, which writes
the one tree this case uses and prints the refusal verbatim):

    ===== arm64 =====
    build: prog.mojo: the image would bind 1 symbol(s) that nothing provides,
    so it could not be loaded: _helper. Nothing on this link line defines them:
    not the C library, and not any library this program linked. Two very
    different causes produce that, and the distinction is not lost — each name
    in this list is either a call the codegen emitted (`info['external_syms']`,
    so some construct was not lowered and the call is dangling) or a name that
    entered the image as a bare reference with no call site behind it. Deciding
    which is a question for the assembler, and it is asked nowhere in this
    backend, so this message stops at the fact both causes share. (Provider
    check: asked the C library (dlsym).)

    ===== x86_64 =====
    build: unsupported call target on the formal x86-64 path (got SubscriptExpr)

## Why each half is wrong

**arm64 — right verdict, wrong reason, and the wrong reason is a worse one
than the test used to assert.** The build gets to the LINKER and is caught by
the dangling-symbol audit, which cannot tell "the codegen emitted a call to
something nothing defines" from "a bare reference entered the image". Both are
`external_syms`. Here the real reason is the export rule: a leading `_` is
private, so there is nothing to bind, and a reader sent to look for a dangling
call finds a private generic with no dangling call in it. The same file's
sibling case (`f[x](...)` reached by a dotted chain) was fixed to say the
export thing; this spelling of the same call was not, and the difference
between them is a node type rather than a rule.

**x86_64 — the call target is not lowered at all.** `_emit_call` in
`formal/x86_64_codegen.py` has no `SubscriptExpr` arm in its `_callee_symbol`,
so every bracketed callee on this architecture reaches
`CodegenError("unsupported call target on the formal x86-64 path …")`
(`formal/x86_64_codegen.py:4914`). That one is already known and counted —
`bugs/FORMAL_wide_receiver_by_reference.md` records it as a pre-existing
architecture gap and `tools/formal_sweep.py --arch x86-64` names it in 56 of
578 files — so it is a restatement here, not a new finding. What the sweep
cannot see, and this file can, is that the two backends now DISAGREE about the
REFUSAL for the same source: one names a dangling symbol, the other names an
unsupported call target. Two architectures answering differently about one
program is the whole reason `test_formal_module_attr.py` builds every case
twice.

## The next step, exactly

1. **arm64 (the real fix).** Find the place that decides a call target is an
   export gap and give it the subscript shape, using the two shared
   recognisers that already exist rather than a new private predicate:
   `formal/model.py:subscript_callee_name(call)` gives the bare name a
   subscript callee applies to, and `formal/model.py:subscript_callee_names`
   gives the names the bracket consumes. `priv._helper[1](2)` should then be
   answered as an export gap on the BASE name `_helper`, with a message naming
   the private rule the way the module's other export refusals do — the strings
   `test_formal_module_attr.py` looks for are `"does not export it"` and
   `"_helper"`, and the assertion that it is NOT the storage message
   (`"no storage for it"`) is already satisfied today.
2. **x86-64.** Only worth doing together with step 1, and only if the
   x86-64 backend is going to learn the call convention: the residual 56-file
   gap is listed and measured, and this case is one line of it.
3. Not this: making the refusal LOUDER. It already fails loudly — this doc
   exists because the test is registered `expect=`, so the tally carries the
   line and `--rerun-failures` re-runs it. The anti-rot direction is covered by
   the runner itself.

## Related

- `test_formal_module_attr.py` builds every case for BOTH architectures and runs
  the foreign image under Rosetta, so this case cannot be made to pass by
  matching arm64's answer alone.
- `formal/model.py:subscript_callee_name`'s own docstring names this exact
  arm64/x86-64 asymmetry as a pre-existing gap, which is why step 1 asks for
  the shared recognisers rather than a new one.
