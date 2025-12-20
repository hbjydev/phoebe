resource "random_password" "self_restic" {
  count   = var.restic ? 1 : 0
  length  = 100
  special = true
}

resource "cloudflare_r2_bucket" "self" {
  account_id = var.account_id
  name = var.name
  location = "WEUR"
  storage_class = var.storage_class
  provider = cloudflare.main
}

resource "cloudflare_api_token" "self" {
  name = "R2-${var.name}-RW"

  policies = [{
    effect = "allow"
    resources = jsonencode({
      "${local.iam_bucket_name}" = "*"
    })
    permission_groups = [for x in local.permission_id_list : { id = x }]
  }]

  provider = cloudflare.tokens
}

resource "onepassword_item" "self" {
  vault = var.op_vault_id
  title = "strg-r2-${var.name}"
  tags = ["bucket/cloudflare", "managed-by/terraform"]
  category = "password"

  section {
    label = "s3"

    field {
      label = "bucketName"
      value = cloudflare_r2_bucket.self.name
    }

    field {
      label = "accessKeyId"
      value = cloudflare_api_token.self.id
    }

    field {
      label = "secretAccessKey"
      type = "CONCEALED"
      value = sha256(cloudflare_api_token.self.value)
    }

    field {
      label = "endpointPublic"
      type = "URL"
      value = "https://${cloudflare_r2_bucket.self.name}.r2.cloudflarestorage.com/${cloudflare_r2_bucket.self.name}"
    }

    field {
      label = "endpointPrivate"
      type = "URL"
      value = "https://${cloudflare_r2_bucket.self.name}.r2.cloudflarestorage.com/${cloudflare_r2_bucket.self.name}"
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

resource "cloudflare_r2_bucket_cors" "self" {
  count = var.name == "sso-haydenmoe-storage" ? 1 : 0

  account_id = var.account_id
  bucket_name = cloudflare_r2_bucket.self.name
  rules = [{
    allowed = {
      methods = ["GET"]
      origins = ["https://sso.hayden.moe"]
      headers = ["Authorization"]
    }
    id = "Allow Authentik access"
    max_age_seconds = 3600
  }]
  provider = cloudflare.main
}
