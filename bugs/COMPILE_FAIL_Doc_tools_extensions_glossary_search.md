# COMPILE_FAIL: Doc/tools/extensions/glossary_search.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py`

## Status (updated 2026-08-06)

Root-caused; not fixed — instance of the tracked dynamic-attribute hard
bug (bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md, task
#136). Not attempted independently here.

```
error: request for member 'glossary_terms' in something not a structure or union
```
at:
```python
if hasattr(app.env, 'glossary_terms'):
    terms = app.env.glossary_terms
else:
    terms = app.env.glossary_terms = {}
```

## Root cause

`app` is a `sphinx.application.Sphinx` instance and `app.env` a
`sphinx.environment.BuildEnvironment` — both from the third-party
`sphinx` package, which this compiler has no model of at all (an
external documentation-build tool, not part of Python's stdlib). This
codegen models attribute access as a real C struct-field read/write,
requiring a known struct layout — `app.env`'s type can't be resolved, so
it falls back to a generic opaque representation with no attribute
storage.

This is exactly the SAME class of gap as the hard bug's own Sub-case A/B
examples (`cls.__slot_names__` on an opaque `cls` param) — except here
the "opaque object" is a genuine third-party library instance rather
than an unresolved user parameter, and the WHOLE POINT of this code is
Sphinx's own documented extension convention: stash arbitrary custom
state on `app.env` via `hasattr(app.env, name)` / dynamic-attribute
assignment, since `BuildEnvironment` is explicitly designed to be
extended this way by any Sphinx extension.

Not independently fixable without the same generic dynamic-attribute-
storage runtime work already planned in the hard-bug doc — added as a
confirmed real-world instance there. No further action here; tracked via
task #136.
