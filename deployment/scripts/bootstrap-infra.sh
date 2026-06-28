#!/usr/bin/env bash
# Provision Inner Loop GCP infrastructure (Terraform single-project layout).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="${ROOT_DIR}/deployment/terraform/single-project"

cd "${TF_DIR}"

if [[ ! -f terraform.tfvars ]]; then
  echo "Create terraform.tfvars from terraform.tfvars.example before running."
  exit 1
fi

terraform init
terraform plan -out=tfplan
terraform apply tfplan

echo ""
echo "Infrastructure applied. Next steps:"
echo "  1. Set Gemini API key: gcloud secrets versions add \$(terraform output -raw google_api_key_secret_id) --data-file=- <<< 'YOUR_KEY'"
echo "  2. Bootstrap schema:   $(terraform output -raw schema_bootstrap_command)"
echo "  3. Build/push images:  see terraform output image_build_commands"
echo "  4. Deploy app images:  gcloud builds submit --config deployment/cloudbuild/build-images.yaml ."
