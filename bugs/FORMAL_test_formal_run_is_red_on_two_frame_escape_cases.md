# `test_formal_run.py` is red on two cases in the frame-escape walk, on
# `master`, and one of them is a CRASH rather than a wrong answer

**Area:** FORMAL — `formal/build.py::_collect_one_field_dropped_stores`'s
`_receiver_frame_escape` arm (the `node.target` read at line 4934) and the
subclass-construction refusal that `test_formal_run.py`'s
`constr_refuse_an_undeclared_base_by_name` expects to see.
Found 2026-10-04 on `work/formal16-4` while landing the floor-division fix, by
running the suite that covers that fix. **NOT fixed here: both are in another
worker's claim** (`formal23-5`'s `FORMAL_one_word_ctor_of_a_nested_frame_is_
unexportable.md`, whose §0 records the change that introduced the crash, and
`formal16-2`'s `FORMAL_a_subclass_drops_the_bases_fields.md` /
`FORMAL_an_exception_constructed_with_its_message_has_no_field_to_hold_it.md`).
Filed because a red suite is evidence of nothing unless somebody says which
change made it red.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
  FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but not
        with the expected words "derives from 'Widget', which this image does not
        declare": … with no user-defined constructor, a struct's fields are filled
        in DECLARATION ORDER from positional arguments and there is no other form, …
  FAIL  one_field_mutator_that_also_returns_a_frame_is_refused: --backend=arm64
        refused, but not with the expected words 'two hidden-word conventions':
        …/formal/build.py", line 4934, in _collect_receiver_frame_escapes
        target = node.target
                 ^^^^^^^^^^^
        AttributeError: 'VarDecl' object has no attribute 'target'

formal run: PASS=962 FAIL=2
```

962 pass, 2 fail, and the rest of the suite is green — including every
division case. Neither failing case contains a division.

## 1. The crash: `_receiver_frame_escape` reads `node.target` off a `VarDecl`

`0dfed3c5` ("formal: a mutator that hands a frame back through its receiver is
not exportable", 2026-10-04, on `master`) added the arm, and the arm walks
statement nodes that are not all assignments:

```python
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, (F.AssignStmt, F.VarDecl)):
            continue
        target = node.target            # ← VarDecl has `name`, not `target`
```

`fire_compiler.py`'s `VarDecl` (line 558) carries `name` / `type_ann` / `value`,
and the reproducer is the ordinary spelling of the very thing the arm is looking
for — a local that captures the frame before the store:

```mojo
    def swap(out self) -> Pair:
        var old = self._p          # ← VarDecl, not AssignStmt
        self._p = Pair()
        return old
```

**Next step:** read `VarDecl.name` where `AssignStmt` reads `target`, i.e. the
bound NAME for a `VarDecl` and the assigned TARGET for an `AssignStmt`, and
compare that name against `recv` — or restrict the arm to `AssignStmt` and let
`var x = <expr>` fall through to whatever handles it today. Whichever it is, the
test that found it (`one_field_mutator_that_also_returns_a_frame_is_refused`, the
last row of `test_formal_run.py`'s `BOTH_ARCH_CASES`) is the reproducer and
should stay red until one of them lands: today it is not a wrong answer but a
`traceback`, and a `refuse:` row that gets a traceback instead of the words is
the shape `tools/formal_fuzz.py` calls `CODEGEN-INTERNAL`.

## 2. The wording: the subclass refusal the test names is not the one emitted

The case builds

```mojo
class MyErr(Widget):
    """no fields at all"""

def boom():
    raise MyErr("the message")
```

and expects `refuse:derives from 'Widget', which this image does not declare`.
What it gets instead, from `fire.py build --formal` on `master`:

```
build: constructing MyErr with 1 argument(s) does not match its fields (no fields
at all), and MyErr declares no `__init__` for it to call instead: with no
user-defined constructor, a struct's fields are filled in DECLARATION ORDER from
positional arguments and there is no other form, so this path can only place a
word in a slot it can name. …
```

Both refusals are TRUE of the program — the class does derive from a name this
image does not declare, and it also cannot be constructed with one argument
because it has no fields — so this is not a wrong answer. It is a decision about
WHICH one to say, and the two candidates belong to two different claims
(`formal16-2`'s subclass and exception rows). The test's expected words are the
older behaviour, so either the classifier now reaches the field-count check
first, or it no longer reaches the base check at all for this program.

**Next step:** decide which refusal this program should get, and make the two
agree. `formal/model.py`'s refusal-precedence table is where "which check
speaks first" lives; if the answer is "the field-count one, because it is the
more specific", then the test's expected words move and `formal/model.py`'s
subclass refusal needs a reproducer that reaches it, because right now this case
was the one reaching it and nothing else in the corpus may be.