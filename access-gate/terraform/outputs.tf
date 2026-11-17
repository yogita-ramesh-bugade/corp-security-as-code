output "issuer_url" {
  description = "OIDC issuer for Pomerium (Step 2.3)"
  value       = "${var.keycloak_url}/realms/${keycloak_realm.lumen.realm}"
}

output "pomerium_client_id" {
  value = keycloak_openid_client.pomerium.client_id
}

output "pomerium_client_secret" {
  value     = keycloak_openid_client.pomerium.client_secret
  sensitive = true
}
