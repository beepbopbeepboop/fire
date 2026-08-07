# CODEGEN_generator_function: Lib/test/test_finalization.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`), now precisely root-caused.

**Classification: `bugs/hard/CODEGEN_generator_classmethod_first_param_
must_be_self.md`** (new hard-bug doc, this file is its sole/primary
occurrence, but with an unusually large 18x blast radius from one root
cause — see the doc). The base method:
```python
@classmethod
@contextlib.contextmanager
def test(cls):
    ...
    yield
    ...
```
is a `@classmethod` generator (first parameter `cls`, not `self`) —
`_gen_cpp_generator_unit`'s method-eligibility check does a literal
string-equality check against `'self'` and refuses ANY other first-
parameter name outright. Because `test` is inherited by 17 different
subclasses in this file (`Simple`, `SimpleBase`, `NonGC`,
`NonGCResurrector`, `NonGCSimpleBase`, `Legacy`, `LegacyBase`,
`LegacyResurrector`, `LegacySelfCycle`, `SimpleChained`,
`SimpleResurrector`, `SimpleSelfCycle`, `SuicidalChained`,
`SuicidalSelfCycle`, `SelfCycleResurrector`, `ChainedResurrector`,
`Simple`) plus the module-level standalone `test`, ONE root cause
produces 18 separate refusal messages.

Not fixed here — see the hard-bug doc's "What a fix needs" section for
why a full fix needs more than relaxing the string check (though a
narrower fix scoped to THIS file's specific case — where `test`'s body
never actually references `cls` — looks plausible; not attempted in
this pass per this task's preference for classification over
speculative fixes to the less-mature coroutine codegen path).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_finalization.py
