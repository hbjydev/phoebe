locals {
  roles = {
    https = {
      key_usage      = ["DigitalSignature"]
      extended_usage = ["ServerAuth"]
    }
    mtls-client = {
      key_usage      = ["DigitalSignature"]
      extended_usage = ["ClientAuth"]
      allow_any_name = true
    }
    mtls-server = {
      key_usage      = ["DigitalSignature"]
      extended_usage = ["ServerAuth"]
    }
  }

  roles_per_intermediate = merge([
    for intermediate_key, intermediate in var.intermediates : {
      for role_name, role in local.roles :
      "${intermediate_key}/${role_name}" => merge(role, {
        intermediate_key = intermediate_key
        role_name        = role_name
        allowed_domains  = intermediate.allowed_domains
      })
    }
  ]...)
}

resource "vault_pki_secret_backend_role" "role" {
  # Configure publication URLs before making leaf issuance available.
  depends_on       = [vault_pki_secret_backend_config_urls.self]
  for_each         = local.roles_per_intermediate
  backend          = vault_mount.self[each.value.intermediate_key].path
  issuer_ref       = vault_pki_secret_backend_issuer.intermediate[each.value.intermediate_key].issuer_ref

  name             = "rl-${each.value.role_name}"
  ttl              = try(each.value.ttl, "2592000")
  max_ttl          = "7776000"
  allow_ip_sans    = try(each.value.allow_ip_sans, false)
  allow_any_name   = try(each.value.allow_any_name, false)
  key_type         = "ed25519"
  key_bits         = 0
  key_usage        = try(each.value.key_usage, [])
  ext_key_usage    = try(each.value.extended_usage, [])
  server_flag      = try(contains(each.value.extended_usage, "ServerAuth") ? true : false, false)
  client_flag      = try(contains(each.value.extended_usage, "ClientAuth") ? true : false, false)
  allowed_domains  = try(each.value.allowed_domains, [])
  allow_localhost  = false
  allow_subdomains = try(each.value.allow_subdomains, true)
}

resource "vault_policy" "role" {
  for_each = local.roles_per_intermediate
  name     = "acl-ca-${var.path}-issue-${each.key}"
  policy   = <<-EOT
    # Managed by Terraform.

    path "${vault_mount.self[each.value.intermediate_key].path}/sign/${vault_pki_secret_backend_role.role[each.key].name}" {
      capabilities      = ["create", "update"]
      denied_parameters = {"not_after" = []}
    }

    path "${vault_mount.self[each.value.intermediate_key].path}/issue/${vault_pki_secret_backend_role.role[each.key].name}" {
      capabilities      = ["create", "update"]
      denied_parameters = {"not_after" = []}
    }
  EOT
}
