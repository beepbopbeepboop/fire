# FORMAL_the_export_gate_row_is_148_files_and_one_gate: the corpus's largest
# codegen row is ONE function, and 133 of its 145 refusals named no line

**Area:** `formal/imports.py` (`check_library_free_calls`) · **Status: PARTIAL —
§3's half is FIXED (2026-10-05): every refusal the row's gate produces now
names the function or method the call is in, on both architectures. §4 is NOT
fixed and is the whole of what is left: the message names four candidate rules
for `doc/ABI.md`'s export rule, and for one file of the row none of the four
applies. §2 is the measurement and §5 is why the row itself is not this
branch's to close.** Measured 2026-10-05 on `master` 80cea3bd, claim
`sweep43:export-gate`, over the row's OWN 148-file scope rather than a sample ·
**Layer:** 1/5 of the formal work

Found by taking the export-gate row — `a call to a name the defining module does
not export`, the largest codegen cause in the corpus for a fifth round running
— after `formal41-exports-and-strings` took the `module exports no public
functions` row out from under it and the `b14` round map
(`bugs/FORMAL_sweep_work_map_2026-10-05_b14.md` §4) recorded it as claimed by
work whose own subject is a different row.

## 0. What this document is, and what it is not

**It is the row's measurement on `master`, and the root-cause finding about the
gate that produces it.** **It is not the row's fix**, and §5 says why in the
words that matter: the row is one FEATURE — template type-argument inference at
a bare call site — and that feature is
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`,
which `formal40-1` and `formal40-1-r2` hold. **A second implementation of the
same feature in a second branch is the thing CLAUDE.md's "no duplicated
implementations" rule exists to prevent**, so this branch fixed the gate and
measured the row, and left the feature to its owner.

## 1. The re-measurement, over the row's OWN 148 files

`bugs/sweeps/sweep-arm-14.txt` names the row's 148 files; they were extracted
by the refusal sentence (`tools/formal_sweep_causes.py::CAUSES`' own key) and
re-swept on `master`:

```sh
export PATH=/opt/homebrew/bin:$PATH
grep -o 'CODEGEN/DEPENDENCY: [^ ]*' bugs/sweeps/sweep-arm-14.txt | …   # + the 15 in-file rows
python3 tools/memslot.py --gb 8 --label eg -- \
  python3 tools/formal_sweep.py -j 3 -t 120 $(cat .tmp/export-gate-files.txt)
```

| | `-14` (the committed log) | **`master` 80cea3bd, this row's 148 files** |
|---|---|---|
| files | 148 | 148 |
| **at the export-gate row** | 148 | **145** |
| moved to `module exports no public functions` | 0 | **3** (`bitset`, `complex`, `pointer`) — all at `_io.mojo`, which is the OTHER row |
| reach a pass | 0 | **0** |

```console
$ python3 tools/formal_sweep_causes.py --min 1 .tmp/eg-arm.txt
  files in-file  cause
    145      10  a call to a name the defining module does not export
          refused in: std.format._utils x103, std.memory.alloc x28, std.bit.mask x8,
                      std.utils.numerics x2, .compiler x1, ..fstat x1, .philox x1, time x1
      3       0  module exports no public functions
