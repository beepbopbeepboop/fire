# FORMAL_holder_rebound_from_a_word: a frame holder's name stops being a frame, and nothing notices

**Status:** found while landing the returned-frame convention, NOT fixed, and
pre-existing — it reproduces on this tree at `HEAD` with the convention absent.
It is a SIGSEGV on **both** machines, so nothing is silently wrong because of
it, but it is a hole in the same recognition the convention leans on and it is
one line of shape away from being reachable in a program that builds.

## The reproducer

```python
# rebind.mojo — 11 lines, no imports
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

```
$ python3 fire.py build --formal --no-prove -o rebind rebind.mojo
Built: rebind  [arm64/macho]
$ ./rebind; echo $?
Segmentation fault: 11        (139; the source says 5)
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o rebindx rebind.mojo && ./rebindx
Segmentation fault: 11
```

The conditional form is the same: `if n: r = 5` also segfaults where the
source says 7.

## The cause

`formal/build.py`'s holder recognition is a SET of names
(`_frame_receivers` → `holders[fn.name]`), and a name enters it from a
constructor binding, a method receiver, a copy, a frame-returning call, or a
callee's parameter. **Nothing ever removes one**, and nothing checks that every
later binding of the name agrees.

So after `r = 5`, `r` is still a holder: `_frame_slots["r.a"] == 0` is still
emitted, and `r.a` lowers to `LDR X0, [X_r, #0]` where `X_r` now holds 5. The
load is at address 5, which is not mapped. The program builds, and the crash is
the first thing that notices.

This is the mirror image of the one-name-two-**shapes** defect wave 3 fixed
(`model.struct_frame_slot_candidates`: "agree or refuse", and the disagreement
is between two FRAMES). That fix asks whether two *frame* layouts agree on a
slot. It cannot see this, because the second binding is not a frame at all: the
candidate set is `[R]` and nothing contradicts it — there is simply a second
binding whose value is a word.

## Why it matters more now than it did

The returned-frame convention adds a fifth edge to the same recognition: a call
to a function that returns a frame makes the target a holder. Every added edge
is another way a name becomes a holder and another reason the "and nothing ever
removes one" property matters. Nothing about THIS change makes the reproducer
new — it is a plain `r = R(); r = 5` — but the fix is the same shape as the
recognition's, and it belongs beside it.

## The next step

One pass, in `formal/build.py`, over each function's assignments, and it has to
be a PARKED finding rather than a branch inside `_check_frame_escapes` — that
function runs inside `_prepare_functions`, which is before the imports resolve,
and a refusal raised from there is reported in place of the import diagnosis.
That defect has already moved 67 files in this repository once, and two
consequences of a new channel there have been measured (`#13` of
`bugs/FORMAL_frame_receiver_handoff.md`: a new branch there moved
`mojo/middle/closures.py` from `not-answerable/host-import` to `codegen`). So:

* collect `(name, spelling)` for every assignment whose target is a holder and
  whose value is **not** one of the five things that produce a frame (a
  constructor call, a bare holder name, a frame-returning call, a method
  receiver, a module-level folded constant);
* park it the way `_defer_subscript_escape` parks a subscript escape, and raise
  it from the entry points beside `check_frame_field_blob_premises`,
  `check_frame_subscript_escapes`, `check_construction_shapes` and
  `check_frame_return_shapes`;
* the message has to name the binding that disagrees, because the two readings
  are `r` is a frame and `r` is a word and the reader has to be told which
  line settles it.

The measurement to take afterwards is the denominator one: files that stop
being `codegen` because a crash became a refusal have not become answerable.
