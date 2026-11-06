# EKS cluster for self-hosted LLM serving.
#  - small on-demand "system" node group for controllers (Envoy Gateway, Prometheus, KEDA)
#  - GPU node group that scales to zero (min_size = 0), tainted so only GPU workloads land there
#  - single NAT gateway and public endpoint to keep the demo cheap; tighten both for production
#
#   terraform init && terraform apply -var budget_alert_email=you@example.com
#   aws eks update-kubeconfig --name llm-platform --region us-east-1
#   ... run the benchmark ...
#   terraform destroy        # GPU nodes cost money every hour they exist

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)
  tags = { project = var.name, managed_by = "terraform" }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  name            = var.name
  cidr            = "10.42.0.0/16"
  azs             = local.azs
  private_subnets = ["10.42.0.0/19", "10.42.32.0/19", "10.42.64.0/19"]
  public_subnets  = ["10.42.96.0/22", "10.42.100.0/22", "10.42.104.0/22"]

  enable_nat_gateway = true
  single_nat_gateway = true

  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  endpoint_public_access                   = true
  enable_cluster_creator_admin_permissions = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  addons = {
    coredns                = {}
    kube-proxy             = {}
    eks-pod-identity-agent = { before_compute = true }
    vpc-cni                = { before_compute = true }
  }

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["t3.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      labels         = { workload = "system" }
    }

    gpu = {
      # AL2023 NVIDIA AMI ships the driver and container toolkit; install the NVIDIA device plugin
      # (scripts/eks-addons.sh) so pods can request nvidia.com/gpu.
      ami_type       = "AL2023_x86_64_NVIDIA"
      instance_types = [var.gpu_instance_type]
      capacity_type  = var.gpu_capacity_type
      min_size       = 0
      max_size       = var.gpu_max_nodes
      desired_size   = 0
      disk_size      = 100 # model weights + vLLM image

      labels = { workload = "llm", "nvidia.com/gpu.present" = "true" }
      taints = {
        gpu = { key = "nvidia.com/gpu", value = "true", effect = "NO_SCHEDULE" }
      }
    }
  }
}

resource "aws_budgets_budget" "monthly" {
  count        = var.budget_alert_email == "" ? 0 : 1
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:project$${var.name}"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
