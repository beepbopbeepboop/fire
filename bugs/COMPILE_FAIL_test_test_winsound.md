# COMPILE_FAIL: Lib/test/test_winsound.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_winsound.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_bytearray", referenced from:
      _PlaySoundTest_test_snd_memory in test_winsound.o
  "_safe_Beep", referenced from:
      _BeepTest_test_extremes in test_winsound.o
      _BeepTest_test_extremes in test_winsound.o
      _BeepTest_test_increasingfrequency in test_winsound.o
      _BeepTest_test_keyword_args in test_winsound.o
  "_safe_MessageBeep", referenced from:
      _MessageBeepTest_test_default in test_winsound.o
      _MessageBeepTest_test_ok in test_winsound.o
      _MessageBeepTest_test_asterisk in test_winsound.o
      _MessageBeepTest_test_exclamation in test_winsound.o
      _MessageBeepTest_test_hand in test_winsound.o
      _MessageBeepTest_test_question in test_winsound.o
      _MessageBeepTest_test_error in test_winsound.o
      ...
  "_safe_PlaySound", referenced from:
      _PlaySoundTest_test_keyword_args in test_winsound.o
      _PlaySoundTest_test_snd_memory in test_winsound.o
      _PlaySoundTest_test_snd_memory in test_winsound.o
      _PlaySoundTest_test_snd_filename in test_winsound.o
      _PlaySoundTest_test_snd_filepath in test_winsound.o
      _PlaySoundTest_test_aliases in test_winsound.o
      _PlaySoundTest_test_alias_fallback in test_winsound.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.11s
