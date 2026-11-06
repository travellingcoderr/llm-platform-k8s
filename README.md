# Self-Hosted LLM Platform on Kubernetes

Serve an open-weight LLM with **vLLM** on Kubernetes, route traffic through the **Gateway API** (Envoy Gateway), autoscale on queue depth with **KEDA**, and track **tokens/sec, latency and $ per 1M tokens** in Prometheus and Grafana. The AWS side is provisioned with **Terraform** (EKS + a GPU node group that scales to zero).

```
                    ┌──────────────── EKS / kind ─────────────────────────────────────┐
client ──HTTP──►  Gateway (Envoy) ──► HTTPRoute ──► Service ──► vLLM pods (GPU node, scale 0..N)
                    │                                              │ /metrics
                    │   KEDA ScaledObject ◄── Prometheus ◄─────────┘ (ServiceMonitor)
                    │   (vllm:num_requests_waiting)  │
                    │                                └──► recording rules ──► Grafana dashboard
                    └─────────────────────────────────────────────────────────────────┘
```

## What's in the repo

| Path | What it does |
|---|---|
| `terraform/` | VPC + EKS (`terraform-aws-modules` VPC v6, EKS v21), a small system node group, a tainted `g5.xlarge` GPU node group with `min_size = 0`, and an AWS Budgets alert |
| `k8s/base/` | vLLM Deployment (OpenAI-compatible server, readiness/liveness/startup probes, `/dev/shm`, PDB), Gateway API `GatewayClass`/`Gateway`/`HTTPRoute` (300 s timeout for long generations), `ServiceMonitor` |
| `k8s/overlays/kind-cpu` | Local, no GPU: vLLM CPU image + `Qwen2.5-0.5B-Instruct` |
| `k8s/overlays/eks-gpu` | `Qwen2.5-7B-Instruct` on 1x A10G, GPU toleration/node selector, KEDA `ScaledObject` scaling on `vllm:num_requests_waiting` |
| `observability/` | kube-prometheus-stack values, `PrometheusRule` (throughput, p95 TTFT/E2E, **$ per 1M output tokens**, backlog + KV-cache alerts), Grafana dashboard (auto-loaded by the sidecar) |
| `scripts/kind-up.sh`, `scripts/eks-up.sh` | One-command bootstrap of the add-ons and the right overlay |
| `scripts/loadtest.py` | Streaming load tester: TTFT, E2E p50/p95, tokens/sec and $ / 1M tokens across a concurrency sweep; writes JSON + a markdown table |
| `.github/workflows/ci.yml` | `terraform fmt/validate`, `kustomize build` + `kubeconform -strict` (incl. Gateway API, Prometheus Operator and KEDA CRDs), `pytest` |

## Run it locally (free, CPU only)

Needs Docker, kind, kubectl and helm, and about 8 GB of free RAM.

```bash
./scripts/kind-up.sh
kubectl -n envoy-gateway-system port-forward svc/<printed-service> 8080:80 &
curl localhost:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qwen","messages":[{"role":"user","content":"Hello"}]}'
python scripts/loadtest.py --url http://localhost:8080 --model qwen --concurrency 1,4 -n 20 --label "kind CPU"
```

Grafana: `kubectl -n monitoring port-forward svc/kps-grafana 3000:80` and open the "LLM Platform" dashboard.

## Run it on AWS with a GPU

A `g5.xlarge` is about $1.006/hour on demand in us-east-1 ([DoiT pricing](https://www.doit.com/compute/compute/aws/us-east-1/g5.xlarge)), plus the EKS control plane and a NAT gateway. The GPU group scales to zero, but **run `terraform destroy` when you're done.**

```bash
cd terraform && cp terraform.tfvars.example terraform.tfvars   # set budget_alert_email
terraform init && terraform apply
cd .. && ./scripts/eks-up.sh
python scripts/loadtest.py --url http://<gateway-lb-hostname> --model qwen \
  --concurrency 1,4,8,16,32 -n 64 --usd-per-hour 1.006 \
  --label "EKS g5.xlarge, vLLM v0.32, Qwen2.5-7B" --out docs/runs/g5-7b.json
kubectl delete -k k8s/overlays/eks-gpu && terraform -chdir=terraform destroy
```

## How cost per token is computed

For a dedicated node, cost per 1M output tokens = (node $/hour ÷ 3600) ÷ sustained output tokens/sec × 1,000,000. The same formula is used by `loadtest.py` (offline) and by the `llm:usd_per_1m_output_tokens` recording rule (live, from `vllm:generation_tokens_total`). Set the node price in `observability/cost-rules.yaml`. This ignores idle time, so the real number is only reached when the node stays busy; that's the main argument for scale-to-zero and for queue-based autoscaling.

## Results

See [docs/benchmark-results.md](docs/benchmark-results.md). The GPU numbers are filled in from a real EKS run; no numbers in this repo are estimates.

## Design notes

- **Gateway API over Ingress:** typed routes, per-route timeouts, and a clean path to AI-gateway features (rate limits per tenant, model routing) without annotations.
- **KEDA on `num_requests_waiting`, not CPU:** GPU inference saturates on batch/KV-cache capacity, so the queue is the honest signal. Scale-up is aggressive, scale-down has a 5 min cooldown because a cold start (node + model pull) takes minutes.
- **Taint + toleration on GPU nodes** so system pods never land on the expensive node and it can scale to zero.
- **Pinned versions** (vLLM image, Envoy Gateway chart, Terraform modules) so the stack reproduces.
