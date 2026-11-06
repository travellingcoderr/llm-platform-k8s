#!/usr/bin/env bash
# Local CPU-only stack: kind + Envoy Gateway + kube-prometheus-stack + vLLM (CPU build, Qwen2.5-0.5B).
# Needs: docker, kind, kubectl, helm. Roughly 8 GB free RAM.
set -euo pipefail
CLUSTER=${CLUSTER:-llm}
ROOT=$(cd "$(dirname "$0")/.." && pwd)

kind get clusters | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER"

# Envoy Gateway (also installs the Gateway API CRDs)
helm upgrade --install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.3 \
  -n envoy-gateway-system --create-namespace --wait

# Prometheus + Grafana (release "kps"; fullnameOverride keeps service names short)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo update >/dev/null
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f "$ROOT/observability/kps-values.yaml" --wait

kubectl apply -k "$ROOT/k8s/overlays/kind-cpu"
kubectl apply -k "$ROOT/observability"

echo "Waiting for vLLM (first start downloads the model)..."
kubectl -n llm rollout status deploy/vllm --timeout=20m

SVC=$(kubectl -n envoy-gateway-system get svc \
  -l gateway.envoyproxy.io/owning-gateway-name=llm-gateway -o jsonpath='{.items[0].metadata.name}')
cat <<MSG

Ready. In separate terminals:
  kubectl -n envoy-gateway-system port-forward svc/$SVC 8080:80
  kubectl -n monitoring port-forward svc/kps-grafana 3000:80      # admin / change-me
Then:
  python scripts/loadtest.py --url http://localhost:8080 --model qwen --concurrency 1,4,8 -n 40
MSG
