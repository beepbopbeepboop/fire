# CODEGEN_generator_function: Lib/codecs.py

## Status (updated 2026-08-06)

**STILL FAILING**, but re-diagnosed against current master (`2b0c4c5`) —
the 2026-07-30 `getincrementalencoder` .cpp error no longer reproduces.
`codecs.py` has exactly 2 generators of its own
(`StreamReaderWriter`/similar `__getattr__`-adjacent helpers around
lines 1056/1074, both simple `yield output` shapes) — **neither shows up
anywhere in the current error list**, and `MOJO_DEBUG=1` shows no "not
eligible"/refusal note naming either of them, so codecs.py's OWN
generator bodies now appear to compile cleanly through the coroutine
path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
codecs.py currently fails to build for a large number of severe,
apparently unrelated pre-existing bugs that have nothing to do with
`yield`/coroutines — dominant ones seen in the current error list:

```
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:685:10: error: expected '=' before '*' token
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:686:3: error: expected expression before 'MojoList'
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:704:3: error: '_t3' undeclared (first use in this function); did you mean '_t2'?
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:710:3: error: implicit declaration of function 'io_Reader_mojo_read'; did you mean 'StreamReader_mojo_read'? [-Wimplicit-function-declaration]
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:923:25: error: invalid use of undefined type 'struct _opcode_toplev'
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:75:26: error: assignment to 'char *' from 'int64_t' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:1362:46: error: stray '\' in program
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:1362:47: error: missing terminating ' character
```

(the 685-789-range block looks like a garbled multi-variable declaration
statement emitted with the wrong syntax entirely — likely a class-field/
tuple-unpack codegen bug; the `:1362` stray-backslash error looks like a
raw-string/escape-handling tokenizer bug; neither is generator-related.)

Not investigated further — genuinely out of scope for this generator-
codegen cluster's mandate. If picked up, these look like they'd need
their own dedicated `COMPILE_FAIL_Lib_codecs.md`-style investigation
(unrelated to `bugs/hard/CODEGEN_*` generator docs), starting with the
malformed declaration block around lines 685-789.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/codecs.py
