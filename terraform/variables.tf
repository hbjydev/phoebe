variable "org_id" {
  description = "The ID of the GCP organisation to deploy seed resources to."
  type        = string
  sensitive   = true
}

variable "project_id" {
  description = "The ID of the GCP project to deploy seed resources to."
  type        = string
  sensitive   = true
}

variable "project_id_numeric" {
  description = "The numerical ID of the GCP project to deploy seed resources to."
  type        = string
  sensitive   = true
}

variable "wif_pool_id" {
  description = "The ID of the Workload Identity Federation pool to use in IAM setup."
  type        = string
  sensitive   = true
}

variable "op_vault" {
  description = "The Vault in 1Password to store generated secrets in."
  type        = string
  sensitive   = true
}
