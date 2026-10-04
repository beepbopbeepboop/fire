# `_refuse_dropped_companion` searches for a prefix nothing emits, so it can never fire

**State: OPEN, measured, not fixed.** Found 2026-10-02 while working
`bugs/CODEGEN_nested_generator_yield_type_and_delegation.md`, whose shape
reaches it. Not that doc's subject and not fixed by it.

## What I ran

```python
import sys; sys.path.insert(0, '.')
import gimple_codegen as G, re
res, gen = G._run_pipeline(open('.tmp/cases/l_nestedgen_plain.py').read(),
                           do_imports=False, filename='p.py')
cpp = getattr(gen, 'generated_cpp', '') or ''
print('_mojogen_render_start' in res, '_mojogen_render_start' in cpp)
print('__mojogen_render_start' in res)
```

with `.tmp/cases/l_nestedgen_plain.py` being

```python
def build(n):
    def render():
        yield ''
        yield 'x'
    return render

def main():
    for s in build(1)():
        print(s)
main()
```

## What I see

The generated `.ci` and the companion `.cpp` agree on the symbol names, and
the prefix is ONE underscore:

```
_mojogen_render_destroy   _mojogen_render_resume
_mojogen_render_start     _mojogen_render_value
```

`gimple_codegen._refuse_dropped_companion` (line 5731) tests
`'__mojogen_' not in code` and scans with
`r'__mojogen_[A-Za-z0-9_]+_(?:start|resume|value|destroy)\b'` — two
underscores. So for every symbol the pipeline actually emits the guard is
false, and `compile_to_gimple` returns a `.ci` whose `extern` declarations
have no definition anywhere.

The `.ci` side, verbatim:

```c
extern MojoGenerator *_mojogen_render_start (void);
extern _Bool _mojogen_render_resume (MojoGenerator *);
extern char * _mojogen_render_value (MojoGenerator *);
extern void _mojogen_render_destroy (MojoGenerator *);
...
static void * _funcptr_render = (void *)_mojogen_render_start;
```

and the link says so, on Darwin's leading-underscore mangling:

```
Undefined symbols for architecture arm64:
  "__mojogen_render_start", referenced from:
      __funcptr_render in cc77Nh3O.o
ld: symbol(s) not found for architecture arm64
```

## Why the docstring's own failure mode is exactly what happens

Its comment says the point of the guard is that "the cost was a link error
tens of thousands of lines away from the cause", and names
`_mojo_gen_<mod>_<fn>_{start,resume}` undefined during `fire1`. Note the
comment itself spells it `_mojo_gen_`, a THIRD spelling, beside the two in
the code. Whatever the prefix was when the guard was written, the emitters
moved (`mojo/backend_gimple/cpp_async.py:543` and `:588` build
`f"_mojogen_{...}"`) and the guard did not follow, so the condition has been
unreachable ever since. The check is the only thing standing between a
discarded companion and that link error, and it is the check that was added
to stop exactly this.

## Blast radius, and why it was not simply fixed here

The guard is called from ONE place — `compile_to_gimple` (line 5727) — and
`compile_to_gimple_cached` calls that, so everything downstream of either is
in scope. Measured, cheap:

* `fire.py`'s real build path (fire.py:700) already routes through
  `compile_to_gimple_with_cpp` whenever
  `module_may_have_supported_generator` is true, and through
  `compile_to_gimple_cached` otherwise — where no companion symbols exist, so
  a live guard would not fire. That path looks unaffected.
* `test_gimple_generator_runner.py` uses `compile_to_gimple_with_cpp`
  throughout; `gimplerunner` is green today, so no case in it emits these
  symbols through the discarding entry point.
* `compile_stdlib.py` cannot be affected at all: of the 610 files
  `compile_stdlib.find_mojo_files` returns, **zero** contain a `yield`
  (measured with `re.search(r'^\s*yield\b', src, re.M)` over every file), so
  no stdlib module can reach either generator backend.
* NOT measured, and this is the blocker: `fire.py --dump-full` (fire.py:1162)
  and the self-hosted compiled path (fire.py:1240) call
  `compile_to_gimple` directly, with NO companion and NO link — they only
  WRITE the `.ci`. Today they succeed and write a `.ci` full of undefined
  externs; with a live guard they would print "Error generating --dump-full"
  and set `any_failed = True`. That is `native-dumpfull` and
  `bootstrap-stage1-dumps`, both of which compile this repository's own
  closure, and whether that closure contains a supported generator is
  exactly the question that needs a `./mojoc` / stage1 build to answer.

Fixing the prefix blind trades a silent-wrong artifact for a possibly-red
`bootstrap-stage1-dumps`, with no way for a light worker to tell which.

## Next step

1. Fix the match so it cannot go stale on a rename: intersect the symbol
   names the `.ci` REFERENCES with the ones the companion `.cpp` DEFINES,
   rather than testing a hard-coded prefix on one side. Both sides then move
   together, which is the property the current one-liner lacks:

   ```python
   _sym = r'_*mojogen_[A-Za-z0-9_]+_(?:start|resume|value|destroy)\b'
   missing = sorted(set(re.findall(_sym, code)) & set(re.findall(_sym, cpp)))
   if not missing:
       return
   raise RuntimeError(... f"{len(missing)} C++20-coroutine generator symbol(s) "
                        f"({', '.join(missing[:6])}...) whose definitions are in "
                        "a companion .cpp that compile_to_gimple cannot return ...")
   ```

2. Then measure it on the two jobs in the blast radius above, in this order:
   `bootstrap-stage1-dumps` (the one that can newly go red) and
   `native-dumpfull`. If `bootstrap-stage1-dumps` reports fewer items dumped
   than at HEAD, this repository's own closure does contain a supported
   generator and the guard's refusal is the correct answer for that path too —
   in which case say so in the doc and leave it live.

Regression, once landed: `test_gimple.py`'s `test_raises` helper (line 129)
on the 12-line fixture above, asserting the message names
`_mojogen_render_start`. That test fails on the parent commit because
`compile_to_gimple` SUCCEEDS.
