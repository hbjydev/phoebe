locals {
  prefix = "sa-b-phoebe"

  crossplane_sas = [
    {
      name = "stg"
      description = "Crossplane Service Account for Cloud Storage"
      roles = [
        "roles/storage.admin",
      ]
    },

    {
      name = "iam"
      description = "Crossplane Service Account for IAM"
      roles = []
    },

    {
      name = "rm"
      description = "Crossplane Service Account for Resource Manager"
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
}

resource "google_service_account" "service_account" {
  for_each = { for sa in local.crossplane_sas : sa.name => sa }

  project     = var.project_id
  account_id  = "${local.prefix}-crossplane-${each.key}"
  description = each.value.description
}

resource "google_organization_iam_member" "crossplane" {
  for_each = local.org_iam_bindings

  org_id = var.org_id
  role   = each.value.role
  member = google_service_account.service_account[each.value.sa_name].member
}

import {
  to = google_service_account.service_account["rm"]
  identity = {
    project = "prj-b-seed-ahjd"
    email = "sa-b-phoebe-crossplane-rm@prj-b-seed-ahjd.iam.gserviceaccount.com"
  }
}

import {
  to = google_service_account.service_account["stg"]
  identity = {
    project = "prj-b-seed-ahjd"
    email = "sa-b-phoebe-crossplane-storage@prj-b-seed-ahjd.iam.gserviceaccount.com"
  }
}

import {
  to = google_service_account.service_account["iam"]
  identity = {
    project = "prj-b-seed-ahjd"
    email = "sa-b-phoebe-crossplane-iam@prj-b-seed-ahjd.iam.gserviceaccount.com"
  }
}
