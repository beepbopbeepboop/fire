# CODEGEN_generator_function: Lib/calendar.py

## Status (updated 2026-08-07)

**Classification bug FIXED** (`bugs/hard/CODEGEN_comprehension_return_
type_defaults_int64.md`, task #145) — `_quick_type` now has a
`Comprehension` case. Confirmed via a direct, isolated compile
(`compile_to_gimple(..., do_imports=False)` on `calendar.py`'s own
source, then `gcc -fgimple -fsyntax-only` on the result): **0 errors**
— both the "non-trivial conversion"/"type mismatch" errors this doc
originally reported AND the trailing `_CLIDemoCalendar___init__` arity
error are gone. `calendar.py`'s OWN code now compiles cleanly in
isolation.

`python3 mojo.py build .../Lib/calendar.py` (the full whole-program,
`do_imports=True` build) still fails — but now entirely due to
UNRELATED, pre-existing issues in OTHER, transitively-imported files
(`os.py`'s `relpath`-ambiguity refusal, several distinct pre-existing
`operator.py` errors) that have nothing to do with calendar.py's own
code or this bug. Not investigated further (out of scope for this
comprehension-return-type fix).

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, but the failure has moved and is NOT actually inside
the coroutine-codegen path anymore. Re-diagnosed from scratch against
current master (`2b0c4c5`) via `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/calendar.py`. The old 2026-07-30 error
("`y` was not declared" in a generator .cpp) no longer reproduces —
`Calendar.itermonthdates`/`itermonthdays`/etc. (calendar.py's own
generator methods) now compile cleanly through the C++20-coroutine path.

The CURRENT failure is a plain-C `.ci`/GIMPLE-stage error, in
NON-generator methods that merely *consume* a generator:

```
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: type mismatch in binary expression
[... same pair repeated at :291, :299, :309, :319, :328, once per each of
Calendar's 7 subclasses (TextCalendar, HTMLCalendar,
LocaleTextCalendar, LocaleHTMLCalendar, _CLIDemoCalendar,
_CLIDemoLocaleCalendar) that inherit the affected methods ...]
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:904:3: error: too few arguments to function '_CLIDemoCalendar___init__'; expected 4, have 3
```

**Root cause (confirmed by reading the generated `calendar.ci`):**
`Calendar.monthdatescalendar`/`monthdays2calendar`/`monthdayscalendar`/
`yeardatescalendar`/`yeardays2calendar`/`yeardayscalendar` each look like:

```python
def monthdatescalendar(self, year, month):
    dates = list(self.itermonthdates(year, month))
    return [ dates[i:i+7] for i in range(0, len(dates), 7) ]
```

`dates = list(self.itermonthdates(...))` (consuming the real generator)
lowers correctly into an inline drive-loop
(`_mojogen_Calendar_itermonthdates_start/_resume/_value/_destroy`) that
builds a real `MojoList *`. The problem is the method's OWN declared
return type: `_infer_return_type`/`_collect_return_types` (used to
populate `func_return_types` for unannotated methods, gimple_codegen.py's
Pass 2b) calls `_quick_type(node.value)` on the `return [...]` statement's
value — a `Comprehension(kind="list", ...)` AST node — but `_quick_type`
has **no `isinstance(node, Comprehension)` case at all**, so it silently
falls through to the final default and returns `'int64_t'`. The method's
real body (correctly, via the separate `_lower_Comprehension`/emission-
time lowering) builds and returns an actual `MojoList *`, so the
generated C has a forward declaration/return type of `int64_t` while the
body constructs and casts a `MojoList *` through a pointer-to-int cast
to satisfy it — `gcc -fgimple` correctly rejects the resulting cast/
comparison shapes as "non-trivial conversion"/"type mismatch".

**This is NOT a generator-codegen-path bug** — `_quick_type` is the
general-purpose, project-wide return/expression-type estimator used for
ALL functions (generator-adjacent or not); any function whose ONLY
`return` statement is a bare list/dict/set comprehension is affected.
It surfaces here specifically because calendar.py's own idiom style is
"consume a generator into a list, then return a comprehension over
slices of it" for six sibling methods in a row. Documented in detail,
with root cause and fix-scope notes, in
`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md` — this
file is one of the confirming instances for that hard bug (recurs
identically in at least `Lib/glob.py`; see that file's own bug doc).
Not fixed here (see that hard-bug doc for why: this is
`_quick_type`, the same broad, high-blast-radius inference surface this
project's existing guidance says to change only with great care).

The trailing `_CLIDemoCalendar___init__` arity error (line 904) is a
distinct, apparently unrelated pre-existing issue not investigated
further here (out of scope for this generator-codegen cluster).

## Build error (current, 2026-08-06)

```
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: type mismatch in binary expression
```

Source file: /Users/mrs/net/Python-3.14.6/Lib/calendar.py
