import os
import signal
import subprocess
from contextlib import contextmanager


@contextmanager
def start_process(command, stdout, stderr):
    """Start the CLI under a platform process group before it can spawn tools."""
    if os.name == "nt":
        from .windows_job import start_windows_process

        with start_windows_process(command, stdout, stderr) as process:
            yield process
        return

    process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
    try:
        yield process
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            finally:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            pass
        process.wait()
