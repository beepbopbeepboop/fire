# A module global whose container holds a string has no initializer

## Status

**Open.** Refused, not miscompiled. Both backends build-nothing and say why.

## What happens

`formal/model.py`'s `build_data_image` can materialise a container of
**integers** into the `__DATA` blob: a `list`/`tuple`/`set` of `int`/`bool`
becomes a run of 8-byte words after a length word. It cannot materialise a
container that *contains* a string.

    L = ["a", "b"]          # refused
    D = {"a": 1}            # refused

A module-level *string* on its own is fine — `NAME = "hi"` gets a slot pointing
at NUL-terminated bytes, and the test suite runs it on both backends
(`read_string_global`, `write_string_global`). The gap is a string **inside** a
container.

## Why it refuses

A container element is a word. For an integer that word is the value. For a
string, it is a *pointer* to NUL-terminated bytes that would have to live
somewhere in `__DATA` too, with the container word holding their address.

So the container is not one blob; it is a blob plus a string arena plus a
pointer per string element, and — this is the part that makes it a different
problem rather than a bigger one — every one of those pointers is a value whose
address must be known before the program runs. Which is the same constraint
that stopped this being done with dyld relocations in the first place: see the
note on `arm64_codegen._emit_global_init` for the measurement that a classic
`LC_DYLD_INFO_ONLY` rebase stream is parsed and then silently not applied on the
macOS this backend runs on. The working code path therefore fills
address-valued slots from *code*, once, guarded by a flag word — and it can do
that for a slot whose initializer it knows, not for one that needs a fresh
layout decision.

## Why refusing is the right answer here

A slot is eight bytes of static storage. An initializer that cannot be laid out
leaves those bytes zero, and zero is a plausible value rather than an obviously
broken one: the list would read as length 0 and the dict as empty, so the
program would print an answer. The refusal names the gap and the file it came
from, which is more useful than a wrong number.

    $ python3 fire.py build --formal --no-prove -o /tmp/x /tmp/stres.mojo
    build: main: 'L' has storage here — it is one of the module-global slots in
    this image's `__DATA`, because a function writes it through `global L` — but
    that storage has no initializer: a container element is a string, and a
    string is a pointer to NUL-terminated bytes, so the blob would need those
    bytes in `__DATA` with a relocation per element. …

## Where it came from

`mlir.py`, in the stdlib sweep: its module-level `MLIR_TYPES` is a dict of
string keys to string values. It is a terminal file, so it is the cheapest
place this gap shows up, which is why the sweep reports it as
`CODEGEN: module-global name has no storage` rather than as a hang.

## Next step

Lay the strings out too, in the same two-part structure the integer case
already has:

1. In `model._static_container_words`, collect the string elements instead of
   refusing them, and return them alongside the integer words.
2. Give `GlobalDataImage` a string arena — append after the container blobs —
   and record a fixup for the container word *and* one per string element,
   where the element's "value" is its offset in the arena.
3. The existing lazy initializer already fills address-valued slots from code,
   so no relocation machinery is needed; `build_data_image`'s fixup list is the
   only thing that has to grow.
4. Extend `test_formal_globals.py`: `L = ["a", "b"]` becomes a *runs* case
   rather than one of `REFUSALS`, and `mlir.py` should leave the sweep's
   "no storage" column.

Steps 1–2 are the whole of it; step 3 is already built. The check that decides
whether it is correct is `mlir.py` compiling, because it is 664 real lines of
the shape rather than one hand-written case.
