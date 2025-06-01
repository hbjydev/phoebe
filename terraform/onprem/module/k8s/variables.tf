variable "name" {
  description = "Name of the cluster"
  type        = string
}

variable "node_names" {
  description = "List of node names"
  type        = list(string)
}