```

**The 3 are `formal41-exports-and-strings`' fix arriving**: it made a
constants-only module importable, and these three files now walk FURTHER, to
`std/sys/_io.mojo`, which declares three module-level constants and no function
at all. **That is the `module exports no public functions` row and not this
one**, and `bugs/FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md`
holds it. **So 145 of 148 is this row's own number on `master`, and the other 3
are a fix landing, not a regression.**

### 1.1 The ten sub-buckets, and the exclusion rule each one is actually stopped by

The message enumerates four candidate rules. `reflect.export_exclusions` is the
ONE function that states them and it answers per name, so the table below is
the rule that applied and not the rule that might have:

| files | the call | the defining module | **`reflect.export_exclusions`' answer** |
|---:|---|---|---|
| 103 | `FormatStruct(writer, "…")` | `std.format._utils` | `generic-template` |
| 28 | `dealloc(x^)` | `std.memory.alloc` | `generic-template` |
| 8 | `is_negative(val)` | `std.bit.mask` | `generic-template` |
| 2 | `isnan` / `_isnan` | `std.utils.numerics` | `generic-template` (and `_isnan` is an ALIAS of `isnan`) |
| 1 | `keep(x)` | `benchmark.compiler` | `generic-template` |
| 1 | `strided_load(…)` | `std.sys.intrinsics` | `generic-template` |
| 1 | `stat(path.__fspath__())` | `os.fstat` | `generic-template` |
| 1 | `PhiloxRandom(seed=seed)` | `random.philox` | `generic-template` (and `PhiloxRandom` is an ALIAS of `Random`) |
| 1 | `now()` | `time` | **NOT EXCLUDED — the module declares no `now` at all** (§4) |

**Eight of the nine that the export rule does stop it are stopped by exactly one
rule, and it is the last one the sentence lists.** Three of the ten callees are
reached by a name the defining module does not declare under that spelling
(`_isnan`, `PhiloxRandom`, `now`), and the first two are aliases whose DEFINING
name is a template.

## 2. THE ROOT-CAUSE FINDING: the row is ONE gate, and 92 % of its messages named no line

**Every file the row blocks is blocked by one function.** Instrumented over all
148 files on `master`, replacing `model.imported_callee_refusal` with a counter
and reading the raising frame:

```console
$ python3 - <<'PY'      # over .tmp/export-gate-files.txt, arm64
… spy on formal.model.imported_callee_refusal, record the raising frame …
sites: Counter({'check_library_free_calls': 144, 'check_module_symbols': 1})
PY
```

**144 of 145 come from `formal/imports.py::check_library_free_calls`** — not
from `formal/build.py`'s two `check_module_symbols` arms, not from
`_bracketed_export_gap`, and not from the dylib build's own export gate. That
matters because the other three are per-function and name the function; this one
walked the consumer's raw top-level statements.

**And it named no function for 133 of the 145.** The walk was

```python
for st in stmts or []:
    fn_name = st.name if isinstance(st, F.FunctionDef) else ""
    for node in M.iter_nodes(getattr(st, "body", None) or [st]):
```

so a `StructDef` — whose `body` is the list of its **METHODS**, and which is
where the corpus's calls are — walked every method with `""`. Measured, over
the same 148 files:

```console
{'total': 145, 'no function name': 133}
```

**The file the reader is then sent to is `std/memory/alloc.mojo`, which has
four `write_to` methods and three `FormatStruct(…)` sites in it**, and whose
refusal read, in full, `build: `FormatStruct` is called, and it is imported
from `std.format._utils`, so …`. That is a diagnostic about a construct, with
no position in a 1000-line file, for the row that is 45 % of the corpus's
findings.

## 3. What this branch FIXED

**`formal/imports.py::_enclosing_scopes`, and the walk is per function.** A
method is reached through its struct and named `Struct.method`; a trait method
through its trait, because a trait method body is compiled into whatever struct
implements it and the trait is the only scope the source has; a top-level
function keeps its own name; and a module-level store is `""`, which is now the
only thing `""` means. `M.struct_methods` is the reader, the one
`find_method_owner` and `structs_declaring_method` already ask.

**The measured effect, same 148 files, same instrument:**

```console
{'named': 145}          # was {'total': 145, 'no function name': 133}
distinct scopes: 12
   68  Allocation.write_to
   33  Slice.write_to
   28  _Global._deinit_wrapper
    8  log2_floor
    1  QuickBench.run          1  _write_float
    1  ComplexSIMD.write_repr_to   1  ThinAllocation_1_T_1_T.write_to
    1  getsize                 1  _PhiloxWrapper.__init__
    1  _convert_f32_to_float8_scalar   1  main
