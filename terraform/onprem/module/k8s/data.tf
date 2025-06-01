data "talos_image_factory_extensions_versions" "this" {
  talos_version = local.talos_version

  filters = {
    names = [
      "qemu-guest-agent"
    ]
  }
}

data "talos_image_factory_urls" "this" {
  platform      = "nocloud"
  schematic_id  = talos_image_factory_schematic.this.id
  talos_version = local.talos_version
}

data "talos_machine_configuration" "control" {
  cluster_endpoint = local.talos_endpoint
  cluster_name     = var.name
  machine_secrets  = talos_machine_secrets.this.machine_secrets
  machine_type     = "controlplane"
  talos_version    = local.talos_version
}

data "talos_machine_configuration" "worker" {
  cluster_endpoint = local.talos_endpoint
  cluster_name     = var.name
  machine_secrets  = talos_machine_secrets.this.machine_secrets
  machine_type     = "worker"
  talos_version    = local.talos_version
}

data "talos_client_configuration" "this" {
  client_configuration = talos_machine_secrets.this.client_configuration
  cluster_name         = var.name
  nodes                = [local.talos_endpoint_ipv4]
}
