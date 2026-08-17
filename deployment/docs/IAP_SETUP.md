# IAP for Ops Web (Cloud Run)

Identity-Aware Proxy protects the Ops Web Cloud Run service with Google login for Workspace users. Uses the **Google-managed OAuth client** (no custom OAuth client required for in-organization identities).

## Terraform

In `terraform.tfvars`:

```hcl
enable_iap_ops_web = true
authorized_domain  = "roboreliance.com"
authorized_invoker_members = [
  "user:steve.wishstar@roboreliance.com",
]
```

Apply grants:

1. `iap_enabled = true` on `inner-loop-ops-web`
2. `roles/run.invoker` to the IAP service agent `service-PROJECT_NUMBER@gcp-sa-iap.iam.gserviceaccount.com`
3. `roles/iap.httpsResourceAccessor` to `domain:` / explicit members
4. Computes `IAP_AUDIENCE` = `/projects/PROJECT_NUMBER/locations/REGION/services/inner-loop-ops-web` for orchestrator JWT validation

```bash
cd deployment/terraform/single-project
terraform apply
terraform output -raw iap_audience
```

## Console (optional)

- [IAP](https://console.cloud.google.com/security/iap?project=robo-reliance-ops) — confirm Ops Web shows IAP enabled
- Custom OAuth client is only needed for principals **outside** the Workspace org ([docs](https://cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run))

## Access notes

- Browser: open the Ops Web URL → Google login → IAP allows Workspace domain users
- SPA → orchestrator API still uses Cloud Run IAM (identity token). For local/dev, keep using:
  ```bash
  gcloud run services proxy inner-loop-orchestrator --region us-central1 --project robo-reliance-ops
  gcloud run services proxy inner-loop-ops-web --region us-central1 --project robo-reliance-ops
  ```
- A same-origin BFF (nginx/proxy with SA identity + forwarded IAP JWT) is a follow-up so the browser does not need a separate orchestrator identity token
