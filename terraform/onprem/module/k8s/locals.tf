locals {
  cluster_name = "k8s-${var.name}"
  talos_bootstrap_host = "control-1"
  talos_endpoint_ipv4  = module.vm[local.talos_bootstrap_host].ipv4_addresses[index(module.vm[local.talos_bootstrap_host].network_interface_names, "eth0")][0]
  talos_endpoint       = "https://${local.talos_endpoint_ipv4}:6443"
  talos_version        = "v1.9.5"

  talos_vm = {
    "control" = {
      count = 1

      settings = {
        cores     = 2
        disk_size = 32
        memory    = 2048
      }
    },
    "worker" = {
      count = 3

      settings = {
        cores     = 2
        disk_size = 64
        memory    = 4096
      }
    }
  }

  vms = flatten([
    for profile_name, profile in local.talos_vm : [
      for index in range(profile.count) : {
        cores     = profile.settings.cores
        disk_size = profile.settings.disk_size
        index     = index + 1
        memory    = profile.settings.memory
        name      = profile_name
      }
    ]
  ])
}
