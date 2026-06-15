"""
Measure TTFT (time-to-first-token) for POST /triage/stream from the client side.

Usage:
    uv run python scripts/measure_ttft.py [N] [API_KEY]

    N        number of requests (default: 10)
    API_KEY  defaults to $API_KEY env var

Example:
    uv run python scripts/measure_ttft.py 20 my-api-key

The script reports p50 / p95 / max and optionally compares against POST /triage latency.
Cross-check the TTFT values against the triage.stream.ttft_ms histogram in Logfire:
a difference >50 ms suggests buffering overhead somewhere in the stack.
"""

import asyncio
import math
import os
import sys
import time

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

PAYLOAD = {
    "subject": "I want a refund",
    "sender": "customer@test.com",
    "body": "I bought a product 3 days ago and want to return it.",
}


async def measure_stream_ttft(client: httpx.AsyncClient, api_key: str) -> float:
    t0 = time.perf_counter()
    async with client.stream(
        "POST",
        f"{BASE_URL}/triage/stream",
        json=PAYLOAD,
        headers={"X-Api-Key": api_key},
    ) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes():
            if chunk:
                return (time.perf_counter() - t0) * 1000
    return math.nan


async def measure_sync_latency(client: httpx.AsyncClient, api_key: str) -> float:
    t0 = time.perf_counter()
    resp = await client.post(
        f"{BASE_URL}/triage",
        json=PAYLOAD,
        headers={"X-Api-Key": api_key},
    )
    resp.raise_for_status()
    return (time.perf_counter() - t0) * 1000


def percentile(sorted_samples: list[float], p: float) -> float:
    idx = int(len(sorted_samples) * p)
    return sorted_samples[min(idx, len(sorted_samples) - 1)]


async def main(n: int, api_key: str) -> None:
    print(f"Measuring {n} requests against {BASE_URL} …")
    async with httpx.AsyncClient(timeout=30) as client:
        stream_samples = [await measure_stream_ttft(client, api_key) for _ in range(n)]
        sync_samples = [await measure_sync_latency(client, api_key) for _ in range(n)]

    stream_samples.sort()
    sync_samples.sort()

    print("\n=== POST /triage/stream — TTFT (ms) ===")
    print(
        f"  p50={percentile(stream_samples, 0.5):.0f}  "
        f"p95={percentile(stream_samples, 0.95):.0f}  "
        f"max={stream_samples[-1]:.0f}"
    )

    print("\n=== POST /triage — full latency (ms) ===")
    print(
        f"  p50={percentile(sync_samples, 0.5):.0f}  "
        f"p95={percentile(sync_samples, 0.95):.0f}  "
        f"max={sync_samples[-1]:.0f}"
    )

    improvement = percentile(sync_samples, 0.5) / max(percentile(stream_samples, 0.5), 1)
    print(f"\n  TTFT p50 is {improvement:.1f}× faster than full /triage p50.")


if __name__ == "__main__":
    n_requests = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    key = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("API_KEY", "")
    if not key:
        print("ERROR: API_KEY not set. Pass as argument or set $API_KEY.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(n_requests, key))
