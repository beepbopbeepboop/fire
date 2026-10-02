# CODEGEN: `print` in a nested `def` body prints an argument as a decimal address

Found 2026-10-01 while testing
`bugs/CODEGEN_annotated_str_param_given_an_int_segfaults.md`'s fix, which had
to keep a by-value string handle reaching a `char *` parameter. Pre-existing:
it reproduces identically on the parent commit, and none of this commit's
edits touch `print` lowering.

## What I ran and what I saw

```python
def outer():
    def inner(s):
        print(s)
    inner("A")
    return 0

def main():
    outer()
    print("D")
main()
```

| | CPython | compiled |
|---|---|---|
| stdout | `A\nD\n` | `4376810744\nD\n` |

The printed value is the DECIMAL OF A POINTER — the string `"A"` arrived in
the unannotated parameter `s` with its pointer bits, and `_gen_print` printed
that raw 64-bit word with `%ld`. Exit 0, no diagnostic; the decimal differs
every run (ASLR), so nothing can match on it.

## Mechanism

`print(s)` inside a lifted nested `def` DOES reach `_gen_print`, and the
newline is emitted correctly. What is wrong is the argument dispatch. The
lifted function's parameter is physically `int64_t` — an unannotated
parameter is typed `int64_t` whatever it is given — so `_gen_print`'s
per-argument ladder takes the generic numeric arm:

```c
void __GIMPLE outer_inner (int64_t s)
{
  char * _t1;
  void * _t2;
  ...
bb_2:
  _t3 = _slit_10000;              /* "%ld" */
  _t2 = malloc (256);
  _t1 = (char *) _t2;
  sprintf (_t1, _t3, s);          /* <- the POINTER, as a decimal */
  mojo_print (_t1);
  free (_t1);
  _t4 = _slit_10001;              /* "\n" -- this part is right */
  mojo_print (_t4);
}
```

The ladder tries `gen._get_actual_type(atype, aval)` first, which recovers
`'char *'` when `_actual_types` has a record — and for a closure/lambda
parameter there is no record, because the value was never seen type-erased
anywhere in this codegen; it simply arrived in an `int64_t` slot. That is the
same ambiguity `mojo_cstr_or_int_str` exists to answer elsewhere in the
runtime, and the same one
`runtime/fire_runtime.c`'s own comment names ("a lambda parameter has no
annotation and is typed `int64_t`, so a string passed to one arrives with its
pointer bits in an int64_t with nothing recorded anywhere").

So `print` is currently the odd one out: every OTHER int64-taken-as-a-string
site in the model (`_char_to_cstr`, the `_kw` dict keys, `mojo_str_cat`'s
operands) asks the runtime's discriminator, and `print` alone decides by
falling through to `%ld`.

## What I expected

`A`. And note the asymmetry that makes this a real bug rather than a
limitation: the SAME program through a lambda prints `C` correctly today
(per `bugs/CODEGEN_print_in_a_lambda_body_drops_its_separator_and_newline.md`
that path coerces the argument with the discriminator instead), so two
spellings of "print a parameter I was handed a string for" disagree.

## Exact next step

In `_gen_print`'s argument ladder (`mojo/backend_gimple/emit_infra.py`), the
final `else` currently splats the raw word through `printf_fmt(atype)`. An
untracked `int64_t` there should go through the model's own discriminator —
`mojo_cstr_or_int_str` — exactly as `_char_to_cstr` does, so a real string
comes back as its content and a genuine integer still prints as a decimal.

The caution, which is why this is filed and not fixed inline: `print` must
keep printing INTEGERS as integers, and an untracked `int64_t` is
indistinguishable from a boxed string at this point, so the change trades one
wrong answer for another unless it is gated on the same positive record the
codegen already builds (`gen._actual_types` for pointers, `gen._int_word_vals`
for provably-integer values). Gate it on that and it is safe; do not gate it
on "no `_actual_types` entry", which is the condition that is true here.