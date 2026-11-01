# Engineering, release and deployment commands for this configuration.
#
# These are thin entry points only: the mechanics live in the scripts they
# call. Nothing here starts an application or a service, and no business logic
# belongs in this file.

set shell := ["bash", "-euo", "pipefail", "-c"]

# Build and test the T3 deployment artifact; deploys nothing (the CI path).
test *ARGS:
    ./packages/t3code/deploy.sh --no-deploy {{ARGS}}

# Build the T3 system artifact and print the identity read from it.
build *ARGS:
    ./packages/t3code/deploy.sh --build-only {{ARGS}}

# Build, test, activate and deploy the built artifact, then verify it.
deploy *ARGS:
    ./packages/t3code/deploy.sh {{ARGS}}

# Read-only check of the deployed and running identity.
verify *ARGS:
    ./packages/t3code/deploy.sh --verify-only {{ARGS}}

# Quick integration checks: the same commands the manual-on-main CI job runs.
# They use the host's existing podman and AppArmor parser, start no long-lived
# service, and read no production secret.
integration *ARGS:
    scripts/check-integration {{ARGS}}
