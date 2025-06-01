output "ipv4_addresses" {
  value = proxmox_virtual_environment_vm.instance.ipv4_addresses
}

output "name" {
  value = proxmox_virtual_environment_vm.instance.name
}

output "network_interface_names" {
  value = proxmox_virtual_environment_vm.instance.network_interface_names
}
