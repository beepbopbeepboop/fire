# a one-word constructor that REBINDS its receiver to a frame is built and exported as a dylib, where it used to be refused

**Area:** FORMAL (the frame-escape check at a dylib boundary; `test_formal_dylib.py`
has been red on it since at least 2026-10-04 and `formal-dylib` is registered
with no `expect=`, so this is an UNDECLARED red on `master`). Found 2026-10-04 on
`work/formal19-4`, while running the formal suites behind
`bugs/FORMAL_module_state_no_storage.md`'s work; not that claim's subject and not
fixed here.

**Status: CONFIRMED on `master`, reachable, and currently contained.** What
builds is a hazard with no live consequence yet — §3 says why the consumer side
is refused today, which is what makes this a bug about a CHECK rather than about
a wrong answer, and what would make it a wrong answer the moment that second
refusal moves.

## 1. What was run

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_dylib.py
formal dylib: PASS=22 FAIL=1
  FAIL  a receiver write-back is not a returned frame
        a constructor that ASSIGNS a frame to its own one word was built as a
        dylib: the frame it hands back is one the CALLEE built, and an importer
        has no way to learn the width of the block it must reserve
```

`tools/suite.py`'s registration for `formal-dylib` says "14 PASS / 0 FAIL"
(`python3 test_formal_dylib.py`, measured 2026-10-03), so the file has grown from
14 to 23 cases and this one went red somewhere in between. It is NOT a
consequence of the 2026-10-04 changes in `formal/model.py` / `formal/build.py`
(`work/formal19-4`): measured with those two files restored from `HEAD`
byte-for-byte, the same `PASS=22 FAIL=1`.

## 2. The two programs, which differ in one line

`test_formal_dylib.py::test_a_receiver_writeback_is_not_a_returned_frame` builds
two modules that differ only in the constructor's second line, and its own
docstring is the specification:

```
struct Inner:                       struct Inner:
    var a: Int                          var a: Int
    var b: Int                          var b: Int

struct Box1:                       struct Box1:
    var inner: Inner                    var inner: Inner

    def __init__(out self, a, b):        def __init__(out self, a, b):
        self.inner.a = a   # WRITING       self.inner = Inner(a, b)   # ASSIGNING
        self.inner.b = b                    # ^ the receiver, rebound to a frame
```

  * **WRITING THROUGH** writes the CALLER's block in place, so the appended
    `return <receiver>` is a no-op and there is no escape. It builds, and its
    manifest is `['Box1___init__', 'mk']` — measured.
  * **ASSIGNING A FRAME** hands back a block the CALLEE built. The test says it
    must be refused, and it is what this build does instead:

```
$ python3 fire.py dylib --formal --no-prove -o .tmp/rb.dylib .tmp/rb.mojo
Built: .tmp/rb.dylib
```

So the frame-escape check at a dylib boundary no longer fires for this shape.

## 3. Why it is contained today, and what it would take to uncontain it

Every consumer spelling is refused at the CONSTRUCTION SITE, before the exported
constructor is ever called:

```
# .tmp/p2/main.mojo:  from rb import Box1
#                     var b = Box1(3, 4)
$ python3 fire.py build --formal --no-prove -o .tmp/p2/main .tmp/p2/main.mojo
build: constructing Box1 with arguments is a call to a user-defined `__init__`
whose body this path does not inline: `Inner(…)`, a construction of a struct
whose receiver is a frame: its block is reserved per call SITE in the prologue
of the function whose body names the call, and a body inlined into a
construction elsewhere has no such site. …

# and the WRITE-THROUGH half, from the same consumer shape
build: … whose body this path does not inline: a local assignment
(`self.inner.a = …`). …
```

So the export is published and unreachable in practice, and nothing computes a
wrong answer today. **That is the wrong reason for the check to be off.** The
check is what makes the second refusal unnecessary: an importer is refused
because the callee is a frame-returning one, and the moment THAT is answered —
by `formal16-2`'s frame handling, by a construction protocol, or by a widened
inline rule — the published `Box1___init__` becomes callable and the escape
becomes live, with no check left to catch it.

## 4. The exact next step

Find which change removed the refusal and put the frame half of it back, or
decide deliberately that a rebinding receiver is no longer an escape on this
path. The candidates, from the tree:

  * `model.py`'s one-word receiver treatment (`_return_the_receiver` and
    `one_field_answer`) — the appended `return <receiver>` is the mechanism the
    test's docstring names, so a change that stopped appending it for a
    REBINDING receiver would take the refusal with it. Measured: the rebinding
    module's manifest is `['Box1___init__', 'mk']`, the same shape the
    write-through one has, which is consistent with both being classified the
    same way now.
  * `formal/build.py`'s receiver-rebind and frame-holder checks
    (`check_receiver_rebinds`, `check_frame_holder_rebinds`), which run in
    `_run_late_checks` and are the dylib-boundary half of this.

The decision is not obviously "refuse": `self.inner = Inner(a, b)` in a
one-word struct is a REBINDING of the receiver rather than a mutation of it, and
the module now simply does not inline it. So the honest answer may be that the
callee must not publish such a constructor — which is what the test says — and
the fix is to restore the refusal rather than to relax the test. **Do not delete
or relax the test row**: it is a documented invariant with a measured reason, and
`tests` are not where a decision about frame lifetime belongs.

## 5. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_dylib.py
# then the two modules by hand, and the manifest:
python3 fire.py dylib --formal --no-prove -o .tmp/rb.dylib .tmp/rb.mojo
python3 -c "import json;print(sorted(e['name'] for e in json.load(open('.tmp/rb.dylib.manifest.json'))['exports']))"
```