import pathlib
import unittest

DOC = pathlib.Path(__file__).resolve().parent / "bugs/mid/GPU_offload_validation_modular-part3.md"


class TestGPUOffloadValidationPart3(unittest.TestCase):
    def test_doc_records_contract_hooks_and_blocker(self):
        self.assertTrue(DOC.exists(), DOC)
        text = DOC.read_text()
        # scope cases
        self.assertIn("enqueue_function_device_passable_closure_arg_error.mojo", text)
        self.assertIn("enqueue_function_device_passable_closure_arg_layout_error.mojo", text)
        # required analysis sections
        for heading in ("## Contract", "## Hook points", "## Blocker", "## Narrow verification"):
            self.assertIn(heading, text, heading)
        # both cases explicitly dispositioned as blocked on named runtime/backend hooks
        self.assertIn("BLOCKED", text)
        self.assertIn("max.gpu.host.DeviceContext", text)
        self.assertIn("compile_function", text)
        self.assertIn("DevicePassable", text)
        self.assertIn("myinterpreter.py", text)


if __name__ == "__main__":
    unittest.main()
