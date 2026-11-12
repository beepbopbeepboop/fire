# CODEGEN_peek_result_prints_raw_address

## Summary
`print(it.peek())` on a `peekable(...)` iterator prints a raw integer (`48136352`) instead of anything that
describes the `Optional[Pointer[...]]` value. The address of the peeked element is printed as if it were a value.

## Evidence
- Program (on fire-merged master, `fire.py build`): `from std.iter import peekable`, `var it = peekable(range(3))`,
  `print(it.peek())`. Output: `48136352`. The same iterator in a `for` loop prints `0 1 2` correctly.
- `peek` returns `Optional[Pointer[Self.Element, ImmOrigin(...)]]` (`std/iter/__init__.mojo`, the `peek` method).

## Repro
As above. Only the `print` of the peek result is wrong; the loop path is correct.

## Status
Open. Not started. What CPython-compatible Mojo should print here is NOT confirmed: the element is needed through
`peek()[][]`, so printing the Optional itself may be a bad test. First step: decide what `print` of an Optional of a
pointer should produce (or whether the test is wrong), then make the compiled output match.

## Done when
A program that prints `peek()` (or `peek()[][]`) as the stdlib's own test (`test/iter/test_peek.mojo`) expects
prints the value the test expects, with a test. Then delete this doc in the same commit.
