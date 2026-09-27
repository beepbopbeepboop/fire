# HARD BUG: `bytes`/`memoryview` silent wrong values in the compiled path

**State: OPEN.** Found 2026-09-26 by re-testing the claims in the now-removed
`CODEGEN_bytes_value_type.md` rather than by reading code. That doc was
correctly closed for the mechanisms it recorded, but re-running its own
symptom list surfaced live wrong-value residue it did not have — including two
cases where the repo's own regression tests assert the WRONG answer as
expected output, which is why they survived.

Split out from that doc on purpose: "bytes works" and "these six bytes paths
return garbage" are different claims, and keeping them in one file is what let
the second hide behind the first.

## Symptom

All of these compile, run, exit 0, and print a plausible wrong value. No
diagnostic anywhere. Verified against CPython byte-for-byte.

    # CPython                          compiled path
    b'a'.ljust(4, b'.')          ->    b'a...'          fire prints b'a```'
    b''.isalpha()                ->    False            fire prints True
    memoryview(b'abcd').readonly ->    True             fire prints False
    d = {}; d[b'a'] = 7
    d.get(b'a')                  ->    7                fire prints 0

The `ljust` one is the worst of the four: the fill byte is the low byte of a
heap address, so the output CHANGES FROM RUN TO RUN. Two consecutive runs of
the same program printed `b'a\x00\x00\x00'` and then `b'a\xe0\xe0\xe0'`.

## The items

1. **`ljust`/`rjust`/`center` with a bytes fill character.** Only the
   *integer* fill spelling works (`b'a'.ljust(5, 46)`, which is what the
   repo's own `gimple_bytes_case_and_affix_methods` case uses). The bytes
   fill — the only form CPython accepts — silently emits an address byte.
   Root cause: `mojo/backend_gimple/emit_methods.py:4267` asks
   `_opt_arg(gen, args, kwargs, 'fillchar', 'int64_t', '32')`, and
   `_opt_arg`'s `want == 'int64_t'` branch
   (`emit_methods.py:4038-4041`) runs `gen._to_int64(*gen.lower_expr(args[0]))`
   on what is a `MojoBytes *` — a pointer-to-integer cast.

2. **Every empty-bytes predicate returns `True`.** `b''.isalpha()` and
   `b''.isdigit()` are `True`; CPython says `False` for all of them. The
   predicates have real lowering, so the bug is in the zero-length case, not
   the dispatch.

3. **`memoryview(...).readonly` is a constant `False`.** CPython: `True` for a
   bytes-backed view (it is genuinely immutable). It is a fold, not a query,
   per the removed doc's own description — so the wrong answer is structural.

4. **`dict.get` and `dict.pop` with a bytes key read the STR domain.**
   `d[b'a'] = 7; d.get(b'a')` returns `0`, and `d.pop(b'a')` returns `0`
   *and does not remove the key* (`len` stays 1). Str-keyed `get`/`pop` are
   correct, so it is bytes-specific. The runtime half of the fix already
   exists and is correct — `mojo_dict_get_bytes_int` (`fire_runtime.c:3265`)
   and `mojo_dict_pop_bytes_int` (`fire_runtime.c:3302`) — but the call
   sites never route to them: `emit_methods.py:3283` (`get`) and
   `emit_methods.py:3405` (`pop`) both call
   `gen._char_to_cstr(key_type, key_val)` unconditionally and then emit the
   str-domain `mojo_dict_get_int`/`mojo_dict_pop_int`. `setdefault`
   (`emit_methods.py:3421-3422`) *does* guard on
   `if key_type != 'MojoBytes *'`, which is exactly why only these two are
   wrong.

5. **The bytes set domain is one-per-FUNCTION, not per-set.** Two set
   iterations over different set domains in one function is a hard
   `gcc -fgimple` error: `assignment to 'MojoBytes *' from incompatible
   pointer type 'char *'` as soon as a `for x in {b'a',b'b'}` is followed by
   `for x in {'p','q'}`. Each in isolation compiles. Loud, so lower severity
   than 1-4, but it is a real limit that was not recorded anywhere.

6. **Low severity, type-only:** `partition`/`rpartition` return a
   `MojoList *` (`[b'noeq', b'', b'']`) rather than a tuple. The values are
   right. Separately, `'a' in [b'a', b'b']` is a hard `gcc -fgimple` type
   error (pre-existing mixed-domain query).

## The part that matters most: two tests assert the wrong answer

`test_gimple_runner.py`'s `gimple_bytes_predicates` expects
`print(b''.isalpha(), b''.isdigit())` to print `"True True"`, and
`gimple_memoryview_descriptors` expects `False True` for readonly. Both
encode CPython-wrong answers as the expected output.

**These are not just stale expectations — they are the reason items 2 and 3
are still here.** Any fix must change the expected output too, and until it
does, the suite actively protects the bug. Fixing item 2 or 3 without
touching these two cases turns a green suite red, which is the correct
outcome and not a regression.

## Also wrong in the removed doc's own claims

`isprintable` and `isnumeric` **do not exist on `bytes` in CPython**
(`AttributeError`), yet both are implemented here — and `b'a'.isnumeric()`
returns `True`, which is also wrong for `str.isnumeric`. The removed doc
justified this with "Python defines only the ASCII flavours of these on
`bytes`", which is factually wrong: CPython's `bytes` predicates are exactly
`isalnum isalpha isascii isdigit islower isspace istitle isupper`. Worth
deciding whether these two should exist at all.

## Not re-testable here

The removed doc's `pickletools.py` end-to-end claim could not be re-tested in
this checkout — there is no `Lib/` directory. The minimal shape it names
(`p[0:end_pos]` into a bytes local) does pass.

## Where

Compiled path only: `mojo/backend_gimple/emit_methods.py`,
`runtime/fire_runtime.c`. Every item is a `MojoBytes *` → `int64_t` cast of
the same family, so one shared guard is likely to close 1, 2 and 4 together
rather than three separate patches.
