variable "keycloak_url" {
  description = "Keycloak base URL"
  type        = string
  default     = "http://localhost:8081"
}

variable "pomerium_redirect_uri" {
  description = "Pomerium's OAuth callback (Step 2.3). *.localhost.pomerium.io resolves to 127.0.0.1."
  type        = string
  default     = "https://authenticate.localhost.pomerium.io/oauth2/callback"
}

variable "test_user_password" {
  description = "Temporary password for every lab user (set via TF_VAR_test_user_password)"
  type        = string
  sensitive   = true
}
