# FORMAL_the_host_import_rows_after_glob_ranked_by_what_they_actually_spell: what is left, which of it is reachable, and why four of the next six are not this wave's

**Status 2026-10-04 (a second pass): §5 item 1, `shlex`, is DONE** —
`formal/hostmods/shlex.mojo` and `test_formal_shlex.py`, 1 file moved, 0 passes,
which is the number every host-import row in this project predicts. §5 items 2-5
remain and each is named below with why it is not this wave's.

**Status 2026-10-05 (`work/formal29-5`): §5 item 2, `random`, is DONE** —
`formal/hostmods/random.mojo` and `test_formal_random.py`, **8 of the 8 files
changed class, 1 reached an in-file finding, 0 passes**, which is the number
every host-import row in this project predicts. §5 items 3-5 remain and each is
named below with why it is not this wave's.

**Status 2026-10-04 (`work/formal25-6`): §5 item 2, `random`, is REACHABLE —
measured, both architectures — and is a real module-sized job, not an afternoon.
The three pieces a Mersenne Twister needs were each measured on this path and
all three are correct:**

    # 1. the STATE: a 624-word list literal
    var s = [1, 1, … 624 …];  printf("len=%d", len(s))          # len=624, BOTH
    # 2. the MUTATION: a loop storing through the loop counter's index
    for i in range(624): s[i] = s[i] + 1                          # last=2 first=2, BOTH
    # 3. the ARITHMETIC MT is made of
    var x = 1812433253; x = x ^ (x >> 30); printf("%d", x % 100000)
    # v=33252 on both, and CPython says 33252

