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
        label = "password"
        type = "CONCEALED"
        value = random_password.self_restic[0].result
      }
    }
  }
}

resource "vault_kv_secret_v2" "self_token" {
  mount     = var.vault_mount
  name      = "ucos/${var.name}"
  data_json = jsonencode({
    endpoint          = "https://${var.storage_endpoint_public}"
    endpoint_private  = "https://${var.storage_endpoint_private}"
    bucket_name       = "${upcloud_managed_object_storage_bucket.self.name}"
    access_key_id     = upcloud_managed_object_storage_user_access_key.self.access_key_id
    secret_access_key = upcloud_managed_object_storage_user_access_key.self.secret_access_key
    restic_password   = var.restic ? random_password.self_restic[0].result : ""
  })

  custom_metadata {
    data = { managed-by = "terraform" }
  }
}
