# Gate job `bootstrap-stage1-transitive` is red: bootstrap stage1 transitive job red

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (the imported-function trailing-default drop, which made `mojoc`'s `compile_to_gimple` call three-argument; fixed on `work/bug-codegen-imported-function-default-ar`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
memcap: bootstrap-stage1-transitive -- ceiling 4.0 GB across the process tree
# ERROR: compiling imported module 'formal.model' from /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: cannot coerce MojoSet * to MojoList * (incompatible container kinds) at /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: value='_t3' dest='live'
# ERROR: compiling imported module 'formal.model' from ../formal/model.py: cannot coerce MojoSet * to MojoList * (incompatible container kinds) at /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: value='_t3' dest='live'
✓ Generated fire.ci (transitive closure)
```

## What to check first

stage1 transitive compile failed (no excerpt captured); rerun alone.

## Next step

1. Run `python3 tools/suite.py bootstrap-stage1-transitive` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
