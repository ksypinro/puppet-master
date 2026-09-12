"""Host-side bridge lifecycle tests. These mocks do not replace live app tests."""
import importlib.util
import json
from pathlib import Path
import shlex
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("tested_lldb_ui", Path(__file__).with_name("lldb_ui.py"))
ui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ui)


class Error:
    def __init__(self, message=""):
        self.message = message

    def Fail(self):
        return bool(self.message)

    def __str__(self):
        return self.message or "success"


class Value:
    def __init__(self, value=0, error=""):
        self.value, self.error = value, Error(error)

    def GetError(self):
        return self.error

    def GetValueAsUnsigned(self, default=0):
        return self.value

    def GetValueAsSigned(self, default=0):
        return self.value


class StackFrame:
    def __init__(self, module=None, valid=True):
        self.module, self.valid = module, valid

    def IsValid(self):
        return self.valid

    def GetModule(self):
        return self.module


class Thread:
    def __init__(self, count=1, frame=None):
        self.count = count
        self.frame = frame or StackFrame()
        self.inspected = []

    def GetNumFrames(self):
        return self.count

    def GetFrameAtIndex(self, index):
        self.inspected.append(index)
        return self.frame


class Bridge:
    def __init__(self):
        self.probe = Mock()
        self.probe.IsValid.return_value = True
        self.state = 5
        self.triple = "arm64-apple-ios27.0-simulator"
        self.threads = [Thread()]
        self.expressions = []
        self.free_result = Value(1)
        self.close_result = Value(0)
        self.main_result = Value(1)
        self.raw = json.dumps({"schemaVersion": "ios-ui-evidence/v1",
                               "capture": {"id": "test-capture", "truncated": False}, "nodes": []})

    def IsValid(self):
        return True

    def GetState(self):
        return self.state

    def GetTarget(self):
        return self

    def GetTriple(self):
        return self.triple

    def FindModule(self, unused):
        return self.probe

    def __iter__(self):
        return iter(self.threads)

    def ReadCStringFromMemory(self, address, limit, error):
        if address != 0x2000:
            raise AssertionError("unexpected capture buffer")
        return self.raw

    def EvaluateExpression(self, source, options):
        self.expressions.append(source)
        if "dlopen" in source:
            return Value(0xAA)
        if "dlclose" in source:
            return self.close_result
        if "0x1010" in source:
            return self.main_result
        if "0x1020" in source:
            return Value(0x2000)
        if "0x1030" in source:
            return self.free_result
        raise AssertionError("unexpected expression: " + source)


class CaptureLifecycleTests(unittest.TestCase):
    def capture(self, bridge):
        fake_lldb = types.SimpleNamespace(eStateStopped=5, eLanguageTypeC=1,
                                          SBFileSpec=lambda path: path, SBError=Error)
        symbols = {"PuppetUIIsMainThread": 0x1010, "PuppetUICapture": 0x1020, "PuppetUIFree": 0x1030}
        with tempfile.TemporaryDirectory(prefix="ui-bridge-test-") as folder:
            probe = Path(folder) / "probe.dylib"
            probe.write_bytes(b"mock artifact; never loaded")
            output = Path(folder) / "capture.json"
            result = Mock()
            debugger = Mock()
            debugger.GetVersionString.return_value = "test"
            context = Mock()
            context.GetProcess.return_value = bridge
            context.GetFrame.return_value = bridge
            command = "%s --compiled-probe %s" % (shlex.quote(str(output)), shlex.quote(str(probe)))
            with patch.object(ui, "lldb", fake_lldb), patch.object(ui, "_options", return_value=Mock()), \
                    patch.object(ui, "_probe_symbol", side_effect=lambda module, name, target: symbols[name]):
                ui.capture(debugger, command, context, result, {})
            data = json.loads(output.read_text()) if output.exists() else None
            return data, result

    def test_success_requires_integer_free_acknowledgement(self):
        bridge = Bridge()
        data, result = self.capture(bridge)
        self.assertEqual(data["capture"]["cleanup"], {"targetBuffer": "freed", "probeImage": "dlclose-succeeded"})
        self.assertEqual(data["capture"]["executionMode"], "compiled-simulator-probe")
        result.SetError.assert_not_called()
        result.AppendWarning.assert_not_called()
        self.assertTrue(any("int (*)(unsigned long long)" in expression for expression in bridge.expressions))

    def test_zero_free_result_is_not_reported_as_freed(self):
        bridge = Bridge()
        bridge.free_result = Value(0)
        data, result = self.capture(bridge)
        self.assertEqual(data["capture"]["cleanup"]["targetBuffer"], "free-failed")
        result.AppendWarning.assert_called()

    def test_debugger_free_error_is_preserved_even_with_one_result(self):
        bridge = Bridge()
        bridge.free_result = Value(1, "unknown debugger result")
        data, result = self.capture(bridge)
        self.assertEqual(data["capture"]["cleanup"]["targetBuffer"], "free-failed")
        result.AppendWarning.assert_called()

    def test_probe_on_stack_prevents_dlclose(self):
        bridge = Bridge()
        bridge.threads = [Thread(frame=StackFrame(bridge.probe))]
        data, result = self.capture(bridge)
        self.assertEqual(data["capture"]["cleanup"]["probeImage"], "not-unloaded-unsafe-debugger-state")
        self.assertFalse(any("dlclose" in expression for expression in bridge.expressions))
        result.AppendWarning.assert_called()

    def test_missing_invalid_or_excessive_frames_prevent_dlclose(self):
        for thread in (Thread(count=0), Thread(frame=StackFrame(valid=False)), Thread(count=201)):
            with self.subTest(count=thread.count, valid=thread.frame.valid):
                bridge = Bridge()
                bridge.threads = [thread]
                data, result = self.capture(bridge)
                self.assertEqual(data["capture"]["cleanup"]["probeImage"], "not-unloaded-unsafe-debugger-state")
                self.assertFalse(any("dlclose" in expression for expression in bridge.expressions))
                self.assertLessEqual(len(thread.inspected), 200)

    def test_read_failure_still_frees_and_closes_without_publishing(self):
        bridge = Bridge()
        bridge.raw = "not-json"
        data, result = self.capture(bridge)
        self.assertIsNone(data)
        result.SetError.assert_called_once()
        self.assertTrue(any("0x1030" in expression for expression in bridge.expressions))
        self.assertTrue(any("dlclose" in expression for expression in bridge.expressions))

    def test_no_enumerated_threads_prevents_dlclose(self):
        bridge = Bridge()
        bridge.threads = []
        data, result = self.capture(bridge)
        self.assertEqual(data["capture"]["cleanup"]["probeImage"], "not-unloaded-unsafe-debugger-state")
        self.assertFalse(any("dlclose" in expression for expression in bridge.expressions))
        result.AppendWarning.assert_called()

    def test_nonzero_dlclose_is_a_reported_cleanup_failure(self):
        bridge = Bridge()
        bridge.close_result = Value(-1)
        data, result = self.capture(bridge)
        self.assertEqual(data["capture"]["cleanup"]["probeImage"], "dlclose-failed")
        result.AppendWarning.assert_called()

    def test_physical_device_rejected_before_loading(self):
        bridge = Bridge()
        bridge.triple = "arm64-apple-ios27.0"
        data, result = self.capture(bridge)
        self.assertIsNone(data)
        self.assertEqual(bridge.expressions, [])
        self.assertIn("Simulator only", result.SetError.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
