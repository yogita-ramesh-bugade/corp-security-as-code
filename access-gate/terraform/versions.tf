terraform {
  required_version = ">= 1.6"
  required_providers {
    keycloak = {
      source  = "keycloak/keycloak"
      version = "~> 5.0"
    }
  }
}

# Admin credentials come from environment variables (KEYCLOAK_USER, KEYCLOAK_PASSWORD),
# never from files in this repo.
provider "keycloak" {
  client_id = "admin-cli"
  url       = var.keycloak_url
  realm     = "master"
}
