# Lumen AI identity: one realm, the groups access decisions depend on,
# lab users, and the OIDC client Pomerium signs people in with.

resource "keycloak_realm" "lumen" {
  realm                    = "lumen"
  display_name             = "Lumen AI"
  enabled                  = true
  login_with_email_allowed = true
  duplicate_emails_allowed = false
  ssl_required             = "none" # lab only: Keycloak runs plain HTTP. Production: TLS in front + "all"
  access_token_lifespan    = "15m"
  sso_session_idle_timeout = "8h"

  password_policy = "length(12) and notUsername"
}

# --- Groups ---------------------------------------------------------------

locals {
  groups = {
    "engineering" = "Engineering staff"
    "sales"       = "Sales staff"
    "it-admins"   = "IT and Security administrators (admin consoles)"
    "break-glass" = "Emergency access; every use raises an alert"
    "traveling"   = "Temporarily abroad; access capped at level 1"
    # Birthright groups used by jml/roles.yaml (Project 3)
    "all-staff"            = "Every employee (not contractors)"
    "research"             = "Research staff"
    "it"                   = "IT staff (no admin rights; those are requested)"
    "finance"              = "Finance staff"
    "people"               = "People (HR) staff"
    "legal"                = "Legal staff"
    "managers"             = "People managers"
    "engineering-readonly" = "Read-only engineering tools (e.g. sales engineers)"
    "contractors"          = "Contractors (end date required)"
    "interns"              = "Interns"
  }

  users = {
    alice = { first = "Alice", last = "Engineer", groups = ["engineering"] }
    bob   = { first = "Bob", last = "Seller", groups = ["sales"] }
    ivan  = { first = "Ivan", last = "Admin", groups = ["it-admins"] }
    tara  = { first = "Tara", last = "Traveler", groups = ["sales"] } # "traveling" comes from travel/trips.yaml
    erin  = { first = "Erin", last = "Emergency", groups = ["break-glass"] }
  }
}

resource "keycloak_group" "g" {
  for_each = local.groups
  realm_id = keycloak_realm.lumen.id
  name     = each.key
  attributes = {
    description = each.value
  }
}

# --- Users ----------------------------------------------------------------

resource "keycloak_user" "u" {
  for_each       = local.users
  realm_id       = keycloak_realm.lumen.id
  username       = each.key
  email          = "${each.key}@lumenai.test"
  email_verified = true
  first_name     = each.value.first
  last_name      = each.value.last
  enabled        = true

  initial_password {
    value     = var.test_user_password
    temporary = false
  }
}

# --- Travel mode (Step 2.6) -----------------------------------------------------
# Trips live in travel/trips.yaml (reviewed by PR). A user is "traveling" only while
# the plan's date is inside their trip, so the group drops off by itself after the end date.
locals {
  trips = yamldecode(file("${path.module}/../travel/trips.yaml")).trips
  traveling_now = toset([
    for t in local.trips : t.user
    if timecmp(plantimestamp(), "${t.start}T00:00:00Z") >= 0 && timecmp(plantimestamp(), "${t.end}T23:59:59Z") <= 0
  ])
}

resource "keycloak_user_groups" "u" {
  for_each = local.users
  realm_id = keycloak_realm.lumen.id
  user_id  = keycloak_user.u[each.key].id
  group_ids = concat(
    [for g in each.value.groups : keycloak_group.g[g].id],
    contains(local.traveling_now, each.key) ? [keycloak_group.g["traveling"].id] : [],
  )
}

output "traveling_now" {
  description = "Users in travel mode as of this plan"
  value       = local.traveling_now
}

# --- OIDC client for Pomerium ----------------------------------------------

resource "keycloak_openid_client" "pomerium" {
  realm_id    = keycloak_realm.lumen.id
  client_id   = "pomerium"
  name        = "Pomerium identity-aware proxy"
  enabled     = true
  access_type = "CONFIDENTIAL"

  standard_flow_enabled        = true
  direct_access_grants_enabled = false
  implicit_flow_enabled        = false
  service_accounts_enabled     = false

  # PKCE is not required: Pomerium is a confidential client (it authenticates with a client secret)
  # and does not send a PKCE challenge, so requiring S256 makes Keycloak reject every login.
  valid_redirect_uris = [var.pomerium_redirect_uri]
}

# Put the user's groups in the token as a "groups" claim, so the posture gate and OPA can read them.
resource "keycloak_openid_group_membership_protocol_mapper" "groups" {
  realm_id   = keycloak_realm.lumen.id
  client_id  = keycloak_openid_client.pomerium.id
  name       = "groups"
  claim_name = "groups"
  full_path  = false
}