```

**145 of 145 name a scope, and the twelve scopes ARE the row's buckets**:
`Allocation.write_to` + `Slice.write_to` + `ComplexSIMD.write_repr_to` +
`ThinAllocation_1_T_1_T.write_to` is the 103-file `FormatStruct` group,
`_Global._deinit_wrapper` is the 28-file `dealloc` group, and `log2_floor` is
the 8-file `is_negative` group. **A reader of this row now gets the file AND
the method, and the method is the whole of what identifies the call.**

**Both architectures, from the same source** (the gate is architecture-blind,
and that is checked rather than assumed):

```console
$ python3 fire.py build --formal --no-prove --backend=arm64  -o .tmp/x.arm64  std/memory/alloc.mojo
build: ThinAllocation_1_T_1_T.write_to: `FormatStruct` is called, …
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/x.x86_64 std/memory/alloc.mojo
build: ThinAllocation_1_T_1_T.write_to: `FormatStruct` is called, …
```

**Zero files move and zero verdicts change**, which is the honest ledger and is
the same shape `FORMAL_sweep_work_map_2026-10-05_b14.md` §5.5 reported for its
own `max`/`min` fix: a diagnostic is not a coverage change. Measured by
re-sweeping all 148 files with the fix in and diffing against the `master`
sweep above:

```console
$ python3 - <<'PY'   # the two logs, keyed by path
… class per path …
BEFORE rows: 148   AFTER rows: 148
only BEFORE: 0     only AFTER: 0
CLASS CHANGED: 0
terminal (module, callee) table identical: True
  BEFORE: {('std.format._utils','FormatStruct'): 103, ('std.memory.alloc','dealloc'): 28,
           ('std.bit.mask','is_negative'): 8, …}                      # all nine pairs
  AFTER : {('std.format._utils','FormatStruct'): 103, ('std.memory.alloc','dealloc'): 28,
           ('std.bit.mask','is_negative'): 8, …}                      # byte-identical
