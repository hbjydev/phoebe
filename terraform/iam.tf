locals {
  sa_prefix = "sa-b-phoebe"
  op_prefix = "sa-gcp"

  wif_principal = "principal://iam.googleapis.com/projects/${var.project_id_numeric}/locations/global/workloadIdentityPools/${var.wif_pool_id}/subject"

  crossplane_namespace = "crossplane-system"
  crossplane_sas = [
    {
      name = "stg"
      description = "Crossplane Service Account for Cloud Storage"
      kube = "cp-gcp-storage"
      roles = [
        "roles/storage.admin",
      ]
    },

    {
      name = "iam"
      description = "Crossplane Service Account for IAM"
      kube = "cp-gcp-iam"
      roles = []
    },

    {
      name = "rm"
      description = "Crossplane Service Account for Resource Manager"
      kube = "cp-gcp-cloudplatform"
      roles = [
        "roles/resourcemanager.folderAdmin",
        "roles/resourcemanager.projectCreator",
        "roles/resourcemanager.projectDeleter",
      ]
    }
  ]

  org_iam_bindings = {
    for binding in flatten([
      for sa in local.crossplane_sas : [
        for role in sa.roles : {
          key     = "${sa.name}:${role}"
          sa_name = sa.name
          role    = role
        }
      ]
    ]) : binding.key => binding
  }

  crossplane_k8s_principals = {
    for sa in local.crossplane_sas : sa.name => "${local.wif_principal}/system:serviceaccount:${local.crossplane_namespace}:${sa.kube}"
  }

  crossplane_k8s_config = jsonencode({
    universe_domain    = "googleapis.com"
    type               = "external_account"
    audience           = "iam.googleapis.com/projects/${var.project_id_numeric}/locations/global/workloadIdentityPools/${var.wif_pool_id}/providers/k8s-talos-phoebe"
    subject_token_type = "urn:ietf:params:oauth:token-type:jwt"
    token_url          = "https://sts.europe-west2.rep.googleapis.com/v1/token"
    credential_source  = {
      file = "/var/run/secrets/kubernetes.io/serviceaccount/token"
      format = { type = "text" }
    }
  })
}

resource "google_service_account" "service_account" {
  for_each = { for sa in local.crossplane_sas : sa.name => sa }

  project     = var.project_id
  account_id  = "${local.sa_prefix}-crossplane-${each.key}"
  description = each.value.description
}

resource "google_organization_iam_member" "crossplane" {
  for_each = local.org_iam_bindings

  org_id = var.org_id
  role   = each.value.role
  member = google_service_account.service_account[each.value.sa_name].member
}

resource "google_service_account_iam_member" "crossplane-k8s" {
  for_each = { for sa in local.crossplane_sas : sa.name => sa }

  service_account_id = google_service_account.service_account[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.crossplane_k8s_principals[each.key]
}

resource "onepassword_item" "crossplane_k8s_config" {
  vault    = var.op_vault
  title    = "svc-crossplane-iam-k8s-config"
  password = base64encode(local.crossplane_k8s_config)
}
