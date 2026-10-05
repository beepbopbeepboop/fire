# FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None

**Area:** FORMAL, both backends — the answer comes from
`formal/model.py`'s `ValueKinds._value_kind` ("`kind_of(value)`, or `INT_KIND`
when it is unclassified and is not a container") together with an epilogue that
does not write the return register (`formal/arm64_codegen.py::_emit_epilogue`
emits the scratch teardown, the frame restore and `RET`, and nothing else), so
nothing in the pair knows the callee returns nothing.
**Status: PARTIAL, and the half that is OBSERVABLE is FIXED (2026-10-04,
`formal/model.py` + both emitters).** `print` of a call to a function of this
module that returns nothing — and of a local every one of whose bindings is such
a call — is now REFUSED on both architectures, with a message that names the
callee, says what CPython answers (`None`) and says what this path would have
printed instead. §0b is what landed and §0b's measurement is the one §4 step 1
was waiting for: **the refusal reaches 0 call sites in 379 files** (§0a counted
510, all of them at positions where nothing observes the value), so the two
gate counts §4 asked for are no longer the decisive measurement — the position
the rule is asked at is.
**What is left is §0b's "What is still not fixed": the positions where nothing
OBSERVES the value (an operand, an argument, a returned, an assigned-then-never-
read local), which need either a liveness pass or direction (b) below.**

## 0c. What is left, measured per POSITION (2026-10-04, `work/formal28-1`) —
## and the one bucket that decides nothing is 62 sites in one file the gate
## compiles

§0b landed the OBSERVATION position and §"What is still not fixed" item 1 names
the rest as one question: *"the positions where nothing observes the value — an
operand, an argument, a `return`, an assigned-and-never-read local — each of
which needs a liveness pass this path does not have."* That is one bucket count
(`assigned 203`, `operand 142`, `returned 81`, `argument of a call 78`) standing
in for four SEPARATE decisions, and a position count does not decide anything:
what a refusal asked at a position costs is decided by which files it lands in.

**So `tools/formal_returnless_census.py` now reports the cross-tab**
(`position_file_table`, over rows of `(same_file, path, position)` and nothing
else), and it answers the `returned` bucket:

```console
$ python3 tools/memslot.py --gb 8 --label rlc -- \
      python3 tools/formal_returnless_census.py --rows 0
the same-file candidates by where the value goes, which is not one claim:
   assigned                   201  WEAKEST: …
   operand of `==`             83
   argument of a call          77  the doc's §0 shape (one argument too deep)
   returned                    76  the callee's own result is None — the clearest divergence, and CPython's
   …
the `returned` sites, by file — what a refusal asked HERE would reach:
      62  formal/hostmods/argparse.mojo
       5  ../new-modular/Mojo/stdlib/std/simd.mojo
       3  ../new-modular/Mojo/stdlib/std/builtin/_format_float.mojo
       3  ../new-modular/Mojo/stdlib/std/math/math.mojo
       2  formal/hostmods/posixpath.mojo
       1  ../new-modular/Mojo/stdlib/std/python/python.mojo
```