PY
```

**The tests** are two rows in `test_formal_imports.py`, beside
`a bare call to a template is refused by the export rule` — the case whose
message this is. `the bare-call refusal names the method the call is in` builds
a program with a call in a struct method AND a call in a top-level function and
requires the message to say `Holder.show:`, so it pins the fix and pins that the
top-level case kept naming itself. `the enclosing-scope reader names a trait
method and a module store` asks `_enclosing_scopes` DIRECTLY for all four
answers, because a build can only show the one it happens to hit first — a
program whose first bare call is a module-level store never reaches the trait —
and it counts the calls per scope so the name and the walk cannot come apart.
**Both were checked to FAIL with the fix reverse-applied against `HEAD~1`**
(`git apply -R` of the `formal/imports.py` hunk saved to `.tmp/`, never
`git checkout`): the first with "the refusal does not name the METHOD the call
is in", the second with `ImportError: cannot import name '_enclosing_scopes'`.

### 3.1 A coverage hole the first version of this fix opened, and how it was caught

**Worth recording because it is the failure mode a "just add the name" change
has, and it is invisible in every shape the corpus has.** The first version
replaced the walk with "one scope per function and per method" and DROPPED the
`StructDef` itself — on the reasoning that its methods are what the corpus
calls. **`iter_nodes` over a `StructDef` reaches its FIELDS as well as its
methods**, and a field's declared type and default are expressions like any
other, so `var n: Int = widen(3)` stopped being asked about by this gate.
Caught by reverse-applying the hunk and building the shape:

```console
# ORIGINAL, and the fix WITH the struct scope kept — identical:
build: `widen` is called, and it is imported from `mylib`, so the call has to …
# the struct scope DROPPED:
build: constructing Holder cannot bring its field 'n' up at its default …
```

**Same program, same verdict (refused), a DIFFERENT and less specific
diagnostic** — and, worse, a gate that has stopped asking a question it used to
ask, which is the shape a coverage hole takes when nothing goes green. The
struct is therefore still yielded, right after its methods and under `""` (a
field initializer is in no function, which is what the empty name now means),
and the second test pins that scope and where it sits.

**A caution about how that was measured, because it nearly made this section
wrong**: the first reverse-apply compared against this branch's own previous
commit rather than against `HEAD~1`, and reported a difference that was an
artefact of the intermediate state. `git apply -R` of `git diff` is only the
original when the diff is taken from the commit the change is measured against.


## 4. NOT fixed: the sentence names four rules, and for one file none applies

`runtime/stdlib_wrapper.mojo` does `from time import now, sleep` and calls
`now()`. The refusal says the reason "is `doc/ABI.md`'s export rule rather than
anything about this call", then lists a leading `_`, a generic template, an
overload, and a C library name.

**`formal/hostmods/time.mojo` declares no `now` and no `sleep`.** Its public
surface is `time_ns`, `time_seconds`, `monotonic`, `monotonic_ns`,
`perf_counter`, `process_time`, `thread_time`, `clock_gettime_ns`, `sleep_ns`,
`sleep_seconds` and the `CLOCK_*` ids. So all four candidate reasons are FALSE
about this file, and the reader is sent to look for an underscore, a bracket, a
second definition, or a libSystem name in a module that has none of them.

**Why it is not fixed here, stated as the next step rather than as a
difficulty.** The rule that applied is already computed by
`reflect.export_exclusions(src)`, which returns `{name: rule}` and is the ONE
place the rule is stated — `collect_exports_src` filters the export table
through it and `monomorph.template_names` reads its `EXCL_GENERIC` set. **What
is missing is the PATH from a module NAME to that module's SOURCE TEXT at the
three sites that have only the name**, and the reason is a table that drops it:
`formal/build.py::dylib_export_lists` projects each manifest down to
`{module, exports, reexports, constants, variables, containers}`, and the
manifest itself records `source` (measured: `"source":
"/…/pa/mask.mojo"`). The exact next step is therefore

1. add `"source"` to that projection, so a module name resolves to the file it
   was built from — the same file, and the same bytes, the library was compiled
   from, which is the argument `_imported_structs` already makes for a struct
   declaration it reads back out of a manifest;
2. one reader, asked by all four `imported_callee_refusal` call sites:
   `export_rule_for(module, name, link_line)` → the path → `export_exclusions` →
   `EXCL_GENERIC` / `EXCL_PRIVATE` / `EXCL_OVERLOADED` / `EXCL_CLIB`, or **no
   entry at all**, which is the fifth answer and the one this file needs;
3. `imported_callee_refusal` names THAT, and when there is no entry says the
   module declares no such name — which is the sentence that is true about
   `formal/hostmods/time.mojo`, and which also turns the 144-file enumeration
   into the one rule that applied.

**Step 1 is one line and step 2 is one function; the reason this branch did not
do them is that it would have touched the emitter's own constructor argument,
which is a different claim's neighbourhood, and the row's gate — the thing §2
found — was already fixed.**

## 5. Why the ROW is not closed here, in the words that matter

**All 145 files are one feature and the feature has an owner.** Every sub-bucket
is a bare call to a declared template whose type arguments are inferable from
the call's own arguments, which is
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
§1, §2 and §5b — the last of which already measured the three pieces (a matcher
over two annotation strings at 2 sites, return-type inference at 71, bound
resolution against an existential at 28) and the order they should be taken in.

**The measurements in §1 and §2 are new and are what that doc did not have:**
that the row's 148 files re-measure at **145 on `master`** (three moved to the
other row under `formal41`'s fix), that the row is **one gate and not four**,
and that **its three biggest buckets have exact terminal sites** —
`Allocation.write_to`/`Slice.write_to` for the 103, `_Global._deinit_wrapper`
for the 28, `log2_floor` for the 8. A worker taking the feature can now skip
the sweep and go straight to the call site of each bucket.

**One structural fact §1.1 adds that is worth carrying into that work, and it is
about the ABI rather than about inference.** On this path a generic **fn**
template's own body is compiled and emitted **under its base name, with its
type parameters as leading runtime words**, and a bare call binds it with each
comptime parameter set to 0 (`formal/arm64_codegen.py::_emit_call`: *"A bare
`f(x)` to the same generic binds each comptime parameter to 0"*; and
`formal/monomorph.py::without_template_bodies` drops a generic **struct**
template's body and deliberately does NOT drop a generic fn's). Measured on
this tree, `def twice[T](x: Int)` in one file and `twice[Int](21)` in it emits
BOTH symbols:

```console
$ python3 -c "import sys; sys.path.insert(0,'.'); import formal.build as B; \
    print(sorted(k for k in B.compile_formal('.tmp/fng2/m4.mojo', prove=False, arch='arm64', fmt='macho')['info']['labels'] if '_sf' not in k))"
