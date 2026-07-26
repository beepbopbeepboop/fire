# COMPILE_FAIL: Doc/tools/extensions/grammar_snippet.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/grammar_snippet.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_CompatProductionList_get_location", referenced from:
      _CompatProductionList_make_grammar_snippet in grammar_snippet.o
      _CompatProductionList_run in grammar_snippet.o
  "_CompatProductionList_set_source_info", referenced from:
      _CompatProductionList_make_grammar_snippet in grammar_snippet.o
      _CompatProductionList_run in grammar_snippet.o
  "_GrammarSnippetBase_get_location", referenced from:
      _GrammarSnippetBase_make_grammar_snippet in grammar_snippet.o
  "_GrammarSnippetBase_set_source_info", referenced from:
      _GrammarSnippetBase_make_grammar_snippet in grammar_snippet.o
  "_GrammarSnippetDirective_get_location", referenced from:
      _GrammarSnippetDirective_make_grammar_snippet in grammar_snippet.o
      _GrammarSnippetDirective_run in grammar_snippet.o
  "_GrammarSnippetDirective_set_source_info", referenced from:
      _GrammarSnippetDirective_make_grammar_snippet in grammar_snippet.o
      _GrammarSnippetDirective_run in grammar_snippet.o
  "_make_id", referenced from:
      _GrammarSnippetBase_make_name_target in grammar_snippet.o
      _GrammarSnippetDirective_make_name_target in grammar_snippet.o
      _CompatProductionList_make_name_target in grammar_snippet.o
  "_super", referenced from:
      _snippet_string_node___init__ in grammar_snippet.o
      _GrammarSnippetBase_make_production in grammar_snippet.o
      _GrammarSnippetDirective_make_production in grammar_snippet.o
      _CompatProductionList_make_production in grammar_snippet.o
  "_token_xrefs", referenced from:
      _GrammarSnippetBase_make_production in grammar_snippet.o
      _GrammarSnippetDirective_make_production in grammar_snippet.o
      _CompatProductionList_make_production in grammar_snippet.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.50s
