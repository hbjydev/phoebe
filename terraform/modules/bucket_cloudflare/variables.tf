variable "name" {
  type = string
}

variable "account_id" {
  type = string
}

variable "storage_class" {
  type = string
}

variable "region" {
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
