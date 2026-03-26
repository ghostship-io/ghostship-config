# Specification: Static UID/GID Assignment and Anti-Overlap Policy

## Overview
This track formalizes the requirement for static UID/GID assignments across all systems in the fleet. It strengthens existing guidelines to ensure that UIDs and GIDs are not only static but also unique across the entire project to prevent permission conflicts during data migration or shared storage scenarios.

## Functional Requirements
- **Strengthen Guidelines**: Update `conductor/product-guidelines.md` to explicitly mandate unique, non-overlapping static UIDs and GIDs for all users and service groups.
- **Establish Allocation Ranges**: Define a clear range allocation strategy (e.g., system users 100-499, human users 1000-1999, service users 2000+) in the guidelines.
- **Centralized Registry (Optional)**: Provide a recommended pattern for registering assigned IDs to prevent accidental overlaps during new host/service creation.

## Non-Functional Requirements
- **Consistency**: Ensure all systems (WSL2, bare metal, servers) follow the same ID allocation rules.
- **Maintainability**: Provide a clear reference for developers when adding new users or services.

## Acceptance Criteria
- [ ] `conductor/product-guidelines.md` is updated with the strengthened policy and range allocation strategy.
- [ ] Existing users (e.g., `nixos`) are verified to align with the new ranges.
- [ ] All new tracks (like `storm_eagle_host`) are instructed to follow this updated policy.

## Out of Scope
- Mass migration of existing third-party or system-generated UIDs/GIDs that aren't managed by our Nix configuration.
- Automated enforcement/validation tools for UID/GID uniqueness (manual verification for now).
