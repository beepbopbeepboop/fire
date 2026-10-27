# Pinning regression for bug:CODEGEN_dict_content_key_aliases_a_string_key
# A tuple content key must NOT alias a plain string key with the same chars.

def main():
    d = {}
    d[("a", 1)] = 1          # content key
    d["('a', 1)"] = 2        # plain string key, same characters
    assert len(d) == 2, f"expected 2 entries, got {len(d)}"
    assert d.get(("a", 1)) == 1
    assert d.get("('a', 1)") == 2
    # Lookup of missing content key must NOT grow dict (old insertion bug)
    before = len(d)
    d.get(("missing",))
    assert len(d) == before, f"get on missing key grew dict to {len(d)}"
    print("pin_dict_content_key_aliases: PASS")

if __name__ == "__main__":
    main()
