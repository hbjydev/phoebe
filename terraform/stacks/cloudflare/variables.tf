variable "api_token" {
  type      = string
  sensitive = true
}

variable "account_id" {
  type      = string
  sensitive = true
}

variable "domains" {
  sensitive = false
  type = map(object({
    domain  = string
    zone_id = string
  }))
}
