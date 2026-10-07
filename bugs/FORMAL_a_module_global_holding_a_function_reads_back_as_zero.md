# A module `global` holding a FUNCTION reads back as 0, and a direct call through it does not link

**Area:** FORMAL (module global storage). Found 2026-10-05 on
`work/formal28-4` while pinning `passing/global-slot` in
`test_formal_specialization.py`, which is a row of
`bugs/FORMAL_function_value_calls_are_not_proved_to_be_calls.md`'s fix — see
"What this is NOT" at the foot, because the row deliberately stops at the
integer case and this is why. **NOT FIXED.** Filed rather than fixed: the
mechanism is `_static_initializer`, which is
`bugs/FORMAL_module_state_no_storage.md`'s subject and a project.

## What was run

Two spellings of the same fact — a module-level name bound to a function, read
by a function that declares it `global` — and they fail in two different ways.

**1. read as a value: it builds, runs, and prints nothing.** A silent wrong
answer, which is the worse of the two.

```mojo
def dbl(x: Int) -> Int:
    return x * 2

var g = dbl

def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    global g
    print(apply_arg(3, g))
    return 0
```

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o i_arm64 prog.mojo
build: rc=0
$ ./i_arm64 ; echo "run rc=$?"
run rc=0            # and it printed NOTHING
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o i_x86_64 prog.mojo
build: rc=0
$ ./i_x86_64 ; echo "run rc=$?"
run rc=0            # and it printed NOTHING
$ python3 fire.py run prog.mojo
6
```

`fire.py run` answers `6` (`dbl(0) + dbl(1) + dbl(2)`). Both architectures print
the empty string. `g` is being read as **0** — the null address — and the call
through it is the same indirect branch this path emits for every other function
value, so it returns without doing anything.

**2. called by name: it does not link, and says so.** Also a refusal rather than
a wrong answer, and the message is about a different thing entirely:

```mojo
def main() -> Int32:
    global g
    print(g(21))
    return 0
```

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o i prog.mojo
build: prog.mojo: the image would bind 1 symbol(s) that nothing provides, so it
could not be loaded: g. `g` is a call this build emitted and nothing provides
it, so that call is not lowered on this path: this backend has no call to bind
there, which is a fact about the PROGRAM and not about the link line. Write the
operation out, or bind the name from a library that provides it. Every name in
this list is one of the calls named above, so nothing about the link line is
left to explain. (Provider check: asked the C library (dlsym).)
```

Identical on x86-64. `fire.py run` answers `42`.

The second message is a symptom of the same fact: a name that is a module-level
FUNCTION is normally **folded** — the substitution path puts the function's entry
address in at each read, which is why `var g = dbl; return g(5)` works inside
`main` (`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md` §1 measures
that spelling at exit 10). A `global g` declaration makes the name MUTABLE, so
`collect_global_slots` gives it a `__DATA` slot instead — and that is where the
folding stops.

## The root cause, measured on the slot table

```
$ python3 - <<'PY'
import fire_compiler as F, formal.model as M
src = ("def dbl(x: Int) -> Int:\n    return x * 2\n\n"
       "var g = dbl\n\ndef main() -> Int32:\n    global g\n"
       "    print(g(21))\n    return 0\n")
tree = F.Parser(F.py_tokenize(src)).parse_module()
fns = [n for n in tree if isinstance(n, F.FunctionDef)]
for name, slot in M.collect_global_slots(
        [n for n in tree if not isinstance(n, F.FunctionDef)], fns).items():
    print(name, slot.init, slot.kind, getattr(slot.site, "value", None))
PY
g ('unknown', None) None IdentExpr(name='dbl', line=4, col=8)
```

`GlobalSlot.init` is `("unknown", _)`, which `build_data_image` lays out as
**zeros**, and `kind` is `None` so `global_slot_kind("g")` answers `None` too.
`("unknown", _)` is the initializer `_static_initializer` produces when it has
no static value for the expression — and a function read as a value is exactly
that, because it is a link-time ADDRESS and `_static_initializer` computes
integers, strings, blobs and frames.

So the chain is one fact stated twice:

1. `_static_initializer(IdentExpr('dbl'))` → `("unknown", None)`. It has no
   case for a symbol whose value is a code address, and the four it does have
   are the four `GlobalSlot.init`'s own docstring lists.
