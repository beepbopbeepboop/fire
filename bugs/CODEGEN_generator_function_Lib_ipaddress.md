# CODEGEN_generator_function: Lib/ipaddress.py

## Status (updated 2026-08-09 — RECLASSIFIED: real tuple-valued-yield refusal, now the blocking error)

Re-verified against current master (`5ba7d4b`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ipaddress.py`.
The build now fails immediately, BEFORE reaching any GCC-stage error, on
a hard Python-level `RuntimeError` from `gen_module`
(`gimple_codegen.py:30968`):

```
Error building: cannot compile module: function(s) _find_address_range
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

Root cause, confirmed by reading the source: `_find_address_range`
(ipaddress.py:164) does `yield first, last` (lines 178 and 181) — a real
**tuple-valued yield**. This is the well-known, already-tracked
structural gap for this generator-codegen family (coroutine promises
only support a single scalar `int64_t`/`double`/`_Bool`/`char *`, no
tuple representation) — see `_infer_generator_yield_ctype`'s explicit
`TupleExpr` handling at `gimple_codegen.py:2699-2724`, which
deliberately returns `None` (refuse) rather than let a tuple yield sail
through to broken C++ emission, citing this exact family of real-world
cases (e.g. `Lib/test/libregrtest/save_env.py`'s `resource_info`).

This is a genuine change from the 2026-08-07 status below: back then,
`ipaddress.py`'s 14 generator sites reportedly compiled through the
coroutine path with no refusal at all, and the file failed later at
GCC-stage on unrelated `@property`/`format`/stray-backslash errors.
Since then, another session's work (visible in the current
`gimple_codegen.py`, citing `save_env.py`'s bug doc) tightened the
tuple-yield eligibility check to honestly refuse rather than silently
mis-emit, so `_find_address_range` (which was apparently NOT one of the
14 sites previously scanned/reported, or was previously eligible under
weaker checking) now correctly aborts the whole-module compile before
any of the other, unrelated GCC-stage errors are even reached. Grepping
the file confirms exactly one tuple-yield site — `_find_address_range`
(lines 178, 181); the file's other 12 `yield` sites (lines 249, 300,
690, 696, 846, 849, 857, 859, 951, 975, 2351) are all single-value.

**Classification: matches the tracked "tuple-valued yield" structural
generator-codegen gap** (no coroutine-promise representation for
tuples) — out of scope for a narrow fix per this task's guidance. Not
attempted here. The previously-noted unrelated GCC-stage errors
(`@property`-as-bound-method, `format` implicit-declaration, stray
backslash) are no longer reachable/relevant until tuple-yield support
(or a source-level workaround) unblocks the whole module, so they are
left undisturbed below for reference but are moot for now.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. `MOJO_DEBUG=1`
still shows no "not eligible" refusal for any of ipaddress.py's own 14
generator sites — still classified correctly as **NOT a generator-
codegen-cluster failure**. The error SET has changed significantly since
2026-08-06 though (down to 12 error lines from a much larger batch) —
the `@property`-access-leaves-a-bound-method pattern
(`'MojoBoundMethod' has no member named 'is_multicast'`) described below
is GONE (apparently fixed elsewhere in the meantime). Current errors:

```
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:325:17: error: expected ')' before ',' token
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:364:4: error: 'first' undeclared (first use in this function)
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:364:11: error: 'last' undeclared (first use in this function)
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:631:10: error: implicit declaration of function 'format'; did you mean 'normpath'? [-Wimplicit-function-declaration]
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:631:28: error: unexpected RHS for assignment before ';' token
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:2643:46: error: stray '\' in program
```

None are inside a generator body. Not investigated further here (still
out of scope for this cluster) — the `:325`/`:364` pair looks like a
parser/codegen mishandling of a multi-target or walrus-adjacent
assignment (`first`/`last` never declared before use, plus a parse-
level "expected ')' before ','" right before it), and the `:2643` stray-
backslash error is the same textwrap.py-transitive tokenizer issue noted
in codecs.py's/other files' docs — both worth a dedicated non-generator
pass, not attempted here.

## Status (updated 2026-08-06, superseded above — error set has since changed)

**STILL FAILING**, but re-diagnosed against current master (`2b0c4c5`) —
the 2026-07-30 `'IPv6Address' does not name a type` .cpp error no longer
reproduces. `ipaddress.py` has 14 `yield` sites across several small
generator methods (`_BaseNetwork.__iter__`/`subnets`/`hosts`/etc.) —
**none of them appear in the current error list**, and `MOJO_DEBUG=1`
shows no "not eligible" refusal naming any of them: ipaddress.py's own
generator bodies now appear to compile cleanly through the coroutine
path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
The file currently fails to build for a large number of severe,
unrelated pre-existing bugs — dominant pattern in the current error list
is `@property`-decorated methods (`is_multicast`, `is_reserved`,
`is_link_local`, `is_private`, `is_global`, `is_unspecified`,
`is_loopback`, `is_site_local`, ...) being called as `x.is_multicast`
and the codegen treating the property access as leaving a raw
`MojoBoundMethod` value instead of invoking it / unwrapping it to the
real property value:

```
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:1027:23: error: 'MojoBoundMethod' has no member named 'is_multicast'
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:631:10: error: implicit declaration of function 'format' [-Wimplicit-function-declaration]
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:1959:47: error: passing argument 1 of '_BaseV6__explode_shorthand_ip_string' from incompatible pointer type
```

Also present: the exact same `stray '\' in program` /
`_classattr_TextWrapper__letter` tokenizer error seen in
`bugs/CODEGEN_generator_function_Lib_codecs.md`'s current re-diagnosis
(both transitively reach `textwrap.py`; same likely shared root cause,
not investigated further here). None of this is generator-related. Not
investigated further — genuinely out of scope for this cluster; the
`@property`-access-leaves-a-bound-method pattern looks like it would be
a high-value, separate, non-generator bug report on its own (it recurs
at 15+ call sites in this one file alone).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/ipaddress.py
