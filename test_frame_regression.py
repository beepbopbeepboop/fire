"""Quick regression for the frame f_trace / f_locals fixes (codegen)."""
# This verifies the fixed behavior that was broken before the commit.
# The fixes are in emit_stmts.py / emit_exprs.py / fire_runtime.c.
# We assert the refusal message for f_locals is named, and that del/bool
# work by running the existing embedded tests in test_gimple_runner.
import sys, os
sys.path.insert(0, '.')
from test_gimple_runner import test_gimple_build_refusal, test_gimple_stdout

# Before fix: f_locals answered garbage; after: named compile error.
test_gimple_build_refusal("reg_f_locals_refused", "import sys\ndef f():\n    x=1\n    return sys._getframe().f_locals\ndef main():\n    print(f())\n", "frame attribute `f_locals` is not modelled")

# Before fix: del all succeeded silently; after: correct CPython answers.
test_gimple_stdout("reg_f_trace_del", "import sys\ndef test():\n    f = sys._getframe(0)\n    f.f_trace = 42\n    del f.f_trace\n    print(f.f_trace is None)\n    try:\n        del f.f_trace_lines\n        print('deleted')\n    except TypeError:\n        print('TypeError')\n    try:\n        del f.f_trace_opcodes\n        print('deleted')\n    except AttributeError:\n        print('AttributeError')\n    print(f.f_trace_lines, f.f_trace_opcodes)\ndef main():\n    test()\n", "True\nTypeError\nAttributeError\nTrue False\n")
