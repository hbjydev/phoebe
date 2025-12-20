resource "random_password" "self_restic" {
  count   = var.restic ? 1 : 0
  length  = 100
  special = true
}

resource "upcloud_managed_object_storage_bucket" "self" {
  name = var.name
  service_uuid = var.storage_uuid
}

resource "upcloud_managed_object_storage_user" "self" {
  username = "os-${var.name}-rw"
  service_uuid = var.storage_uuid
}

resource "upcloud_managed_object_storage_user_policy" "this" {
  username     = upcloud_managed_object_storage_user.self.username
  name         = "ECSS3FullAccess"
  service_uuid = var.storage_uuid
}

resource "upcloud_managed_object_storage_user_access_key" "self" {
  username     = upcloud_managed_object_storage_user.self.username
  service_uuid = var.storage_uuid
  status       = "Active"
}

resource "onepassword_item" "self" {
  vault = var.op_vault_id
  title = "strg-ucos-${var.name}"
  tags = ["bucket/upcloud", "managed-by/terraform"]
  category = "password"

  section {
    label = "s3"

    field {
      label = "bucketName"
      value = upcloud_managed_object_storage_bucket.self.name
    }

    field {
      label = "accessKeyId"
      value = upcloud_managed_object_storage_user_access_key.self.access_key_id
    }

    field {
      label = "secretAccessKey"
      type = "CONCEALED"
      value = upcloud_managed_object_storage_user_access_key.self.secret_access_key
    }

    field {
      label = "endpointPublic"
      type = "URL"
      value = "https://${var.storage_endpoint_public}"
    }

    field {
      label = "endpointPrivate"
      type = "URL"
      value = "https://${var.storage_endpoint_private}"
    }
  }

  dynamic "section" {
    for_each = var.restic ? [1] : []
    content {
      label = "restic"

      field {
        label = "resticRepoPassword"
        type = "CONCEALED"
        value = random_password.self_restic[0].result
      }
    }
  }
}
