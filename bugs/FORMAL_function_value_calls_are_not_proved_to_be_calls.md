# A call through a VALUE is not proved to be a call: the word might not be an address

**Status 2026-10-05 (`work/formal19-3-r2`): the PASSING end's caller-LOCAL half
landed too, on both architectures, so what is left of that end is only the
shapes a walk cannot SEE — `apply_arg(3, xs[0])` with `xs` a local list, which
this round measured as still building and still trapping, is now refused by name.
The doc stays because the CALLING end's undecidable half and the dylib boundary
are still the subject.** See "What is still open" below, which is the current
status of both halves.

**Status 2026-10-04 (`work/formal19-3`): the DECIDABLE half of the analysis below
landed, on both architectures, and the doc stayed because the undecidable half was
still the subject.** Measured before the change and repeated by the test it
landed with:

```mojo
def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    return apply_arg(3, 17)
```

built on both machines, branched to the number 17, and died of SIGBUS (exit 138)
on arm64 and SIGSEGV (exit 139) on x86-64 — the same two verdicts as the
reproducer below, and CPython raises `TypeError` on the same text. **It is now
refused at build time**, by `formal/model.py::not_a_code_address_refusal`, and
both architectures print the same sentence.

**What landed is both of the two analyses "What closing it would take" names,
restricted to the part each reader can DECIDE.** That restriction is not a
shortcut; it is the discipline every other check on this construct already keeps
(`value_callee_can_hold_a_function` is the declaration and nothing else), and it
is what makes the addition safe on a corpus nobody can re-sweep cheaply:

| half | where it is asked | what it reads | what it needs |
|---|---|---|---|
| the PASSING end — "every call site must pass a function" | `formal/build.py`'s name-placement walk, beside `function_value_argument_refusal` | the argument's own SHAPE: a literal, a container literal, a subscript of one, arithmetic over either, a comparison, a type read as a value, or a parameter of the CALLER whose annotation cannot hold a function | the callee is a function of THIS unit — it is not in `callee_defs` otherwise |
| the CALLING end — "every site that writes the name must write a function" | both emitters, at the line that has already decided the call goes through a value | the calling function's agreed `ValueKinds` kind AND every syntactic write site | the caller's `ValueKinds`, which each backend already has |

The PASSING end is guarded on `parameters_called_through_a_value`, so `f(17)`
is only refused for a function that actually branches through that parameter —
without that conjunct every call in the corpus would be refused. The CALLING end
needs BOTH kinds of evidence and neither alone is right: `ValueKinds` seeds an
unannotated parameter as an integer (its own header says a word is one), so
`var g = f` inside a function that received `f` is an integer to the model, and
`test_formal_specialization.py`'s `via_local` — the CORRECT program and this
construct's own positive row — was refused by the model alone. Measured, both
architectures, before the syntactic conjunct was added; it is why
`_binding_values` records an unpack target, a loop target, a `with … as` and an
augmented assignment as UNDECIDED rather than as their value.

**The PASSING end's caller-LOCAL half landed 2026-10-05 (`work/formal19-3-r2`),
and what is left of the PASSING end is now only the shapes a walk cannot see:**

```mojo
def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    var xs = [10, 20, 30]
    return apply_arg(3, xs[0])      # was: BUILT, and trapped at run time
```

`formal/model.py::caller_local_holds` and `::caller_local_element_holds` read the
caller's own statements, and both architectures now refuse it with the one
message, the same sentence:

```
main: `xs[0]` is called as a FUNCTION and the source says it holds an element
read out of a container literal, passed to `apply_arg()` as parameter `f`, which
`apply_arg()` calls through a value — …
```

**Why this half needed a different rule from the calling end's, and the reason
is arithmetic rather than semantics.** `callee_word_is_not_an_address` needs TWO
kinds of evidence — the value model's agreed kind plus every syntactic write
site — because each backend already holds a `ValueKinds` and the model's own
default ("a word is an integer") would otherwise refuse the correct
`via_local` program. **`formal/build.py` holds no `ValueKinds`, so this reader
takes the one leg that needs only the SOURCE**: unanimity over
`_binding_values`' sites, with at least one site required so a name with no write
here is silence rather than a vacuous agreement. A site `_binding_values`
records as `None` — an augmented assignment, an unpack target, a loop target, a
`with … as`, exactly the shapes its own docstring names — makes the answer
silence, which is the conservative direction and the one that matters: this
reader cannot claim a name is a number when a statement writes a word it does
not understand.

