variable "name" {
  type = string
}

variable "storage_uuid" {
  type = string
}

variable "op_title" {
  type = string
  nullable = true
}

variable "op_vault" {
  type = string
  sensitive = true
}
