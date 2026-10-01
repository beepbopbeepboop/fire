# FORMAL_a_frame_holder_rebound_from_a_word: fixed

**Status: FIXED and measured before and after on both architectures.** The
defect, the reproducer and the design argument are in
`bugs/FORMAL_holder_rebound_from_a_word` on `work/merge2-formal`; this file
records what landed, because the filing's stated next step was a PARKED finding
and the reason that is load-bearing is the part most likely to be got wrong a
second time.

## What landed

`formal/build.py::_collect_holder_rebinds` (one pass over every function's
assignments, after the holder tables are settled) and
`formal/model.py::holder_rebound_from_a_word_refusal` (the words, shared by both
backends and by the build pass), raised from
`formal/build.py::check_frame_holder_rebinds` — which is called from the two
ENTRY POINTS beside `check_frame_subscript_escapes`, and not from
`_frame_receivers`.

**Parked, not raised, and that is the design.** The filing says it, and the
reason is measurable rather than stylistic: a refusal raised from
`_prepare_functions` is reported INSTEAD of the import diagnosis, because
`_prepare_functions` runs before `_resolve_imports`. `check_frame_field_blob_
premises` was moved out of that window because it fired on 67 of the repository's
284 files (67 of them importing a CPython host module) and
`check_construction_shapes` because it fired on 14 — all 14 moved
`not-answerable/host-import` → `codegen`, which puts unbuildable files into the
measured denominator. `mojo/middle/closures.py` moved that way once already when
a new channel was added inside. So the finding lands on
`fn._frame_holder_rebinds` and the entry point raises it.

## The reproducer, before and after

```
class R:
    def __init__(self):
        self.a = 0
        self.b = 0

def main(n):
    r = R()
    r.a = 7
    r = 5
    return r.a
```

| | arm64 | x86-64 |
|---|---|---|
| before | **Built.** SIGSEGV, exit **139** | **Built.** SIGSEGV, exit **139** |
| after | refused, identical words | refused, identical words |

The source says 5. The refusal names both bindings, because "r is a frame" and
"r is a word" are the whole disagreement and the reader has to be told which
line settles it:

> r is assigned 5 in main(), and r also holds the address of a R frame — R()
> binds it to one, and this path has no way to say that a later binding changes
> what the name is. Every field access through r is already lowered as a load at
> `[base + 8·slot]` on the strength of the first binding, so after this store the
> load reads address `5 + 8·slot`: measured, the program builds, runs, and dies
> with SIGSEGV (exit 139) on both architectures …

`if n: r = 5` is the same finding and is not special-cased: the analysis has no
path sensitivity, which is the statement `struct_frame_slot_candidates` and
`struct_dunder_dispatch_candidates` already rest on when they refuse rather than
pick.

## What a holder MAY be assigned, and why the list is three

`_value_may_be_a_frame` is the recognition's own list rather than a new one,
because a name becomes a holder from four things and three of them are
assignments with a value: a CONSTRUCTION of a framed struct (`r = S(…)`), a COPY
of another holder (`r = other`), and a method's receiver (a parameter, not a
value). A call to one of this module's own functions is deliberately NOT on it:
it looks like the frame-returning case and there is no evidence for it — the
function returns whatever its body returns, and a frame that outlived the
function that built it is the use-after-free the escape checks exist for.
Allowing every call would make the check silent for the shape it is most needed
for.

**The method's own receiver is excluded, and the measurement that forced it is
the content.** `self = Self(…)` is how a Mojo constructor rebinds its receiver
and is in real stdlib code — five occurrences across `memory/alloc.mojo` and
`runtime/tracing.mojo` alone — so a check that flagged a receiver would have
refused **9 of the 294 stdlib files** for rebinding a name to a fresh frame of
its own type. `Self(…)` is still recognised as a construction (via the enclosing
method's struct, as an alias), so a LOCAL `x = Self(…)` is not refused either.
What the exclusion leaves open is filed separately, in
`bugs/FORMAL_receiver_rebound_to_a_word.md`.

## The coverage measurement, and it is the one that matters here

A refusal added to a build pass can move a file out of the sweep's PASS set, and
a file that stops being `codegen` because a crash became a refusal has not
become answerable — so the question is not "did the numbers move" but "does this
fire anywhere that answered before". Measured by running the pass over every
file and reading the parked findings, with no codegen and no linking:

| scope | files scanned | raised before the collect | would refuse |
|---|---|---|---|
| this repository | 319 | 40 | **0** |
| the stdlib (`std/**.mojo`) | 294 | 75 | **2** |

and the two are `std/python/_cpython.mojo` (`error = String()`, a parameter
reached with a frame address and then assigned a `char *`) and
`std/testing/prop/strategy/string_strategy.mojo` (`s = String()`). Both are
already `codegen/dependency` in the sweep, so neither moves. **Net: no file that
answered before stops answering.**

## Tests

`test_formal_value_model.py` — the CPython-oracle rows
`holder_rebound_from_a_word_is_refused` and
`holder_rebound_under_a_condition_is_refused` (both architectures must refuse
with the same words), and `holder_may_be_construction_copy_and_self_write`, which
is the GUARD: a construction under a branch, a copy under a second name, and a
field write through a method's own `self` must all keep working, because a check
that broke one of those would be refusing correct code.
`test_formal_run.py` gains `holder_rebound_from_a_word_is_refused` as a `refuse:`
row, so the registered suite job pins it too.