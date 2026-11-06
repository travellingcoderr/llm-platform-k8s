"""Streaming load test for an OpenAI-compatible endpoint (vLLM or any compatible server).

Measures, per concurrency level:
  - time to first token (TTFT) p50/p95, from the first streamed content chunk
  - end-to-end latency p50/p95
  - output tokens/sec across the whole run, and requests/sec
  - $ per 1M output tokens, given the node price (--usd-per-hour)

Example:
  python scripts/loadtest.py --url http://localhost:8080 --model qwen \
      --concurrency 1,4,8 -n 40 --max-tokens 128 --usd-per-hour 1.006 \
      --label "EKS g5.xlarge, vLLM, Qwen2.5-7B" --out docs/runs/g5-7b.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

PROMPTS = [
    "Explain Kubernetes in two sentences.",
    "Write a haiku about GPUs.",
    "List three risks of running LLMs in production and one mitigation each.",
    "Summarize what a KV cache is for a junior engineer.",
    "Give a short SQL query that counts orders per customer.",
    "What is the difference between latency and throughput?",
    "Describe blue/green deployment in one paragraph.",
    "Why does batching improve GPU utilization for inference?",
]


@dataclass
class RequestResult:
    ok: bool
    ttft_s: float | None = None
    e2e_s: float | None = None
    output_tokens: int = 0
    error: str | None = None


@dataclass
class LevelSummary:
    concurrency: int
    requests: int
    errors: int
    wall_s: float
    output_tokens: int
    tokens_per_s: float
    requests_per_s: float
    ttft_p50_s: float | None
    ttft_p95_s: float | None
    e2e_p50_s: float | None
    e2e_p95_s: float | None
    usd_per_1m_output_tokens: float | None = None
    extra: dict = field(default_factory=dict)


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100). Returns None for an empty list."""
    if not values:
        return None
    s = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(s)))
    return s[rank - 1]


def usd_per_1m_tokens(usd_per_hour: float, tokens_per_s: float) -> float | None:
    """Cost of a dedicated node per 1M generated tokens at a sustained rate."""
    if not usd_per_hour or tokens_per_s <= 0:
        return None
    return usd_per_hour / 3600 / tokens_per_s * 1_000_000


def summarize(concurrency: int, results: list[RequestResult], wall_s: float,
              usd_per_hour: float | None = None) -> LevelSummary:
    good = [r for r in results if r.ok]
    toks = sum(r.output_tokens for r in good)
    tps = toks / wall_s if wall_s > 0 else 0.0
    ttft = [r.ttft_s for r in good if r.ttft_s is not None]
    e2e = [r.e2e_s for r in good if r.e2e_s is not None]
    return LevelSummary(
        concurrency=concurrency, requests=len(results), errors=len(results) - len(good),
        wall_s=round(wall_s, 3), output_tokens=toks, tokens_per_s=round(tps, 2),
        requests_per_s=round(len(good) / wall_s, 3) if wall_s > 0 else 0.0,
        ttft_p50_s=_r(percentile(ttft, 50)), ttft_p95_s=_r(percentile(ttft, 95)),
        e2e_p50_s=_r(percentile(e2e, 50)), e2e_p95_s=_r(percentile(e2e, 95)),
        usd_per_1m_output_tokens=_r(usd_per_1m_tokens(usd_per_hour or 0, tps), 4),
    )


def _r(x, n=3):
    return None if x is None else round(x, n)


