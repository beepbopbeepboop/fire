# CODEGEN: `re` findall / split / sub / finditer on a BYTES subject read the bytes object as a C string

Found while fixing the match-object bug (a match's group and repr read a bytes subject as str; 2026-11-02).
Match objects now keep their subject's kind; the pattern methods below do not.

## Measured (compiled, this tree)

    import re
    print(re.compile(b"a").findall(b"aa"))       # CPython [b'a', b'a']      compiled []
    print(re.compile(b",").split(b"a,b"))        # CPython [b'a', b'b']      compiled [' ', '=\x03\x01'] (garbage)
    print(re.compile(b"a").sub(b"x", b"aa"))     # CPython b'xx'             compiled `5=`5==  (garbage)
    # finditer on bytes: not probed, same entry shape as findall (see below)

`re.compile(b"(a)(b)").match(b"ab").groups()` is correct (`(b'a', b'b')`) after the match fix.

## Why

`mojo_re_call` routes `pattern.findall/split/sub/finditer(subject)` to `_re_findall`,
`_re_split`, `_re_sub`, `_re_finditer` in `runtime/fire_runtime.c`. Those take `char *s` and call
`strlen(s)` / `fre_exec(..., s, ...)`. When the argument is a registered bytes object (a
`MojoBytes *`), it is read as if it were a C string: the struct's own bytes are the "text", and
the results are built with `strdup`/`malloc` of str pieces. `mojo_re_exec` and
`mojo_re_exec_bytes` already dispatch on `mojo_is_registered_bytes`; these four do not.

The `sub` replacement is also taken as a str (`_re_expand` / `APPEND` on `strlen`), so a bytes
template must be read by its kind too.

## Next step

1. Give `_re_findall`, `_re_split`, `_re_sub`, `_re_finditer` the same subject-kind dispatch as
   `mojo_re_exec`: a bytes subject runs `fre_exec_bytes` on `s->data`/`s->len`, builds bytes pieces
   with `mojo_bytes_new_lit`, and returns a list of bytes words. `_re_sub` returns a bytes object for
   a bytes subject; its template and callable result are read by kind as well.
2. The result kinds the codegen assigns (`_lower_re_dynamic_call` in
   `mojo/backend_gimple/emit_methods.py`, `_elem_types[lt] = 'char *'` for findall/split) must stop
   claiming `char *` elements for a bytes subject; `groups()` already works with word elements.
3. Test: add `print(re.compile(b"a").findall(b"aa"))`, the split and sub lines above to
   `test_glob_bytes_regress.py`, each compared to CPython; each must fail on the current tree first.
