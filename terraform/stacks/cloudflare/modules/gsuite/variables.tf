variable "domain" {
  type = string
}

variable "dkim_value" {
  type      = string
  sensitive = false
}

variable "zone_id" {
  type      = string
  sensitive = true
}