That is the whole of "a Mersenne Twister is integer arithmetic" made concrete,
and the doc's §2.1 claim that only the two module-level spellings are in reach
still stands (a `Random` INSTANCE is 624 words behind a pointer, which is
`FORMAL_module_state_no_storage`). What is NOT an afternoon is the module:
`init_by_array` (CPython seeds from the key's WORDS, not from a scalar), the
`genrand_res53` shift, and `randrange`'s `getrandbits` rejection loop, each of
which has to agree with CPython to the bit for the two callers'
differential checks to be worth anything.

**Two of those three pieces were measured on a LOCAL list, and the module needs
the state to be MODULE-level, which is the premise the 2026-10-05 work
measured separately and which is the one thing worth carrying forward from
this paragraph: a module's OWN `global` HAS storage and survives across calls
in one process** (see §1a below). That is what makes the row reachable at all,
and `bugs/FORMAL_module_state_no_storage.md`'s framing does not describe it —
`formal/imports.py`'s own `module_attribute_refusal` advice ("give it an
accessor … which reads the same slot and lowers today") already assumed it.

**Growing the state used to be unavailable on x86-64 and is FIXED (2026-10-04,
`work/formal28-6`).** `s = s + [x]` inside a loop printed NOTHING on x86-64
past 65 elements (exact: 65 worked, 66 exited 1) because a blob's reservation is
made once per SITE and the site runs once per iteration; `formal/model.py`'s
`blob_loop_growth` now multiplies a loop-carried site's estimate by the loop's
compile-time trip count, on BOTH backends, and `s.append(x)` in the same loop
(which stopped at the second append on both) is fixed by the same change. So a
state built by filling 624 slots in a loop now works on both machines, as does a
624-word literal.

**What is still the only spelling of the module-level state that works is the
LITERAL**, and that is a different shape from loop growth and was measured
separately: `[0] * 624` at module level builds and then prints NOTHING on BOTH
architectures, while the 624-word literal reads back correctly at every size
tried (4, 65, 66, 128, 624).

**Claim** `sweep20:hostmods-wave3` on `work/formal20-hostmods-wave3`. Written
2026-10-04 after `formal/hostmods/glob.mojo` landed (commit `d2edb1aa`). The
ranking is `tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-9.txt`,
the sweep is that file's own, and every count below is measured on this tree —
§3 says how, and §4 is what the measurements cost.

The short version: **`glob` was the last row that was both large and reachable,
and the task's "next 4-6 modules by files blocked" does not exist as stated.**
The rows below it are 22, 11, 10, 10, 4, 4 files, and of those the 22 is
**claimed by another worker**, two are type factories whose capability has a doc
and an owner, two need an object this target does not have, and the rest are
1-4 files. That is the finding, and §2 gives the row it hands the queue.

## 1. What landed, and what it moved

`formal/hostmods/glob.mojo` — `glob`, `glob_free`, `has_magic`, `escape` — the
50-file row, 16 of whose blocked files name it. Re-sweeping exactly those 50
files (`tools/formal_sweep.py -j 4 -t 120 --no-stdlib`, arm64,
`cas: 0 hit / 50 miss`, so a measurement and not a replay):

| | before | after |
|---|---|---|
| `not-answerable/host-import` | **50** | **8** |
| `codegen` (a finding IN the file) | 0 | **5** |
| `codegen/dependency` (a finding one level down) | 0 | **35** |
| `not-answerable/unresolved-import` | 0 | **2** |
| **files that changed class** | | **42 of 50** |
| **pass** | **0** | **0** |

**0 passes, and that is the prediction every host-import row in this project has
made** (`bugs/FORMAL_subprocess_row_measured_b7.md` §7 for `tempfile`,
§"what it moved" for `textwrap`, and the `platform` row's thirty files, none of
them a small program): none of these 50 files is a small program — they are
`cas.py`, `driver.py`, `module_loader.py`'s callers, the test suite. What moved
is that they now report the truth about where they actually stop.

And where they stop is **one row**: `cas.py: line 164: FileNotFoundError is a
handler arm with a body this path cannot put in the image`, 35 of the 42.
`FORMAL_except_arm_is_never_emitted`, claimed (`formal8-5`), and the refusal is
CORRECT: `formal` has no unwinder, so no edge runs from a raise site into an arm
and every statement in an arm's body would be absent from the program that runs.
The other five: `print()` cannot classify its argument's type
(`bootstrap-validate.mojo`), a module attribute read as a value
(`tools/fix_genexpr_anyall.py`, `FORMAL_module_state_no_storage`), and three
single refusals of their own.

**The remaining 8, and what they are waiting for** — the honest number, since
`glob` unmasked them:

| blocked on | n | reachable? |
|---|---:|---|
| `itertools` (via `test_formal_dylib.py`) | 3 | **no** — §3 |
| `importlib` (via `fire_compiler.py`) | 2 | no: an embedded CPython |
| `zlib` (via `gimple_codegen.py`) | 1 | a project, and it is `zlib` |
| `collections` | 1 | **claimed** (`module:…collections-rest`) |
| `copy` (via `formal/build.py`) | 1 | a type factory, `formal8-1` |
| `formal_sweep` (unresolved-import) | 2 | this repository's own tool |

**So 42 files moved, 0 passed, and the destination is one claimed row.** A
reader deciding what to do next should read that as: the `glob` row is closed and
the row behind it is somebody else's, which is the queue's answer and not a
disappointment.

## 1a. `random`, and the premise the row rests on (2026-10-05)

`formal/hostmods/random.mojo` — `seed`, `randrange` — a Mersenne Twister over
a 624-word module-level state, transcribed from CPython 3.14's
`Modules/_randommodule.c` and checked answer-by-answer against CPython's own
`random` on both architectures by `test_formal_random.py` (8 groups: the two
call sites in this repository verbatim — 320 draws; one case per branch of
`getrandbits`; 700 draws so the 624-word twist is inside the corpus; 15 seeds of
one to three key words in both signs and zero; 7 widths just under a power of
two so the rejection loop runs; the two ranges CPython raises on as the `-1`
statuses they are here; and the four names the module does not publish refused
by name).

**THE PREMISE, measured before any of it was written, and it is the part worth
keeping: a module's OWN `global` HAS storage, and it survives across calls inside
one process.** A module-level `var` written through `global` by one function and
read by another — arm64 exit 186, x86-64 exit 186, CPython 186 — and the same
through a module-level `List[Int]` subscript: 211 on both, CPython 211.

This is what `formal/imports.py`'s own `module_attribute_refusal` has been
telling callers ("give `{mod}` an accessor … which reads the same slot and
lowers today"), and it is NOT what `bugs/FORMAL_module_state_no_storage.md`'s
title says. **The two are about different things and the difference is worth a
sentence: a module's own globals have a home in its `__DATA`, while a value
that has to CROSS a dylib boundary does not** — which is why `os.environ` is
still refused and why a `Random` instance is still unreachable. The doc this
one names is not mine to edit, so the note beside `random` in `HOST_MODELLED`
records it where the ranking reads it.

**What the row was worth, measured, and 0 passes is the number every host-import
row in this project predicts.** All eight files re-swept
(`tools/formal_sweep.py -j 2 -t 120 --no-stdlib`, arm64):

| | before | after |
|---|---|---|
| `not-answerable/host-import` on `random` | **8** | **0** |
| `codegen` (a finding IN the file) | 0 | **1** |
| `not-answerable/host-import` on a DIFFERENT module | 0 | **6** |
| `not-answerable/unresolved-import` (a sibling module) | 0 | **1** |
| **files that changed class** | | **8 of 8** |
| **pass** | **0** | **0** |

The one file that reached an in-file finding is `test_formal_hashlib.py`, whose
first refusal is an f-string at line 137 — a string with no buffer to compose
in, which is `FORMAL_string_composition_has_no_buffer`'s row. The six that are
behind a different host import are `fractions` ×1 (`test_formal_time.py`),
`inspect` ×1 (`test_gimple.py`) and `collections` ×4 (the three
`tools/formal_*fuzz.py` and `formal/x86_64_model_fuzz.py`'s sibling), so **the
destination of this row is now mostly a CLAIMED row**
(`module:platform+fnmatch+collections-rest`) and one fact about the target.

**The five `Random(seed)` files are not a module-sized job and never were**, and
§2.1's reasoning above is what said so first: a `Random` is an object with 624
words of state behind a pointer, so it is `FORMAL_module_state_no_storage` and
not a `.mojo` file's to fix. Four of the five also pass a STRING
(`random.Random(f"{seed}:{index}:{mix}")`), which is CPython's version-2 seed —
`sha512` of the bytes folded into a big integer — and a big-integer
construction is not a value here at all. So the row's ceiling was 2 of 8 files
when this doc was written and the ceiling is what landed.

**A bug was found on the way, in another worker's area, and is filed rather
than fixed:** `bugs/FORMAL_x86_64_seven_argument_call_evaluates_its_stack_arguments_first.md`
— on x86-64 a call with seven or more integer arguments evaluates its
STACK-passed arguments first, so a corpus that printed six `randrange` calls in
one `printf` answered a rotation of CPython's sequence on one architecture and
the right one on the other. arm64 and the gimple path are both right.

## 2. The ranking after `glob`, and why "the next 4-6 modules" is not there

`tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-9.txt`, with `glob`
already written (the ranking reads `formal/hostmods/` for real, so this is the
table as it stands rather than as it stood):

| files | uses | tier | module | what the callers spell | verdict |
|---:|---:|---|---|---|---|
| 54 | 0 | unreachable | `importlib` | — | 54 files of CLOSURE behind `fire_compiler.py`. 0 uses, so writing it would move 0. |
| 50 | 16 | **written** | `glob` | `glob` x16 | **DONE 2026-10-04**, §1 |
| 27 | ? | unreachable | `zlib` | not measurable | a project: DEFLATE is arithmetic over bytes and the module is a few hundred lines. The entry says so at the head of `HOST_UNREACHABLE`. |
| **22** | **10** | modelled | **`collections`** | `Counter` x4, `defaultdict` x3, `OrderedDict` x2, `namedtuple` x2 | **CLAIMED** — `module:platform+fnmatch+collections-rest`, `hostmods-platform` |
| 11 | 3 | modelled | `copy` | `deepcopy` x2, `copy` x1 | §3: `copy.copy` IS the identity |
| 11 | 11 | unreachable | `unittest` | `TestCase` x11, `main` x10 | process-wide reporting machinery; a fact about the target |
| 10 | ? | modelled | `itertools` | not measurable (frozen) | §3 |
| 10 | **10** | modelled | `types` | `ModuleType` x7, `SimpleNamespace` x4 | §3: a type factory. **The 0 was a tool defect**, `6a7c36bb` |
| 7 | 3 | unreachable | `signal` | `signal` x3 | a process-wide host object |
| ~~4~~ | 4 | modelled | ~~`random`~~ | `Random` x3, `seed` x3, `randrange` x2 | **WRITTEN 2026-10-05**, §1a — this table is the `-9` census; today's reads **8 files, 7 uses** (`Random` x5, `randrange` x2, `seed` x2) on `bugs/sweeps/sweep-arm-12.txt` |
| 4 | 4 | modelled | `inspect` | `getsource` x6, `signature` x5, `getsourcelines` | §3: needs a live interpreter's frames |
| 3 | 3 | unreachable | `importlib.util` | `module_from_spec`, `spec_from_file_location` | an embedded CPython |
| 2 | 2 | modelled | `datetime` | `datetime.now()` | a clock this tree reads plus a shaped record; `FORMAL_time_struct_shaped_answers.md` |
| 2 | ? | modelled | `resource` | `getrusage(RUSAGE_CHILDREN)` | `struct rusage` is a shaped record, same doc |
| 1 | 1 | modelled | `uuid` | `uuid4().hex[:8]` | §3: `uuid4()` needs entropy this path has and `.hex` is a method on a 128-bit answer |
| 1 | 1 | modelled | `shlex` | `quote` | §3: **reachable, cheapest row in the census, 1 file** |
| 1 | 1 | modelled | `functools` | `lru_cache` x1 | claimed — `FORMAL_functools_is_unbuildable_as_a_host_module`, and a decorator is silently DROPPED |

**Counting what is left and unclaimed and reachable: two modules, `shlex` (1
file) and `random` (4 files).** Everything else is claimed (3 rows), a fact
about the target (4 rows), or a type factory / shaped record with a doc and an
owner (4 rows). That is the answer to the task's "next 4-6 modules by files
blocked", and it is the reason this wave modelled one module and wrote this
document instead of four: **modelling a module that four workers already hold,
or one whose blocker is `FORMAL_module_state_no_storage`, is not work — it is
the queue's problem re-created in a branch that will not merge cleanly.**

### 2.1 The two that are genuinely next, and what each costs

**`shlex.quote` — 1 file, and the cheapest row in the census.**
`tools/suite.py` spells `shlex.quote(a)` three times and nothing else
(`test_suite.py` twice more, same file's test). It is the `html.escape` /
`textwrap.dedent` shape exactly: CPython's `quote` is a scan over the string
deciding per byte whether it is in `_find_unsafe`, then either the bare string
or `'` + inner + `'`, and `_syscalls.mojo` has `str_put`/`str_len` for it. Two
to three hours including the corpus, 1 file moved, 0 passes. `shlex.join` is
`" ".join(map(quote, argv))` — a generator and a list, so not in reach by the
same argument (`fnmatch.iglob`'s shape); `shlex.shlex` is a streaming reader.

**~~`random` — 4 files, and reachable for a reason nobody had written down.~~
DONE 2026-10-05, §1a: `formal/hostmods/random.mojo`, and the accounting is
**2 of 8 files moved into `codegen`'s neighbourhood, 8 of 8 changed class, 0
passes.** The reasoning below was right about the catch and optimistic about the
rest, so both halves are worth reading next to what landed:

`arc4random_buf` is in libSystem and is already called
(`formal/hostmods/tempfile.mojo` uses it for `mkdtemp`'s eight characters), and
CPython's `Random` is a **Mersenne Twister**: pure integer arithmetic over a
624-word state, reproducible from a seed, no host object involved. So
`seed(n)`, `random()`, `randrange(a, b)` and `Random(n)` are all computable here
and `test_formal_hashlib.py`/`test_formal_time.py` compare their answers against
CPython's own on every run — which is the differential test already written by
the callers. **The catch is that a `Random` INSTANCE is an object with 624 words
of state**, so `test_gimple.py`'s `rng = random.Random(20260930)` and
`tools/formal_fuzz.py`'s are outside what a module function can answer
(`FORMAL_module_state_no_storage`), and only the two module-level spellings
(`seed` then `randrange`) are in reach: **2 of the 4 files, not 4.** It is worth
a worker's afternoon and it is not worth this one.

**WHAT THAT PARAGRAPH GOT WRONG, measured: `seed(n)` and `randrange(a, b)` are
computable here only because a module's own `global` has storage and survives
across calls** (§1a), and nothing in this section said so — the argument above
rests on "no host object involved", which is true of the ALGORITHM and silent
about where its 624 words live. A reader who took this section at its word would
have written the module with the state in a parameter and found that no caller
spells it that way. And the module turned out to be a day rather than an
afternoon for a reason this section also did not say: `getrandbits(k)` for
`33 <= k` has a wrong answer that LOOKS right (`((w0 | (w1 << 32)) >> (64-k))`
drops the low word's top bits, so `k = 33` gives 2 bits and every answer is under
`2**32`), and only a corpus compared against CPython finds it.

## 3. Why each of the rest is not work, in the order a reader will ask

**`copy` (11 files, 3 uses) — `copy.copy(x)` IS `x`, and `deepcopy` is a type
clone.** `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`
(claimed `formal8-1`) owns the second half and says so. The first half is why
shipping `copy` is a trap rather than a module: `formal/hostmods/textwrap.mojo`'s
docstring records the rule this project already learned the hard way — "a `floor`
that returns its argument is `copy.copy`", i.e. an identity function under a name
that promises a copy will be believed and will be wrong the moment the argument is
a blob rather than an integer. **One name, three uses, 8 of the 11 files are
closure: not worth it.**

**`itertools` (10 files, uses not measurable) — a generator.** CPython's
`itertools` is frozen into the interpreter so the tool cannot count the uses
(this is the `NOT MEASURED` row, and the tool says so rather than guessing). What
the 10 files are is worth recording: **`test_formal_dylib.py` and
`test_formal_run.py` spell `itertools.combinations(sorted(segs), 2)` and nothing
else, and the other 8 never mention it.** A generator of 2-tuples cannot be
returned from a module function (`FORMAL_listdir_no_run_time_sequence.md`, and a
tuple is a frame blob besides). Not reachable, and the row is 2 files.

**`types` (10 files, 10 uses) — a type factory, and it is now honestly counted.**
`SimpleNamespace(**kwargs)` builds a namespace object at run time and
`ModuleType(name)` builds a module object; neither is a value on this path
(`FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`, claimed
`formal8-1`). **What was NOT honest until this wave was the count**: the ranking
printed `0 uses — pure closure` for this row, and all 10 files name a name it
declares. That was `tools/formal_sweep_causes.py::_host_declared_names` scanning
`ast.parse(...).body` and stopping there, while CPython's `types.py` binds
`SimpleNamespace` inside a module-level `try:` and its `__all__` is a
comprehension `ast.literal_eval` cannot answer. Fixed in `6a7c36bb` with a
regression test in `test_refusal_taxonomy.py` that fails on the old scan. **The
direction that tool was wrong in is the one that reads as "nothing to do here",
which is why it was worth fixing rather than noting.**

**`inspect` (4 files, 4 uses) — needs a live interpreter.** `getsource(obj)` and
`signature(fn)` read a live object's `__code__`, `__globals__` and frame
values. There is no interpreter here: a formal image is a Mach-O binary with an
embedded CPython to COMPILE it and none to run in. `formal/imports.py` already
says this at the `HOST_MODELLED` entry for `inspect` ("what it cannot do is walk
a live interpreter's frames, because there is no interpreter"), and that entry
was written as considered rather than missed.

**`datetime` (2) and `resource` (2) — a shaped record.** Both are reachable
CALLED (`datetime.now()` is a clock `formal/hostmods/time.mojo` already reads;
`getrusage(2)` is libSystem) and both answer a STRUCT: a `datetime` is six
fields, a `struct rusage` is sixteen. `FORMAL_time_struct_shaped_answers.md`
(claimed `formal16-8`) is the doc and says why, and `os.stat`'s per-field
readers (`fs_stat_field64`) are what the shape costs. 2 files each.

**`uuid` (1 file) — `.hex` is a method on a 128-bit answer.**
`uuid.uuid4().hex[:8]` needs 16 bytes of entropy formatted as 32 hex digits.
`arc4random_buf` is available, so the entropy is not the obstacle; **the answer
is the obstacle** — `uuid4()` returns a `UUID` object and `.hex` is one of its
methods, and an object is more than one 64-bit word. The same limit
`formal/hostmods/hashlib.mojo` records for its factory API ("CPython's factory
API is not expressible — a hash object is 8 to 64 bytes of state that cannot
cross a dylib boundary"). 1 file, and a `_uuid4_hex()` spelling would answer a
different question than the one the caller asks.

## 4. What this wave cost, stated as a measurement

| | |
|---|---|
| files blocked on `glob` | **50**, of which 16 name it |
| files whose class changed | **42 of 50** |
| files reaching `pass` | **0** (and every earlier host-import row predicts 0) |
| the destination | **one row, 35 of the 42**: `cas.py:164`'s handler arm, `FORMAL_except_arm_is_never_emitted`, claimed `formal8-5` |
| new host modules | 1 (`glob`), 0 admitted contracts |
| tests | `test_formal_glob.py`, 6 groups, both backends: 33 cases / 206 paths in order, 7 hidden cases / 130 paths, 46 `escape`+`has_magic` answers, `len`/`[i]`/`for`/`glob_free`, 4 absent names refused by name, and the resolve group |
| a pre-existing bug found and fixed | `os.path.join`'s trailing-separator branch, `b5ea7787` + its doc — 10 runs in 10 SIGABRT before, 10 in 10 clean after |
| a tool defect found and fixed | the `uses` column's module-scope scan, `6a7c36bb`, which had `types` reading as closure |
| suites needing the integrator | `formal-glob` is not registered (`tools/suite.py` untouched per the task rules); `test_formal_glob.py`, `test_formal_os.py`, `test_formal_admitted.py`, `test_formal_link_accounting.py`, `test_formal_imports.py`, `test_refusal_taxonomy.py` all pass individually |

**Peak memory across every command in this wave: 0.7 GB**, against the 8 GB
`memslot` reservation each was given. No `formal_sweep` over the 697-file scope,
no lean invocation, no gate.

## 5. The next step, per row, in the order the ranking gives

0. **`shlex`, 1 file — DONE 2026-10-04** (`formal/hostmods/shlex.mojo`,
   `test_formal_shlex.py`). `quote` only, and what is absent is named at the top
   of the module: `split` and `join` answer a LIST or a generator
   (`bugs/FORMAL_listdir_no_run_time_sequence.md`), the `shlex.shlex` reader is a
   generator over `readline`. Checked against **CPython's own `shlex.quote`** over
   61 corpus cases and every byte 1..255 alone AND after a safe byte — 1020
   answers on each of two backends — and every answer re-split by **CPython's own
   `shlex.split`** to say the quoting is one shell word, which is the only
   property `tools/suite.py`'s three call sites need of it since they build a
   command line out of the answer. `shlex` has left `HOST_MODELLED` by being
   written, which is the rule that set states for itself, and two other suites
   carried rows about it (`test_formal_imports.py`'s
   `test_a_stdlib_module_in_no_tier_is_not_reported_as_a_typo` used `shlex` as its
   example of a module in NO tier; `test_formal_link_accounting.py` accounts for
   it beside `html`, `posixpath` and `glob`).
1. ~~**`shlex`, 1 file.**~~ Done, above.
2. ~~**`random`, 2 of 4 files.**~~ **DONE 2026-10-05** — §1a, and the row is
   CLOSED at the 2 files it could reach. `formal/hostmods/random.mojo` is
   `seed` and `randrange` and nothing else, **8 of 8 files changed class, 1
   reached an in-file finding, 0 passes**, and the row's destination is now
   `collections` ×4 (claimed), `inspect` and `fractions` (facts about the
   target) and one unresolved sibling import. The five `Random(seed)` callers
   need an object with 624 words of state and are behind
   `FORMAL_module_state_no_storage`, four of them through a STRING seed besides.
   **What this item did not say and §1a measures: the premise is that a
   module's OWN `global` has storage and survives across calls**, which is why
   the arithmetic was reachable at all and which no other row in this file
   needed.
3. **`zlib`, 27 files.** A project, not a patch, and the entry in
   `formal/imports.py` says so with the argument. Whoever takes it should read
   `bugs/FORMAL_subprocess_row_measured_b7.md` §5 item 1 first.
4. **`collections`, 22 files.** **CLAIMED** — `module:platform+fnmatch+
   collections-rest`. Not this queue's.
5. **The type factories** (`types`, `copy`, `datetime`, `resource`) — each has a
   doc and an owner, and the capability behind all four is one thing: a run-time
   value that is more than one word. That is `Phase 6`'s tagged-value
   convergence arriving from the `os` side
   (`bugs/FORMAL_listdir_no_run_time_sequence.md` items 2 and 3), and it is the
   only thing on this page that is worth more than a module.

## 6. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
cd "$(git rev-parse --show-toplevel)"

# §1a: the row, its eight files, and their class after the module.
python3 tools/memslot.py --gb 8 --label sw -- python3 tools/formal_sweep.py \
  -j 2 -t 120 --no-stdlib formal/x86_64_model_fuzz.py test_formal_fuzz.py \
  test_formal_hashlib.py test_formal_time.py test_gimple.py \
  tools/formal_fuzz.py tools/formal_model_fuzz.py tools/formal_proof_fuzz.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_random.py

# §1 and §2: the ranking, and the slice it names.  (`-12` is the current
# census; §2's table is `-9` and says so.)
python3 tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-12.txt
python3 .tmp/rowfiles.py bugs/sweeps/sweep-arm-9.txt glob > .tmp/glob50.txt

# §1: the re-sweep of exactly those 50 files, and the class delta.
python3 tools/memslot.py --gb 8 --label globresweep -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --no-stdlib \
  $(cat .tmp/glob50.txt | tr '\n' ' ') > .tmp/glob-after.txt 2>&1
python3 .tmp/classdelta.py .tmp/glob-before.txt .tmp/glob-after.txt

# §1 and §4: the tests.
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_glob.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_refusal_taxonomy.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py strings posixpath
```

`.tmp/rowfiles.py`, `.tmp/classdelta.py` and `.tmp/mkbefore.py` are **scratch,
not committed** (`.tmp/` is git-ignored, and `…_b7.md`/`…_b8.md`/`…_b9.md` did
the same) — each is described in its own docstring instead. `classdelta.py`
compares two logs' printed lines, so a file neither run classified is absent
from both and cancels; `mkbefore.py` builds the "before" log from the COMMITTED
sweep over the same slice, so the delta is between two runs of one tool over one
file list rather than between a log and a recollection.

**The re-sweep is 50 builds and finishes in about a minute at `-j 4 -t 120`**
against the committed sweep's own `~2.2 s of wall per build`
(`FORMAL_subprocess_row_measured_b7.md` §9). It is not a whole-scope sweep and
was run inside an 8 GB `memslot` reservation that peaked at 0.7 GB.