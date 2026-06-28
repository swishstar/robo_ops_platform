resource "google_secret_manager_secret" "database_url" {
  secret_id = "${var.name_prefix}-database-url-${var.environment}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  secret_data = format(
    "postgresql://%s:%s@/%s?host=/cloudsql/%s",
    var.db_user,
    urlencode(random_password.db_password.result),
    var.db_name,
    google_sql_database_instance.main.connection_name,
  )
}

resource "google_secret_manager_secret" "google_api_key" {
  secret_id = "${var.name_prefix}-google-api-key-${var.environment}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "google_api_key" {
  secret      = google_secret_manager_secret.google_api_key.id
  secret_data = "REPLACE_ME_WITH_GEMINI_API_KEY"
  lifecycle {
    ignore_changes = [secret_data]
  }
}