async def one_request(client: httpx.AsyncClient, url: str, model: str, prompt: str,
                      max_tokens: int) -> RequestResult:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    t0 = time.perf_counter()
    ttft, chunks, usage_tokens = None, 0, None
    try:
        async with client.stream("POST", f"{url.rstrip('/')}/v1/chat/completions", json=body) as r:
            if r.status_code != 200:
                await r.aread()
                return RequestResult(ok=False, error=f"HTTP {r.status_code}: {r.text[:200]}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("usage"):
                    usage_tokens = event["usage"].get("completion_tokens")
                for choice in event.get("choices") or []:
                    if (choice.get("delta") or {}).get("content"):
                        chunks += 1
                        if ttft is None:
                            ttft = time.perf_counter() - t0
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        return RequestResult(ok=False, error=f"{type(e).__name__}: {e}")
    # Servers that ignore include_usage: fall back to counting content chunks (~1 token each in vLLM).
    tokens = usage_tokens if usage_tokens is not None else chunks
    return RequestResult(ok=True, ttft_s=ttft, e2e_s=time.perf_counter() - t0, output_tokens=tokens)


async def run_level(url: str, model: str, concurrency: int, n: int, max_tokens: int,
                    timeout: float) -> tuple[list[RequestResult], float]:
    sem = asyncio.Semaphore(concurrency)
    results: list[RequestResult] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        async def task(i: int):
            async with sem:
                results.append(await one_request(client, url, model, PROMPTS[i % len(PROMPTS)], max_tokens))
        t0 = time.perf_counter()
        await asyncio.gather(*(task(i) for i in range(n)))
        return results, time.perf_counter() - t0


def markdown_table(label: str, rows: list[LevelSummary]) -> str:
    out = [f"### {label}", "",
           "| Concurrency | Requests (errors) | Output tok/s | Req/s | TTFT p50 / p95 (s) | E2E p50 / p95 (s) | $ / 1M output tokens |",
           "|---|---|---|---|---|---|---|"]
    for s in rows:
        cost = f"{s.usd_per_1m_output_tokens:.2f}" if s.usd_per_1m_output_tokens is not None else "n/a"
        out.append(f"| {s.concurrency} | {s.requests} ({s.errors}) | {s.tokens_per_s} | {s.requests_per_s} | "
                   f"{s.ttft_p50_s} / {s.ttft_p95_s} | {s.e2e_p50_s} / {s.e2e_p95_s} | {cost} |")
    return "\n".join(out)


async def main(a: argparse.Namespace) -> None:
    levels = [int(c) for c in str(a.concurrency).split(",") if c.strip()]
    if a.warmup:
        await run_level(a.url, a.model, 1, a.warmup, a.max_tokens, a.timeout)
    rows = []
    for c in levels:
        results, wall = await run_level(a.url, a.model, c, a.n, a.max_tokens, a.timeout)
        s = summarize(c, results, wall, a.usd_per_hour)
        errs = [r.error for r in results if not r.ok][:3]
        if errs:
            s.extra["sample_errors"] = errs
        rows.append(s)
        print(f"c={c:>3} req={s.requests} err={s.errors} tok/s={s.tokens_per_s} "
              f"ttft_p95={s.ttft_p95_s}s e2e_p95={s.e2e_p95_s}s $/1M={s.usd_per_1m_output_tokens}", flush=True)
    md = markdown_table(a.label, rows)
    print("\n" + md)
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "label": a.label, "url": a.url, "model": a.model, "max_tokens": a.max_tokens,
            "n_per_level": a.n, "usd_per_hour": a.usd_per_hour,
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "levels": [asdict(r) for r in rows],
        }, indent=2))
        out.with_suffix(".md").write_text(md + "\n")
        print(f"\nwrote {out} and {out.with_suffix('.md')}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8080", help="base URL, without /v1")
    p.add_argument("--model", default="qwen", help="served model name")
    p.add_argument("--concurrency", default="1,4,8", help="comma-separated levels to sweep")
    p.add_argument("-n", type=int, default=40, help="requests per concurrency level")
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--warmup", type=int, default=2, help="requests sent before measuring")
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--usd-per-hour", type=float, default=None, help="node price for cost math")
    p.add_argument("--label", default="run")
    p.add_argument("--out", default=None, help="write JSON (and .md next to it)")
    return p.parse_args(argv)


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
