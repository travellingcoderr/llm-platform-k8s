variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "llm-platform"
}

variable "kubernetes_version" {
  type    = string
  default = "1.36"
}

variable "gpu_instance_type" {
  description = "g5.xlarge = 1x NVIDIA A10G 24 GB (about $1.006/hr on-demand in us-east-1, Nov 2026)"
  type        = string
  default     = "g5.xlarge"
}

variable "gpu_capacity_type" {
  description = "ON_DEMAND or SPOT. Spot is roughly half price but can be reclaimed."
  type        = string
  default     = "ON_DEMAND"
}

variable "gpu_max_nodes" {
  type    = number
  default = 1
}

variable "monthly_budget_usd" {
  description = "AWS Budgets alert for everything tagged project=<name>"
  type        = number
  default     = 50
}

variable "budget_alert_email" {
  description = "Email for budget alerts. Leave empty to skip the budget."
  type        = string
  default     = ""
}
