"""Simple concurrent load test against an OpenAI-compatible endpoint (vLLM).

Usage: python scripts/loadtest.py --url http://localhost:8000 --model Qwen/Qwen2.5-0.5B-Instruct -n 50 -c 10
"""
import argparse, asyncio, statistics, time
import httpx

async def one(client, url, model, results):
    t0 = time.perf_counter()
    r = await client.post(f"{url}/v1/chat/completions", json={
        "model": model,
        "messages": [{"role": "user", "content": "Explain Kubernetes in two sentences."}],
        "max_tokens": 128,
    }, timeout=120)
    r.raise_for_status()
    results.append((time.perf_counter() - t0, r.json()["usage"]["completion_tokens"]))

async def main(a):
    results, sem = [], asyncio.Semaphore(a.c)
    async with httpx.AsyncClient() as client:
        async def guarded():
            async with sem:
                await one(client, a.url, a.model, results)
        t0 = time.perf_counter()
        await asyncio.gather(*[guarded() for _ in range(a.n)])
        wall = time.perf_counter() - t0
    lat = sorted(r[0] for r in results)
    toks = sum(r[1] for r in results)
    print(f"requests={len(results)} wall={wall:.1f}s tokens/sec={toks / wall:.1f}")
    print(f"p50={statistics.median(lat):.2f}s p95={lat[int(len(lat) * 0.95) - 1]:.2f}s")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    p.add_argument("-n", type=int, default=50)
    p.add_argument("-c", type=int, default=10)
    asyncio.run(main(p.parse_args()))
