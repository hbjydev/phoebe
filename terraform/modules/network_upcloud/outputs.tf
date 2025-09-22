output "network_id" {
  value = upcloud_network.self.id
}

output "network_router_id" {
  value = upcloud_router.self.id
}

output "network_object_storage_id" {
  value = try(upcloud_managed_object_storage.self[0].id, null)
}

output "network_object_storage_private_endpoint" {
  value = try(tolist(upcloud_managed_object_storage.self[0].endpoint)[index(tolist(upcloud_managed_object_storage.self[0].endpoint.*.type), "private")].domain_name, null)
}

output "network_object_storage_public_endpoint" {
  value = try(tolist(upcloud_managed_object_storage.self[0].endpoint)[index(tolist(upcloud_managed_object_storage.self[0].endpoint.*.type), "public")].domain_name, null)
}