**The element case is narrower than the value case on purpose, and the
narrowness is the finding.** An element of a container CAN be a function — a
list of them is `stdlib/std/algorithm/backend/cpu/map.mojo`'s own shape — so
`xs[i]` on a list is not an answer, which is why this doc's reader stopped at "a
subscript of a NAME". `caller_local_element_holds` narrows it to the one case
where the walk can see every element the subscript could ever hand back: **every
syntactic write of the name is a container LITERAL, and every element of every
such literal is itself something the module's own
`value_argument_is_not_an_address` refuses as an address.** A name bound to `[]`
and then appended to is silence, because `xs = []; xs.append(dbl)` is a list of
functions. `test_formal_specialization.py`'s `…and a list of FUNCTIONS is still
one, on both` is that boundary run rather than asserted: the same subscript with
a function among the elements builds, runs and answers CPython on both
architectures, which is what says the reader reads the ELEMENTS and not the
spelling.

**One ordering decision came with it, and it is in `formal/build.py` rather than
in `model.py` because it is about which witness is BETTER.** The passing-end
loop now skips a position whose own parameter DECLARATION refuses:
`value_callee_can_hold_a_function` is asked first, because `call_container(xs,
4)` against `f: List[Int]` is refused by `callee_value_refusal`, whose message
names the type and the parameter, where this pass's reader would answer "an
integer" or "a container". Measured: without the guard
`test_formal_specialization.py`'s `the two remaining refusals of a value call`
went red with the row's own `List[Int]` needle missing — the two readers are
then not disagreeing, because only one of them fires.

**Corpus, without a sweep** — the same cheap form the first half of this change
used, and over-approximating: the two readers were driven over every `.py` and
`.mojo` in this tree (482 files parsed) asking only "would any call site's
argument shape reach them", with the `ValueKinds` conjunct dropped so every hit
would be a file that MIGHT newly refuse: **0 hits**. That is a syntactic
over-approximation and not a substitute for a sweep, which the machine's
per-architecture lock was holding for another worker; what it proves is that the
two new readers' triggers do not occur in the corpus at all.

Measured, this tree, after the change:

```
python3 test_formal_specialization.py    PASS=19 FAIL=0   (three new rows)
python3 test_refusal_taxonomy.py         PASS (271/271 checks, 47 families, 67 causes)
python3 test_formal_run.py               PASS=1024 FAIL=0
python3 test_formal_value_model.py       PASS=82 FAIL=0
python3 test_formal_monomorph.py         PASS=24 FAIL=0
python3 test_formal_dylib.py             PASS=24 FAIL=0
```

**What is still open, and each item says which of the two halves it belongs to:**

* **the PASSING end, and it is now only what a walk cannot see** — a write from
  a function this unit does not compile (`g = mk()`, where `mk` is in a linked
  image and this module has no body), an `append` into the container whose
  element is then subscripted, a `global` slot, and a subscript of a DICT name
  (`d[k]`, which can hand back a function and which no spelling distinguishes
  from a list). Each is silence rather than a wrong answer, and each is a shape
  `_binding_values`' own residual paragraph names.
* **the PASSING end across a dylib boundary** — a callee in another image is not
  in `callee_defs`, so its parameters are not in the table and nothing is
  checked. This is the half the doc's own §"What closing it would take" says
  "crosses a dylib boundary", and it needs the callee's body or a manifest row
  that says which of its parameters are called through a value.
* **the CALLING end for a name bound by a shape this walk does not name.** Stated
  in `_binding_values`' docstring rather than implied: a site it cannot see is a
  site whose agreement is not established, and the reader answers permissively
  there.
* **the runtime check**, still declined for the doc's own reasons (O(n)
  comparisons per call, no coverage of another image, and a static property
  turned into a runtime one).

**Measured, this tree, at the time the decidable half landed (the tables above
are the current ones; this one is kept because it is what the decidable half was
verified against):**

```
python3 test_formal_specialization.py      PASS=18 FAIL=0   (17 rows unchanged)
python3 test_formal_run.py                 PASS=1024 FAIL=0
python3 test_formal_value_model.py         PASS=82 FAIL=0
python3 test_formal_monomorph.py           PASS=22 FAIL=0
python3 test_formal_dylib.py               PASS=24 FAIL=0
python3 test_refusal_taxonomy.py           PASS (267/267 checks, 45 families, 66 causes)
```

and the corpus question this change had to answer without a sweep — "does any
file in this repository newly refuse?" — by driving both readers over every
`.py`/`.mojo` in the tree with the `ValueKinds` conjunct dropped, so every hit
would be a file that MIGHT newly refuse: **0 hits over 299 non-test files and 0
over the 169 `test_*.py`**, on this tree. That is a syntactic over-approximation
and not a substitute for a sweep, which the machine's per-architecture lock was
holding for another worker at the time; it is the cheap form of the check and
what it proves is that the two readers' triggers do not occur in the corpus at
all.

**Area:** FORMAL (the value model). Found 2026-10-03 on
`work/formal18-tile-specialization`, while landing the lowering this file is
the boundary of — a function value is a CODE ADDRESS and `f[a, b](x)` through
a word is one `BLR` / `CALL r64`
(`bugs/FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`
§"What landed"). **The residual below is what is NOT FIXED; the decidable half
is.**

## What is refused, and what is not

```mojo
def apply(size: Int, f, func):      # `f` is unannotated — the common case
    for i in range(size):
        f(i)                        # one BLR / CALL r64 through the word
