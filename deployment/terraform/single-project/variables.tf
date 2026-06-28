variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Primary GCP region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment label (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "name_prefix" {
  description = "Resource name prefix"
  type        = string
  default     = "inner-loop"
}

variable "db_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-custom-1-3840"
}

variable "db_disk_size_gb" {
  description = "Cloud SQL disk size in GB"
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Application database name"
  type        = string
  default     = "roboreliance"
}

variable "db_user" {
  description = "Cloud SQL application user"
  type        = string
  default     = "engine_admin"
}

variable "orchestrator_image" {
  description = "Container image URI for the ADK orchestrator"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "mcp_quickbooks_image" {
  description = "Container image URI for the QuickBooks MCP adapter"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "mcp_linkedin_image" {
  description = "Container image URI for the LinkedIn MCP adapter"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "allow_public_orchestrator" {
  description = "Allow unauthenticated ingress to orchestrator webhooks"
  type        = bool
  default     = true
}

variable "orchestrator_min_instances" {
  type    = number
  default = 0
}

variable "orchestrator_max_instances" {
  type    = number
  default = 10
}
