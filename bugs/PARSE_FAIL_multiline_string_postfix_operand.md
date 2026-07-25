# PARSE_FAIL: a triple-quoted/multiline string literal can't be used as a postfix/binary-operator operand

## Status
Fixed (2026-07-25)

## Reproduction (two distinct manifestations of the same root cause)

**1. Method call directly on the literal:**
```mojo
def f():
    var s = """
    hello
    """.strip()
    print(s)
f()
```
```
SyntaxError: test.mojo:4:0: Unexpected DOT('.')
```

**2. `%`-format operator directly on the literal:**
```mojo
def f():
    var name = "world"
    var s = """hello
%s""" % (name,)
    print(s)
f()
```
```
SyntaxError: test.mojo:4:0: Unexpected OP('%')
```

Both fail at `mojo_compiler.py:2957` (`_parse_primary`, "Unexpected ...") via
`_parse_postfix` (line 2616) — i.e. the parser gets partway through parsing
the string literal expression and then can't find a valid primary/postfix
continuation when the very next token is `.` or `%` (or, presumably, any
other postfix/binary operator) directly following the literal's closing
`"""`.

## Expected Behavior
A multiline (triple-quoted) string literal should be usable as an ordinary
expression operand exactly like a single-quoted string literal already is
— `"hello".upper()` and `"a %s" % x` both work fine today; only the
triple-quoted form breaks. `"""..."""` followed immediately (same line, no
whitespace needed) by `.method(...)`, a binary operator (`%`, `+`, `==`,
...), or a subscript (`[...]`) should all parse identically to the
single-quote case.

## Root Cause (confirmed)
`mojo_compiler.py`'s tokenizer (`py_tokenize`) never actually mis-tokenized
the triple-quoted literal itself — the `STRING`/multiline lexing is fine.
The bug was in `replace_multiline_strings()` (a pre-pass inside
`py_tokenize` that collapses each triple-quoted literal to a single
`__MOJO_STR_N__` placeholder token, restoring the original text from a
cache after line-based tokenization). To keep every *subsequent* physical
line's diagnostics/line numbers correct, that pre-pass has to re-insert as
many `\n` characters as the literal itself contained (since the literal
just became a single line). The old code did this via
`return placeholder + '\n' * literal.count('\n')` — i.e. it inserted the
"owed" newlines **immediately after the placeholder**, on the *same*
synthetic line.

That's the bug: if anything followed the literal's closing `"""` on its
*original* source line (`.strip()`, ` % (name,)`, etc.), that trailing text
was appended to `out` from the source *after* those padding newlines were
already emitted — so it ended up shoved onto an artificial blank line of
its own, disconnected from the placeholder. The line-based tokenizer
(Phase 2 of `py_tokenize`) then emitted a `NEWLINE` right after the
placeholder token, ending the statement there, and the `.`/`%` on the next
"line" had no primary expression before them —
`SyntaxError: Unexpected DOT('.')` / `Unexpected OP('%')`.

