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

`grep -rn "escapes are NOT\|escapes are not decoded\|interned verbatim" formal/ test_formal_*.py doc/*.md`
on the merge of `work/formal14-hostmods-more2` (2026-10-03).

**This doc's own census was wrong, and that merge is what made it wrong.** It
said `ast.mojo` was "the only remaining place in `formal/`" describing a string
literal's escapes as undecoded, and named the two places it meant to exempt —
both of them `formal/arm64_codegen.py`. There were three HOSTMOD sites, plus three
more since fixed:

| site | state |
|---|---|
| `formal/hostmods/ast.mojo` `_quotes()` | **this doc's subject** — still to do |
| `formal/hostmods/argparse.mojo:1761` (`_ws_set`'s own docstring) | **still to do**, and the cheapest: see below |
| `formal/hostmods/platform.mojo:336` (`_int_is_space`'s docstring) | **still to do** — and `formal/hostmods/platform.mojo` is claimed by `hostmods-platform` (`module:platform+fnmatch+collections-rest`), so it is not the merger of `formal14-hostmods-more2`'s to edit |
| `formal/hostmods/textwrap.mojo` module docstring | FIXED on that merge; it carried the same false claim and cited the deleted doc |
| `test_formal_html.py` header | FIXED on that merge, same |
| `test_formal_textwrap.py`'s `mask` comment | FIXED on that merge, same |

`argparse.mojo` contradicts ITSELF, which is what makes it the cheapest of the
three: the comment at `argparse.mojo:317-327` already carries the corrected
reason ("That reason is CURRENT. The reason this file used to give ... is NOT,
and had stopped being true at `9023031b`"), while `_ws_set`'s docstring fourteen
hundred lines below still states the false premise. The replacement text is
already in the file; the fix is to move it.

The emitters already record the fix and cite the deleted doc AS DELETED
(`formal/arm64_codegen.py:3480`, `:9769`, `formal/x86_64_codegen.py:3873`), and
`formal/hostmods/re.mojo:2430` says so in prose — those are the two this doc's
census meant to name, and it named one of them twice.

Not changed here: `formal/**` is the busiest area in the tree, and these are
comments in host modules that go into real formal images. Each is a two-line edit
for whoever is in there.

## Next step

Replace the "interned VERBATIM and its escapes are not unescaped" premise with
the one that holds (escapes are decoded by `fire_compiler.decode_c_escapes`, as
CPython does), and either keep the byte-by-byte construction with that reason
or simplify it to a literal and say why the measurement was dropped.
`test_formal_sys.py`'s `string escapes are interpreted as CPython does` is the
test that keeps the underlying behaviour pinned either way.

Three sites, and the reason each still matters is the same: it is the reason a
reader would give for NOT simplifying a construction that is no longer
necessary, and a stated reason that is false sends them the wrong way. The
wording to use is already in the tree twice — `formal/hostmods/argparse.mojo:317-327`
and, as of the `formal14-hostmods-more2` merge, `formal/hostmods/textwrap.mojo`'s
"THE BYTE SETS ARE BUILT WITH `memset`, and here is the CURRENT reason" section,
which also records why the `memset` idiom SURVIVES the fix: these separators are
written at a computed offset, and one of them is a NUL-terminated `strspn`
accept-set at a length a literal cannot spell.