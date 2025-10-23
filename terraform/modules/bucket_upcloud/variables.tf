variable "name" {
  type = string
}

variable "storage_uuid" {
  type = string
}

variable "storage_endpoint_private" {
  type = string
  sensitive = true
}

variable "storage_endpoint_public" {
  type = string
  sensitive = true
}

variable "vault_mount" {
  type = string
}
