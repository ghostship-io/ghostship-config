# Engineering, release and deployment commands for this configuration.
#
# These are thin entry points only: the mechanics live in the scripts they
# call. Nothing here starts an application or a service, and no business logic
# belongs in this file.

set shell := ["bash", "-euo", "pipefail", "-c"]

# Build and test the T3 deployment artifact; deploys nothing (the CI path).
test *ARGS:
    ./packages/t3code/deploy.sh --no-deploy {{ARGS}}

# Build the host system artifact (the toplevel a switch needs) and print the
# identity read from it. `test` builds only the T3 deployment closure.
build *ARGS:
    ./packages/t3code/deploy.sh --build-only {{ARGS}}

# Build, test, activate and deploy the built artifact, then verify it.
deploy *ARGS:
    ./packages/t3code/deploy.sh {{ARGS}}

# Read-only check of the deployed and running identity.
verify *ARGS:
    ./packages/t3code/deploy.sh --verify-only {{ARGS}}

# Roll the host back to its previous system generation and return T3 to the
# deployment recorded in that generation. The script switches the system, then
# reconciles the T3 deployment to the now-current system, so the system and the
# running image cannot disagree. Works with T3 down.
rollback *ARGS:
    ./packages/t3code/deploy.sh --rollback {{ARGS}}

# The behavioural candidate suite, run explicitly and never from deploy or
# verify: it starts a candidate container and needs a live provider route.
acceptance *ARGS:
    python3 ./packages/t3code/candidate-acceptance.py {{ARGS}}

# Quick integration checks: the same commands the manual-on-main CI job runs.
# They use the host's existing podman and AppArmor parser, start no long-lived
# service, and read no production secret.
integration *ARGS:
    scripts/check-integration {{ARGS}}
