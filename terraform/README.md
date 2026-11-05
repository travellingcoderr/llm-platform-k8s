# Terraform

Use your existing reusable-module style. Suggested layout:

```
terraform/
  main.tf          # provider + module calls
  variables.tf
  outputs.tf
  modules/
    cluster/       # EKS (terraform-aws-modules/eks/aws) or AKS
    gpu-nodepool/  # one GPU node group (e.g., g5.xlarge / Standard_NC4as_T4_v3), min 0, max 1
```

Cost guardrails:
- GPU node group `min_size = 0` so it scales to zero
- Tag everything `project = llm-platform`, and set a budget alert
- Always run `terraform destroy` after each session
