# Benchmark results

Produced with `scripts/loadtest.py` (streaming, `max_tokens=128`, `temperature=0`, 8 rotating short prompts). Each row is one concurrency level. Raw JSON for each run lives in `docs/runs/`.

Cost per 1M output tokens = (node $/hour ÷ 3600) ÷ output tokens/sec × 1e6, assuming the node is fully busy.

## EKS g5.xlarge (1x NVIDIA A10G 24 GB), vLLM v0.32.0, Qwen2.5-7B-Instruct

Node price: $1.006/hour on demand, us-east-1 ([DoiT](https://www.doit.com/compute/compute/aws/us-east-1/g5.xlarge)).

_Pending: run `./scripts/eks-up.sh`, then the load test command in the README, and paste the generated `docs/runs/g5-7b.md` here._

## kind, CPU only, vLLM CPU build, Qwen2.5-0.5B-Instruct

_Pending: needs a machine with Docker and about 8 GB of free RAM (`./scripts/kind-up.sh`)._

## Hosted API comparison

To compare with a hosted model, take the provider's published price per 1M output tokens for a model of similar quality and put it next to the self-hosted number at the concurrency you actually expect. Self-hosting only wins when utilization stays high; at low traffic the idle GPU dominates.

| Option | $ / 1M output tokens | Notes |
|---|---|---|
| Self-hosted, g5.xlarge, Qwen2.5-7B | _from the run above_ | at concurrency __ |
| Hosted API (model, date checked) | _published price_ | |
