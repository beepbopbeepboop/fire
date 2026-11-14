# CODEGEN: the yield-from walk-memo pin is red after the generator keyword binder

**Found:** 2026-11-14 by the `SUITE_silentnoop` part 1 worker while running
`python3 tools/dangling_doc_refs.py --ratchet` (the pin cited a deleted doc;
that citation is now removed). The test itself was already red on master.

## Symptom

`python3 test_codegen_yield_from_walk_ast_memo.py` (the root pin added by
commit `40985caba` for the `_cpp_yield_from` walk-memo invalidation fixed in
`c158c0b38`) now fails before it asserts anything:

```
Traceback (most recent call last):
  File ".../test_codegen_yield_from_walk_ast_memo.py", line 88, in main
    out, recorded = _drive(gen, call)
  File ".../test_codegen_yield_from_walk_ast_memo.py", line 68, in _drive
    out = cc._cpp_yield_from(gen, yf, '')
  File ".../mojo/backend_gimple/cpp_core.py", line 12479, in _cpp_yield_from
    _slots = _cpp_generator_call_slot_pairs(
  ...
mojo.middle.exprtypes._UnsupportedGeneratorShape: `yield from
S._iter_member_by_def_(...)`: too many arguments (the callee takes 0)
```

Both scenarios in the file use the same stub registration shape, so both would
fail the same way if the first one got past this error.

## Why

`_StubGen` registers the generator method as

```python
('S', '_iter_member_by_def_'): {
    'base': '_S_iter', 'params': [], 'receiver': 'self', ...}
```

`params=[]` while `receiver='self'` is not a shape real registration produces:
`module_gen.py` (`gen_module_impl`'s method registration, and
`_cpp_generator_param_names`) puts the receiver in `params[0]` —
`_cpp_generator_param_names` says so in its docstring ("A generator method's
receiver is its own leading slot ... and is NOT part of `fn.params[1:]`") and
starts the name list with the receiver.

Commit `51934e78b` replaced `_cpp_yield_from`'s per-site positional/defaults
arithmetic with the shared `_cpp_generator_call_slot_pairs`, which now checks
the callee's slot count *including* the `leading` receiver. The old inline code
appended the receiver without an arity check, so the stub's inconsistent
`params=[]` went unnoticed. There is no production bug here: a real
registration always carries the receiver slot.

The test is also not registered in `tools/suite.py`, so no gate job runs it and
nothing reported the breakage.

## Expected

The pin runs its two scenarios and passes (the invalidation assertions are
unchanged; this is not a failure of the subject it pins).

## Next step

Make the stub's registration match what `module_gen.py` produces: for the
self-method scenario, `params: ['int64_t']` with `param_names: ['self']` (the
receiver is the leading slot); for the classname scenario, `params:
['int64_t']` with `param_names: ['self']` too, because `_StubGen` registers
`receiver: 'self'` for `S.plan` as well. Alternatively register the callee with
no receiver and a matching static-method stub. Run

```
python3 tools/memslot.py --gb 8 --label t -- python3 test_codegen_yield_from_walk_ast_memo.py
```

and register the test in a bucket if it is intended to keep pinning this.
