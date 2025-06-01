resource "talos_image_factory_schematic" "this" {
  schematic = yamlencode(
    {
      customization = {
        systemExtensions = {
          officialExtensions = data.talos_image_factory_extensions_versions.this.extensions_info.*.name
        }
      }
    }
  )
}

resource "proxmox_virtual_environment_download_file" "this" {
  for_each = toset(var.node_names)

  content_type = "iso"
  datastore_id = "local"
  node_name    = each.value
  file_name    = "${local.cluster_name}.iso"
  url          = data.talos_image_factory_urls.this.urls.iso
}

module "vm" {
  for_each = { for vm in local.vms : "${vm.name}-${vm.index}" => vm }

  source = "../vm"

  boot_order     = ["virtio0", "ide3", "net0"]
  cdrom          = proxmox_virtual_environment_download_file.this[var.node_names[each.value.index % length(var.node_names)]].id
  cores          = each.value.cores
  memory         = each.value.memory
  name           = "${local.cluster_name}-${each.value.name}"
  node_name      = var.node_names[each.value.index % length(var.node_names)]

  disks = [
    {
      datastore_id = "local-lvm"
      file_id      = null
      interface    = "virtio0"
      size         = each.value.disk_size
    }
  ]
}

resource "talos_machine_secrets" "this" {
  talos_version = local.talos_version
}

resource "talos_machine_configuration_apply" "this" {
  for_each = { for vm_key, vm in module.vm : vm_key => vm }

  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = strcontains(each.value.name, "control") ? data.talos_machine_configuration.control.machine_configuration : data.talos_machine_configuration.worker.machine_configuration
  node                        = each.value.ipv4_addresses[index(each.value.network_interface_names, "eth0")][0]

  config_patches = [
    yamlencode({
      machine = {
        install = {
          disk  = "/dev/vda"
          image = data.talos_image_factory_urls.this.urls.installer
        },
        kubelet = {
          extraConfig = {
            serverTLSBootstrap = true
          }
        }
      }
    })
  ]
}

resource "talos_machine_bootstrap" "this" {
  client_configuration = talos_machine_secrets.this.client_configuration
  node                 = local.talos_endpoint_ipv4

  depends_on = [
    talos_machine_configuration_apply.this
  ]
}
