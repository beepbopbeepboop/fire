# Every `.py` module of the self-host closure parses: no keyword steals an identifier (part 3)

Part 3 of 3 of `bugs/hard/CODEGEN_dict_slot_reads_refuse_compiler_sources.md`.
Class: easy — two narrow parser lookaheads; the compiler's own source is
Python and must keep parsing unchanged.

## Measured (2026-11-14, this tree)

Parsing every `.py` module in `cas.selfhost_inputs()` with the front end the
self-host build uses (`gimple_codegen.Parser(py_tokenize(src)).parse_module()`)
takes 7.9 s and fails on exactly three files:

    elaborate.py:3689:11              Expected NAME got ASSIGN('=')
        trait = (trait or '').strip()
    mojo/middle/mojoc_conformance.py:106:15   Expected NAME got ASSIGN('=')
        trait = (records or {}).get(_split_bound(bound))
    formal/build.py:19170:32          Unexpected COLON(':')
        lambda fn=fn, st=st: _bound_receiver_structs(

`trait` and `fn` are both in `_KEYWORDS` (`fire_compiler.py:1371`). A
statement-initial `trait` is dispatched unconditionally to `_parse_trait`
(`fire_compiler.py:9880`), so an assignment to a local named `trait` is read as
a trait declaration and dies at the `=`. A lambda parameter list refuses a
keyword-spelled parameter outright — measured:

    def f(fn): ...                    parses (with the existing "'fn' has been removed" warning)
    def f(trait): ...                 parses
    lambda fn: fn                     fails  "Unexpected COLON(':')"
    lambda fn=fn, st=st: ...          fails  "Unexpected COLON(':')"
    lambda st=st: ... (non-keyword)    parses

These are not cosmetic: `test_selfhost.py::closure_coroutines_are_lowerable`
parses the whole closure before its build half, raises the first of these, and
`test_selfhost.py` catches it as "self-host build raised" — so the `selfhost`
quick-tier job cannot even reach the build this doc's Done-when names.

    $ python3 - <<'PY'
    import test_selfhost
    test_selfhost.closure_coroutines_are_lowerable()
    PY
    SyntaxError: elaborate.py:3689:11: Expected NAME got ASSIGN('=')

## Why this is a parser part and not a source rename

The compiler's own source is Python, and Python identifiers are allowed to
spell Mojo keywords. The front end already accepts them in a `def` parameter
list (with the existing `fn` warning), and the compiler must also compile user
Python through `--dump-full`; renaming these three sites would leave the next
`let = ...` or `var = ...` to break the closure again. The reserved-word
meaning must survive: `trait Foo:` and `fn f():` still declare.

## Goal

An identifier position that cannot be a declaration accepts a keyword-spelled
name exactly as the `def` parameter list already does, so every `.py` module of
the self-host closure parses with no source change.

## Acceptance

- A statement-initial `trait` followed by `=` is an assignment to a local named
  `trait`, and `trait Marked:` still parses as a trait declaration whose body
  is checked as today. Generalise the lookahead to the sibling keyword-led
  statement dispatches that share the shape, so the next one does not repeat
  this (the `comptime`/`param` arms already state the rule).
- A lambda parameter list accepts a keyword-spelled parameter, with and
  without a default, in call-argument position: `lambda fn=fn, st=st: ...`
  parses, and `lambda st=st: ...` is unchanged.
- Every `.py` file in `cas.selfhost_inputs()` parses (skip a name that is not
  on disk), including `elaborate.py`, `mojo/middle/mojoc_conformance.py` and
  `formal/build.py`. No source file is renamed to work around the parser.
- `test_selfhost.py::closure_coroutines_are_lowerable` no longer raises (its
  own verdict is a separate matter; the parse must get through).
- `test_parser_error_recovery_part1.py` and `test_parser_param_for.py` stay
  green, and `def f(fn)` still emits its existing removed-keyword warning.

## Done when

File: `test_selfhost_closure_parses.py` (repo root; created by this part).

Command: `python3 test_selfhost_closure_parses.py`

It parses every `.py` in `cas.selfhost_inputs()` plus the two controls above
(`trait Marked:` declares, `lambda fn=fn, st=st: ...` parses) and fails with a
`file:line:col` list. Red today with exactly the three failures measured
above; it must pass.

## Where to start

- `fire_compiler.py:1371` — `_KEYWORDS`, where `trait` and `fn` enter.
- `fire_compiler.py:9876-9884` — the statement dispatch that sends every
  `trait` to `_parse_trait` with no lookahead.
- `fire_compiler.py:6125` — `_parse_trait`; its declaration form starts with a
  NAME, which is the lookahead that separates it from an assignment.
- The lambda parameter parser (search `lambda` in `fire_compiler.py`'s primary
  expression parser) — it takes the strict NAME-only path, unlike the `def`
  parameter list.
- `cas.py:317` — `selfhost_inputs()`, the closure set the test walks.
