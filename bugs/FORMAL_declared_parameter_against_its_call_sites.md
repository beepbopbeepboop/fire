# FORMAL_declared_parameter_against_its_call_sites: the 13-file row, split by what each call site actually hands over

**Status: MEASURED AGAIN (2026-10-03), and the row has moved off this refusal
entirely: 0 of the 13 files now reach it.** `frame_declared_parameter_refusal`
(`formal/model.py:7109`, raised from `formal/build.py`'s
`_check_declared_parameter`) names 13 files in the 630-file arm64 sweep. The
construct is `construct:declared-param-vs-call-sites`; this doc is its
measurement and it answers the question the enqueue asked — **"is a row of
programs that are already wrong a stdlib bug or a compiler gap?"** — with
per-file evidence rather than with a guess.

The short answer: **none of the 13 is a wrong program. All 13 are programs this
path cannot lower, and they fall into FOUR groups that want four different
things.** One group was a false refusal and is fixed and verified by execution
(§2). One group is a refusal whose TEXT is about the wrong argument (§4). One
group is a real defect in a neighbouring construct, filed separately (§5). The
largest group is a word-versus-frame representation question that is not this
construct's to answer (§3).

**THE RE-MEASUREMENT (2026-10-03, this tree), and it is the only thing to read if
you are picking this up.** §2–§5 below describe the state of the tree they were
written on, and §4 and §5 have since been fixed by other work; the 13 files are
now blocked EARLIER than this construct, so none of its per-file conclusions
can be re-measured on them today. Measured with the sweep's own row tool, over
exactly these 13 files, arm64:

| class | n | what it is |
|---|---|---|
| `codegen/dependency` | 9 | a module the file IMPORTS is refused first — `std/collections/binary_heap.mojo` (8 files) and `std/collections/string/_unicode_lookups.mojo` (1), both refused as "a formal dylib has no public functions". Already recorded as a family in `bugs/FORMAL_known_limits.md` §1.1a; nothing new, and it is the same refusal nine times |
| `not-answerable/host-import` | 4 | the four `.py` files import CPython host modules (`importlib` ×2, `copy`, `tempfile`) — a fact about the TARGET, not about this check |
| **on `frame_declared_parameter_refusal`** | **0** | — |

