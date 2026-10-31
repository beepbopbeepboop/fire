# Pinning regression for CODEGEN_dict_literal_container_key_value_spellings
# Root cause fixed in master (ae9d7605): container-keyed tuple literal
# must render by content (mojo_dict_key_for), not by pointer.
# See bugs/CODEGEN_dict_literal_container_key_value_spellings.md (deleted by fix).

def main():
    d = {}
    d[("a",)] = "R"
    def k(s): return s + "!"
    d[(k("a"),)] = "R"
    print(d[(k("a"),)], len(d))

# Expected: R 1 (matches CPython content-keyed tuple key)