['main', 'twice', 'twice_1_T_3_Int']
```

**So the export rule's `EXCL_GENERIC` is right about a struct template and is a
statement about the WRONG SHAPE about a fn template**: the base name is a real
emitted symbol with a real, uniform ABI, and what crosses the boundary for it is
the type arguments as leading words rather than a mangled name. **Publishing it
would be the cheap half of the feature** — and it is deliberately NOT done here,
because it contradicts `doc/ABI.md` §Generics and
`test_formal_imports.py::a generic template is not exported under its base name`,
which pins the empty export set, and because a bare caller would then bind a
symbol with every comptime parameter set to 0 — **which is a silent wrong
answer wherever the body's result depends on the type argument**, and this path
has a rule about that (`type_arg_text`: refusing rather than guessing "is how a
call binds another instantiation's body"). **It is recorded here as the ABI
shape the inference has to fit, not as a change to make.**

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
S=../new-modular/Mojo/stdlib/std

# §1 — the row's own 148 files, re-swept on master
python3 tools/memslot.py --gb 8 --label eg -- \
  python3 tools/formal_sweep.py -j 3 -t 120 $(cat .tmp/export-gate-files.txt)
python3 tools/formal_sweep_causes.py --min 1 .tmp/eg-arm.txt

# §1.1 — the exclusion rule each sub-bucket is actually stopped by
python3 -c "import sys;sys.path.insert(0,'.');import reflect;print(reflect.export_exclusions(open('$S/format/_utils.mojo').read())['FormatStruct'])"
sed -n '287p' $S/format/_utils.mojo      # struct FormatStruct[T: Writer, o: MutOrigin]
sed -n '904p' $S/memory/alloc.mojo        # def dealloc[T: AnyType, /](…)
sed -n '26p'  $S/bit/mask.mojo            # def is_negative[dtype: DType, //](…)
grep -nE '^(def|fn|alias) (now|sleep)\b' formal/hostmods/time.mojo   # §4: no match

# §2 — the single gate, and the missing scope name
python3 - <<'PY'
import sys, collections, traceback; sys.path.insert(0, '.')
import formal.build as B, formal.model as M
orig, sites, stats = M.imported_callee_refusal, collections.Counter(), collections.Counter()
def spy(name, sym, fn_name):
    stats['named' if fn_name else 'unnamed'] += 1
    for fr in traceback.extract_stack():
        if fr.name in ('check_library_free_calls', 'check_module_symbols'):
            sites[fr.name] += 1
    return orig(name, sym, fn_name)
M.imported_callee_refusal = spy
for f in open('.tmp/export-gate-files.txt').read().split():
    try: B.compile_formal(f, prove=False, arch='arm64', fmt='macho')
    except Exception: pass
print(sites, stats)
PY

# §3 — the fix, both architectures
for a in arm64 x86_64; do
  python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove --backend=$a -o .tmp/eg.$a $S/memory/alloc.mojo
done   # both answer "build: ThinAllocation_1_T_1_T.write_to: `FormatStruct` is called"

# §3's tests
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
```

**Three cautions about reproducing this at all**, each of which cost this
branch time:

* **The instrument is a `sys.path` shim, not a build flag.** The row's files
  live in another checkout (`../new-modular/Mojo/stdlib/std`) and
  `formal_sweep.py` takes paths, so the row is re-measurable without a corpus
  change — but `tools/formal_sweep_causes.py`'s `refused in:` column reads the
  module name out of the MESSAGE, which is why §1.1 had to ask
  `reflect.export_exclusions` directly rather than believe the sentence.
* **The two architectures must be run by DIFFERENT commands.** A loop that
  runs both under `arch -x86_64` reports Rosetta's `Bad CPU type in
  executable` as the arm64 half's answer — the `-14` map §7 records this
  producing a table of confident, wrong numbers including a "cross-architecture
  divergence" that was one arm64 image never executing.
* **`.tmp/` is under the repository root and `DEFAULT_PATHS` used to walk it**,
  so a sweep's file count could include a test's scratch. Fixed
  2026-10-04 (`is_derived_dir`), and this measurement names its 148 files
  explicitly rather than relying on the scope.
