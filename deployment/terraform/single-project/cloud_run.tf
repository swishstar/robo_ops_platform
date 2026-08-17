resource "google_cloud_run_v2_service" "mcp_quickbooks" {
  name     = local.mcp_qbo_name
  location = var.region
  labels   = local.labels
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.mcp.email
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = var.mcp_quickbooks_image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }
      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds = 30
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "mcp_linkedin" {
  name     = local.mcp_linkedin_name
  location = var.region
  labels   = local.labels
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.mcp.email
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = var.mcp_linkedin_image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }
      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds = 30
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "orchestrator" {
  name     = local.orchestrator_name
  location = var.region
  labels   = local.labels
  ingress  = "INGRESS_TRAFFIC_ALL"
  # Org-policy-friendly public ingress for Slack (allUsers is blocked). App verifies Slack/Chat signatures.
  invoker_iam_disabled = var.orchestrator_invoker_iam_disabled

  template {
    service_account = google_service_account.orchestrator.email
    scaling {
      min_instance_count = var.orchestrator_min_instances
      max_instance_count = var.orchestrator_max_instances
    }

    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = var.orchestrator_image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "MCP_USE_IDENTITY_TOKEN"
        value = "true"
      }
      env {
        name  = "MCP_QUICKBOOKS_ENDPOINT"
        value = google_cloud_run_v2_service.mcp_quickbooks.uri
      }
      env {
        name  = "MCP_LINKEDIN_ENDPOINT"
        value = google_cloud_run_v2_service.mcp_linkedin.uri
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SLACK_SIGNING_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_signing_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SLACK_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_bot_token.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "FIELD_LEARNINGS_SEARCH_ENDPOINT"
        value = "https://discoveryengine.googleapis.com/v1/projects/${var.project_id}/locations/global/collections/default_collection/engines/field-learnings/servingConfigs/default_search"
      }
      env {
        name  = "SOP_SEARCH_ENDPOINT"
        value = "https://discoveryengine.googleapis.com/v1/projects/${var.project_id}/locations/global/collections/default_collection/engines/sop-library-search/servingConfigs/default_search"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "CORS_ORIGINS"
        value = "*"
      }
      env {
        name  = "FINANCE_MANAGER_EMAILS"
        value = var.finance_manager_emails
      }
      env {
        name  = "ADMIN_EMAILS"
        value = var.admin_emails
      }
      env {
        name  = "IAP_AUDIENCE"
        value = local.effective_iap_audience
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT_NUMBER"
        value = data.google_project.current.number
      }
      env {
        # Prefer Chat app Authentication audience = Project number (always verified via
        # GOOGLE_CLOUD_PROJECT_NUMBER). HTTP-endpoint audience should use this URL form:
        name  = "GOOGLE_CHAT_AUDIENCE"
        value = "https://${local.orchestrator_name}-${data.google_project.current.number}.${var.region}.run.app/webhooks/google-chat"
      }
      env {
        name  = "REQUIRE_WEBHOOK_VERIFICATION"
        value = var.environment == "development" ? "false" : "true"
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 10
        period_seconds        = 10
        failure_threshold     = 5
      }
      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds = 30
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_sql_database_instance.main,
    google_cloud_run_v2_service.mcp_quickbooks,
    google_cloud_run_v2_service.mcp_linkedin,
  ]

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "orchestrator_invoke_qbo" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.mcp_quickbooks.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.orchestrator.email}"
}

resource "google_cloud_run_v2_service_iam_member" "orchestrator_invoke_linkedin" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.mcp_linkedin.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.orchestrator.email}"
}

resource "google_cloud_run_v2_service_iam_member" "public_orchestrator" {
  count    = var.allow_public_orchestrator ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.orchestrator.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "ops_web" {
  name     = local.web_app_name
  location = var.region
  labels   = local.labels
  ingress  = "INGRESS_TRAFFIC_ALL"
  iap_enabled = var.enable_iap_ops_web

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = var.web_app_image
      ports {
        container_port = 8080
      }
      env {
        name  = "VITE_API_BASE"
        value = google_cloud_run_v2_service.orchestrator.uri
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 10
      }
    }
  }

  depends_on = [google_project_service.required]

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_ops_web" {
  count    = var.allow_public_web_app ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ops_web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# IAP service agent must be able to invoke the protected Cloud Run service.
resource "google_cloud_run_v2_service_iam_member" "iap_invokes_ops_web" {
  count    = var.enable_iap_ops_web ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ops_web.name
  role     = "roles/run.invoker"
  member   = local.iap_service_agent
}

resource "google_iap_web_cloud_run_service_iam_member" "ops_web_domain" {
  count                  = var.enable_iap_ops_web && var.authorized_domain != "" ? 1 : 0
  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.ops_web.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = "domain:${var.authorized_domain}"
}

resource "google_iap_web_cloud_run_service_iam_member" "ops_web_members" {
  for_each = var.enable_iap_ops_web ? toset(var.authorized_invoker_members) : toset([])

  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.ops_web.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value
}

# Google Chat posts to the orchestrator; grant Chat SA invoker (HTTP-endpoint audience mode).
resource "google_cloud_run_v2_service_iam_member" "google_chat_invokes_orchestrator" {
  count    = var.grant_google_chat_invoker ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.orchestrator.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:chat@system.gserviceaccount.com"
}

resource "google_cloud_run_v2_service_iam_member" "domain_invoke_orchestrator" {
  count    = var.authorized_domain != "" ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.orchestrator.name
  role     = "roles/run.invoker"
  member   = "domain:${var.authorized_domain}"
}

resource "google_cloud_run_v2_service_iam_member" "domain_invoke_web" {
  count    = var.authorized_domain != "" ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ops_web.name
  role     = "roles/run.invoker"
  member   = "domain:${var.authorized_domain}"
}

resource "google_cloud_run_v2_service_iam_member" "member_invoke_orchestrator" {
  for_each = toset(var.authorized_invoker_members)
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.orchestrator.name
  role     = "roles/run.invoker"
  member   = each.value
}

resource "google_cloud_run_v2_service_iam_member" "member_invoke_web" {
  for_each = toset(var.authorized_invoker_members)
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ops_web.name
  role     = "roles/run.invoker"
  member   = each.value
}
