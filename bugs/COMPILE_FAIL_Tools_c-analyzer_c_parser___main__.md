# COMPILE_FAIL: Tools/c-analyzer/c_parser/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_add_commands_cli", referenced from:
      _parse_args_132aaf in __main__.o
  "_add_files_cli", referenced from:
      __cli_parse_dad6ee in __main__.o
  "_add_kind_filtering_cli", referenced from:
      __cli_parse_dad6ee in __main__.o
  "_add_preprocessor_cli", referenced from:
      __cli_parse_dad6ee in __main__.o
  "_configure_logger", referenced from:
      __toplevel in __main__.o
  "_get_processor", referenced from:
      _cmd_parse_3a0040 in __main__.o
      __get_preprocessor_a64463 in __main__.o
  "_locals", referenced from:
      _fmt_summary_132aaf in __main__.o
      _fmt_summary_132aaf in __main__.o
      _fmt_summary_132aaf in __main__.o
      _fmt_summary_132aaf in __main__.o
  "_main_for_filenames", referenced from:
      _cmd_parse_3a0040 in __main__.o
  "_process_args_by_key", referenced from:
      _parse_args_132aaf in __main__.o
  "_vars", referenced from:
      _parse_args_132aaf in __main__.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.32s
