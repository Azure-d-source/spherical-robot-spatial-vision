import unittest
from subprocess import TimeoutExpired
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from src.workers import process_group, runner


class WorkerReportingTests(unittest.TestCase):
    def test_report_gives_up_after_three_network_failures(self):
        stopping = Mock()
        stopping.wait.return_value = False
        with patch.object(runner, "post", side_effect=ConnectionResetError("test")) as post:
            with self.assertLogs(runner.log, level="WARNING"):
                reported, result = runner.report_terminal("api", "jobs/id/complete", {}, stopping)
        self.assertFalse(reported)
        self.assertIsNone(result)
        self.assertEqual(post.call_count, 3)

    def test_posix_reaps_process_after_forced_group_termination(self):
        process = Mock(pid=123)
        process.wait.side_effect = [TimeoutExpired("test", 3), 0]
        operating_system = Mock(name="posix_os")
        operating_system.name = "posix"
        signals = SimpleNamespace(SIGTERM=15, SIGKILL=9)
        with patch.object(process_group, "os", operating_system):
            with patch.object(process_group, "signal", signals):
                with patch.object(process_group.subprocess, "Popen", return_value=process):
                    with process_group.start_process(["test"], None, None):
                        pass
        self.assertEqual(operating_system.killpg.call_args_list, [call(123, 15), call(123, 9)])
        self.assertEqual(process.wait.call_args_list, [call(timeout=3), call()])
