# CODEGEN: a starless dict for-target still binds the whole key plus a 0 instead of splitting it, and accepts non-str keys

**State: OPEN, unfixed — this is the residual the fixed starless-arity doc
deliberately left alone.** Found 2026-10-19. The arity check that doc added
(now landed, its doc removed with the fix) refuses a key whose length differs
from the target's slot count, so those two shapes raise what CPython raises.
What it did not change — and says so in its own comment — is the binding
itself: a key of the *right* length is still bound whole to the first name,
with a literal `0` for every other name, instead of being split into one
character per name the way CPython splits a str key.

## What I ran and what I saw

### 1. A right-length key is not split

    def main():
        d = {"ab": 7, "cd": 8}
        for k, v in d:
            print(k, v)

    main()

| | CPython | compiled |
|---|---|---|
| stdout | `a b` newline `c d` | `ab 0` newline `cd 0` |
| exit | 0 | 0 |

Same exit, different answer — a silent wrong answer rather than a diagnostic,
which is the shape this project ranks worse than a raise.

### 2. A non-string key is stringified and then split

    def main():
        d = {10: 7, 20: 8}
        for k, v in d:
            print(k, v)

    main()

| | CPython | compiled |
|---|---|---|
| stdout | — | `10 0` newline `20 0` |
| exit | 1 (`TypeError: cannot unpack non-iterable int object`) | 0 |

The key is an int; the lowering still treats it as a C string and slices it.
`{"10": 7}` and `{10: 7}` are indistinguishable here.

A 1-character key already raises correctly — `not enough values to unpack
(expected 2, got a shorter string)` — because that is the arity check from the
fixed doc, and a 3-character key now raises `too many values to unpack
(expected 2)` for the same reason. Only the exactly-right-length case and the
non-str-key case are wrong.

## Why

The starless dict branch's lowering is "bind the whole key to slot 0, bind 0 to
every other slot", which is the shape it inherited from the sibling list arm,
where the iterated element *is* a sequence and slot 0 legitimately takes the
element. For a dict the iterated element is a pair, and CPython unpacks the
key's characters, so the shape is wrong for every key of length ≥ 2. The
key-kind question is a second, independent gap: `_DictSlot.keykind` already
knows whether a slot holds a str, bytes, int or container key, and the branch
never consults it.

## Reproduce

Any of the programs above:

    python3 fire.py --jit that-file.mojo
    python3 fire.py run   that-file.mojo

## Not fixing here

- The star-armed form (`for a, *rest in d`) has its own index arithmetic and
  was not exercised for either shape.
- Non-str keys reaching a `for`-target at all may belong with the dict
  key-kind work rather than here; this doc records the symptom.
- A 2-character key is the shape the fixed doc's own regression case pointedly
  avoids, for exactly this reason.
