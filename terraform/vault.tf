resource "vault_mount" "phoebe" {
  path        = "phoebe-secrets"
  type        = "kv"
  options     = { version = "2" }
  description = "Secrets for the Phoebe Kubernetes cluster."
}

resource "vault_kv_secret_backend_v2" "phoebe" {
  mount                = vault_mount.phoebe.path
  max_versions         = 5
  cas_required         = false
}