**62 of the 76 are in `formal/hostmods/argparse.mojo`**, whose `_err`, `_toobig`,
`_putset`, `_nl` and `_wrap*` helpers print and return nothing, and whose
`return _err(msg)` shape is ordinary Python. That file is a HOST MODULE the gate
compiles — `test_formal_argparse.py` PASS=9 and `test_formal_hostmods_census.py`
64/64 rows build — so a `None` refusal asked at the `returned` position refuses
it. That is this document's own standard applied to its own best candidate
(§0a's "a refusal that fires on 57 files without the full suite behind it is a
worse risk than the wrong answer it replaces"), and it is why §0b's measured-zero
at the OBSERVATION position and this one are different answers rather than the
same answer measured twice.

**The other three buckets are the same shape and cheaper:** `argument of a call`
is 75 of 77 in `argparse.mojo`, `operand of ==` is 82 of 83, `assigned` is 186 of
201. So of the four positions item 1 names, **none is affordable**, and the
liveness pass item 1 asks for would not change that — it can only shrink
`assigned`, which is the one bucket already marked WEAKEST, and the two largest
buckets are `==` and `argument of a call`, where CPython raises `TypeError` rather
than answering (so a refusal there replaces a silent wrong answer with a refusal
of a program CPython also refuses, which item 1 already calls "a decision about
what a wrong-but-computable operand should say, not a patch").

**What this leaves, and it is item 2 and nothing else.** Direction (b),
representing `None`, is the only direction that makes all four positions correct
rather than only the observed one, and it remains a change to the value model,
both emitters' return paths and `lib/ProofLib.lean` at once. Item 3 (a
deterministic epilogue word) still alters every proof generator's step lemma for
the epilogue and is still not CPython's answer.

**And one correction to the instrument, because a census whose numbers move with
the worktree's scratch is not a measurement.** §0a and this section both quoted
the census over `DEFAULT_PATHS`, which includes the repository ROOT — so the walk
descended into `.tmp/<some test's tmpdir>/` and counted `.mojo` files a test had
written an hour earlier. `.tmp`, `.git` and `__pycache__` are now pruned in
place. Measured, same command: definitions 5 586 → **5 340**, candidate sites 510
(§0a) / 503 (2026-10-04 pre-fix) → **502**, files with a candidate 22 → **18**.
§0a's numbers are therefore an OVERCOUNT of that much, and the `returned` bucket's
62-of-76 share is the same figure either way — `argparse.mojo` is a tracked
source file, not scratch.

**The tests.** `test_formal_returnless_census.py`'s
`a_bucket_is_reported_BY_FILE_and_that_is_what_decides_it` is the cross-tab on
two sources small enough to read — two files, two positions, and each bucket
names the file its sites are in — because a report whose headline is a
cross-tab and whose unit test asserts only the row count is a report whose
second half nothing checks. No Lean, no build.

**Re-measured 2026-10-03 (`work/formal18-1`): §2's objection to direction (a) —
"the blast radius is unmeasured" — is now measured, and it came out the other
way. §0's census said "much narrower than §2 feared"; §0a says ten times wider,
because §0's number was a floor produced by name-keying and by counting one
position (`argument of a call`) out of seven. §2's conclusion is unchanged and
its reason is now a measurement rather than an argument — and §0b is what shows
the objection and the measurement are both about the wrong POSITION.**

Found 2026-10-03 on `work/formal17-fuzz-continue-a` by `tools/formal_fuzz.py`,
on the `strings` mix, seeds 0-3 — and, worth saying because it is unusual,
**not from the generator**: the generated program agreed on everything except a
`print` of one call's result, and the disagreement became visible only after the
minimiser deleted a `return` statement from a helper (`shrink` removes
statements, and a helper whose body is left with no `return` is a program with a
different defect in it). The reduced program is the minimal one and it is below.
The full program and the reduced program are both in
`.tmp/fz/sweep/strings/findings.json` in the worktree it was found in.

---

## 0c. §0a's NUMBER was wrong, and the correction unblocks the decision §2
## refused to make (2026-10-04, `tools/formal_returnless_census.py`)

**§0a's 510 candidate sites were 456 phantom rows from one `and`.** The census's
rule is the doc's own: a candidate is a site whose callee has **neither** a
value-returning `return` **nor** a declared return type, so either half keeps it
out, and `_declares_a_return`'s docstring says so in those words. The reader was
a conjunction:

```python
decided = {name: defs[0][2] and defs[0][3] for name, defs in index.items() …}
```

A function that RETURNS a value without DECLARING one is the commonest shape in
this corpus, so it needed both halves false at once and that never happened for
an undeclared function. `formal/hostmods/argparse.mojo`'s `_fld`, `_cp`,
`_alpha_index` and `_name_ptr` each end in `return p` / `return u + n` /
`return k` and none of them declares a type — and `collect()` had all four right
(`returns_a_value=True`), so the conjunction was the only thing wrong. Same
command, before and after:

```console
$ python3 tools/memslot.py --gb 8 --label rlc -- \
      python3 tools/formal_returnless_census.py
                                     before      after
   same-file candidate sites          507         17
   files with one                     22           7
   formal/hostmods/argparse.mojo      456           0
   callee returns something         7998        8491
```

**And the 17 are all in the stdlib**, which is the whole of what §2 and §4 step
1 needed and did not have: `math.mojo` 6, `simd.mojo` 1, `sys/_libc_errno.mojo`
2, `itertools.mojo` 2, `builtin/_format_float.mojo` 3, `python/python.mojo` 1,
`runtime/_asyncrt.mojo` 2, split 8 `returned` / 3 `MemberExpr` / 2
`argument of a call` / 2 `assigned` / 2 `a subscript index`. Every one of them is
an `out`-PARAMETER helper — `def _sqrt_nvvm(x: SIMD, out res: …)` and
`def _errno_ptr(out result: Pointer[…])` — which is a real return-nothing
function and not a second phantom.

**What this changes, and it is the doc's decision rather than its diagnosis.**
§2 rejected direction (a) — "refuse where the value is OBSERVED", extended to
every consuming position — on the measurement "with 510 candidate sites, 456 of
them in one host module that builds today, direction (a) as §2 states it is
predicted to regress the build, and §4 step 4 would answer (b)". **The
prediction rested on the 456, and there are none.** A refusal asked at every
consuming position costs **zero** builds in this repository and **zero** in
`formal/hostmods/`, which is every file
`test_formal_hostmods_census.py` (72/72 rows) and `test_formal_argparse.py`
(PASS=9) build. What is left is the one measurement §2 named and that a light
worker cannot take: `build_stdlib_dylib.py`'s `skip <module>:` count, over at
most those seven modules — and §0b's own measurement says most of the stdlib is
already past the gate for other reasons
(`FORMAL_a_bare_call_to_a_template_…`'s 163-file row), so the marginal increase
may well be 0 as well.

**And §4 step 0 — "re-do §0's census keyed on the resolved DEFINITION" — is now
answered by a census that is right.** Its `name_defs` join, its UNDECIDED bucket
(98 names, `__abs__`, `__await__`, `__enter__` and the rest of the operator
table) and its generator/coroutine exclusion were all correct; the only wrong
thing was the conjunction above, and it was wrong in the direction that invents
rows. §4 step 0's ~~strikethrough~~ can stay: the work landed, and this is what
it landed *to*.

**Two halves of the rule now have a case each**, and that is why the `and`
survived: the one case for the declared half spelled a function that returns AND
declares, so every copy of the comprehension (`tools/formal_returnless_census.py`,
its own `main()`, and `test_formal_returnless_census.py`'s helper — three) agreed
on every case the tests had. There is one reader now (`decided_names`) and two
new cases ask each half alone; both fail on the old conjunction
(`test_a_return_with_no_declared_type_is_not_a_candidate`,
`test_a_declared_type_with_no_return_is_not_a_candidate_either`).

## 0b. What landed (2026-10-04): the observation, refused — and the measurement §4 step 1 was waiting for

**The refusal, on BOTH architectures, for both shapes.**

```console
$ python3 tools/memslot.py --gb 8 --label rn -- python3 fire.py build --formal \
      --no-prove -o .tmp/rn/x .tmp/rn/p.mojo
build: print() is asked to render the value of g(…), and g returns nothing:
CPython evaluates that call to `None` and prints `None`, and a value on this
path is one 64-bit word with no way to say `no value` — the epilogue writes no
return register, so the word printed here would be whatever g's last instruction
left there, which is a number nothing in the source wrote (measured on BOTH
architectures from this source: CPython printed `None` where this path printed
`0`). Refused rather than emitted, because a plausible number is worse than a
refusal. Give g a `return`, or do not use its value
```

`--backend=x86_64` gives the same sentence (the refusal is one f-string in
`formal/model.py`, asked from both emitters — §4 step 3's requirement, and the
reason it is not two copies of the rule). `v = g(1, 2); print(v)` is refused
with the same words, and the message names `g` rather than `v`, because the
callee is what the reader has to change.

### The measurement, and why it is the answer to §4 step 1 rather than a substitute for it

§4 step 1 wanted `compile_stdlib.py`'s `U` count and
`build_stdlib_dylib.py`'s `skip <module>:` count, as a PROXY for "will a refusal
asked at every consumed value regress the build". §0a answered the question
behind the proxy and the answer was 510 sites, which is why §2(a) looked
unaffordable. **The proxy is the wrong question, because it counts positions
rather than divergences**: a local assigned a return-less call and never read is
not an observable divergence at all — §0a says so of its own 203 `assigned` rows
— while §1's shape is observable the moment it is printed.

So the rule is asked at the position where a value this path cannot carry
becomes TEXT (`_print_call` in each emitter, the one choke point each has for a
printed operand), and over this repository, `formal/hostmods/` and all 252 files
of `../new-modular/Mojo/stdlib/std` — **379 files parsed, 0 sites**:

| the refusal's own rule, at an observation position | sites |
|---|---:|
| a direct `print(f(…))` / `printf(fmt, f(…))` where `f` returns nothing and declares no return type | **0** |
| a `print(x)` where `x`'s every binding in the function is such a call | **0** |
| …and the same walk with the "declares a return type" half switched OFF (i.e. what the rule would reach if a declaration did not settle it) | 1 |

and the one is `scripts/stage2_mojo_interpreter.mojo:154`,
`print(c_code)` after `c_code = stage2_compile(mojo_file)` — which declares
`-> AnyType` and returns `None` on every branch, so the declared-type half of the
rule (`model.fn_declares_a_return`, delegating to the existing
`declared_returns_a_value`) is what keeps it out. **A declared return type is out
of scope by the doc's own rule and it costs exactly one known site**, which is
the trade §0a's census could not see because it counted all seven positions.

**Two real builds behind the syntactic census**, because a census is a parse and
a walk and this rule runs in the emitters:

| what | verdict |
|---|---|
| `python3 test_formal_hostmods_census.py` — every `formal/hostmods` module as a translation unit, both backends | **64/64 rows build** (that is §0a's `argparse.mojo` 456 rows and `re.mojo`'s 5, as BUILDS rather than as census rows) |
| `python3 test_formal_argparse.py` | **PASS=9 FAIL=0** — `argparse.mojo` itself, built and run |
| `python3 test_formal_run.py` | PASS=995 FAIL=**0** on the tree this table was measured on. It carried a red for a while, and it was not this bug: a one-field mutator's receiver hand-off read `node.target` off a `VarDecl` and raised `AttributeError`, so the returned-frame refusal for that shape never printed. That collector has since been superseded by `_collect_one_field_receiver_rebinds`, which reads a `VarDecl`'s own `name` — `formal/model.py`'s single reader of "is this call a frame" is what it asks now, so there is no second place that can disagree — and `test_formal_run.py`'s `one_field_mutator_that_also_returns_a_frame_is_refused` is the row that pins the corrected behaviour |

### What is in the code, and why it is shaped this way

* **`formal/model.py::fn_returns_a_value` / `fn_declares_a_return` /
  `function_returns_a_value`** — the ONE reader of "does a call to this produce a
  value", in `model.py` because both emitters and the census have to agree and
  this file is where every other arch-free rule lives. `tools/formal_
  returnless_census.py`'s two private copies now DELEGATE to it (they were the
  same question in a second implementation, which is the defect the census's own
  header complains about in §0's name-keyed census), and the census's report is
  unchanged, so the measurement that sized this and the refusal that answers it
  cannot drift apart.
* **`ValueKinds._no_value_calls` + `_note_no_value_call` + `no_value_callee_of`**
  — the evidence for the `v = g(); print(v)` shape, in the same shape and with
  the same tombstone discipline as `_ctor_calls` and `_dict_inits` beside it,
  with ONE difference that the docstring states: a RETRACTION always wins and a
  claim never does, because the question is about the name as a whole ("every
  binding of `v` here is a call that produces no value") rather than about a
  site. `v = g(); v = 5; print(v)` prints 5, as CPython does, and that is a
  `CASES` row rather than a comment.
* **`ValueKinds.returns_a_value`** — the same fact about the function the table
  is built for, so the emitter can ask about a callee without a second reader.
* **`_callee_returns_value` in both emitters** — the hook, and it is a hook for
  the same reason `_callee_kind` is: the answer is about ANOTHER function, which
  is the emitter's question. Its default for a name that is not a function of
  this unit is True, the safe direction, so a linked module's export (no body
  here to read) changes nothing.
* **`tools/formal_sweep_causes.py` gets a row** for the new message
  (`a printed value that is not a value: the callee returns nothing`, keyed on
  the two clauses that state the fact), with its sample cut from
  `model.py`'s own f-string — the discipline `…_b10.md` §5.1 states, so a reword
  fails `test_refusal_taxonomy.py` instead of emptying a row into `other
  refusal`. 61 causes → 62, 229 checks → 231.

### What is still not fixed, and it is the whole of what is left

1. **The positions where nothing observes the value.** §0a's other buckets:
   203 `assigned`, 142 `operand`, 81 `returned`, 78 `argument of a call`. None of
   them is an observable divergence on its own, and a refusal at any of them is a
   refusal of ordinary code — `x = _fld(rec, 1)` is correct Python and CPython
   never complains. Asking there needs a LIVENESS pass to tell "assigned and
   never read" from "assigned and printed through a path this walk did not
   see", and this path has none. The operand case is a different defect again:
   CPython raises `TypeError` (`None + 1`), so refusing it replaces a silent
   wrong answer with a refusal of a program CPython also refuses — defensible,
   but it is a decision about what a wrong-but-computable operand should say, not
   a patch.
2. **Direction (b), representing `None`.** Unchanged by any of this: a
   distinguished word makes every USE correct rather than only the observed ones
   (`if g():` is right by accident today, `x is None` and `x == None` are not),
   and it is a change to the value model, both emitters' return paths, and
   `lib/ProofLib.lean` if the proofs are to keep checking. Still a project.
3. **The epilogue could at least be deterministic.** Both images answered `0`
   here and the doc is careful to say the word is "whatever the callee's last
   instruction left in the return register" — which is not guaranteed to be 0.
   Writing a defined value would remove that instability WITHOUT making it
   CPython's answer, so it is not in this change: it alters every proof
   generator's step lemma for the epilogue, and a wrong-but-stable 0 is still a
   wrong answer. Worth doing with (2), not instead of it.

### Reproducing §0b

```console
$ cat .tmp/rn/p.mojo
def g(a, b):
    w = 1

def main() -> Int32:
    print(g(1, 2))
    print(5)
    return 0
$ python3 tools/memslot.py --gb 8 --label rn -- python3 fire.py build --formal \
      --no-prove -o .tmp/rn/x .tmp/rn/p.mojo          # and --backend=x86_64
build: print() is asked to render the value of g(…), and g returns nothing: …
$ python3 -c 'exec(open(".tmp/rn/p.mojo").read().replace("-> Int32","")); main()'
None
5
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_value_model.py
formal value model: PASS=77 FAIL=0
```

The observation census of §0b's table is a scratch script in the worktree that
wrote this section (`.tmp/rn/obs_census.py`), and it is left there rather than
promoted for the reason `tools/formal_returnless_census.py`'s header gives for
its own limits: it is a parse and a walk over two shapes, and the rule it
measures now has its own reader in `formal/model.py` that a tool could call. That
tool is the obvious next thing to write and it is not this section's job.

## 0. The census §2 asked for, over the repository AND the stdlib

§4's step 1 is "measure `compile_stdlib.py`'s `FAILED: N (E expected, U
unexpected)` and `build_stdlib_dylib.py`'s `skip <module>:` count". Those are two
hours and two gigabytes and they belong to the integrator. What can be measured
without either is the question the refusal would actually be asked about: **how
many call sites in this corpus consume the value of a function that has no
`return`?** A census over `fire_compiler.Parser`'s own AST, over this worktree's
`*.mojo` and all 252 under `../new-modular/Mojo/stdlib/std`:

| | |
|---|---|
| files scanned | every `*.mojo` under `.` and `../new-modular/Mojo/stdlib/std` |
| functions whose body has no value-returning `return` | **1586** |
| call sites of one, from the same module | **682** |
| …of which the call's VALUE is consumed (it is an argument of another call) | **48**, in **4 files** |

**And every one of those 48 is an artefact of the census being NAME-keyed.**
The four files are `utils/coord.mojo`, `testing/prop/strategy/string_strategy.mojo`,
`itertools/itertools.mojo` and `_gpu/host/info.mojo`, and the call sites are
`self.value()`, `self._flatten()`, `self.normalize_target_arch()` — calls through
a receiver. `coord.mojo` declares `def value` **three times** (lines 59, 150,
395) and `info.mojo` declares `normalize_target_arch` twice (214, 224); at least
one definition of each RETURNS a value, and a `{name: has-no-return}` set cannot
tell which. That is the imprecision every by-name table in `formal/build.py`
already refuses to have ("a name whose definitions disagree about whether they
return a frame is absent from it"), and a census that repeats it answers a
question nobody asked.

**So: zero free-function call sites in the whole corpus consume the value of a
return-less function, and the only rows a syntactic census reports are
overloaded method names.** That is a strong result for direction (a) and it is
not sufficient on its own, for two reasons the reader should not skip:

  * **it is syntactic and same-module.** A call through a receiver, and a call
    into an IMPORTED module, are both outside it, and a method's value being
    consumed is exactly the case the doc's own §1 shape is (`self.value()` is
    how a `DType`-like accessor reads). The right census keys on the resolved
    DEFINITION (`formal/build.py`'s `_name_defs`), not on the name.
  * **`compile_stdlib.py`'s `U` count is a different question.** It counts files
    that stop compiling, and the four files above are inside the stdlib the gate
    builds. Whether each of them is a genuinely `None`-printing row is still the
    question §4's step 4 asks, and it is answerable only by the two counts.

The census's script is `.tmp/census_none.py` in the worktree that wrote this
section, and it is deliberately left in `.tmp` rather than promoted: a census
whose own imprecision is this large is not a tool, it is a measurement with a
footnote.

## 0a. §0's census, redone the way §4 asked for it: 510 candidate sites, not 48
##
## **SUPERSEDED IN ITS NUMBER by §0c — the 510 is 17, and the 456 are phantom.
## Read §0c first; this section is kept because its per-position counts are
## what §0c's 17 are read against.**

`bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`
§4 step 0 asks for the census keyed on the resolved DEFINITION, including calls
through a receiver and into an imported module, and calls §0's number "a floor,
not the count". **It is now a census, and it is a tool rather than a script left
in `.tmp`**: `tools/formal_returnless_census.py`, over this repository,
`formal/hostmods/` and all 252 files of `../new-modular/Mojo/stdlib/std`
(`python3 tools/memslot.py --gb 8 --label rlc -- python3
tools/formal_returnless_census.py`).

```console
$ python3 tools/formal_returnless_census.py
definitions: 6250   of which return nothing: 1827   structs (construction sites, excluded): 348
names: 3030   decided: 2931   undecided (definitions disagree): 99
call sites whose value is consumed, by what the callee is:
   callee returns something                8786
   callee's name is undecided              7499
   CANDIDATE (same file)                    510
   CANDIDATE (same name, other file)         37

files with at least one same-file candidate: 22   candidate sites: 510
     456  formal/hostmods/argparse.mojo
       7  bootstrap_test_stress.mojo
       6  ../new-modular/Mojo/stdlib/std/math/math.mojo
       6  ../new-modular/Mojo/stdlib/std/simd.mojo
       5  formal/hostmods/re.mojo
       …
```

Three numbers, and they change §2's recommendation:

| | §0's census | this one |
|---|---|---|
| functions that return nothing | 1586 | **1827** (and it excludes generators and coroutines, whose "return value" is the object) |
| call sites whose VALUE is consumed | **48**, in 4 files, all of them artefacts of name-keying | **510** same-file sites across **22 files**, plus 37 more where only the NAME matches |
| of those, the value is the function's own RESULT | not counted separately | **81** |
| …assigned to a local (the weakest kind: no liveness pass) | — | **203** |
| …passed as another call's argument (§0's shape) | 48 | **78** |
| …used as an operand (`==`, `<`, `>`, `+`, …) | — | **142** |

**§0c supersedes the number below — the 510 is 17 and the 456 are phantom — and
the conclusion this section draws from it does not survive.**

~~**The direction (a) refusal is not free, and §2's "a NEW refusal, and ordinary
Python" is right for a reason nobody had measured.**~~ 456 of the 510 are in ONE
file — `formal/hostmods/argparse.mojo`, whose `_fld`, `_cp`, `_alpha_index` and
`_name_ptr` are helpers that mutate and return nothing, and whose
`x = _fld(rec, 1)` / `return _cp(src)` shapes are exactly the case. That file is
a host module the gate compiles, so a refusal asked at every consumed value
would move `build_stdlib_dylib.py`'s `skip <module>:` count, which is the one
measurement CLAUDE.md says must not move silently.

**And the 203 `assigned` rows are the weakest, for a reason the instrument says
out loud**: nothing here does a liveness pass, so a local that is assigned a
return-less call and never read is not an observable divergence at all. The 81
`returned` rows are the ones with no such escape — CPython's answer there is
`None` and this path's is a word — and the 142 rows that use the value as an
OPERAND are a different defect again (CPython raises `TypeError`; this path
computes with a word).

**What the census deliberately does not do.** A same-name function in an
unrelated module is still a candidate, and a name whose definitions disagree
about whether they return is UNDECIDED and reported in its own bucket with both
sites — which is `formal/build.py`'s existing rule ("a name whose definitions
disagree about whether they return a frame is absent from it") and is what §0's
census got wrong. 99 of 3030 names are undecided here, and `add`, `chain`,
`gcd`, `count`, `__enter__` and `__exit__` are among them: a refusal cannot be
asked about those at all without resolving the name first.

So the census answered §4 step 0, and §0c is the correction to its arithmetic:
**the 510 is 17, the 456 in `argparse.mojo` are phantom, and every one of the 17
is in the stdlib.** The conclusion this section drew — that direction (a) is
predicted to regress the build and §4 step 4 would answer (b) — does not follow
from the corrected number: a refusal at every consuming position costs nothing in
this repository. What it now needs is only §4 step 1's stdlib half, over at most
seven modules, which is the integrator's `build_stdlib_dylib.py`.

## 1. What is wrong

A `def` with no `return` statement returns a WORD, and the word is printed as
an integer, where CPython returns and prints `None`.

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove -o .tmp/x .tmp/probe/p82.mojo
```

`p82.mojo`:

```mojo
def g(a, b):
    w = 1

def main() -> Int32:
    print(g(1, 2))
    print(5)
    return 0
```

| source | CPython 3.14 | arm64 | x86-64 |
|---|---|---|---|
| `print(g(1, 2))` | `None` | `0` | `0` |
| `print(5)` | `5` | `5` | `5` |

Both images build, run and exit 0. Two further shapes, measured:

* through a local — `v = g(1, 2); print(v)` prints `0` on both;
* after a call that returned something —

  ```mojo
  def noisy(a, b):
      print("side")
      return 77

  def quiet(a, b):
      w = 1

  def main() -> Int32:
      print(noisy(1, 2))
      print(quiet(3, 4))
      return 0
  ```

  prints `side / 77 / 0` on both images and `side / 77 / None` on CPython — so
  the value is NOT the caller's leftover (77 does not survive), and the honest
  description is "whatever the callee's last instruction left in the return
  register", which was 0 in every case measured here and is not guaranteed to
  be.

The `-> Int32` spelling is not the subject: `def quiet(a) -> Int32: w = 1;
return 0` agrees with CPython, and so does any function that RETURNS. The
subject is the function that falls off its end.

## 2. Why it is not a one-line fix

Two directions, and they are not equivalent in what they cost.

**(a) Refuse where the value is OBSERVED.** The value model already refuses
`print(x)` when `x` is an unclassified name ("print() cannot tell whether
IdentExpr is a string or a number on the formal … path, and guessing would
print an address as if it were text"), and `print(g(...))` is the same question
one call deeper: the callee states nothing, so the same guess follows. The
predicate exists and is already computed per function: `ValueKinds._returns` is
empty for a function with no `return`, and `ValueKinds.return_is_dict` /
`func_kind` are asked from it. So the refusal has a home.

**The blast radius is the reason this is not done here.** The refusal would fire
on `print`/`len`/`%s` of such a call — and on a stdlib or host-module file that
prints the result of a side-effecting helper, which is ordinary Python. That is
a NEW refusal, and the rule this repository holds itself to is that a
type-resolution or shape change must not move the `skip <module>:` count in
`stdlib-dylib` (§ "Two gate verdicts need judgement" in `CLAUDE.md`). Measuring
that means `compile_stdlib.py` and `build_stdlib_dylib.py`, which are the
integrator's jobs and not this worker's. **So the first step of any fix is to
run those two and record the two counts before touching a refusal.**

**(b) Represent `None`.** A distinguished word (a pointer to a `__DATA` cell, or
a tag like the type index already in this model) makes every *use* correct
rather than only the observed ones — `if g():` is already right by accident
(0 is falsy like `None`), `x is None` and `x == None` are not. That is a change
to the value model itself, to both emitters' return paths, and to the Lean
model in `lib/ProofLib.lean` if the proofs are to keep checking, which makes it
a project rather than a patch.

The recommendation is (a) with the counts measured first, because it is the
direction this path already takes everywhere else it cannot tell what a word
holds, and because a refusal is a sentence a reader can act on where `0` is not.

**§0c has now measured them, and the objection above is answered in (a)'s
favour**: the repository half is 0 candidate sites and the stdlib half is 17
sites in 7 modules, so the counts no longer stand between (a) and the code.

## 3. What this is NOT

* **Not a miscompile of a construct that has a representation.** `None` is
  genuinely absent from this value model — one 64-bit word per value, and a
  word has no way to say "no value" (`formal/model.py`'s "What a value is"
  section). This is the same class as `bugs/FORMAL_string_value_model.md`: the
  question is what the path does when the source says something the word cannot
  hold, and the answer must not be a plausible number.
* **Not the arm64/x86-64 divergence class.** Both machines answer `0`. It is
  reported here because it is a wrong answer, not because the two disagree.
* **Not a fuzzer artefact to be silenced.** It must NOT become a
  `KNOWN_DIVERGENCES` row: `tools/formal_fuzz.py`'s rule is that a row is a
  claim that the corpus still MEASURES the construct, and the corpus cannot
  produce a function with no `return` — `Gen.define_function` always emits one.
  A row nothing can trigger is a row that has stopped measuring. If the
  generator is ever taught to emit a helper with an empty body, this is the
  construct to add, and this doc is what it should point at.

## 4. The exact next step

0. ~~**Re-do §0's census keyed on the resolved DEFINITION.**~~ **DONE**
   (§0a): `tools/formal_returnless_census.py`, over the corpus, keyed on every
   definition of every name with a name UNDECIDED when its definitions disagree,
   counting all seven consuming positions rather than one, and excluding
   generators, coroutines and struct constructions. **510 same-file candidate
   sites in 22 files, 456 of them in `formal/hostmods/argparse.mojo`.** The
   difference from "direction (a) reaches four stdlib files" and "direction (a)
   reaches none" is 456 rows in a file the gate builds.
1. ~~**Measure `compile_stdlib.py`'s `FAILED: N` and `build_stdlib_dylib.py`'s
   `skip <module>:` count on master, and keep them.**~~ **NOT NEEDED, and §0b
   says why**: those counts are a PROXY for "does a refusal asked at every
   consumed value regress the build", and §0b measures the thing itself — the
   rule at the one position where a value this path cannot carry becomes TEXT
   reaches **0 sites in 379 files**, and the two real builds behind it
   (`test_formal_hostmods_census.py` 64/64 rows build, `test_formal_argparse.py`
   PASS=9) cover the 461 candidate rows §0a found in `formal/hostmods/`. A
   worker who wants the gate counts as well now has a change whose blast radius
   is knowable in advance, which is what step 1 was for.
2. ~~**Add to `formal/model.py` a refusal with the shape of
   `print_kind_refusal`…**~~ **DONE** (§0b): `model.returnless_value_refusal`,
   asked from `_print_call` in both emitters, naming the callee, saying CPython
   returns `None`, and saying what this path has instead — the wording discipline
   `string_concat_refusal` uses. **One reader of the rule**
   (`model.function_returns_a_value`) and one message, so the census and the
   refusal cannot answer "does this function return" differently.
3. ~~**Ask it from BOTH backends' single choke point for a call's value**~~ **DONE**
   (§0b): both emitters' `_print_call`, over `model.returnless_value_refusal`.
4. ~~**Re-run the two counts from step 1.**~~ **SUPERSEDED** by step 1 above.
5. ~~**The positions §0b's list of what is left names** — an operand, an
   argument, a `return`, an assigned-and-never-read local.~~ **MEASURED, per
   position, 2026-10-04 (§0c): none of the four is affordable.** `returned` is
   62 of 76 in `formal/hostmods/argparse.mojo`, `argument of a call` 75 of 77
   there, `operand of ==` 82 of 83 — and `argparse.mojo` is a host module the
   gate compiles, so a refusal at any of the three refuses it. The fourth,
   `assigned`, is the bucket a liveness pass would shrink, so the pass this step
   asked for does not change the answer.
6. **What is next, and it is direction (b)**: representing `None`, which makes
   every USE correct rather than only the observed one, and is a change to the
   value model, both emitters' return paths and `lib/ProofLib.lean` at once.
   Nothing else on this list is left that a build can decide.

## 5. A second thing this found, about the fuzzer itself

The disagreement was INVISIBLE in the generated program and appeared only after
`shrink` deleted a `return`. That is worth knowing as a property of the tool
rather than as a defect in it: the minimiser is allowed to leave constructs in a
reduced program that the original did not have, and `blame` then correctly
reports the disagreement as unexplained — because the explanation is a construct
the generator never intended to emit. `tools/formal_fuzz.py`'s attribution
already states the conservative direction it takes when a disagreement is not
explained ("there is a known bug in here too is not a reason to miss this one"),
and this is the case that direction is for: **a finding reached through the
minimiser is a finding about a construct the corpus does not cover, and the
ledger records it as one.**
