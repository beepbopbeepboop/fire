# CODEGEN: a `re` match on BYTES returns str from `group()` and prints garbage

Found while working `CODEGEN_glob_bytes_pattern_returns_empty.md` (2026-11-01). The match itself
is right (`span()`, truthiness and `fullmatch` agree with CPython on bytes); what the match object
hands back, and how it prints, is not.

## Measured (compiled, this tree)

    print(re.compile(b'a(b)').match(b'ab').group(1))   # CPython b'b'   compiled b'b' printed without the b-prefix (a str)
    print(re.compile(".*").search("abc"))              # CPython <re.Match object; span=(0, 3), match='abc'>
                                                       # compiled: an empty line in a 3-line probe (HEAD and this tree);
                                                       # `���` in test_glob_bytes_regress.py's driver (this tree)
    print(re.compile(b".*").search(b"abc"))            # CPython <re.Match object; span=(0, 3), match=b'abc'>   compiled: garbage

## Why

- `mojo_re_m_group` reads the match's `text`, which is a `char *` copy of the subject, so a bytes
  subject's group comes back as a str. `mojo_re_exec_bytes` stores the bytes subject's data in
  `text` as well, so the group's kind is lost there.
- The match object's repr is not implemented: `repr(match)` is not the CPython
  `<re.Match object; span=..., match=...>` form, so `print(m)` shows whatever the handle's word
  reads as.

## Next step

1. Record the subject's kind on the `MojoReMatch` (`is_bytes` plus the `MojoBytes` it came from),
   and have `mojo_re_m_group` / `_groups_list` return a bytes object for a bytes match (the same
   word-kind convention as `mojo_dirent_name`).
2. Implement the match repr to CPython's form: `<re.Match object; span=(s, e), match=REPR>`, with
   the `REPR` of the group 0 as a str or bytes by the kind from step 1.
3. Tests: `test_glob_bytes_regress.py` currently prints `span()` on purpose, to avoid this gap.
   When this lands, switch two lines back to `print(m)` and `print(m.group(1))` and compare with
   CPython. Each must fail on this tree first.
