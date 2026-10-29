# Gate job `sqliteruntime` is red: sqliteruntime job timed out at 600 s

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
# ERROR: compiling imported module 'formal.model' from /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: cannot coerce MojoSet * to MojoList * (incompatible container kinds) at /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: value='_t3' dest='live'
# ERROR: compiling imported module 'formal.model' from ./formal/model.py: cannot coerce MojoSet * to MojoList * (incompatible container kinds) at /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: value='_t3' dest='live'
  ... 214/218 jobs done, 4 running, 1096s elapsed
  ... 214/218 jobs done, 4 running, 1126s elapsed
  ... 214/218 jobs done, 4 running, 1157s elapsed
  exit: 0   secs: 674.5   peak: 0.4 GB
```

## What to check first

a hang or a very slow build; rerun alone and time it.

## Next step

1. Run `python3 tools/suite.py sqliteruntime` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
