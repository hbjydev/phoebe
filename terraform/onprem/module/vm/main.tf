resource "proxmox_virtual_environment_vm" "instance" {
  boot_order    = var.boot_order
  migrate       = true
  name          = var.name
  node_name     = var.node_name
  scsi_hardware = "virtio-scsi-single" # enabled for iothread

  agent {
    enabled = true
  }

  cdrom {
    file_id = var.cdrom
  }

  cpu {
    cores = var.cores
    type  = "x86-64-v2-AES"
  }

  dynamic "disk" {
    for_each = toset(var.disks)

    content {
      datastore_id = disk.value.datastore_id
      file_id      = disk.value.file_id
      interface    = disk.value.interface
      iothread     = true # enabled w/ virtio-scsi-single
      size         = disk.value.size
    }
  }

  memory {
    dedicated = var.memory
    floating  = 0
  }

  network_device {
    bridge = var.network_device
  }

  operating_system {
    type = var.operating_system
  }

  lifecycle {
    ignore_changes = [disk[0].file_id]
  }
}
