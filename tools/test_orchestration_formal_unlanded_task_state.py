#!/usr/bin/env python3
"""bugs/ORCHESTRATION_formal_unlanded_task_state_2026-11-11.md is a collected
inventory, not an open bug; it must not be tracked in the bug queue.

    python3 tools/test_orchestration_formal_unlanded_task_state.py
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "bugs", "ORCHESTRATION_formal_unlanded_task_state_2026-11-11.md")

if __name__ == "__main__":
    if os.path.exists(DOC):
        print("FAIL collected formal unlanded-task-state inventory is still tracked as an open bug doc")
        sys.exit(1)
    print("PASS collected formal unlanded-task-state inventory is not tracked as an open bug doc")
    sys.exit(0)
