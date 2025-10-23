resource "vault_mount" "phoebe" {
  path        = "kv-phoebe-secrets"
  type        = "kv"
  options     = { version = "2" }
  description = "Secrets for the Phoebe Kubernetes cluster."
}

resource "vault_kv_secret_backend_v2" "phoebe" {
  mount        = vault_mount.phoebe.path
  max_versions = 5
  cas_required = false
}

resource "vault_jwt_auth_backend" "phoebe" {
  description            = "JWT auth backend for the Phoebe Kubernetes cluster"
  path                   = "jwt-phoebe"
  type                   = "jwt"
  jwt_validation_pubkeys = [ file("./jwtca.pub") ]
}

resource "vault_policy" "eso" {
  name = "pol-phoebe-eso"
  policy = <<EOT
path "${vault_mount.phoebe.path}/*" {
  capabilities = ["read"]
}
path "${vault_mount.phoebe.path}/tls/*" {
  capabilities = ["create", "update", "read"]
}
EOT
}

resource "vault_jwt_auth_backend_role" "eso" {
  backend   = vault_jwt_auth_backend.phoebe.path
  role_name = "rl-phoebe-eso"
  role_type = "jwt"

  bound_audiences = ["vault"]
  bound_subject   = "system:serviceaccount:external-secrets:external-secrets"
  user_claim      = "sub"
  token_policies  = [vault_policy.eso.name]
}