```

lowers, and the word is whatever the CALL SITE put there. This build does not
check that the word is a code address, and it cannot at the call: the callee
cannot see its call sites, and the call sites cannot see the callee's body
across a dylib boundary. So

```mojo
def main():
    apply(3, 17)                    # CPython: TypeError, 'int' object is not callable
```

builds, and the image branches to address 17.

**The failure mode is a TRAP, not a wrong answer.** An indirect branch to a
word that is not code lands on an unmapped page, so there is nothing to
execute: measured, SIGBUS (exit 138) on arm64 and SIGSEGV (exit 139) on
x86-64. That is the loud end of this backend's range
— `bugs/FORMAL_known_limits.md`'s standing complaint is about refusals that
"build, run, and return a number the source never wrote", and this is not one.
What it costs is a diagnostic: a program whose own bug it is used to be told
about at build time is now told about by the kernel.

### And the one function whose value is NOT its address: a lifted closure

```mojo
def make(n):
    def add(x):
        return x + n                # a CAPTURE, lifted as a leading parameter
    return add                      # `add` is now `make_add`, with `n` prepended
def main():
    a = make(10)
    print(a(5))                     # CPython: 15
```

is **refused**, and refused by a sentence that names the rename
(`formal/model.py::lifted_closure_value_refusal`, reached from
`check_module_symbols` through `model.pre_lift_def`). Two facts about it belong
here rather than only in the diagnostic, because both bear on the open question
above:

- **A plain function's value IS its address on this path** — each backend's
  `_load_var` materializes it and `_emit_call` branches through it — so
  "a function is not a value" stopped being true in this project, and the
  now-dead `function_value_refusal` would be the wrong sentence to reach for.
  What is refused here is a narrower thing with a name: a **lifted** function.
- **A lifted closure's value would have to be more than its address.** The lift
  prepends captures as parameters (`make_add(n, x)`), so the word would carry an
  environment as well as a code pointer, and the capture ABI this path
  implements is a CALL-SITE rewrite in the scope that DEFINES the closure —
  there is no call site at `return add` to pass them at. Materializing the bare
  address would therefore print a number nobody wrote and, called back through,
  drop the capture.

So this shape needs no part of the analysis below to be closed before it can be
*named*, and it is named. **Closing it is a feature and not a check**: it means
giving a lifted function a value representation — an environment struct
allocated at the `return`, passed through the word, and unpacked at the
indirect call — and the compiled path already has both halves of that machinery
under different names (`_gen_lifted_closure` allocates `_env`; see
`bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md` for what the
allocation costs today). It is not filed as its own FORMAL doc because nothing
here is refused-by-accident and nothing traps: it is refused, and the sentence
says what to write instead.

## What IS checked, and why each check is the honest one available

Both are in `formal/model.py`, both asked from both backends, and both read the
caller's DECLARATION rather than its dataflow:

* **`value_callee_can_hold_a_function(ann)`** — a parameter declared a
  container this path subscripts (`List[Int]`, `String`, `SIMD`) or a scalar
  (`Int`, `Bool`, `DType`) cannot hold a code address, so a call through it is
  refused by name (`callee_value_refusal`). This is the only soundness check
  available locally and it catches the shape a corpus actually writes. A
  container-typed `f(x)` is a program its own declaration refutes.
* **`value_call_bracket_reading(fn, name, ann)`** — a bracketed callee through a
  value is a specialization or an index, and the declared type is the only thing
  that can say. `Some[…]` and a `def[…]` function type cannot be subscripted on
  this path, so their brackets are comptime parameters; a container's are an
  index; an unannotated parameter is refused rather than guessed at.

An UNANNOTATED parameter is allowed through, deliberately: it is the common
spelling (`stdlib/std/algorithm/backend/cpu/map.mojo`'s own `func`) and a
function value is the most likely thing it holds. That is the permissive
direction on purpose, and it is where the residual lives.

## What closing it would take

A whole-module analysis over every value a callee might have been handed:

* for each name called through a value, every site that WRITES it — an
  assignment, an augmented assignment, a loop target, a `with … as`, a
  container store, a `return` — must be a bare read of a function of this
  image;
* for each PARAMETER called through a value, every call site of that function
  must pass a function-name read in that position, which needs the callee's
  body and the caller's body at once and crosses a dylib boundary.

Both halves are syntactic and neither is cheap to get right: `formal/build.py`
already has a family of walks over the same shapes (`_names_bound_in`,
`bound_names_in_order`) and each has its own documented imprecision, and a walk
that MISSES a write is not a missed warning — it is a program that traps
instead of being refused.

**A cheaper alternative exists and is NOT taken, because it would be a
property of the wrong thing**: emitting a runtime check that the word is one of
this image's function entry addresses. It is O(n) comparisons per call on a
target whose programs are small, it cannot cover a function in another image
(whose addresses are not known at build time), and it turns a static property
into a runtime one, which is the opposite of what this backend is for.

## Reproducing the residual

```sh
export PATH=/opt/homebrew/bin:$PATH
cat > .tmp/fv_bad.mojo <<'EOF'
def apply(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    return apply(3, 17)
EOF
for a in arm64 x86_64; do
  python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=$a -o .tmp/fv_bad-$a .tmp/fv_bad.mojo
  .tmp/fv_bad-$a ; echo "[$a] exit=$?"
done
```

Measured: both BUILD; the arm64 image dies of SIGBUS (exit 138) and the x86-64
image of SIGSEGV (exit 139). The interpreter refuses the program outright
(`TypeError: 'int' object is not callable`), so the two engines disagree about a
program they both reject — which is the honest statement of this file's
subject.

Pinned, so the residual stays visible rather than becoming folklore:
`test_formal_specialization.py`'s `the two remaining refusals of a value call`
pins the CHECKED side of it (a keyword, an unreadable bracket, a
container-typed callee) on both architectures, its `a function read as a value
is its code address` row pins the POSITIVE side (`call_it(plain, 5)` and
`bare(add, 4)` / `var g = f; g(x, 100)`, which run and answer CPython on both),
its `a word the source says is not an address is refused` row pins the five
sources of evidence — the argument's own shape, the caller's parameter
declaration, the caller's LOCAL's write sites, an element of a container literal,
and the calling end — with the oracle checked through `fire.py run` rather than
assumed and the two architectures required to produce the SAME sentence, and its
`…and a list of FUNCTIONS is still one, on both` row pins the boundary the
element reader draws (a subscript whose literal holds a function still reaches
the function). This file is what the UNCHECKED side is.
