# FORMAL_loop_invariant_range_message_says_no_step_for_a_three_argument_range

**A message false about the source it names, in `formal/loop_invariants.py`.**
Found 2026-10-13 (`work/formal370-docs`) while measuring whether a
negative-step range loop is lowerable. NOT fixed here: it is not one of this
worker's documents, and nothing in `tools/control.py claims` holds it.

## What was run

A three-argument `range` — the countdown spelling a `reversed(range(n))`
lowering would produce — lowered and RAN correctly on both architectures:

```mojo
def main(n) -> Int:
    var s = 0
    for i in range(n - 1, -1, -1):
        s = s * 10 + i
    print(s)
    return 0
```

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/rev/r.arm64 .tmp/rev/r.mojo
loop invariants: 1 loop(s) (SYNTHESISED only …):
  loop 1 of `main`: UNKNOWN — [unreadable]; no affine invariant; no decreasing affine variant; 0/1 obligation(s) closed by the ladder
      UNKNOWN no-candidate main_loop1_unreadable: `range` with 3 arguments and no step argument
$ ./.tmp/rev/r.arm64
9876543210   # rc 0
```

and the same on x86_64.

## What was seen

`formal/loop_invariants.py::_read_for_range` (line ~765) reads the 1- and
2-argument spellings and returns, for anything longer:

```python
else:
    return f"`range` with {len(args)} arguments and no step argument"
```

For the program above `len(args) == 3`, so the sentence says a three-argument
`range` has "no step argument" — and the third ARGUMENT IS the step. The
message contradicts itself, and it is exactly the class this project removes
elsewhere: a diagnostic that is false about the name or construct it prints.

## Why it is false, and what the change is

The arm exists because this layer synthesizes affine invariants and reads only
the `step == 1`, up-counting form (`shape.stop_step = F.IntLiteral(1, …)` on the
next line), so a step argument is genuinely NOT read. The sentence says the
argument is absent rather than unsupported. A true sentence says which fact is
missing, e.g.

    `range` with a step argument, which this layer does not read

or

    `range` with 3 arguments (this layer reads the 1- and 2-argument forms)

## The exact next step

1. Reword the arm at `formal/loop_invariants.py:780` to name the STEP as the
   unsupported fact rather than as absent.
2. Add a row that asserts the message. `test_formal_loop_invariants.py` drives
   the synthesis over a corpus and compares to a table, so either add a
   unit row for `_read_for_range`'s three-argument arm or a corpus program
   whose recorded reason is the new words — and assert the OLD sentence is
   absent, which is the half a reword otherwise passes without.
3. Re-run that file's own command under `tools/memslot.py --gb 8`.
