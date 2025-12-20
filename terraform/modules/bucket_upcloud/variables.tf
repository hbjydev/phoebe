variable "name" {
  type = string
}

variable "storage_uuid" {
  type = string
}

variable "restic" {
  type = bool
}

variable "storage_endpoint_private" {
  type = string
  sensitive = true
}

variable "storage_endpoint_public" {
  type = string
  sensitive = true
}

variable "op_vault_id" {
  type = string
}
