# `formal/contracts.py`'s expression IR cannot READ the source's `//`, so a clause over it is refused with a reason that names the wrong operator and a body containing it is a silent skip

**Claim** `project:loop-invariants` on `work/formal66-loop-invariants`.  **Not
mine**: `formal/contracts.py` is the contracts layer's file and nothing here
touches it.  **Measured** on `cd2a1678` + the loop-invariant layer's commits, on
this tree, 2026-10-06.

## What is broken

`formal/contracts.py`'s one expression IR reads `fire_compiler`'s own AST nodes,
and its arithmetic arm is keyed on the operator the AST carries:

    formal/contracts.py:424   _ARITH_OPS = {"+", "-", "*", "/", "%"}

The AST's operator for integer division is `//`, not `/`:

    $ python3 -c 'import sys; sys.path.insert(0,"."); import fire_compiler as F;
      m = F.Parser(F.py_tokenize("def h(a,b):\n  return a // b\n")).parse_module();
      print(m[0].body[0].value.op)'
    //

So `//` matches nothing, and the two readers fail in two different ways.

**A clause that MENTIONS `//` is refused, with a sentence that names the wrong
operator.**  `_Reader.value` returns `None`, `contract_theorems` emits nothing,
and `unlowered_reason` reports:

    1 of 1 clause(s) has no Lean rendering (`@ensures(...)`); the expression
    subset a contract may use is literals, the parameters, `result`, `+ - * / %`,
    the six comparisons, `and`/`or`/`not`, a conditional expression, and
    `abs`/`min`/`max`/`clamp`

for the source `@ensures(result == a // b)`.  The subset list names `/` and not
`//`, so a reader who takes it as the specification is told `a // b` is outside
the subset when it is inside it.  **The IR tag and both printers already handle
it**: `_Op.ARITH` with `/` renders as `UInt64.div` (`_lean_of`, measured:
`(a UInt64.div b)`) and evaluates as `(a // b) & _MASK` (`_eval_of`).

**A function whose BODY contains `//` cannot be run by the bounded search, at
any input**, and the skip is not visible in the verdict:

    >>> from formal import contracts as CT
    >>> r = CT.SourceRunner(fn); r(7, 2)
    CT.Unsupported: the binary operator '//'

`search_counterexample` counts that as a `skipped` input and `classify` folds the
count into its UNKNOWN sentence, which is the right mechanism — but the count is
*every* input for such a function, so the sentence says "83 of the inputs were
SKIPPED" and the reader has to notice that 83 is all of them.

## Why it is worth fixing, and it is a one-line fix

`formal/loop_invariants.py`'s bounded search runs loop bodies through this IR,
and `formal/loop_examples/collatz.mojo` halves a variable:

    while v != 1:
        if v % 2 == 0:
            v = v // 2

**Measured before the local workaround: 11 of 12 entry values were SKIPPED**,
because every halving step hit `Unsupported('//')` — and a skip reads as "no
counterexample", which is how a corpus of twelve loops had two shapes silently
outside its own instrument.  The layer works around it by rewriting the node's
operator to `/` before handing it to the reader (`_word_arith`), which is a
correct workaround and is the wrong place for it: the reader is the ONE reader of
a clause's expression in this project, and a rule that lives in a second reader
is a rule the next reader does not have.

The fix is to accept both spellings in `_Reader.value`'s arithmetic arm:

    if op in ("/", "//"):
        …
        return (_Op.ARITH, "/", a, b), None

and, for symmetry, `SourceRunner.binary`'s operator dispatch — where `//` should
take the same path `/` already takes (both are `(a // b) & _MASK`; the module's
own docstring for `_eval_of` records that the word reading is what the machine
computes).

## How to reproduce

    export PATH=/opt/homebrew/bin:$PATH
    cd /Users/mrs/net/chatgpt/claude/work-531

    # 1. a clause over `//` is refused, and the reason names `/`
    python3 - <<'EOF'
    import sys; sys.path.insert(0, ".")
    from formal import contracts as CT
    import fire_compiler as F
    src = '@ensures(result == a // b)\ndef h(a, b):\n    return a // b\n'
    fn = [s for s in F.Parser(F.py_tokenize(src)).parse_module()
          if type(s).__name__ == "FunctionDef"][0]
    c = CT.read_contracts(fn, "x")
    print("emitted:", bool(CT.contract_theorems(c, ["a", "b"], fn=fn)))
    print(CT.unlowered_reason(c, ["a", "b"]))
    EOF

    # 2. the source evaluator cannot run a body with `//`
    python3 - <<'EOF'
    import sys; sys.path.insert(0, ".")
    from formal import contracts as CT
    import fire_compiler as F
    fn = [s for s in F.Parser(F.py_tokenize("def h(a, b):\n    return a // b\n")).parse_module()
          if type(s).__name__ == "FunctionDef"][0]
    print(CT.SourceRunner(fn)(7, 2))
    EOF

    # 3. and what the IR would render if it had read it
    python3 - <<'EOF'
    import sys; sys.path.insert(0, ".")
    from formal import contracts as CT
    print(CT._lean_of((CT._Op.ARITH, "/", (CT._Op.VAR, "a"), (CT._Op.VAR, "b"))))
    EOF

## Where the local workaround is, so the next reader knows it is not the fix

`formal/loop_invariants.py::_word_arith` rewrites `//` to `/` on the node before
the reader sees it, and its docstring says why and says that the fix belongs in
the reader.  Removing that call is step 2 of the fix above; `test_formal_
loop_invariants.py::test_a_program_the_search_cannot_run_is_recorded_as_skipped`
is the row that would then have to be narrowed, because `collatz`'s search is no
longer a skip and `array_fill`'s still is (a subscript, which is a separate
frontier this doc does not claim).