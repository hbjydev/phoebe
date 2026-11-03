locals {
  policy_files = fileset(path.module, "policies/*.hcl")
  policies = { for file in local.policy_files : trimsuffix(basename(file), ".hcl") => file }
}

resource "vault_policy" "policies" {
  for_each = local.policies
  name     = each.key
  policy   = file(each.value)
}

module "ca" {
  source = "./modules/ca"

  path                  = "dummy"
  ca_tree_name_prefix   = "Dummy Authority"
  ca_tree_issuer_prefix = "dummy-auth"

  intermediates = {
    "h1" = {
      common_name     = "Dummy Intermediate H1"
      allowed_domains = ["dummy.net"]
    }
    "c1" = {
      common_name     = "Dummy Cluster C1"
      allowed_domains = ["cluster.local", "dummy.local"]
    }
  }
}
