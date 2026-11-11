"""V8-120: a Docling worker that dies without a traceback is reported with its exit code
and the path of its retained log, so the page's FAILED_FALLBACK can be diagnosed."""
import subprocess
import sys

from ocr_structure.docling_client import worker_exit_message


class FakeProcess:
    def __init__(self, code=None, running=False):
        self.code, self.running = code, running

    def wait(self, timeout=None):
        if self.running:
            raise subprocess.TimeoutExpired("worker", timeout)
        return self.code


def test_real_exit_code_and_log_path_are_reported(tmp_path):
    process = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(3)"])
    message = worker_exit_message(process, tmp_path / "worker.log")
    assert "exit code 3;" in message and str(tmp_path / "worker.log") in message


def test_windows_crash_and_posix_signal_codes_are_shown_in_hex(tmp_path):
    assert "exit code 3221225477 (0xC0000005)" in worker_exit_message(FakeProcess(3221225477), tmp_path / "w.log")
    assert "(0xFFFFFFF7)" in worker_exit_message(FakeProcess(-9), tmp_path / "w.log")
    assert "exit code 0;" in worker_exit_message(FakeProcess(0), tmp_path / "w.log")


def test_a_worker_still_running_after_stdout_closed_is_unknown(tmp_path):
    message = worker_exit_message(FakeProcess(running=True), tmp_path / "w.log", wait_seconds=0.01)
    assert "exit code unknown" in message
