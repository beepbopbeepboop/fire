# CODEGEN_generator_function: Lib/ipaddress.py

## Status (updated 2026-08-06)

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
