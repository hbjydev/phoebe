resource "upcloud_router" "dione" {
  name = "${local.resource_prefix}-dione-rt"
  labels = {
    "moe.hayden.source" = "github/hbjydev/phoebe",
    "moe.hayden.network" = "dione",
  }
}

resource "upcloud_network" "dione" {
  name   = "${local.resource_prefix}-dione-net"
  router = upcloud_router.dione.id
  zone   = "uk-lon1"

  ip_network {
    dhcp    = true
    family  = "IPv4"
    address = "172.19.0.0/24"
  }
}

resource "upcloud_managed_object_storage" "dione" {
  name              = "${local.resource_prefix}-dione-os"
  region            = "europe-1"
  configured_status = "started"

  network {
    family = "IPv4"
    type   = "private"
    name   = "dione-net"
    uuid   = upcloud_network.dione.id
  }

  network {
    family = "IPv4"
    type   = "public"
    name   = "public-net"
  }

  labels = {
    "moe.hayden.source" = "github/hbjydev/phoebe",
    "moe.hayden.network" = "dione",
  }
}

module "bucket_upcloud" {
  source   = "./modules/bucket_upcloud"
  for_each = local.buckets_upcloud

  name = try(each.value.name, each.key)

  storage_uuid             = upcloud_managed_object_storage.dione.id
  storage_endpoint_private = tolist(upcloud_managed_object_storage.dione.endpoint)[index(tolist(upcloud_managed_object_storage.dione.endpoint.*.type), "private")].domain_name
  storage_endpoint_public  = tolist(upcloud_managed_object_storage.dione.endpoint)[index(tolist(upcloud_managed_object_storage.dione.endpoint.*.type), "public")].domain_name

  op_title = try(each.value.name, "uc-os-${try(each.value.name, each.key)}")
  op_vault = var.PHOEBE_VAULT_ID
}

moved {
  from = module.bucket
  to = module.bucket_cloudflare
}

module "bucket_cloudflare" {
  source   = "./modules/storage_bucket"
  for_each = local.buckets_cloudflare

  name          = try(each.value.name, each.key)
  account_id    = "09c8f0e370aa6c96c9b46741f994d5f5"
  storage_class = try(each.value.storage_class, "Standard")
  region        = try(each.value.region, "WEUR")
  op_title      = try(each.value.name, "cf-r2-${try(each.value.name, each.key)}")
  op_vault      = var.PHOEBE_VAULT_ID

  providers = {
    cloudflare.main = cloudflare
    cloudflare.tokens = cloudflare.tokens
  }
}

module "vm_upcloud" {
  source   = "./modules/vm_upcloud"
  for_each = local.instances_upcloud

  name      = try(each.value.name, each.key)
  zone      = try(each.value.zone, "uk-lon1")
  plan      = try(each.value.plan, "1xCPU-1GB")
  network   = try(each.value.network, "UNKNOWN")
  tailscale = try(each.value.tailscale, true)
  volumes   = try(each.value.volumes, [])
}
