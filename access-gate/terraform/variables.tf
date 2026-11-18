variable "keycloak_url" {
  description = "Keycloak base URL. keycloak.lumen.test is in /etc/hosts on the Mac (127.0.0.1) and on each VM (the Mac's IP)."
  type        = string
  default     = "http://keycloak.lumen.test:8081"
}

variable "pomerium_redirect_uri" {
  description = "Pomerium's OAuth callback (Step 2.3)"
  type        = string
  default     = "https://auth.lumen.test:4443/oauth2/callback"
}

variable "test_user_password" {
  description = "Temporary password for every lab user (set via TF_VAR_test_user_password)"
  type        = string
  sensitive   = true
}