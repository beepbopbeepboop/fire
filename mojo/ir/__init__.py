"""mojo.ir -- the typed IR for the gimple backend.

Read doc/GIR.md first.  The short version:

  types.py    one `Type` object per C type (interned).  The ONLY place that
              knows which conversions GIMPLE allows without a cast.
  instr.py    `Ex` (operand / expression), `Instr` (one statement),
              `Function`, `Module`.
  verify.py   type-checks a `Module` and returns `Finding`s.
  reader.py   TRANSITIONAL: builds a `Module` from emitted `.ci` text, so the
              verifier can check today's string-emitting backend.

types.py / instr.py / verify.py are written in the self-hostable subset
(plain classes, annotated fields, no closures, no regex, no tuple unpacking)
because the backend will import them.  reader.py is a tool-side module and
must never be imported by the compiler.
"""
