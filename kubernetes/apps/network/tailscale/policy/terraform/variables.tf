variable "oauth_client_id" {
  type = string
}

variable "oauth_client_secret" {
  type      = string
  sensitive = true
}
