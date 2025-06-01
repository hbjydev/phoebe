module "k8s" {
  for_each = local.k8s

  source = "./module/k8s"

  name       = each.key
  node_names = each.value.node_names
}

module "vm" {
  for_each = local.vm

  source = "./module/vm"

  cores          = each.value.cores
  disks          = each.value.disks
  memory         = each.value.memory
  name           = each.key
  network_device = try(each.value.network_device, "vmbr0")
  node_name      = each.value.node_name
}
