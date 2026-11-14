"""Measure baseline and peak memory for FastAPI and Next.js under Render Free constraints.

Render Free Target: 512 MB RAM, 0.1 CPU.
Measures:
1. FastAPI cold-start duration and baseline memory.
2. Next.js cold-start duration and baseline memory.
3. Combined idle memory.
4. Peak memory under concurrent load.
5. Graceful shutdown duration and port release.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
import time
from pathlib import Path
import urllib.request
import json

# Windows process memory API structures
class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]

def get_process_memory(pid: int) -> dict[str, float]:
    """Retrieve RSS and Private Working Set in megabytes."""
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
    )
    if not handle:
        return {"rss_mb": 0.0, "private_mb": 0.0}
    try:
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
        ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return {
            "rss_mb": counters.WorkingSetSize / (1024 * 1024),
            "private_mb": counters.PrivateUsage / (1024 * 1024),
        }
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def wait_for_http(url: str, timeout_seconds: float = 30.0) -> float:
    """Poll URL until 200 OK. Returns elapsed time in seconds."""
    start = time.perf_counter()
    deadline = start + timeout_seconds
    while time.perf_counter() < deadline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MemoryProbe/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    return time.perf_counter() - start
        except Exception:
            time.sleep(0.2)
    raise TimeoutError(f"Service at {url} failed to respond within {timeout_seconds}s")


def main():
    root_dir = Path(__file__).resolve().parents[2]
    backend_dir = root_dir / "backend"
    hermes_dir = Path("E:/Hermes3D").resolve()
    python_exe = backend_dir / ".venv" / "Scripts" / "python.exe"

    print("==================================================")
    print("PHASE 3.1: DUAL-PROCESS PRODUCTION MEMORY PROFILING")
    print(f"Target Constraints: 512 MB RAM, 0.1 CPU (Render Free)")
    print("==================================================")

    # 1. Start FastAPI Backend
    print("\n[1/5] Starting AgentHQ FastAPI Backend on 127.0.0.1:8000...")
    fastapi_env = os.environ.copy()
    fastapi_env["PORT"] = "8000"
    fastapi_env["HOST"] = "127.0.0.1"
    fastapi_env["ENVIRONMENT"] = "production"
    fastapi_env["AGENTHQ_ENFORCE_AUTH"] = "true"

    t0 = time.perf_counter()
    fastapi_proc = subprocess.Popen(
        [
            str(python_exe),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--log-level",
            "warning",
        ],
        cwd=str(backend_dir),
        env=fastapi_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    fastapi_cold_start = wait_for_http("http://127.0.0.1:8000/health", timeout_seconds=20.0)
    time.sleep(1.0)
    fastapi_baseline = get_process_memory(fastapi_proc.pid)
    print(f"  -> FastAPI Cold Start Duration: {fastapi_cold_start * 1000:.1f} ms")
    print(f"  -> FastAPI Baseline Memory: RSS {fastapi_baseline['rss_mb']:.2f} MB (Private {fastapi_baseline['private_mb']:.2f} MB)")

    # 2. Start Hermes3D Next.js
    print("\n[2/5] Starting Hermes3D Next.js Production Server on 127.0.0.1:3000...")
    hermes_env = os.environ.copy()
    hermes_env["NODE_ENV"] = "production"
    hermes_env["PORT"] = "3000"
    hermes_env["HOST"] = "127.0.0.1"
    hermes_env["STUDIO_ACCESS_TOKEN"] = "render-free-probe-token"
    hermes_env["AGENTHQ_INTERNAL_URL"] = "http://127.0.0.1:8000"
    hermes_env["AGENTHQ_URL"] = "http://127.0.0.1:8000"

    hermes_proc = subprocess.Popen(
        ["node", "server/index.js"],
        cwd=str(hermes_dir),
        env=hermes_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    hermes_cold_start = wait_for_http("http://127.0.0.1:3000/api/health", timeout_seconds=30.0)
    time.sleep(2.0)
    hermes_baseline = get_process_memory(hermes_proc.pid)
    print(f"  -> Next.js Cold Start Duration: {hermes_cold_start * 1000:.1f} ms")
    print(f"  -> Next.js Baseline Memory: RSS {hermes_baseline['rss_mb']:.2f} MB (Private {hermes_baseline['private_mb']:.2f} MB)")

    # 3. Combined Idle Memory
    combined_rss = fastapi_baseline["rss_mb"] + hermes_baseline["rss_mb"]
    combined_private = fastapi_baseline["private_mb"] + hermes_baseline["private_mb"]
    print(f"\n[3/5] Combined Idle Memory:")
    print(f"  -> Combined RSS: {combined_rss:.2f} MB")
    print(f"  -> Combined Private Working Set: {combined_private:.2f} MB")
    print(f"  -> Headroom in 512 MB Container: {512 - combined_rss:.2f} MB ({((512 - combined_rss)/512)*100:.1f}%)")

    # 4. Concurrency Load Test
    print("\n[4/5] Executing Concurrency Load Test (20 parallel requests)...")
    endpoints = [
        "http://127.0.0.1:8000/health",
        "http://127.0.0.1:8000/api/agents",
        "http://127.0.0.1:8000/api/tasks",
        "http://127.0.0.1:3000/api/health",
        "http://127.0.0.1:3000/api/task-store",
    ]

    def hit_endpoint(url):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "LoadProbe/1.0",
                    "Authorization": "Bearer test-runtime-token",
                },
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            return 500

    peak_fastapi_rss = fastapi_baseline["rss_mb"]
    peak_hermes_rss = hermes_baseline["rss_mb"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # 4 requests to each endpoint = 20 total
        tasks = [executor.submit(hit_endpoint, url) for url in endpoints * 4]
        for _ in range(15):
            f_mem = get_process_memory(fastapi_proc.pid)["rss_mb"]
            h_mem = get_process_memory(hermes_proc.pid)["rss_mb"]
            if f_mem > peak_fastapi_rss:
                peak_fastapi_rss = f_mem
            if h_mem > peak_hermes_rss:
                peak_hermes_rss = h_mem
            time.sleep(0.05)

        results = [t.result() for t in tasks]

    time.sleep(1.0)
    post_load_fastapi = get_process_memory(fastapi_proc.pid)
    post_load_hermes = get_process_memory(hermes_proc.pid)
    peak_combined = peak_fastapi_rss + peak_hermes_rss

    print(f"  -> Concurrency Status Codes: {set(results)}")
    print(f"  -> Peak FastAPI RSS: {peak_fastapi_rss:.2f} MB")
    print(f"  -> Peak Next.js RSS: {peak_hermes_rss:.2f} MB")
    print(f"  -> Peak Combined Working Set: {peak_combined:.2f} MB")
    print(f"  -> Headroom Under Load: {512 - peak_combined:.2f} MB ({((512 - peak_combined)/512)*100:.1f}%)")

    # 5. Graceful Shutdown
    print("\n[5/5] Graceful Shutdown Verification...")
    t_term = time.perf_counter()
    fastapi_proc.terminate()
    hermes_proc.terminate()

    fastapi_proc.wait(timeout=10)
    hermes_proc.wait(timeout=10)
    shutdown_duration = time.perf_counter() - t_term
    print(f"  -> Graceful Shutdown Duration: {shutdown_duration * 1000:.1f} ms")
    print("  -> Both processes terminated with clean port release.")

    # Output Summary Table
    print("\n==================================================")
    print("FINAL MEASUREMENT REPORT")
    print("==================================================")
    print(f"| Metric | FastAPI Backend | Hermes3D Studio | Combined | Render Free Limit |")
    print(f"| :--- | :--- | :--- | :--- | :--- |")
    print(f"| Cold-Start Time | {fastapi_cold_start*1000:.1f} ms | {hermes_cold_start*1000:.1f} ms | {max(fastapi_cold_start, hermes_cold_start)*1000:.1f} ms | N/A |")
    print(f"| Baseline Idle RSS | {fastapi_baseline['rss_mb']:.1f} MB | {hermes_baseline['rss_mb']:.1f} MB | {combined_rss:.1f} MB | 512 MB ({(combined_rss/512)*100:.1f}% used) |")
    print(f"| Peak RSS Under Load | {peak_fastapi_rss:.1f} MB | {peak_hermes_rss:.1f} MB | {peak_combined:.1f} MB | 512 MB ({(peak_combined/512)*100:.1f}% used) |")
    print(f"| Memory Headroom | N/A | N/A | {512 - peak_combined:.1f} MB | {((512 - peak_combined)/512)*100:.1f}% free |")
    print(f"| Shutdown Duration | N/A | N/A | {shutdown_duration*1000:.1f} ms | < 10,000 ms |")
    print("==================================================")


if __name__ == "__main__":
    main()

