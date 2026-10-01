# FORMAL_receiver_rebound_to_a_word: `self = <a word>` inside a method, and the caller never sees the effect

**Status: OPEN, pre-existing, arch-independent, and deliberately NOT fixed by the
holder-rebind check that landed next to it.** Found by measuring what that check
fires on across the 294 stdlib files: nine of them were being refused for
rebinding a receiver, five of them for `self = Self(…)`, which is idiomatic Mojo
and not the defect. So the receiver is excluded from the check, and what the
exclusion leaves open is this.

## The shape

```
struct R:
    var a: Int
    var b: Int
    def rebind(self):
        self = 5            # or any word
    def read(self):
        return self.a       # [5 + 8·0]
```

Two things are wrong and the second is the interesting one:

* `self.a` inside `read` is a load at `base + 8·0` where `base` is 5. That is the
  crash the landed check now refuses for a LOCAL name, and for a receiver it is
  the same arithmetic.
* **Before that, the write does not reach the caller at all.** A method's effect
  on a field reaches its caller because the caller holds the SAME address the
  method dereferences — that is the whole of the by-reference receiver
  (`bugs/FORMAL_wide_receiver_by_reference.md`). Rebinding `self` points the
  method at a *different* word, so `R(); r.rebind(); r.a` leaves `r.a` reading
  whatever the caller built the fresh frame with. That is a silently dropped
  store with an address-shaped cause, and it is the same family as wave 5's
  "a missing branch on x86-64 is a dropped store".

## Why it is not the landed check's to decide

`bugs/FORMAL_holder_rebound_from_a_word` (fixed in this branch) is about a
LOCAL: `r = R(); r.a = 7; r = 5; return r.a`. Its rule is "a name in the holder
set must only be assigned one of the three things that can be a frame", and its
message names a repair — use a different name for the word, or copy the value
out. Neither repair makes sense for a receiver: the receiver is not a name the
caller can re-declare, and "copy the value out of `self`" is not a thing.

So the check excludes the method's own receiver names, by NAME from
`model.struct_receivers`, which covers `out self` and `inout self` by the same
rule. The measurement that forced it: **9 stdlib files** carry
`self = Self(…)` or `self = <expr>` inside a constructor, and refusing them
would have put 9 files into the measured denominator for a construct that is
correct. After the exclusion the check fires on **2 of 294**, both real:

```
std/python/_cpython.mojo           CPython_unsafe_get_error   error = String()
std/testing/prop/strategy/string_strategy.mojo  _StringStrategy_value  s = String()
```

— a parameter reached with a frame address at some call site and then assigned a
`char *`, which is the defect the check is for. Both files are already
`codegen/dependency` in the sweep, so neither moves.

## What would close it

The receiver's frame identity is the missing fact, and it is not a *lowering* gap
— it is a statement the analysis cannot make. `self` means "the address the
caller passed", and nothing in the body says whether the body's later `self`
still means that. Two shapes, and the first is cheap:

1. **Refuse a rebinding of the receiver to anything that is not a construction of
   its own struct** — `self = Self(…)` and `self = other` are fine (they are
   frames, and `self = other` is the same address), `self = <word>` and
   `self = f()` are not. That is `_value_may_be_a_frame` with the receiver's own
   struct as the alias, which `_collect_holder_rebinds` already computes and
   currently uses only to stop the local check. It belongs in
   `model`, beside the other receiver refusals, so both backends get the same
   words from one place.
2. **The one that is a real limit, and is not this**: a method that *returns*
   the fresh frame it built, handing the caller a word that is not the address
   the caller passed. That is the frame-return lifetime question
   `frame_receiver_escape_refusal` is about, and it wants its own decision
   rather than a rule of the form "a rebinding of the receiver is illegal".

`self = other` deserves a note because it is the case a rule of the form "never
rebind the receiver" would break for no reason: it copies the address, the
caller's slot already holds it, and the method's field writes still land where
the caller expects.