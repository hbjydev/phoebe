variable "path" {
  type = string
}

variable "ca_tree_name_prefix" {
  type = string
}

variable "ca_tree_issuer_prefix" {
  type = string
}

variable "intermediates" {
  description = "A map of intermediate certificate authorities to create. The key is the name of the intermediate, and the value is a list of allowed domains for that intermediate."
  type = map(object({
    common_name     = string
    allowed_domains = list(string)
  }))
}
