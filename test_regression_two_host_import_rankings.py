# Regression for bugs/DOCS_two_host_import_rankings_are_two_tools.md
# The shapes tool's reach/alone must come from the wall tool's own corpus,
# and the suite registry must include the wall file in the shapes job's
# extra list so edits to the wall invalidate the shapes cached pass.

def test_shapes_extra_includes_wall_file():
    import ast, inspect, tools.suite as s
    src = inspect.getsource(s)
    # Verify the formal-host-import-shapes registration names the wall file
    assert "tools/formal_host_import_wall.py" in src
    # And it sits inside the extra list for that job
    assert "formal-host-import-shapes" in src

def test_shapes_reach_alone_uses_wall_default_rank():
    import tools.formal_host_import_shapes as sh
    import tools.formal_host_import_wall as w
    sweep = sh.default_sweep()
    rows, _, _ = sh.rows_for(sweep, 1)
    for r in rows:
        if r["name"] == "copy":
            wall = w.default_rank().get("copy", {"reach": [], "alone": []})
            assert r["reach"] == len(wall["reach"]), "shapes reach != wall reach"
            assert r["alone"] == len(wall["alone"]), "shapes alone != wall alone"
            break
    else:
        raise AssertionError("copy row not found")
