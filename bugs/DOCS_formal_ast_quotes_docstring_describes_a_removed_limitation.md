# DOCS: `formal/hostmods/ast.mojo`'s `_quotes()` still explains a limitation
# that was removed

## What it says

`formal/hostmods/ast.mojo`, `_quotes()`, docstring:

> BUILT, and not written as a literal, for a measured reason: a string literal
> on this path is interned VERBATIM and its escapes are not unescaped, so
> there is no spelling of a two-byte set holding both quotes. `"\""` emits a
> backslash and a quote (the escape is not interpreted, so the set would also
> match every backslash in the source) …

None of that is true any more. 9023031b ("formal: a string literal's escapes
are decoded, on this path too") moved the decoder into
`fire_compiler.decode_c_escapes` and gave the formal backends the one every
other engine already used; `bugs/FORMAL_string_literal_escape_is_not_decoded.md`
went with it, and `formal/hostmods/sys.mojo`'s matching note and
`test_formal_sys.py`'s two assertions were updated with it. This one was missed,
because nothing fails on it: the function still builds the set a byte at a time,
which is still correct, just no longer necessary.

## Why it matters anyway

It is the reason a reader would give for NOT simplifying the function, and the
stated reason is false. The two spellings it rules out now work:
`"\""` is a one-character string containing a quote, and `'"'` is a one-character
string containing a quote — the second spelling is what the comment says "looks
right" and then rejects. Anyone who reads this before touching the function
concludes the byte-by-byte construction is load-bearing.

## What I ran

`grep -n "escape" formal/hostmods/*.mojo` — this is the only remaining place in
`formal/` that describes a string literal's escapes as undecoded. The other two
(`formal/arm64_codegen.py`, `formal/arm64_codegen.py:7789`) already record the
fix and cite the deleted doc.

Not changed here: `formal/**` is the busiest area in the tree, and this is a
comment in a host module that goes into real formal images. It is a two-line
edit for whoever is in there.

## Next step

Replace the "interned VERBATIM and its escapes are not unescaped" premise with
the one that holds (escapes are decoded by `fire_compiler.decode_c_escapes`, as
CPython does), and either keep the byte-by-byte construction with that reason
or simplify it to a literal and say why the measurement was dropped.
`test_formal_sys.py`'s `string escapes are interpreted as CPython does` is the
test that keeps the underlying behaviour pinned either way.