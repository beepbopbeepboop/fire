# step-22 verdicts (chunk a)

| # | file | verdict | message (first 100 chars) | reason / fix | commit |
|---|------|---------|---------------------------|-------------|--------|
| 1 | bootstrap_test_classes.mojo | T | create_point returns a frame address, and the returned-frame convention needs a caller to reserve a block and pass its address — and create_point is this | create_point returns a frame address but is the ENTRY, causing convention mismatch |  |
| 2 | formal/build.py | T | build: parse error: /Users/mrs/net/chatgpt/claude/mojo-reference2/formal/build.py:19162:19: Unexpected COLON(':') | not Mojo source |  |
| 3 | formal/hostmods/subprocess.mojo | T | build: run returns a frame address, so it needs one hidden word for the caller's block — and it already takes 14 arguments, which is this path's whole argument | build: run returns a frame address but takes 14 args, exceeding ABI budget |  |
| 4 | formal/x86_64_decode.py | T | build: decode_one returns a frame address on one path and falls off the end of its body on another, so a caller that reserved a block for the result would read a block nobody wrote: the bytes are whatever the scratch held. Every path that leaves the function must return a frame address, so that the caller's one reservation is the right one — give the last branch a `return the frame in 'decode_one_insn()'` as well, or copy a field out instead of returning the object | not Mojo source |  |
| 5 | runtime/stdlib_wrapper.mojo | T | build: main: `now` is called, and it is imported from `time`, so the call has to bind a symbol `time` exports. **`time` declares no function or struct named `now` at all** | time is not declared in time module |  |
| 6 | t1.mojo | T | build: sys.exit(): `sys` is a linked module but it exports no `exit`, so the call has no symbol to bind. What it does export: api_version, byteorder, flush_output, get_coroutine_origin_tracking_depth, get_int_max_str_digits, getdefaultencoding, getfilesystemencodeerrors, getfilesystemencoding, …. A name `doc/ABI.md`'s export rule excludes (a leading `_`, a generic template, an overload, or a C library symbol such as `exit` or `write`) is not advertised | time's `exit` not exported; need proper export rule for sys module |  |
| 7 | test_arm64_encoders.py |  |  |  |  |
| 8 | test_char_star_local_regress.py |  |  |  |  |
| 9 | test_dict_literal_container_key_pin.py |  |  |  |  |
| 10 | test_exception_object_attributes_regression.py |  |  |  |  |
| 11 | test_formal_globals.py |  |  |  |  |

TOTALS: T=5 M=0 S=0 C=0