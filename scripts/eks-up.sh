#!/usr/bin/env bash
# Cluster add-ons for the EKS GPU stack, after `terraform apply` in ./terraform.
# Installs: NVIDIA device plugin, Envoy Gateway, kube-prometheus-stack, KEDA, then the eks-gpu overlay.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
eval "$(terraform -chdir="$ROOT/terraform" output -raw kubeconfig_command)"

helm repo add nvdp https://nvidia.github.io/k8s-device-plugin >/dev/null
helm repo add kedacore https://kedacore.github.io/charts >/dev/null
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo update >/dev/null

# Exposes nvidia.com/gpu on GPU nodes (chart tolerates the nvidia.com/gpu taint by default)
helm upgrade --install nvdp nvdp/nvidia-device-plugin -n nvidia-device-plugin --create-namespace --wait
helm upgrade --install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.3 \
  -n envoy-gateway-system --create-namespace --wait
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f "$ROOT/observability/kps-values.yaml" --wait
helm upgrade --install keda kedacore/keda -n keda --create-namespace --wait

kubectl apply -k "$ROOT/k8s/overlays/eks-gpu"
kubectl apply -k "$ROOT/observability"

echo "GPU node group scales from 0, so the first pod can take ~10 min (node boot + 15 GB model pull)."
kubectl -n llm rollout status deploy/vllm --timeout=30m
kubectl -n envoy-gateway-system get svc -l gateway.envoyproxy.io/owning-gateway-name=llm-gateway
echo "Tear down when finished: kubectl delete -k k8s/overlays/eks-gpu && terraform -chdir=terraform destroy"
