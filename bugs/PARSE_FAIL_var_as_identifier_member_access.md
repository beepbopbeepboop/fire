# PARSE_FAIL: `var` used as a plain identifier followed by `.attr`/`.method()` misparses as a var-declaration

## Status
**Fixed** (2026-07-25). `mojo_compiler.py`'s statement-level `_parse_stmt`
dispatch for `var` (~line 1413) replaced the narrow "only `var = expr` falls
through" special case with the same positive-lookahead style used for
`fn`/`struct`/`enum`: only commit to `_parse_var_decl()` when the token
right after `var` is name-like (NAME/KW/backtick-STRING, matching what
`_parse_var_decl` itself accepts as a declared name) or `COLON` (the
`var: Type` field-annotation shape, where `var` itself is the name — same
parse either way `var` is read, so no ambiguity there). Anything else —
`.` (member access/assignment), `,` (as one of several plain tuple-unpack
targets), comparison/binary operators, bare `var` alone, etc. — now falls
through to ordinary expression/assignment parsing.

Added `test_gimple.py` coverage (`var_as_plain_ident_member_access`,
`var_as_plain_ident_tuple_unpack_target`, `var_decl_forms_still_work`) and
confirmed the minimal repro below, plus
`Tools/cases_generator/stack.py` (line 321's `var.in_local` error is gone;
parsing now progresses to an unrelated `for var, other_var in zip(...)`
for-loop-target parse issue further down at line 606, out of scope for this
fix — for-loop targets are a different call site) and
`Lib/idlelib/dynoption.py` (parses past line 43's `var.set(...)`
entirely; only remaining failure is a runtime Tkinter-availability error,
unrelated to parsing).

Full quality gate: `make check-selfhost` green, `test_gimple.py` (168/168)
and `test_module_cache.py` (64/64) green, and a from-scratch
`libmojostdlib.dylib` rebuild stayed at 0 skipped modules before and after
(already at the "every stdlib file compiles" ceiling from the prior
boxing-stub regression fix, so no room to decrease further, but confirmed
no regression).

## Repro

```python
class C:
    pass
var = C()
var.x = 5
print(var.x)
```

```
$ python3 mojo.py run repro.py
SyntaxError: repro.py:4:3: Expected NAME or KW got DOT('.')
```

Also reproduces in real stdlib source:
- `Lib/idlelib/dynoption.py:43`: `var.set("Old option set")` (`var = StringVar(top)` on the previous line)
- `Tools/cases_generator/stack.py:321-323`: `var.in_local`, `var.memory_offset = var_offset`, etc. — this is
  the SECOND bug in that file; the first (`assert(var not in self.variables)`)
  was fixed in commit `7537794` (`bugs/PARSE_FAIL_conv_kw_prefix_misfires_on_var_not_in.md`),
  and the fix's own report noted this exact remaining failure at line 321
  as a separate, not-yet-fixed issue.

## Root cause

`mojo_compiler.py`'s statement-level `_parse_stmt` dispatch (~line 1413-1419):

```python
if t.value == 'var':
    # "var = expr" means 'var' is used as a plain identifier (Python compat)
    # "var name" or "var name:" is a proper var declaration
    if self._peek(1).kind == "ASSIGN":
        pass  # fall through to expression/assignment handling below
    else:
        return self._parse_var_decl()
```

This only special-cases the `var = expr` shape (assignment). Any other use
of `var` as a plain identifier — `var.attr` (member access), `var.method()`
(method call), `var,` (tuple-unpacking target), `var == x` (comparison),
`var[0]` (subscript), bare `var` alone, etc. — falls into the `else` branch
and unconditionally commits to `_parse_var_decl()`, which then expects a
declaration name and chokes on the next token (`.`, `,`, `==`, `[`, ...)
instead of falling through to ordinary expression-statement parsing.

This is the exact same keyword-vs-identifier collision class already fixed
for `fn` (commit `bd2227c`), `struct`/`enum` (`4179ac7`, `7e4a397`), and the
narrower `(var not in x)` parenthesized case (`7537794`) — but the
statement-level `var` dispatch itself was never given the same
positive-lookahead treatment those got. `var` is an especially common
target for this collision since it's an extremely common plain Python
variable name (unlike `fn`/`struct`/`enum` which are rarer as identifiers),
so this is likely to affect many more real-world files than the already-fixed
cases.

## Suggested fix

Apply the same positive-lookahead-disambiguation pattern used for
`fn`/`struct`/`enum`: only commit to `_parse_var_decl()` when the token
shape that follows `var` could actually BE a declaration (per whatever
`_parse_var_decl` itself expects — likely `var` followed by a name-like
token, then `:` (type annotation) or `=` (assignment with declaration) or
end-of-statement). Anything else (`.`, `,`, `[`, `==`, comparison/binary
operators, etc.) should fall through to ordinary expression-statement
parsing, which already accepts KW tokens as identifiers via
`_parse_primary`'s generic KW-as-identifier fallback.
