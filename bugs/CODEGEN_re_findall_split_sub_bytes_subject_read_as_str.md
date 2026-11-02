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

## Status (2026-11-02): partial fix landed

Landed:

- Runtime (`runtime/fire_runtime.c`): `findall`, `split`, `sub`, `finditer` (and `mojo_split_dyn`)
  take the subject as a WORD and read it by kind (`_re_subj_word`): a bytes object by its length
  (a NUL is data), a str to its NUL; a None subject raises TypeError. One search path
  (`_re_search`) now serves `mojo_re_exec` and `mojo_re_exec_bytes`, which were duplicates.
  Pieces are built by `_re_piece` and pushed with `mojo_list_append_word`, so each element carries
  its kind. `sub` returns a bytes object for a bytes subject; a bytes template and a callable's
  bytes result are read by length (`_re_expand` takes a length).
- Codegen (`mojo/backend_gimple/emit_methods.py`, `_lower_re_dynamic_call`): the subject's STATIC
  type picks the result kind. A `MojoBytes *` subject gives a `MojoBytes *` `sub` result and
  `MojoBytes *` list elements; a str subject is unchanged.
- Regression: `test_glob_bytes_regress.py` compares findall / split (incl. a NUL in the subject) /
  sub (incl. `\g<0>`) / finditer on bytes, plus str lines, to CPython. It failed on the prior tree
  and passes now.

Still open (the next step):

- A subject whose static type is NOT known (a runtime-kinded word, e.g. an untyped parameter that
  holds bytes) still takes `char *` results from `_lower_re_dynamic_call`, so `sub` on such a
  subject reads the bytes object as a C string. The fix is a runtime-kinded result for that case,
  which needs `sub`'s str users (`re.sub(...) + x`) checked first: the result cannot be a plain word
  for every str subject without regressing them. Next step: probe an untyped bytes parameter, then
  decide between a dyn-word `sub` result for unknown subjects and a type-directed specialisation.
