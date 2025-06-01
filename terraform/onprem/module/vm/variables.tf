variable "boot_order" {
  default     = null
  description = "The boot order of the virtual machine."
  type        = list(string)
}

variable "cdrom" {
  default     = ""
  description = "The path to the CD-ROM image (ie. [storage pool]:iso/[name of iso file])."
  type        = string
}

variable "cores" {
  default     = 1
  description = "The number of cores to allocate to the virtual machine."
  type        = number
}

variable "disks" {
  default = [{
    datastore_id = "local-lvm-virtual"
    file_id      = null
    interface    = "virtio0"
    size         = 50
  }]
  description = "The disks to attach to the virtual machine."
  type = list(object({
    datastore_id = string
    file_id      = optional(string)
    interface    = string
    size         = number
  }))
}

variable "memory" {
  default     = 2048
  description = "The amount of memory to allocate to the virtual machine."
  type        = number
}

variable "name" {
  description = "The name of the virtual machine."
  type        = string
}

variable "network_device" {
  default     = "vmbr0"
  description = "The network device type."
  type        = string
}

variable "node_name" {
  description = "The name of the node to deploy the virtual machine on."
  type        = string
}

variable "operating_system" {
  default     = "l26"
  description = "The operating system of the virtual machine."
  type        = string
}