2. `build_data_image` writes a zero for an `unknown` slot, on the documented
   ground that a slot with no static initializer is written by the module body —
   and here the module body does not write it either, because
   `filled_by_body` is False (nothing in the module body *stores* `g`; the
   `var g = dbl` is the initialiser, and a function is folded rather than
   stored).

The `filled_by_body` half is what makes this a silent wrong answer rather than a
refusal: `static_initializer_refusal_reason` is what must NOT refuse a slot the
body writes, and this slot is written by NEITHER, so nothing complains.

## What has to change

**`_static_initializer` needs a case for a name bound to a function of this
unit**, and the word it produces has to be an address the dynamic linker
REBASES — the same treatment `GlobalSlot`'s own docstring gives the three
address forms (`("blob", …)`, `("str", …)`, `("frame", …)`), and
`build_data_image`'s `is_address` fixup list is where that decision is already
made. So it is one new `init` kind plus one entry in the address classification,
and the fold-vs-slot question is settled for free: a slot whose initializer is
an address does not need the fold, and the direct-call spelling (2) stops
emitting a `bl g` for a name nothing provides.

**Until then, the honest answer at the boundary is a REFUSAL, and this is a
silent wrong answer.** That is the part worth acting on independently of the
project: `collect_global_slots` already knows the difference between a slot whose
initializer it computed and one it did not, and `("unknown", _)` is precisely
"this build has no static value for this name". A module global in that state
which is read as a VALUE should be refused by name — the same rule, and for the
same reason, as `static_initializer_refusal_reason`'s arm for the slots that DO
have an initializer. That is a bounded change in `formal/model.py` and
`formal/build.py` and it needs no `lib/ProofLib.lean` work at all.

**Do not widen this to `static_initializer_refusal_reason` wholesale.** Its
current job is to NOT refuse a slot the body writes, and this slot is not one of
those; a name that reads as a value is a narrower question than "may this slot
exist", and folding the two would refuse every computed global
(`G = compute()`), which is a case
`bugs/FORMAL_module_state_no_storage.md` §1 landed deliberately.

## The exact next step

1. The refusal, as above: in `formal/build.py`, at the same chokepoint that
   asks `static_initializer_refusal_reason`, ask one new reader —
   `model.module_global_value_refusal(name)` — for a name whose slot initializer
   is `("unknown", _)` AND which some read in this image uses as a value. Both
   conjuncts, or it refuses every computed global.
2. The address initializer, in `_static_initializer` + `build_data_image`, which
   is the fix and needs the address-rebase decision stated once.

Step 1 is a day and it converts a silent zero into a diagnostic. Step 2 is the
project, and it is the same `__DATA` lifetime argument
`bugs/FORMAL_module_state_no_storage.md` §2 is already making about an EXPORTED
slot — a function address in a data segment is a relocation this target's dyld
has to honour, which is the question that document's own measurement says is
**not** available for `__DATA` on this target. So read that doc before starting
step 2, because its answer decides this one.

## What this is NOT

This is **not** part of `bugs/FORMAL_function_value_calls_are_not_proved_to_be_calls.md`,
whose walk-visible shapes are closed by `formal/model.py::_container_element_writes`
and friends. Two reasons it is separate, both worth stating because the boundary
is easy to blur:

  * the reader that fix adds (`_global_slot_value`) asks the SLOT TABLE for the
    module's binding of a `global` name, and `global_slot_kind("g")` answers
    `None` here, so the reader is SILENT on this program — correctly. It cannot
    tell a function from a name it knows nothing about, so the walk has nothing
    to refuse and the wrong answer happens further downstream, in the slot's
    initializer;
  * `test_formal_specialization.py`'s `passing/global-slot` row therefore covers
    the INTEGER slot (`var g = 17`) and not this one. A row asserting `6` here
    would be asserting a build this path does not do, and the row's docstring
    says so where the next reader of it will find it.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
mkdir -p .tmp/gv && cd .tmp/gv
cat > prog.mojo <<'EOF'
def dbl(x: Int) -> Int:
    return x * 2

var g = dbl

def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    global g
    print(apply_arg(3, g))
    return 0
EOF
for a in arm64 x86_64; do
  python3 "$OLDPWD/fire.py" build --formal --no-prove --backend=$a -o i_$a prog.mojo
  echo "$a build rc=$?"; [ -x i_$a ] && { ./i_$a; echo "$a run rc=$? out=[$(./i_$a)]"; }
done
python3 "$OLDPWD/fire.py" run prog.mojo     # 6
```
