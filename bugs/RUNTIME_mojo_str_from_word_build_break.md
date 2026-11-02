# RUNTIME: mojo_str_from_word missing errors arg breaks build

## What ran
`python3 fire.py build .tmp/len_word.mojo -o ...`

## What saw
`runtime/fire_runtime.c:12651:16: error: too few arguments to function 'mojo_bytes_decode'; expected 3, have 2`
`mojo_str_from_word(int64_t w, char *encoding)` calls `mojo_bytes_decode(..., encoding)` with 2 args; declaration needs 3 (`encoding`, `errors`).

## Expected
Build passes; this is unrelated to CODEGEN_bytes_os_path_and_word_len.

## Next step
Add `char *errors` parameter (or pass `"strict"`) at call site in `mojo_str_from_word`, or match declaration.
