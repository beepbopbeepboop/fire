# FORMAL_an_out_of_range_subscript_exits_1_with_no_message

**Area:** FORMAL, both backends. `formal/arm64_codegen.py`'s
`_emit_subscript_addr` — the `oob_label` arm at the end of the function, and
the matching one in `formal/x86_64_codegen.py`.
**Status: OPEN, diagnosed, not fixed.** The fix is three lines per emitter plus
one message function; §4 says why it is not in this branch.

## What was run

    $ python3 tools/memslot.py --gb 8 --label mc -- \
          python3 tools/formal_memcheck.py --memcheck

`formal/memcheck/list_subscript_past_end.mojo` is the reproducer and is a
standing row of the memcheck corpus:

    def main(n: Int) -> Int:
        var a = [10, 20, 30]
        printf("%d\n", a[0])
        printf("%d\n", a[2])
        printf("%d\n", a[3])
        return 0

## What was seen

    $ ./list_subscript_past_end.arm64 ; echo $?
    10
    30
    1

    $ ./list_subscript_past_end.arm64 2>&1 1>/dev/null | wc -c
    0

Both architectures, identical. The image prints the two in-range lines, then
**stops with exit status 1 and writes NOTHING — not to stdout, not to stderr.**

## What is NOT wrong, and had been assumed wrong

**The bounds check exists and it is correct.** `_emit_subscript_addr` loads the
blob's own count (`ldr x2, [x9]`), applies Python's negative-index rule
(`index += count` when `index < 0`), and takes the `oob_label` arm unless
`count > index` **unsigned** — which is what covers "still negative after the
fold". `M.BLOB_HEADER_BYTES` and `M.blob_elem_stride` put the address at the
right place for a byte blob and a word blob alike. So there is no
read-past-the-end here, and this document is NOT
"a list subscript has no bounds check": that was the first reading, and it is
wrong. What is missing is the MESSAGE.

The consequence matters for how the next person reads this tree: a memcheck
sweep reports this row `MATCH`, because the answer is stable and the exit status
is stable. A bounds check that stops the program is invisible to a
stdout/exit-status oracle by construction — and so is a bounds check that is
MISSING, which is why the two must be told apart by reading the emitter. That
distinction is the reason this file exists.

## Why the sibling stops on the same path DO say something

`_emit_overflow_diagnostic` is the shared half of every bounded stop on this
path, and it is a raw `write(2)` rather than a libc call for a reason that is
written down in its own docstring: an unfollowable `BL` spends the proved
function's single-halt-address budget. Its callers include the dict-store
overflow arm (`_emit_dict_store`, which calls it with
`M.dict_store_overflow_message`) and the frame-scratch exhaustion arm. So the
helper exists, its message format is established, and the subscript's `oob_label`
is the one bounded stop that calls `_emit_exit(1)` with nothing in between:

    self.asm.label(oob_label)
    self._emit_exit(1)          # <- no _emit_overflow_diagnostic above this

CPython answers the same program with
`IndexError: list index out of range`, and it says it on stderr. So the
divergence from the source's meaning is not the STOP, it is the silence.

## What was expected

A message naming the subscript and the bound, in the shape
`M.dict_store_overflow_message` already establishes, then exit 1. Concretely
something like `list index 3 is out of range for a list of 3`, printed with
`_emit_overflow_diagnostic` so the raw-`write`/single-halt-address property is
preserved.

## The exact next step

1. Add `M.subscript_out_of_range_message(obj_spelling, index, count)` in
   `formal/model.py`, beside `dict_store_overflow_message`, and give it the
   same two-sentence shape (what was asked, what the bound was, what CPython
   answers). It must be a plain string built at EMIT time: the message goes
   through `_emit_overflow_diagnostic`, which takes a constant.
2. One line above each emitter's `self._emit_exit(1)` in `oob_label`:
   `self._emit_overflow_diagnostic(msg)`. The message text has to reach the
   emitter, so the spelling and the count come from what
   `_emit_subscript_addr` already has in X0/X1/X2 at that point — check what
   survives to the label before assuming, because that function's own comment
   records that it clobbers X0..X4 and restores SP.
3. Then assert it in `test_formal_run.py`'s two-architecture case for this
   shape: exit 1 **and** the message on stderr **and** nothing on stdout after
   the last in-range line. Asserting the exit status alone is what let the
   silence through here.

## Why this is filed and not fixed in the same branch

`formal/arm64_codegen.py` and `formal/x86_64_codegen.py` are the subject of
`project38:arm64-instruction-coverage` and the x86-64 emitter's own claim area,
and this branch's claim is `project38:memory-safety`. The defect was FOUND by
the memory-safety instruments but it is a missing diagnostic on a
correctness check, so editing two other workers' files from here is the merge
conflict this project's rules exist to avoid. The finding is exact enough to be
a three-line change for whoever holds those files.

## What this row is worth keeping for

The memcheck corpus row should stay, with its comment corrected to say what is
actually true — that the check fires and says nothing. A reader who takes the
older comment at its word will conclude the bound is missing and go looking for
a check that is already there.