So the construct is correct, load-bearing, and currently unreachable in this
row: fixing §3's call-site coercion would move 0 of these 13 files. What would
move them is the §1.1a family (a module of module-level constants and generic
struct templates exporting nothing under `doc/ABI.md`'s rules), and that is not
this construct's to answer either.

```console
$ python3 tools/memslot.py --gb 8 --label row13 -- python3 tools/formal_sweep.py \
      -j 3 -t 600 -M 4 formal/types.py elaborate.py mojo/middle/closures.py \
      mojo/middle/offload.py $STD/{random/philox,python/python,base64/base64}.mojo …
  [arm64] 13 files: PASS=0 not-pass=13
         codegen/dependency              9
         not-answerable/host-import      4
  cas: 0 hit / 13 miss
  verdict history: previous report 2026-10-01T13:23:35 [arm64], 13 files
    codegen -> codegen/dependency: 9
    codegen -> not-answerable/host-import: 4
```

**§4 and §5 are FIXED on this tree**, measured with the two reproducers §4 and
§5 describe, both architectures:

| reproducer | §4/§5 measured | now |
|---|---|---|
| `struct Python: def import_module(var module: String)`, called `Python.import_module("sys")` | refused as *"declares 'module' as String … passes a name, 'Python'"* — the RECEIVER compared against the first declared parameter | refused with *"too many positional arguments (2 for 1 parameter(s); the parameters are ['module'])"*, **identical on both architectures** — the accurate message, and the one the receiver-rewrite produces |
| `@staticmethod def one_round(counter: Int)`, reached through an instance `r.one_round(c)` with `c = 3` | rewritten to `R__one_round(self, counter)` — two arguments to a one-parameter function | **computes `6`**, CPython's answer, on both architectures |

So §5's neighbour (`@staticmethod` compiled as an instance method) no longer
needs its own doc, and §4's "one line of diagnosis-quality work" is done by that
same work rather than by anything here.

| # | file | callee / parameter / declared | what the call site hands over | group |
|---|---|---|---|---|
| 1 | `formal/types.py` | `mask_of` / `t` / `IntType` | `mask_of(IntType(w, False))` — a **construction** | **A — FIXED** |
| 2 | `std/random/philox.mojo` | `Random__single_round` / `counter` / `SIMD` | position 0 is `self` — the receiver is passed to a `@staticmethod` | **B** |
| 3 | `std/python/python.mojo` | `Python_import_module` / `module` / `String` | position 0 is `self` — compared against the FIRST declared parameter | **C** |
| 4 | `std/base64/base64.mojo` | `b64encode` / `result` / `String` | a name (`var result = String()`) | **D** |
| 5 | `std/os/path/path.mojo` | `_user_home_path` / `path` / `String` | a name (`var fspath = path.__fspath__()`) | **D** |
| 6 | `std/sys/_metal_print.mojo` | `_metal_os_log_chunk` / `data` / `Pointer` | a name (`unsafe_stack_allocation[… ]()`) | **D** |
| 7 | `std/memory/memory.mojo` | `unsafe_memcpy` / `src` / `Pointer` | a name, by keyword (`src=src`) | **D** |
| 8 | `std/collections/string/_unicode.mojo` | `_to_index` / `lookup` / `Span` | `Span(global_constant[… ]())` — a call the emitters route to a type CONVERSION | **D** |
| 9 | `std/collections/string/_parsing_numbers/parsing_integers.mojo` | `to_integer` / `standardized_x` / `Array` | `standardize_string_slice(x)`, which returns a non-frame `Array` | **D** |
| 10 | `std/collections/check_bounds.mojo` | `check_slice_bounds_do_asserts` / `location` / `SourceLocation` | `location.or_else(call_location[…]())` — a method call | **D** |
| 11 | `elaborate.py` | `_method_sig` / `fn` / `FunctionDef` | a name (`m`, a loop element) | **D** |
| 12 | `mojo/middle/closures.py` | `mutated_free_names` / `inner` / `FunctionDef` | a name (`inner`) | **D** |
| 13 | `mojo/middle/offload.py` | `synthesise` / `info` / `Offloadable` | a name (`info`) | **D** |

## 0. How the 13 were reproduced without a sweep

The b3 sweep's log lives in another worker's `.tmp/`, and a whole-tree sweep is
not this session's to run. The per-file verdicts are **cached in the CAS** under
`cas.formal_build_key(source, path, flags, criteria)` with the message in the
payload (`tools/formal_sweep.py`'s `_verdict_bytes`), so the row can be read back
by recomputing the key for each of the 630 files in the scope and opening the
entry:

```console
$ python3 .tmp/probe/row.py arm64     # the script this doc's numbers come from
scope: 630 files
cached 618 / not cached 12
FILE .../stdlib/std/base64/base64.mojo
  build: b64encode() declares 'result' as String, so it is compiled with
  'result' as the ADDRESS of a frame of 8-byte slots, where every field is a
  load at `base + 8k` — and every call site in this image hands it something
  else: b64encode(input_bytes, result) passes a name, 'result'
… 13 rows
```

**13 files, matching `bugs/FORMAL_sweep_work_map_2026-10-01_b3.md` §2's row
exactly**, on the same tree (`e695183a`), with no build at all. Worth keeping as
a tool: the sweep's own ledger records only path → class, so the CAUSE text is
in the per-file `.result` entries and nowhere else.

A cheap first pass that did **not** find all 13, recorded because it is the
obvious thing to try: a parse-only scan for "a function with a declared struct
parameter that this file also calls" found 46 candidate files and 10 of the 13.
It missed `check_bounds.mojo`, `python.mojo` and `philox.mojo` because
`structs_by_name` is the file's own StructDefs **plus** everything reachable
through its imports (`formal/build.py`'s `_imported_structs`), and the scan
resolved only the imports it could parse to a file with the right name. A
candidate filter that reads the real table (`formal.imports.imported_struct_defs`)
found them. **The lesson: enumerate the row from the sweep's own verdicts, not
from a re-derivation of the decision.**

## 1. STEP 1: does CPython raise on the same source?

**No — for all 13, and the four `.py` files can be asked directly.**

`elaborate.py`, `formal/types.py`, `mojo/middle/closures.py` and
`mojo/middle/offload.py` are this repository's own Python, so CPython runs them
and the answers are the programs' own:

| file | command | result |
|---|---|---|
| `formal/types.py` | `python3 -c "from formal.types import lean_trunc_defs, IntType; print(lean_trunc_defs({IntType(8, False)}))"` | prints the truncator for `t8u`/`t8s`, exit 0 |
| `elaborate.py` | `python3 -c "import elaborate; print(elaborate.type_methods(open(SRC).read(), 'Foo'))"` on a two-method source | `[('bar', ['Int'], 'Int')]`, exit 0 |
| `mojo/middle/closures.py` | `discover_closures(GimpleGen(None), parse(SRC))` on a closure source | `{'outer': {'inner': ([], [])}}`, exit 0 |
| `mojo/middle/offload.py` | `offload.synthesise_module(parse(SAXPY))` (`test_metal_codegen.py`'s own `SAXPY`) | `['_mg_offload_saxpy']`, exit 0 |

Each of those four runs the very call site the refusal names — `mask_of(IntType(w, False))`,
`_method_sig(m)`, `mutated_free_names(inner, …)`, `synthesise(s, info)` — and
none raises. So **the row is not stdlib bugs.** What it is instead is §2–§5.

The nine `.mojo` files cannot be run by CPython at all (Mojo syntax, and imports
this repo does not have), so for those the question is answered from the source:
at every one of the nine, the argument at the site is a value of the declared
type by the source's own declarations. The three that are not obvious, read:

* `std/sys/_metal_print.mojo` — `var chunk = unsafe_stack_allocation[_CHUNK_SIZE, UInt8]()`
  and `unsafe_stack_allocation` is declared `-> Pointer[Scalar[dtype], MutUntrackedOrigin, …]`
  (`std/memory/stack_allocation.mojo:35`), which is what `_metal_os_log_chunk`'s
  `data: Pointer[UInt8, MutUntrackedOrigin]` declares. Same type.
* `std/collections/string/_parsing_numbers/parsing_integers.mojo` —
  `standardize_string_slice(x)` is declared `-> Array[Byte, CONTAINER_SIZE]`
  (line 20) and `to_integer`'s parameter is declared `Array[Byte, CONTAINER_SIZE]`
  (line 54). Same type.
* `std/collections/check_bounds.mojo` — `location.or_else(call_location[inline_count=2]())`
  where `location: Optional[SourceLocation]`, so the argument is a `SourceLocation`.

**And for the whole row, the two architectures agree** (b3 §2: "identical on
arm64 and x86-64"), which is what makes it a construct and not a backend's
accident: every message is in `formal/model.py`, and both emitters read the same
shared model tables.

## 2. Group A — the false refusal, FIXED (`3e8b0803`)

`formal/types.py`'s `mask_of(t: IntType)` is called as `mask_of(IntType(w, False))`.

The check's rule is "every call site agrees with the declaration", and the
agreement test — `_argument_frames` — knew **two** of the four shapes that put a
frame ADDRESS in a callee's argument slot: a holder NAME and a placed NESTED
field. The other two are

* a **CONSTRUCTION** of a framed struct, `take(P(3, 4))`, and
* a call to a function that **RETURNS** a frame, `take(make(5))`,

and both are already lowered by both emitters: each reserves a block per site in
the caller's prologue and the call's value is that block's address
(`model.struct_constructor_sites` + `arm64_codegen._emit_frame_constructor`, and
`model.struct_returned_frame_sites` for the returned half — the same two tables
`x86_64_codegen.py:762,778` reads). So the check was calling a call site that
hands over exactly what the declaration promised a **contradiction**, and
refusing the program.

**"Cannot place" is not "contradicts", and the two were the same answer.** That
is the defect, and it is the same conflation the sibling rule is careful about
in the other direction (`formal/model.py:7085`: "empty read as agreement").

Landed: `_frame_valued_calls`, which reads the emitters' own two block tables and
puts the construction case through `model.call_lowers_as_framed_construction` —
the emitters' own dispatch predicate. That last part is what keeps `String()` (a
type CONVERSION, and a plain **word**) out of the frame set while `P(3, 4)` (a
construction, and an **address**) is in it, so lifting this cannot hand a callee
a word where it reads `base + 8k`.

Verified by EXECUTION on both architectures against CPython, not by "it builds":

| program | CPython | arm64 | x86-64 |
|---|---|---|---|
| `take(P(3, 4))` returning `p.a * 10 + p.b` | 34 | 34 | 34 |
| `take(make(5))`, same | 52 | 52 | 52 |

(the two are `test_formal_method_param_field.py`'s new
`construction_in_argument_position_agrees` and
`frame_returning_call_in_argument_position_agrees`, which carry their own CPython
transcription, so the expectation is not mine). `p.a * 10 + p.b` rather than a
sum on purpose: a read at the wrong SLOT says which field moved (43, not 34).

**The fix's reach, measured on all 13** (the whole point of the b3 map's §5
"measure the marginal effect before anyone invests"):

* **1 of 13** leaves this refusal. `formal/types.py` does, and lands on the
  **sibling** `frame_holder_disagreement_refusal` for a different function,
  `resolve(t: IntType)` — a different rule about a different parameter, which
  this construct must not swallow (see §6).
* **12 of 13 stay**, for the reasons §3–§5 give.
* **0 of 13 reach `pass`.** So the honest headline is: one false refusal removed
  and verified, thirteen files still blocked, and the reason is not this check.

## 3. Group D — the word/frame question, 9 of the 13, and NOT this construct's to answer — **and, per the re-measurement above, not reachable on this row today**

Nine files hand the parameter something this path **cannot place**, and in most of
them the thing it cannot place is a **word** where the declaration compiled the
parameter to a **frame**. Lifting the refusal there would be lifting it on
evidence that is absent, which is the whole reason the check exists (the load-
bearing case is measured: `formal/model.py`'s sibling documents the family as
"builds, runs, and dies with SIGSEGV, exit 139").

The sharpest case is `std/base64/base64.mojo`, and it is worth reading because it
is the example the enqueue quoted:

```
def b64encode(input_bytes: ImmSpan[Byte, _], mut result: String):
    …
    var result = String()
    b64encode(input_bytes, result)
```

`String` is a 3-field struct here (`std/collections/string/string.mojo`'s
`_ptr_or_data`, `_len_or_data`, `_capacity_or_data` — measured), so a parameter DECLARED `String` is
compiled as a 3-slot frame and `result._len_or_data` is a load at `base + 8`.
But `String` is in `model.IDENTITY_TYPE_CTORS`, so `String()` is lowered as a type
CONVERSION and its value is **one word** — `model.call_lowers_as_framed_construction`
says so explicitly, and `_constructor_bindings` uses that to keep the name a plain
word (its docstring records what happens otherwise: a store into an interned
`""`, SIGBUS exit 138). So `var result = String()` is a word, the parameter is a
frame, and **the refusal is telling the truth.**

**The inconsistency is upstream of the check: one name is a word where it is
constructed and a frame where it is declared.** `Pointer` and `Span` are the same
story (`std/sys/_metal_print.mojo`, `std/memory/memory.mojo`,
`std/collections/string/_unicode.mojo`: `Span` is `UNREPRESENTABLE_TYPE_CTORS`,
so `Span(…)` refuses by name). `std/memory/memory.mojo` adds a second instance of
the same family — `unsafe_uninit_move_n`'s `src: MutPointer[T, _]` handed to
`unsafe_memcpy`'s `src: Pointer[T, _]`, a legitimate implicit conversion this path
has no representation for.

**What closing this group needs, and why it is not this construct:** the CALLER
has to materialise a frame for an argument whose value is a one-word struct value,
and pass its address. That is a call-site coercion in both emitters (reserve a
block per site, copy the value's slots in, pass the address), keyed on the
callee's published `fn._frame_param_contract` — the machinery
`model.resolve_frame_parameter_contract` already reads for an IMPORTED callee.
Until that exists, "this call site hands over a word" is true, and refusing is the
answer this backend owes rather than a fault at an address it did not mean to
touch. **The remaining 9 are worth that feature, not a relaxation of this check.**

## 4. Group C — `std/python/python.mojo`: the refusal is TRUE and about the WRONG argument — **FIXED, see the re-measurement above**

```
struct Python:
    def import_module(var module: String) raises -> PythonObject:
…
Python.import_module("sys")
```

The message reads `Python_import_module() declares 'module' as String … every
call site … hands it something else: Python_import_module(Python, sys) passes a
name, 'Python'` — and the instrumented holders confirm why:

```
DBG callee=Python_import_module position=0 p=module struct=String
DBG params=['module']
DBG fn=Python_import_module holders=['module'] hstruct={ module:['String'] }
```

The method's parameter list is `['module']` — **no receiver** — while the call
carries `(Python, "sys")`. So position 0 compares the RECEIVER against the first
declared parameter, and every argument after it is off by one. Two facts make
this a message-accuracy defect rather than a wrong diagnosis:

* the program is refused either way, because an implicit receiver has no home on
  this path. Measured on the shape in isolation (`def take(m: Word)` with no
  spelled receiver): `build: Holder_take: 'self' has no home: the module-level
  symbol table is empty for this unit…`. That is the refusal the reader wants.
* and a receiver-less method is a construct the tree already models —
  `formal/build.py`'s `_receiverless_methods` exists for it. It recognises one
  from an **empty parameter list** and not from a `@staticmethod`, which is the
  same gap as §5's.

So: one line of diagnosis-quality work, no coverage. Not fixed here; it is a
property of the method-call rewrite, not of this check.

## 5. Group B — `std/random/philox.mojo`: a `@staticmethod` is compiled as an instance method — **FIXED, see the re-measurement above**

```
struct Random:
    def step(mut self) -> SIMD[.uint32, 4]:
        var counter = self._counter
        …
        counter = self._single_round(counter, key)
…
    @staticmethod
    def _single_round(counter: SIMD[.uint32, 4], key: SIMD[.uint32, 2]) -> SIMD[.uint32, 4]:
```

Instrumented, the refusal is over position 0 of a call that should not have a
position 0:

```
DBG callee=R__single position=0 p=counter struct=Vec     # the reproducer
DBG params=['counter']
DBG fn=R__single holders=['counter', 'self'] hstruct={ self:['R'], counter:['Vec'] }
```

`self` is in the `@staticmethod`'s holder set, and the call site is rewritten to
`R__single(self, counter)` — **two arguments to a one-parameter function.** With
the declared-parameter check lifted the build says exactly that, and stops:

```
build: call R__single(): too many positional arguments (2 for 1 parameter(s);
       the parameters are ['counter'])
```

**This is a neighbour's construct, and it is measured here so that whoever holds
it does not have to start from nothing.** Two independent halves, both one line,
both in `formal/build.py`:

1. **the definition half** — `formal/build.py:2498` seeds `self` as a frame
   holder for every method of a framed struct, from `model.struct_receivers`,
   whose `out = {"self"}` seed is unconditional and whose `@staticmethod` skip
   only stops the method's FIRST PARAMETER from being added. Patching that
   seeding with `and F.method_receiver_kind(fn)` removes `self` from
   `R__single`'s holders — measured.
2. **the call half** — `_receiverless_methods` (`formal/build.py:7499`) collects
   methods that take no receiver from an **empty parameter list**, so a
   `@staticmethod` with parameters is not in it and `_rewrite_method_calls`
   prepends the receiver. Patching it with `or not F.method_receiver_kind(m)`
   rewrites the call to `R__single(counter)` — measured.

`fire_compiler.method_receiver_kind` is the tree's single rule for this question
and already has five call sites reading it (`mojo/middle/coro.py` twice,
`mojo/middle/module_shared.py`, `mojo/backend_gimple/cpp_async.py`,
`mojo/backend_gimple/emit_methods.py` by delegation); two readers that consult
only the parameter list are the defect, and `struct_receivers`' unconditional
`out = {"self"}` is the first of them.

**Both halves together are still not enough for this file**, and saying so is the
useful part: with them applied the site becomes `R__single(counter)` and the
refusal moves to "passes a name, 'counter'" — `var counter = self._counter` is a
field read of a `SIMD` field of a framed struct, and the NESTED-frame placement
(`model.struct_nested_frame_fields`) does not place it, because the field's type is
the generic `SIMD[.uint32, 4]` rather than a plain struct name. So `philox.mojo`
is at least two constructs, and the second one is worth its own measurement.

Filed as `bugs/FORMAL_staticmethod_is_compiled_as_an_instance_method.md`.

## 6. What is deliberately NOT changed

* **The two rules stay two rows.** `frame_holder_disagreement_refusal` ("One
  parameter, two kinds of value", 2 files) compares the call sites with EACH
  OTHER; this one compares them with the DECLARATION. They are separate causes
  and `formal/types.py`'s remaining refusal is the second rule, on `resolve`,
  not this one on `mask_of`. Merging them would lose exactly the information the
  map's table carries.
* **`formal/types.py` does not build yet, and this doc does not claim it does.**
  It cleared THIS refusal; `resolve(t: IntType)` is behind the sibling one, whose
  sites include `resolve(infer_expr(s.value, vtypes, call_types))` — a call whose
  return type nothing establishes — and `resolve(DEFAULT_INT_TYPE)`. Whether that
  is decidable is the sibling's measurement to make.
* **The bare `fill(raw)` case still refuses.** `d4.mojo` — a declared `Cell`
  parameter reached with an `Int` local — is the load-bearing case and is a test
  case (`refuse_a_plain_word_at_every_site`); the fix does not touch it, because
  a bare name that is not a holder is still a word.

## 7. Reproducing every number here

```console
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove .tmp/probe/d4.mojo     # still refused
$ python3 tools/memslot.py --gb 8 --label t1 -- \
      python3 test_formal_method_param_field.py                        # 18/18, both arches
$ python3 tools/memslot.py --gb 8 --label sweep13 -- \
      python3 tools/formal_sweep.py -j3 -t 600 -M 4 $(cat .tmp/probe/row13.txt)
      # the 13, before and after 3e8b0803: one file moves, and where it lands
$ python3 -c "from formal.types import lean_trunc_defs, IntType; \
      print(lean_trunc_defs({IntType(8, False)}))"                    # the §1 oracle
$ python3 tools/formal_sweep_causes.py --min 4 .tmp/sweep-arm-b3.txt   # the row as first counted
```

## 8. Related

* `bugs/FORMAL_receiver_stored_in_a_field.md` §2 — the sibling row this one was
  split out of, and the 7-line reproducer this construct's docstring still uses.
  **Its §2 claim that the base64 case is "a contradiction in the source" is
  wrong**, and §3 here is the measurement: `b64encode(input_bytes, result)` with
  `mut result: String` is exactly the declared type at every call site. The
  contradiction is between the WORD `String()` produces and the FRAME `String`
  compiles to, and it is in this compiler's model, not in the stdlib.
* `bugs/FORMAL_field_set_method_name_and_kwarg_blind_spot.md` — the same
  `struct_field_names` derivation reads `Pointer` as 13 fields and `Span` as 6,
  of which 10 and 2 respectively are METHOD names. Measured here for the same
  two types; it does not change their framed-ness (both have 3+ real fields) but
  it is why a refusal quotes "13 fields" for a pointer.
* `bugs/FORMAL_wide_receiver_by_reference.md` — the design this refusal protects,
  and the SIGSEGV measurement that says it is load-bearing.