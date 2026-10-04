# CODEGEN: a comprehension's `for` target becomes a LOCAL of the enclosing function, shadowing a module global for the rest of the body

**Area:** CODEGEN (`gimple_codegen.py` / `mojo/backend_gimple/*`, the
comprehension lowering). Found 2026-10-04 on `work/bugs5-1` while fixing the
interpreter half of the same defect — the interpreter's fix is
`myinterpreter.py::eval_Comprehension`, and the case that pins it is
`test_interp_oracle.py`'s
`a_comprehension_does_not_shadow_a_module_constant`.

**Status: NOT FIXED, reproduced twice on two engines, and narrowed to four
lines of generated C.** A silent wrong answer: the program builds, links, runs,
exits 0, and prints a number that is not the one the source says.

## What I ran

```console
$ cat .tmp/ci2.mojo
G = 5

def f(rows):
    var out = [G for G in rows]
    return G + out[0]

def main():
    print(f([1, 2]))
    return 0

$ python3 fire.py run .tmp/ci2.mojo      # the interpreter, after its fix
6
$ python3 fire.py --jit .tmp/ci2.mojo
3
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build -o .tmp/ci2.exe .tmp/ci2.mojo && .tmp/ci2.exe
3
$ sed 's/var //' .tmp/ci2.mojo > .tmp/ci2.py && printf '\nmain()\n' >> .tmp/ci2.py && python3 .tmp/ci2.py
6
```

Both compiled engines answer **3** where CPython answers **6**, and the JIT
answer is not a cache artefact — a plain `fire.py build` and running the
binary gives the same number.

**It is the trailing `G`, not `out[0]`.** `3` is `rows`' last element (2) plus
`out[0]` (1), so the read after the comprehension saw the comprehension's own
target. CPython's rule is that a comprehension is its own scope, so that `G` is
still the module's 5 and the answer is `5 + 1`.

**The formal backends are right.** Both arm64 and x86_64 print 6, and
`test_formal_globals.py`'s
`a_comprehension_target_does_not_shadow_a_module_constant` checks exactly this
program against both images (its own comment records that the interpreter was
the third engine that had to be removed and has now been restored). They are
right because they desugar the comprehension rather than inlining it — which is
the difference between this bug and the interpreter's, and why three of the
four engines in this tree can be right about the same source.

## The generated C, which is the whole narrowing

`compile_to_gimple(src, do_imports=False, filename='ci2.mojo')`:

```c
int64_t f_815e8f (MojoList * rows)
{
  MojoList * _t1;
  int64_t G;              /* <-- a LOCAL named G, from the comprehension target */
  ...
  MojoList * out;
  ...
bb_4:
  _t5 = mojo_list_get_int (rows, _t3);
  G = (int64_t) _t5;      /* the target's store */
  _t6 = G;
  mojo_list_append_int (_t1, _t6);
  goto bb_5;
...
bb_6:
  out = _t1;
  mojo_cleanup_push_list (out);
#line 5 "ci2.mojo"
  _t10 = mojo_list_get_int (out, _t9);
#line 5 "ci2.mojo"
  _t11 = G + _t10;        /* `return G + out[0]` reads the LOCAL, not the global */
  ...
  return _t11;
}
```

The module global is right there and correct — `.G = 5` in the `_root_globals`
struct initialiser, and `root__mojo_global_get_G()` returning `_root_globals.G`
— and `f_815e8f` never calls it. The comprehension's target was allocated as an
ordinary local **of the enclosing function, under its own source name**, so it
shadows every other read of that name in the same body for the rest of the
function.

So the defect is not "a local is allocated" (a comprehension target needs
storage somewhere) but **"it is allocated under a name the enclosing body also
uses"**. Two spellings of the same fix, and the second is the one that cannot
regress:

1. give the target a generated name that cannot collide (`_comp_target_1`, or
   whatever the lowering's temp-naming already produces for a value that has no
   source name), so a shadowing read is impossible by construction; or
2. keep the source name but make the enclosing body's read of that name resolve
   to the global — which is what the desugaring path does by not inlining.

Option 1 is the local fix and option 2 is the structural one. Worth saying
which is which, because option 1 alone leaves the *inverse* bug reachable: a
comprehension whose target name matches a local the body reads AFTER the
comprehension would then read the local's value where Python reads the
comprehension's — and `test_runtime_diff.py`'s existing
`comprehension_target_shadows_an_enclosing_local` case is the shape that would
notice.

## What is already pinned, and where a fix should land its test

* `test_interp_oracle.py::a_comprehension_does_not_shadow_a_module_constant` —
  interpreter vs CPython, 6 vs 6. Green now; it is the anti-rot for the
  interpreter half.
* `test_formal_globals.py::a_comprehension_target_does_not_shadow_a_module_constant`
  — arm64 + x86_64 + the interpreter, 6 on all three.
* **Nothing pins the compiled path.** That is why this is filed rather than
  fixed: a fix here lands in `mojo/backend_gimple/`, which owes a full
  `make gate`, and the case that would catch it belongs in
  `test_runtime_diff.py` — where it was written and then REMOVED, because until
  the compiled half is fixed an interpreter-vs-JIT case sits red and a red case
  in a suite nobody is working on is indistinguishable from a broken suite.

## Exact next step

1. Find the comprehension lowering. `_lower_list_literal` and its set/dict
   siblings are in `mojo/backend_gimple/emit_exprs.py`; the target's slot
   allocation is whatever emits the `int64_t G;` declaration above — grep the
   generated C's shape (`<type> <target>;` in a function's prologue) back to the
   emitter, or start from `ast_rewriter.py`, which `test_gimple.py` exercises
   directly and which is where a comprehension is most likely desugared before
   emission.
2. Change the allocation to a generated name (option 1 above), or desugar
   instead of inlining (option 2).
3. Put the case back into `test_runtime_diff.py`'s `BUILTIN_PROGRAMS` **and**
   `CPYTHON_COMPARABLE`, verbatim as it was written — the source is in this
   doc's first code block and in `test_interp_oracle.py` under the same name,
   so the two suites can be compared line for line.
4. Run `python3 tools/suite.py gimple gimplerunner gimplegenerators runner`
   and the `check` bucket: a generated-C template change is the class of edit
   that can be green on every single-branch test and wrong in the RESULT (see
   `bugs/MERGE_bugs4_gimplerunner_four_remaining.md`'s closing paragraph, which
   is two instances of it from one merge).
