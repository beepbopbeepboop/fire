# plan/step-11: the runtime string buffer

**Source:** `bugs/FORMAL_string_value_model.md` (`LENGTH_DEPENDENT_METHODS`,
the missing buffer; the cost list's latent embedded-NUL gap).
**Master plan:** `doc/finish-formal.md` §"Step 11".

## Goal

`lstrip` is the only string method that works today, because it yields an
interior pointer into static text. Anything that must produce a *new* string —
`upper`, `strip`, `rstrip`, `replace`, `join`, a one-character `s[i]`, `chr` —
has nowhere to put it. Add the runtime buffer capability.

## What to add

- A runtime buffer: an allocation the image owns, reachable as a `char *`, with
  a documented lifetime. Static storage no longer suffices for a computed
  string, so decide the owner (caller's frame? heap? the one-word constraint)
  **once in `formal/model/`**.
- Lower the length-dependent methods onto the buffer, or refuse each by name
  with the buffer as the reason. For ASCII, `s[i]` currently gives a byte (a true
  fact about the representation, deliberately left alone); the one-character
  object is the buffer's first client.
- A buffer-lifetime differential: a computed string returned from the function
  that made it, on both backends, against CPython.

## Structure-only rule

This is the first method that can build a string at run time; per the doc,
whoever adds it "inherits the obligation" of the embedded-NUL gap. Record that
obligation where the buffer is defined.

## Files

`formal/model/strings.py`, `formal/arm64_codegen.py`,
`formal/x86_64_codegen.py`, `runtime/` (if an allocator is needed),
`test_formal_string_methods.py`, `test_formal_run.py`.

## Verification

The method suite on both backends against CPython; a returned-computed-string
lifetime row.

## Done when

- [ ] `upper`/`strip`/`replace`/`join` answer CPython on both backends, or refuse
      with the buffer named
- [ ] the NUL obligation is recorded where the buffer is defined
- [ ] a returned computed string survives the function that made it

## Dependencies

step-01 (holes only).
