"""Compare replay throughput when the in-flight cap changes.

Latency includes time spent waiting for a concurrency slot, so a cap of 1
makes later requests look slow even though each one does the same server work.
"""

import asyncio
import math
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from replay_core.models import RequestSpec
from replay_core.runner import execute

REQUEST_COUNT = 50
DELAY_MS = 20
CONCURRENCY_LEVELS = (1, 10, 50)


def main() -> int:
    port = _free_port()
    stderr_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    stderr_path = Path(stderr_file.name)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--app-dir",
            str(ROOT / "examples" / "demo_api"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
    )
    try:
        _wait_until_ready(port, proc, stderr_path)
        print(f"requests={REQUEST_COUNT} delay_ms={DELAY_MS} latency_includes_queue_wait=true")
        for concurrency in CONCURRENCY_LEVELS:
            if _run_level(port, concurrency) != 0:
                return 1
    finally:
        _stop(proc)
        stderr_file.close()
        try:
            stderr_path.unlink()
        except OSError:
            pass
    return 0


def _run_level(port: int, concurrency: int) -> int:
    specs = [
        RequestSpec(id=f"delay-{index}", method="GET", path=f"/delay?ms={DELAY_MS}")
        for index in range(REQUEST_COUNT)
    ]
    started = time.perf_counter()
    attempts = asyncio.run(
        execute(
            f"http://127.0.0.1:{port}",
            specs,
            concurrency=concurrency,
            timeout=30,
        )
    )
    elapsed = time.perf_counter() - started
    failed = [item.exchange for item in attempts if item.exchange.error or item.exchange.status != 200]
    if failed:
        first = failed[0]
        print(f"concurrency={concurrency} failed {first.id}: {first.error or first.status}", file=sys.stderr)
        return 1
    latencies = [item.elapsed_ms for item in attempts]
    throughput = REQUEST_COUNT / elapsed
    print(
        f"concurrency={concurrency:<2} "
        f"throughput_rps={throughput:7.1f} "
        f"p50_ms={_percentile(latencies, 50):7.1f} "
        f"p95_ms={_percentile(latencies, 95):7.1f} "
        f"wall_ms={elapsed * 1000:7.1f}"
    )
    return 0


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(port: int, proc: subprocess.Popen[bytes], stderr_path: Path) -> None:
    import httpx

    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(stderr_path.read_text(encoding="utf-8"))
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/v1/health", timeout=0.5)
        except httpx.HTTPError:
            time.sleep(0.1)
            continue
        if response.status_code == 200:
            return
    raise RuntimeError(stderr_path.read_text(encoding="utf-8") or "demo API did not start")


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
