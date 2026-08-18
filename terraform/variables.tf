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
