# gdbtool — persistent REPL wrapper

Wraps any interactive line-oriented program (lldb, gdb, bash, python, etc.)
with a persistent daemon and one-shot CLI commands.

Server holds the subprocess on a pty. Client invocations connect via Unix
socket, send one line, read raw output, print, exit. Subprocess stays alive
between commands preserving state (breakpoints, watches, loaded binary, etc).

Socket is `./.gdbtool-socket` — one per directory, no env vars needed.

## Usage

```
# start server
gdbtool serve lldb /path/to/binary

# one-shot commands (each connects, sends, prints, exits)
gdbtool "b main"
gdbtool run
gdbtool stepi
gdbtool bt
gdbtool "frame variable"
gdbtool continue

# stop server + child
gdbtool terminate
```

## Debug workflow

```
gdbtool serve lldb stage2/mojo
gdbtool "b GimpleGen_gen_func"
gdbtool run
gdbtool stepi               # single step
gdbtool bt                  # backtrace
gdbtool "frame variable"    # inspect locals
gdbtool "frame select 1"    # up the stack
gdbtool continue            # resume execution
gdbtool terminate
```

## Timeout

Client has a 30-second timeout. If a command (e.g. `continue` on a long
running program) takes longer, the client prints a warning and returns
whatever output arrived so far. The server and program keep running.

## Source-line smuggling

Adding `#line N "file.py"` directives to generated GIMPLE C output makes
lldb map breakpoints and frame info back to the original source:

```
#line 1234 "mojo_compiler.py"
```

## Works with any REPL

```
gdbtool serve /usr/bin/python3
gdbtool "2+2"              # prints 4

gdbtool serve /bin/bash
gdbtool "ls -la | head -3"
```
