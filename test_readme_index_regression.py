#!/usr/bin/env python3
"""Regression test: bugs/hard/README.md must not index completed/deleted docs."""
import os, sys

worktree = "/Users/mrs/net/chatgpt/claude/work-3344"
readme_path = os.path.join(worktree, "bugs", "hard", "README.md")

def test_index_has_only_existing_docs():
    with open(readme_path) as f:
        content = f.read()
    # Every backtick-quoted doc name in the index must exist on disk.
    import re
    names = re.findall(r'`([A-Z_]+\.md)`', content)
    for name in names:
        doc_path = os.path.join(worktree, "bugs", "hard", name)
        assert os.path.isfile(doc_path), f"README indexes missing doc: {name}"

def test_no_stale_gate_doc_indexed():
    with open(readme_path) as f:
        content = f.read()
    assert "CODEGEN_gate_test_linked_list_red_is_not_the_box_free_change" not in content, \
        "README still indexes completed gate-linked-list doc"

if __name__ == "__main__":
    test_index_has_only_existing_docs()
    test_no_stale_gate_doc_indexed()
    print("PASS: README index clean, no stale completed doc referenced.")
