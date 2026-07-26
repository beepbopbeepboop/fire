# COMPILE_FAIL: Lib/idlelib/idle_test/test_tooltip.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_tooltip.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_HovertipTest_addCleanup", referenced from:
      _HovertipTest_test_showtip in test_tooltip.o
      _HovertipTest_test_showtip_twice in test_tooltip.o
      _HovertipTest_test_hidetip in test_tooltip.o
      _HovertipTest_test_showtip_on_mouse_enter_no_delay in test_tooltip.o
      _HovertipTest_test_hover_with_delay in test_tooltip.o
      _HovertipTest_test_hover_with_delay in test_tooltip.o
      _HovertipTest_test_hidetip_on_mouse_leave in test_tooltip.o
      ...
  "_HovertipTest_assertEqual", referenced from:
      _HovertipTest_test_hover_with_delay in test_tooltip.o
  "_HovertipTest_assertFalse", referenced from:
      _HovertipTest_test_showtip in test_tooltip.o
      _HovertipTest_test_showtip in test_tooltip.o
      _HovertipTest_test_showtip_twice in test_tooltip.o
      _HovertipTest_test_showtip_twice in test_tooltip.o
      _HovertipTest_test_hidetip in test_tooltip.o
      _HovertipTest_test_hidetip in test_tooltip.o
      _HovertipTest_test_showtip_on_mouse_enter_no_delay in test_tooltip.o
      _HovertipTest_test_showtip_on_mouse_enter_no_delay in test_tooltip.o
      ...
  "_HovertipTest_assertGreater", referenced from:
      _HovertipTest_test_showtip_on_mouse_enter_no_delay in test_tooltip.o
      _HovertipTest_test_hover_with_delay in test_tooltip.o
      _HovertipTest_test_hidetip_on_mouse_leave in test_tooltip.o
  "_HovertipTest_assertIs", referenced from:
      _HovertipTest_test_showtip_twice in test_tooltip.o
  "_HovertipTest_assertTrue", referenced from:
      _HovertipTest_test_showtip in test_tooltip.o
      _HovertipTest_test_showtip in test_tooltip.o
      _HovertipTest_test_showtip_twice in test_tooltip.o
      _HovertipTest_test_showtip_twice in test_tooltip.o
      _HovertipTest_test_showtip_on_mouse_enter_no_delay in test_tooltip.o
      _HovertipTest_test_hover_with_delay in test_tooltip.o
  "_ToolTipBaseTest_addCleanup", referenced from:
      _ToolTipBaseTest_test_base_class_is_unusable in test_tooltip.o
      _ToolTipBaseTest_test_base_class_is_unusable in test_tooltip.o
  "_ToolTipBaseTest_assertRaises", referenced from:
      _ToolTipBaseTest_test_base_class_is_unusable in test_tooltip.o
  "_requires", referenced from:
      __toplevel in test_tooltip.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.53s
