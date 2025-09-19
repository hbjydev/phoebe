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

variable "op_title" {
  type = string
  nullable = true
}

variable "op_vault" {
  type = string
  sensitive = true
}
