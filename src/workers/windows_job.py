"""Keep Windows worker children in a Job Object that closes with the runner."""

import ctypes
import subprocess
import sys
from contextlib import contextmanager
from ctypes import wintypes


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


def checked(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


@contextmanager
def start_windows_process(command, stdout, stderr):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    job = checked(kernel.CreateJobObjectW(None, None))
    process = None
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        checked(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        # Wait for job assignment before starting the CLI or any of its descendants.
        gate = "import subprocess, sys; sys.exit(subprocess.call(sys.argv[1:]) if sys.stdin.buffer.read(1) else 1)"
        process = subprocess.Popen([sys.executable, "-c", gate, *command],
                                   stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
        handle = checked(kernel.OpenProcess(0x0101, False, process.pid))  # SET_QUOTA | TERMINATE
        try:
            checked(kernel.AssignProcessToJobObject(job, handle))
        finally:
            kernel.CloseHandle(handle)
        process.stdin.write(b"1")
        process.stdin.close()
        yield process
    finally:
        kernel.CloseHandle(job)
        if process is not None:
            if not process.stdin.closed:
                process.stdin.close()
            process.wait()
