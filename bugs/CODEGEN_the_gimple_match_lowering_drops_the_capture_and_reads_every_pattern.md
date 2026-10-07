# The gimple `match` lowering drops the capture, reads every pattern, and has no guard for a structural one

**Area:** CODEGEN (`mojo/backend_gimple/emit_stmts.py::_gen_stmt_MatchStmt`),
pattern matching. Found 2026-10-05 on `work/formal55-match-statements`, which
owns the FORMAL backends' `match` and had just landed the lowering this
document is about the other half of. **OPEN, and deliberately not fixed
there:** a change to `mojo/backend_gimple/*` owes a full `make gate` by
CLAUDE.md's own rule, which a light worker does not run. The formal side is
`formal/build.py::_rewrite_match_statements`; the intended semantics are written
down there and this document is the other implementation's divergence from them.

## 1. What I ran and what I saw

Four programs, each run three ways: `python3 fire.py run` (the reference
interpreter, `myinterpreter.py::execute_MatchStmt`), the gimple image
(`python3 fire.py build -o …`), and the formal images (`--formal
--backend=arm64|x86_64`, both of which agree with the interpreter on every
row since `work/formal55-match-statements` landed).

| source | `fire.py run` | gimple | formal (both arches) |
|---|---|---|---|
| `case v:` with `v` unbound, subject 7 | `cap 7` | **`rest`** | `cap 7` |
| `case 1, other:` with subject 5 | `low` | **`rest`** | `low` |
| `case 1, other:` subject 5, no later case | `low` | **prints nothing** | `low` |
| `case TBL[0], TBL[5]:` subject 10 (TBL has 2) | `low` | `low` | `low` |
| `case [a, b]:` with `a`, `b` unbound | **`NameError`** | **`rest`** | **REFUSED by name** |
| `case 1 \| 2:` with subject 1 | `rest` | `rest` | **REFUSED by name** |

Reproduce any row with

```sh
cat > /tmp/m.py <<'EOF'
def main():
    n = 7
    match n:
        case v:
            print('cap', v)
        case _:
            print('rest')
    return 0
main()
EOF
python3 fire.py run /tmp/m.py            # cap 7
python3 fire.py build -o /tmp/m /tmp/m.py && /tmp/m     # rest
```

## 2. Why — three separate gaps in one 60-line emitter

`mojo/backend_gimple/emit_stmts.py::_gen_stmt_MatchStmt` builds, per case, one
C `_Bool` and enters it when it is true:

* **`match_bool` starts as the FIRST pattern's comparison and every later
  pattern is `|`-ed in** (`gen._emit(f"  {combined} = {match_bool} | {cv};")`).
  Bitwise-or on `_Bool`s evaluates both operands, so a pattern list is
  evaluated in full before anything is tested. The reference stops at the first
  pattern that matches, and that is observable — `case TBL[0], TBL[5]:` reads
  `TBL[5]`, one past the end of a two-element list, which traps on the formal
  backends when read on its own. The row above happens to agree only because
  the trap this creates is in dead code on that program.
* **There is no capture at all.** The emitter never asks whether a bare name is
  bound, so `case v:` becomes `subject == v` and reads an undeclared `v` as
  whatever the C compiler gave it — which is why `case v:` prints `rest`, and
  why `case 1, other:` prints nothing at all (both comparisons false, no later
  case, fall off the end). This is the whole of `formal/build.py`'s
  `_match_scope_names` plus the `binds` list in `_lower_one_case`.
* **There is no structural-pattern refusal.** Every pattern is lowered as an
  expression, so `case [a, b]:` reads `a` and `b` as ordinary reads of
  undeclared names and compares the subject against a list literal built from
  them — where the reference raises `NameError` and the formal path refuses by
  name (`formal/model.py::match_pattern_refusal`). `case 1 | 2:` is worse,
  because here the `|` is the emitter's OWN or: it compares the subject against
  `1 | 2 == 3`, so a subject of 3 would enter an arm no `case` in the source
  names.

The one thing the gimple lowering gets RIGHT that is easy to get wrong is the
wildcard: `_gen_stmt_MatchStmt` detects `case _:` explicitly rather than by an
`any(isinstance(...))` comprehension, and its comment records that the
comprehension form emitted `case _:` as `case 0:` on the self-hosted path.

## 3. The next step

Three changes, in this order, each independently testable:

1. **Short-circuit the pattern list.** Build the case's test as nested
   `if`s in a loop over `match_case.patterns` with the next pattern in the
   `else`, rather than `|`-ing every comparison into one `_Bool`. The emitter
   already has `gen._new_bb()` / `_emit_label`, and the loop is already there —
   it just needs a block per pattern instead of a temp per pattern. `&&`/`||`
   over the `_Bool`s is not enough: C's `||` does short-circuit, but the
   emitter's `_ensure_bool_cond` is what decides the C type, and a `_Bool`
   operand of `||` is fine, so either shape works as long as ONE side is emitted
   per pattern.
2. **Decide capture vs comparison the way the reference does.** The emitter
   already knows the function's locals (`gen.var_types` / the declared set it
   builds for `declared`), so a bare `IdentExpr` pattern that is not among them
   assigns the subject temp to that name and is irrefutable — which also ends
   the pattern list, and which is the rule that makes row 3 above print
   `low`. The formal side's version of this decision, with the measured reason
   a static answer is sound, is `formal/build.py::_lower_one_case`'s docstring.
3. **Refuse the structural patterns by name**, by asking
   `formal/model.py::match_pattern_kind` — the classifier already exists and is
   shared, so this is one call and not a fourth copy of the rule. The sentence
   comes from `formal/model.py::match_pattern_refusal`, which is already written
   to be architecture-neutral.

## 4. Why it is worth fixing rather than leaving to the formal path

`FORMAL.md`'s thesis is that the two backends are two implementations of ONE
language and a fix that teaches only one of them teaches nothing. This is the
concrete case: `match` now means one thing on the formal path (a decision tree
of compares and branches, with a capture, a guard, and six constructs refused by
name) and a subtly different thing on the gimple path, for the same source
text. Nothing in the tree can see that today — `test_runtime_diff.py` compares
the two ENGINES and both are the interpreter here, and the other direction
(a construct one backend answers and the other refuses) is a different bug
rather than this one (a construct both answer, differently).

**A regression test for the gimple half** belongs beside the existing gimple
statement tests: one program per row of the table above, built and RUN through
`fire.py build` (not `--formal`), compared against `fire.py run`. The formal
half is `test_formal_match.py`, whose rows are the same programs on both
architectures.