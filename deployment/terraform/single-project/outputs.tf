output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "artifact_registry_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "orchestrator_url" {
  value = google_cloud_run_v2_service.orchestrator.uri
}

output "mcp_quickbooks_url" {
  value = google_cloud_run_v2_service.mcp_quickbooks.uri
}

output "mcp_linkedin_url" {
  value = google_cloud_run_v2_service.mcp_linkedin.uri
}

output "cloud_sql_connection_name" {
  value = google_sql_database_instance.main.connection_name
}

output "cloud_sql_instance_name" {
  value = google_sql_database_instance.main.name
}

output "orchestrator_service_account" {
  value = google_service_account.orchestrator.email
}

output "cicd_service_account" {
  value = google_service_account.cicd.email
}

output "database_url_secret_id" {
  value = google_secret_manager_secret.database_url.secret_id
}

output "google_api_key_secret_id" {
  value = google_secret_manager_secret.google_api_key.secret_id
}

output "schema_bootstrap_command" {
  description = "Apply init-scripts to Cloud SQL after first terraform apply"
  value       = <<-EOT
    gcloud sql connect ${google_sql_database_instance.main.name} \
      --project=${var.project_id} --user=${var.db_user} --database=${var.db_name} \
      < init-scripts/01_init_schema.sql
    gcloud sql connect ${google_sql_database_instance.main.name} \
      --project=${var.project_id} --user=${var.db_user} --database=${var.db_name} \
      < init-scripts/02_platform_configs.sql
  EOT
}

output "image_build_commands" {
  description = "Build and push container images to Artifact Registry"
  value       = <<-EOT
    gcloud auth configure-docker ${var.region}-docker.pkg.dev
    docker build -t ${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_id}/orchestrator:latest -f orchestrator/Dockerfile orchestrator/
    docker build -t ${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_id}/mcp-quickbooks:latest -f mcp-servers/quickbooks/Dockerfile mcp-servers/quickbooks/
    docker build -t ${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_id}/mcp-linkedin:latest -f mcp-servers/linkedin/Dockerfile mcp-servers/linkedin/
    docker push ${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_id}/orchestrator:latest
    docker push ${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_id}/mcp-quickbooks:latest
    docker push ${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_id}/mcp-linkedin:latest
  EOT
}
