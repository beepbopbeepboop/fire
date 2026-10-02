# FORMAL_argparse_help_wrapping_not_implemented: `--help` is laid out but never wrapped, and a usage line longer than 78 columns is not folded

**Status: OPEN, and it is a property of the target rather than a gap in
`argparse`. Found while writing `formal/hostmods/argparse.mojo` (2026-09-29,
the `module:argparse` claim). Everything else CPython's `argparse` does to a
command line is reproduced there and checked case for case; this is the one
part that is not, and it is named in that file's own docstring so a reader does
not have to discover it.**

## What is and is not implemented

`argparse.mojo`'s `help_text` reproduces CPython's `HelpFormatter` layout
exactly: the usage line, a blank, the description, a blank,
`positional arguments:` with its entries, `options:` with its entries, each
block followed by a blank line, and the whole ending in exactly one newline. It
reproduces `_format_action`'s three cases too — a short invocation padded out to
the help column with its help on the same line, a long one on its own line with
the help indented under it, and an action with no help text as the invocation
and nothing else. The two-column position is `_HelpFormatter.add_argument`'s
`_action_max_length` plus the section indent, capped at `max_help_position=24`,
which is what `_format_action`'s `help_position` computes.

What it does NOT do is fold anything:

- a **help entry** whose text does not fit the column is printed long rather
  than wrapped;
- a **description** longer than the width is printed long;
- a **usage line** longer than the width is printed on one line where
  CPython's `_format_usage` folds it onto indented continuation lines.

## Why, measured

CPython's width is
`shutil.get_terminal_size().columns - 2` (`HelpFormatter.__init__`), and
`shutil.get_terminal_size()` asks the OPERATING SYSTEM for the terminal size:

```python
def get_terminal_size(fallback=(80, 24)):
    try:
        columns = int(os.environ['COLUMNS'])
    except (KeyError, ValueError):
        columns = 0
    ...
    if columns <= 0 or lines <= 0:
        try:
            size = os.get_terminal_size(sys.__stdout__.fileno())
```

Both halves are host objects on this target and neither is reachable:
`shutil` is in `formal/imports.py`'s `HOST_UNREACHABLE` under "a terminal, or a
writable filesystem this target does not get", and so is `os.get_terminal_size`
— an ioctl on a file descriptor this image has no terminal behind. There is no
`sys.__stdout__` either, for the reason `sys.mojo`'s docstring gives: a stream
OBJECT cannot cross the module boundary because it is more than one word.

So **78 is the only width this target can know**, and `argparse.mojo` uses it
unconditionally: `shutil.get_terminal_size().columns - 2` is 78 when `COLUMNS`
is unset and stdout is not a terminal, which is exactly the situation a piped
program is in and the situation every measurement in
`test_formal_argparse.py` is taken in. `COLUMNS` is not consulted — it is an
environment variable, and reading one needs a `char **` walk the value model
cannot do (the reason `os.environ` is three functions and not a mapping; see
`formal/hostmods/os/__init__.mojo`).

## What the difference costs

For every parser in the corpus this module was written against, nothing: the
widest entry is `-j, --jobs JOBS  worker count` and the longest usage line is
72 columns, both inside the width. `test_formal_argparse.py` compares the
`--help` output of the `demo` parser against CPython's byte for byte and they
are identical.

It costs something the moment a help string is long, and the cost is a
DIFFERENCE, not a failure: CPython prints

```
  --jobs JOBS  the number of workers to run in
               parallel; more than the core count
               is usually slower
```

and this module prints the second line unwrapped and past the column. A user
comparing the two outputs sees a layout difference, not an error.

## The exact next step

**Still unmade (2026-10-02), and it is a choice about the API before it is
work.** Option A changes `help_text`'s signature, which is a decision about what
a caller may ask for; option B reimplements `textwrap`, which the rest of
`formal/hostmods/` deliberately does not do. A light worker may not make that
call and ship half of either, and the honest cost of getting it wrong is a
`--help` that differs from CPython's in a NEW way rather than the current
difference, so nothing was touched. What is worth knowing before the choice is
made: the wrapping is a pure function of `(text, width)` with no host objects in
it, so **once a width is decided, option B is a self-contained routine with a
byte-exact oracle already in place** — `test_formal_argparse.py` compares the
whole `--help` output against CPython's over 63 cases, so a wrong fold is a red
line, not a silent difference. That harness is what makes B safe to attempt and
also what would catch it.

Two options, in the order they should be tried.

**A. Make the width askable.** `ioctl(TIOCGWINSZ)` on a descriptor is a
libSystem call and `os` already has a `_syscalls.mojo` that reaches libSystem
for everything it needs, so the CAPABILITY is there; what is missing is a
descriptor to ask about, because there is no `sys.stdout` on this path. A
program that wants the real width could pass it in — `help_text` takes a
`desc` parameter already, and a `width` parameter would be the same kind of
change, with `COLUMNS` (an environment variable, reachable through
`os.getenv`, which exists and works) as the fallback. That is a decision about
the API rather than a backend change, and it is cheap.

**B. Implement the wrapping for the width that IS known.** The algorithm is
`textwrap.wrap(help_text, help_width)` for an entry and
`textwrap.fill(text, width, initial_indent=indent, subsequent_indent=indent)`
for the description, plus `_format_usage`'s own `get_lines` loop for a long
usage line. All three are ordinary greedy line-breaking over strings, which
this backend does — `os/path/__init__.mojo` walks separators with `strcspn`
and `strrchr` for the same reason. The cost is a re-implementation of
`textwrap`, which is the "second implementation of a routine that already
exists" the rest of `formal/hostmods/` avoids; it is worth doing only if the
width cannot be asked for, and A makes it less worth.

Whichever is chosen, the thing that must not happen is the current state
reaching a user silently: the module says at the top of its own docstring that
help text is not wrapped and why, and `argparse.mojo` is not in anyone's list
as byte-identical to CPython's `--help`.
