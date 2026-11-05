# Project 01: Self-Hosted LLM Platform on Kubernetes

Serve an open-source LLM (Qwen / Llama) with **vLLM** on Kubernetes, expose it through the **Kubernetes Gateway API**, autoscale it, and track cost per token, all provisioned with **Terraform**.

**Why it matters:** many AI Platform / LLMOps job posts ask for open-source model serving, GPU workloads, and Kubernetes. This builds on your EKS + Terraform experience and the Gateway API you've been learning.

## Architecture
```
Client ──► Gateway (Gateway API) ──► HTTPRoute ──► Service ──► vLLM Deployment (GPU node)
                                                              │
                                    Prometheus ◄── /metrics ──┘ ──► Grafana (tokens/sec, latency, $/1M tokens)
```

## Milestones (about 2–3 weeks, 6–8 hrs/week)
1. **Local first (no GPU cost):** run `kind` locally, deploy vLLM in CPU mode with a tiny model (`Qwen/Qwen2.5-0.5B-Instruct`), call it with `curl`.
2. **Gateway API:** install a Gateway API implementation (e.g., Envoy Gateway or NGINX Gateway Fabric), apply `k8s/gateway.yaml` + `k8s/httproute.yaml`.
3. **Cloud GPU:** Terraform an EKS (or AKS) cluster with one GPU node pool (`terraform/`), deploy `k8s/vllm-deployment.yaml`. **Destroy it when done**, because GPU nodes are expensive.
4. **Observability:** scrape vLLM `/metrics` with Prometheus, build a Grafana dashboard: tokens/sec, p95 latency, GPU util, cost per 1M tokens.
5. **Load test + autoscale:** load test with `scripts/loadtest.py`, add an HPA or KEDA on queue depth, document results.
6. **Write-up:** README with diagram, benchmark table, cost comparison vs a hosted API (Claude / Azure OpenAI).

## Quick start (local)
```bash
kind create cluster --name llm
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/vllm-deployment.yaml   # edit image/resources for CPU vs GPU first
kubectl -n llm port-forward svc/vllm 8000:8000
curl localhost:8000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"Hello"}]}'
```

## Resume bullet once finished (fill in your numbers)
> Built a self-hosted LLM serving platform (vLLM on Kubernetes, Gateway API, Terraform) with Prometheus/Grafana token-cost observability, sustaining __ tokens/sec at p95 __ ms and cutting cost per 1M tokens by __% vs hosted APIs.
