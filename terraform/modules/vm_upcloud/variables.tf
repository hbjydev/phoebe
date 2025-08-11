variable "name" {
  type = string
}

variable "zone" {
  type = string
}

variable "plan" {
  type = string
}

variable "network" {
  type = string
}

variable "tailscale" {
  type = bool
}

variable "volumes" {
  type = list(object({
    name      = string
    mountPath = string
    size      = number
  }))
}
