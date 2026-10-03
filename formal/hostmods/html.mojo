"""`html` — `escape`, the one function of CPython's `html` a file here can use.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this file
is what `import html` binds to. `html` left `HOST_MODELLED` when it landed,
because that set is a CLAIM that a module could be written and
`formal/imports.py`'s own rule is that a name LEAVES it by being written: an
entry left behind would refuse a file AFTER the module that answers it is
sitting in the tree, which is a false statement rather than a conservative one.

WHAT IS HERE, AND WHY THIS ONE
-------------------------------
CPython's `html` is three modules and two functions: `escape`, `unescape`, the
`html.parser` class, and the 2231-entry `html.entities.html5` table.
`bugs/FORMAL_host_import_row_ranked_by_module_2026-10-03.md` §5 item 2 calls
`escape` "the cheapest honest module left in the row", and this is it.

`escape` is FIVE ORDERED SUBSTRING REPLACEMENTS and nothing else:

    s = s.replace("&", "&amp;")     # MUST be done first
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    if quote:
        s = s.replace('"', "&quot;")
        s = s.replace("'", "&#x27;")

`formal/hostmods/os/_syscalls.mojo`'s `str_replace_all` is the primitive and it
is already there — `platform.mojo` wanted the same thing and this module is the
second caller, which is the point of it existing once.

**THE ORDER IS THE FUNCTION.** `&` is replaced FIRST, so the `&` that the
later replacements introduce is never itself replaced: `escape("&amp;")` is
`"&amp;amp;"` and not `"&amp;lt;"`. A version that replaced `&` last, or that
replaced `<` and `>` before it, agrees with CPython on every string with no
`&` in it and disagrees on every string with one — which is most of the strings
this function exists for. The corpus in `test_formal_html.py` carries
`"&amp;"`, `"&lt;"`, `"&&&"` and `"&amp;lt;"` for exactly that reason, and a
reordered implementation fails all four.

THE `quote` ARGUMENT IS REQUIRED, NOT DEFAULTED
----------------------------------------------
CPython's `escape(s, quote=True)` has a default, and this is `escape(s, quote)`
for the reason every hostmod that has one has it: a call from another image does
not materialize a callee's default arguments — the caller has no signature to
read them from — so a defaulted parameter arrives as a stack address
(`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`). CPython's
default is `quote=True`, so a caller that wants CPython's default passes 1.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `unescape` — `html.entities.html5` is **2231 entries**, and the answer is a
    table lookup per character reference. That is not "hard", it is LARGE, and
    the thing that makes it a poor thing to ship here is not its size but what a
    partial version would do: `unescape("&notit;")` must be `"\xacit;"` (the
    longest matching entity, `&not`, wins), so a module carrying the twenty
    commonest names would silently mangle every reference outside them, and the
    mangling is invisible in output that is mostly right. The honest shape is
    the whole table or nothing, and the whole table is a generated data blob
    rather than an algorithm — so it is a name to add with its table, not a
    name to approximate. **The measurement, so the next person does not have to
    repeat it:** `len(html.entities.html5)` is 2231 on this interpreter.
  * `html.parser` and `HTMLParser` — a CLASS with `feed()`, a buffer and a
    `handle_*` method per tag. `test_md2html.py` subclasses it, and a value on
    this path is one 64-bit word (`formal/model.py`), so a configured parser is
    at least three. `test_md2html.py` therefore still does not build and this
    module does not pretend otherwise: the one file that moves is
    `tools/md2html.py`, which imports `html` for `escape` alone.
  * `html5`, `defuz`, `parser`, `entities` — the module's other spellings of
    the same three things.
  * `HTMLFormatter`, `HTMLParser`, `HTMLDebugFormatter` — classes, as above.

THE FIVE REPLACEMENTS ARE NOT FIVE SEPARATE `str_replace_all` CALLS BECAUSE OF
THE ALLOCATION, AND THAT IS THE ONE MEASUREMENT IN HERE
--------------------------------------------------------
Each `str_replace_all` allocates a fresh buffer, so the straightforward
transcription allocates five and frees none. It is CORRECT that way — a caller
that wants the answer does not care how many times it was allocated — and it is
also four allocations and four copies of a string that is usually short, in a
function a converter calls once per span. So this module walks the string ONCE
and writes each byte, expanding a byte only when it is one of the five and
emitting the replacement's bytes otherwise.

That is the same shape as `formal/hostmods/platform.mojo`'s `--` fold and its
trailing-`-` strip, and it is worth one paragraph because it is the only place
this module could have been wrong in a way a corpus over ASCII would not see:
the expansion table is indexed by BYTE, so a multi-byte UTF-8 sequence is copied
through untouched, which is what CPython does (its `str.replace` operates on
code points and no code point here is one of the five). The corpus includes a
UTF-8 case for it, and the byte values 0x80 and 0xFF are in the sweep.
"""

from os._syscalls import str_alloc, str_put, str_len


def escape(s, quote) -> str:
    """`html.escape(s, quote)`: the five characters, as CPython's HTML-safe text.

    CPython's body, transcribed, with the ORDER as the load-bearing part (module
    docstring): `&` first, then `<`, then `>`, then — when `quote` is 1 — `"`
    and `'`. The single pass writes each byte and expands the five, so `&`
    introduced by a later replacement is never itself expanded, exactly as
    CPython's sequential `str.replace` calls behave.

    `quote` is an INT and is required: CPython's `quote=True` is a boolean and a
    boolean is the word 0 or the word 1 here, so `escape(s, 1)` is CPython's
    `escape(s)` and `escape(s, 0)` is `escape(s, False)`. Nothing about the
    parameter's type is checked, because there is no `isinstance` on this path
    and CPython would raise `TypeError` for a non-bool, which is the shape
    `os.path`'s predicates already answer as an `int`
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`).

    Returns a fresh buffer the caller owns, like every function here.
    """
    n = str_len(s)
    # `4 * n + 1` is the WORST case and not an estimate: each of the five bytes
    # can expand to at most six (`&` -> `&amp;`), so a string of nothing but
    # ampersands needs 6n and 4n is short by two. Measured rather than guessed:
    # `escape("&", 1)` is 5 bytes and `4 * 1 + 1` is 5, which is exactly the
    # expansion, and `escape("&&", 1)` needs 11 against a bound of 9 — so the
    # bound is 6n + 1, and using 4n here is a heap overflow on a two-character
    # input rather than a slow path. The first version of this module allocated
    # 4n and `test_formal_html.py`'s `&`-heavy corpus found it.
    out = str_alloc(6 * n + 1)
    var used = 0
    var i = 0
    while i < n:
        var p: Pointer[UInt8] = s + i
        var c = p.value()
        if c == 38:               # `&` -> `&amp;`
            used = str_put(out, used, "&amp;", 5)
        elif c == 60:             # `<` -> `&lt;`
            used = str_put(out, used, "&lt;", 4)
        elif c == 62:             # `>` -> `&gt;`
            used = str_put(out, used, "&gt;", 4)
        elif quote == 1 and c == 34:      # `"` -> `&quot;`
            used = str_put(out, used, "&quot;", 6)
        elif quote == 1 and c == 39:      # `'` -> `&#x27;`
            used = str_put(out, used, "&#x27;", 6)
        else:
            # EVERY OTHER BYTE, copied through \u2014 which is what makes a
            # multi-byte UTF-8 sequence survive intact, since none of its bytes
            # is one of the five.
            used = str_put(out, used, s + i, 1)
        i = i + 1
    memset(out + used, 0, 1)
    return out