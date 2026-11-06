import asyncio, json, subprocess, sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import loadtest as lt  # noqa: E402


def test_percentile_nearest_rank():
    assert lt.percentile([], 50) is None
    assert lt.percentile([3, 1, 2], 50) == 2
    assert lt.percentile(list(range(1, 101)), 95) == 95
    assert lt.percentile([5], 99) == 5


def test_cost_per_million_tokens():
    # $1.006/h at 500 tok/s -> 1.006/3600/500*1e6 = 0.5589
    assert lt.usd_per_1m_tokens(1.006, 500) == pytest.approx(0.5589, abs=1e-4)
    assert lt.usd_per_1m_tokens(1.0, 0) is None
    assert lt.usd_per_1m_tokens(0, 100) is None


def test_summarize_excludes_errors():
    rs = [lt.RequestResult(ok=True, ttft_s=0.1, e2e_s=1.0, output_tokens=100),
          lt.RequestResult(ok=True, ttft_s=0.3, e2e_s=2.0, output_tokens=100),
          lt.RequestResult(ok=False, error="boom")]
    s = lt.summarize(2, rs, wall_s=2.0, usd_per_hour=3.6)
    assert (s.requests, s.errors, s.output_tokens) == (3, 1, 200)
    assert s.tokens_per_s == 100
    assert s.usd_per_1m_output_tokens == pytest.approx(10.0)
    assert s.ttft_p95_s == 0.3


def _sse(events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


def test_one_request_parses_stream_and_usage():
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True
        events = [{"choices": [{"delta": {"role": "assistant"}}]},
                  {"choices": [{"delta": {"content": "Hello"}}]},
                  {"choices": [{"delta": {"content": " world"}}]},
                  {"choices": [], "usage": {"completion_tokens": 7}}]
        return httpx.Response(200, text=_sse(events), headers={"content-type": "text/event-stream"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await lt.one_request(c, "http://x", "m", "hi", 16)
    r = asyncio.run(go())
    assert r.ok and r.output_tokens == 7 and r.ttft_s is not None and r.e2e_s >= r.ttft_s


def test_one_request_counts_chunks_without_usage_and_reports_http_errors():
    def ok(request):
        return httpx.Response(200, text=_sse([{"choices": [{"delta": {"content": t}}]} for t in "abc"]))

    def bad(request):
        return httpx.Response(503, text="overloaded")

    async def go(h):
        async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as c:
            return await lt.one_request(c, "http://x", "m", "hi", 16)
    assert asyncio.run(go(ok)).output_tokens == 3
    r = asyncio.run(go(bad))
    assert not r.ok and "503" in r.error


def test_markdown_table_has_row_per_level():
    s = lt.summarize(4, [lt.RequestResult(ok=True, ttft_s=0.1, e2e_s=1, output_tokens=10)], 1.0, None)
    md = lt.markdown_table("x", [s, s])
    assert md.count("\n| 4 |") == 2 and "n/a" in md


def test_grafana_dashboard_queries_reference_vllm_or_recording_rules():
    dash = json.loads((ROOT / "observability" / "grafana-dashboard.json").read_text())
    exprs = [t["expr"] for p in dash["panels"] for t in p["targets"]]
    assert exprs and all(("vllm:" in e) or e.startswith(("llm:", "histogram_quantile", "sum(", "max(", "avg(")) for e in exprs)
    rules = (ROOT / "observability" / "cost-rules.yaml").read_text()
    for name in ["llm:usd_per_1m_output_tokens", "llm:generation_tokens:rate5m", "llm:ttft_seconds:p95_5m"]:
        assert name in rules


def test_shell_scripts_parse():
    for s in (ROOT / "scripts").glob("*.sh"):
        subprocess.run(["bash", "-n", str(s)], check=True)