Confirmed via direct token-stream inspection: for repro #1, tokenizing
`__MOJO_STR_0__\n\n.strip()` (2 blank lines injected right after the
placeholder for the literal's 2 internal newlines) produces
`STRING NEWLINE .strip() ...` instead of `STRING . strip ( ) NEWLINE`.

## Fix
`mojo_compiler.py`, `py_tokenize`'s `replace_multiline_strings()` (~line
738): rewrote the placeholder substitution from two independent `re.sub`
passes (one for `"""`, one for `'''`) with immediate padding, to a single
left-to-right `pattern.finditer(src)` scan that tracks the newlines "owed"
by each collapsed literal in a `pending_pad` counter and defers emitting
them until the **next real `\n`** actually present in the source — i.e.
after any trailing same-line text (postfix chain / binary operator) has
already been copied through. This keeps the placeholder and any same-line
continuation glued together on one synthetic line, while still shifting
every later line's line-number accounting by the correct amount once that
line's real newline is reached. Also folds the two separate `"""`/`'''`
`re.sub` passes into one combined-pattern scan, so interleaved literals of
both quote styles are matched in true source order.

Note: an earlier draft of this fix extracted the newline-flush logic into a
small nested closure (`def _flush_segment(...): nonlocal pending_pad`)
shared by the in-loop and tail cases. That version was byte-for-byte
equivalent in behavior (verified: same repros pass) but broke
`make check-selfhost` — `gimple_codegen.py` failed to self-compile with
unrelated errors elsewhere in the file (`request for member 'name' in
something not a structure or union` in `_merge_struct_inheritance_resolve`,
`'SubscriptExpr' has no member named 'attrs'` in `_lower_subscript`,
`invalid conversion in gimple call` in `mojo.py`'s own `t.join()`) —
reproduced deterministically across repeated runs. Inlining the same logic
directly in both call sites (no nested closure) fixes the same bug
identically but self-hosts cleanly; kept that version. Root cause of the
self-host interaction not further chased down (out of scope — this is the
same class of self-host whole-program-inference fragility documented
elsewhere for this codebase), but flagged here in case it recurs.

## Verification
- Both original repros: no longer crash; repro #1 prints `hello`, repro #2
  prints `hello\nworld`.
- Additional cases checked, all correct: `"""abc"""[0]` (subscript),
  `"""a\nb""" + "c"` (different binary operator on a multi-line literal),
  a standalone triple-quoted docstring statement (unaffected/still works),
  `var s = """text"""` with nothing after it on the same statement
  (unaffected/still works), and a syntax error several lines *after* a
  multi-line literal still reports the correct physical line number
  (line-number preservation not regressed).
- `python3 test_gimple.py` — 159 passed, 0 failed (unchanged from
  pre-fix baseline in this worktree/branch).
- `python3 test_module_cache.py` — 58 passed, 0 failed (unchanged from
  pre-fix baseline in this worktree/branch).
- `make check-selfhost` (`python3 test_selfhost.py`) — passes, verified
  stable across repeated runs.
- From-scratch stdlib dylib build
  (`rm -f build/libmojostdlib.dylib && python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)"`)
  — completes cleanly, **0** `  skip` lines (no regression from the
  pre-fix 0-skip baseline).

(Note: this worktree/branch's baseline for `test_gimple.py`/
`test_module_cache.py` is 159/58 passed, not the 161/64 figures from a
different, more up-to-date branch — confirmed by re-running both suites
against the pre-fix `git stash`'d tree before attributing any count to
this change.)

## Real-world impact
Confirmed via real CPython 3.14 stdlib source: `Lib/xmlrpc/server.py:815`
and `Lib/unittest/mock.py:205` both use `"""...multiline template...""" %
(args)` (a very common Python idiom: a triple-quoted template string
formatted with `%`). `Lib/concurrent/interpreters/__init__.py:33` uses
`"""...""".strip()` on a triple-quoted docstring-shaped constant.

## Files Affected
- `mojo_compiler.py` — `py_tokenize`'s `replace_multiline_strings()`
  helper (~line 738).

## Merge note (2026-07-25)
The dev worktree above was based on an older commit that still had the
prior, naive two-`re.sub`-pass version of `replace_multiline_strings()`.
By the time this landed, `master` had independently gained a *different*
fix to the same function (a single-pass, quote-nesting-aware char-by-char
scan, guarding against a triple-quote character sequence embedded inside an
*ordinary* quoted string being misread as a real triple-quote delimiter —
see that fix's own inline comment for its own real-world trigger,
`_MULTI_QUOTES = ('"""', "'''")` in CPython's `_ast_unparse.py`). The two
fixes address different bugs in the same function and both needed to
coexist. Applied by hand: kept master's char-by-char quote-nesting-aware
scan structure, and within it replaced the single
`out.append(placeholder + '\n' * literal.count('\n'))` line with the same
`pending_pad`-deferred-to-next-real-newline approach described above,
inlined at both flush points (never as a shared closure, per the
self-host-fragility note above). Re-verified after merging: both original
repros, the embedded-triple-quote-in-a-string case
(`('"""', "'''")` inside a tuple, plus a real docstring after it — both
still resolve correctly), `test_gimple.py` 161/0, `test_module_cache.py`
64/0, `make check-selfhost` clean, from-scratch stdlib build 0 skips — all
on `master`, not just the isolated dev worktree.
