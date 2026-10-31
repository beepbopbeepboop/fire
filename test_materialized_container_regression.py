"""Regression: materialized container through ambiguous handle must keep
its runtime kind markers, so `list(ident(d))` reads keys as strings."""

def ident(x):
    return x
def main():
    d = {"k": 1, "j": 2}
    # Before fix: compiled stdout printed pointer decimals.
    # After fix: prints `['k', 'j']` like CPython.
    result = list(ident(d))
    assert len(result) == 2
    assert result[0] == "k"
    assert result[1] == "j"
main()
