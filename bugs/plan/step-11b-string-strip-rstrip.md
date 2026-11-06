# plan/step-11b: `strip()` / `rstrip()` on the runtime buffer
Class: mid      Size: M      Depends: 11a      Blocks: 13c
Source: `bugs/FORMAL_string_value_model.md` § "The cost" and `LENGTH_DEPENDENT_METHODS["strip"]` / `["rstrip"]` (`formal/model/cfg.py:4046-4060`, the measured `maxprot 0x5` read-only text and the wrong-answer story).

## Current state (measured; verified 2026-11-05)
- `strip`/`rstrip` are refused (`LENGTH_DEPENDENT_METHODS`), except on a literal receiver where `STRING_FOLDED_METHODS` folds them (`formal/model/methods.py:369`). `lstrip` is lowered as `s + strspn(s, STRIP_CHARS)` (`arm64_codegen.py:8207`, `x86_64_codegen.py:6411`). `STRIP_CHARS = " \t\n\v\f\r"` is the single whitespace definition (`formal/model/cfg.py`, near `STRIP_MAX`).
- After step 11a: `strdup` is the buffer allocator (never freed), `_emit_str_case` is the model for a byte loop, and `string_buffer_methods()` / `buffer_case_refusal` exist (`formal/model/strings.py`).

## Decisions already made
- `rstrip()` = `p = strdup(s)`, then trim the COPY in place: `n = strlen(p); while n > 0 and strchr(STRIP_CHARS, p[n-1]) != NULL: n -= 1; p[n] = 0`. `strip()` = the same with `strdup(s + strspn(s, STRIP_CHARS))` (leading trim by pointer, trailing on the copy). The copy is writable heap, which is why the original objection ("the receiver's bytes cannot be written") does not apply.
- Whitespace test is libc `strchr(STRIP_CHARS_interned, byte)`, NOT a hand-written range test: byte is never 0 inside `n > 0` so a NUL match cannot occur. Intern the set with the same call `_emit_str_lstrip` uses: `self._emit_expr(F.StringLiteral(M.STRIP_CHARS))`.
- Zero-argument form only. `strip(chars)` / `rstrip(chars)` keep being refused via the arity tables (`STRING_METHOD_ARGS`/`STRING_METHOD_MAX_ARGS`, `formal/model/methods.py:61,74`): add `"strip": ()`, `"rstrip": ()` there. Reason: the accept-set variant needs `strspn` complement logic that `lstrip(chars)` has but a trailing scan does not; out of scope, refusal text stays true ("takes no arguments on this path").
- ASCII-only image rule exactly as 11a (CPython strips Unicode whitespace such as U+00A0 and U+3000; this path would not): `buffer_case_refusal` is reused by renaming its wording once to cover "whitespace/case" ("only change/strip ASCII ...").
- Result kind `STR_KIND`; an all-whitespace or empty receiver yields the empty string (`p[0] = 0` when `n` reaches 0) which is truthy-false like any empty string.

## Work order
1. `formal/model/cfg.py`: move `"strip"`, `"rstrip"` from `LENGTH_DEPENDENT_METHODS` to `POINTER_BOUNDED_METHODS` as `("str_strip", STR_KIND)`, `("str_rstrip", STR_KIND)`. Fix the other entries' "see strip"/"see strip. lstrip() is the lowered half" cross-reference text so it is still true (mention strip/rstrip are now lowered on the buffer). Add the names to `string_buffer_methods()`.
2. `formal/model/methods.py`: arity entries above.
3. `formal/arm64_codegen.py`: `_emit_str_trim(self, e, leading: bool)` beside `_emit_str_case`; dispatch `elif how == "str_strip": ...(leading=True)` / `"str_rstrip": ...(leading=False)`. Slots: [sp+0]=p, [sp+8]=n, [sp+16]=set. Sequence: emit recv -> X0; if leading: `X1=set; call strspn; add X0 = recv + X0` (reload recv from a slot); `call strdup`; store p; `call strlen(p)` -> n; loop: `cbz n -> done; ldr p; add X1=p+n-1; ldrb W1,[X1]; X0=set; call strchr(X0=set, X1=byte)` (arg order: strchr(const char *s, int c): X0 = the set, X1 = the byte, so zero-extend the byte into X1); `cbz X0 -> done (not whitespace)`; `n -= 1; b loop`; done: `ldr p; add X1=p+n; strb WZR,[X1]`; result X0 = p.
4. `formal/x86_64_codegen.py`: same algorithm, same names, SysV registers (RDI/RSI).
5. Tests in `test_formal_str_methods.py`, CPython oracle, both backends, receivers that defeat the fold (a parameter): `"  hi  "`, `"hi"`, `"   "`, `""`, `"\t a b \n"`, internal spaces preserved; a returned-from-function lifetime row for `strip`; `rstrip` keeps the leading spaces (`"  hi  ".rstrip()` -> `"  hi"`); a `strip("x")` refusal row (needle: the arity sentence); non-ASCII-image refusal row.
6. Status paragraph in `bugs/FORMAL_string_value_model.md` (what landed; replace/join and swapcase/capitalize/title/casefold remain refused, see 11c).

## Do NOT
- Do not write the trailing scan as a hand-built byte-range compare (`<= 0x20`): `STRIP_CHARS` is the single source and the `lstrip` history is two private loops each wrong once.
- Do not trim the receiver in place (read-only text or shared interned string).
- Do not forget that `n` is a `size_t`: the `cbz n` test must come BEFORE `n-1` is formed.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_str_methods.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_unicode.py
```

## Done when
- [ ] the six `strip`/`rstrip` oracle rows pass on both backends
- [ ] `grep -n '"strip"' formal/model/cfg.py` shows it only inside `POINTER_BOUNDED_METHODS`
- [ ] `test_formal_unicode.py` unchanged-green

## If stuck
Land nothing past the model half, put `strip`/`rstrip` back in `LENGTH_DEPENDENT_METHODS` (tree green), write the failing row and register dump into the doc Status, stop.
