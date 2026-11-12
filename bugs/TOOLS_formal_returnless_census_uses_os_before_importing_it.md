# TOOLS: `tools/formal_returnless_census.py` raises `NameError: name 'os' is not defined` at import

Found 2026-11-12 while running the return-less census's own test as the
"existing test file that covers the code" for a fix in `formal/model/calls.py`.

## What I ran

```
python3 test_formal_returnless_census.py
  File ".../test_formal_returnless_census.py", line 48, in <module>
    import formal_returnless_census as C
  File ".../tools/formal_returnless_census.py", line 2, in <module>
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NameError: name 'os' is not defined
```

## What I expected

The census's test to run (it is a parse-and-walk test, no build), or at least
the tool's module docstring and imports to execute in order.

## Cause

The file begins with executable lines that use `os` and `module_loader` before
either is imported, and the `#!/usr/bin/env python3` shebang + module docstring
are *below* them (lines 4 onward), so they are not a shebang or a docstring at
all:

```
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from module_loader import STDLIB_PATH
#!/usr/bin/env python3
"""Which call sites CONSUME ..."""
...
import argparse
import collections
import os
import sys
```

This looks like a merge that put the three lines above the file's real header.

## Next step

Move the shebang and the module docstring back to the top of
`tools/formal_returnless_census.py`, then the imports, then the
`sys.path`/`module_loader` bootstrap. Re-run
`python3 test_formal_returnless_census.py`. The tool and its test are in no
`tools/suite.py` bucket, which is why this never failed a gate.
