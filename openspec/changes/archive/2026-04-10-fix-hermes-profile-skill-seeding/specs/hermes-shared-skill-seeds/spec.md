## REMOVED Requirements

### Requirement: Hermes SHALL provide repo-managed shared skill seed content
**Reason**: The current Hermes runtime should no longer use a global shared
skill seed root. The old shared `skill-creator` content is being moved into
each managed profile's local `skills/` seed directory instead.
**Migration**: Remove the repo-managed shared seed source tree and shared
runtime seeding logic, then manually clean up stale host artifacts under
`/srv/apps/hermes/home/seeds/shared/skills/` after the updated config is
applied.

### Requirement: Hermes SHALL seed missing shared skill directories without overwriting existing ones
**Reason**: The shared runtime seed path `/home/hermes/seeds/shared/skills/`
is retired in favor of profile-local `skills/` seed directories.
**Migration**: Replace shared-path seeding with copy-once seeding under
`/home/hermes/seeds/profiles/<profile>/skills/<skill>/` for each managed
profile and remove stale shared runtime artifacts manually after cutover.

### Requirement: Hermes-specific skill adaptation SHALL minimize markdown churn
**Reason**: Hermes-specific `skill-creator` content remains relevant, but its
active runtime contract now belongs to the profile-local skill-seeding
capability rather than the retired shared-skill capability.
**Migration**: Carry the existing `skill-creator` content forward into each
managed profile's `skills/` seed tree and keep the adaptation guidance in the
new profile-local skill-seeding capability.
