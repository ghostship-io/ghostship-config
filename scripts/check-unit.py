#!/usr/bin/env python3
"""Fast local regression tests; host and container evaluation runs nightly."""
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "test_seerr.py",
    "test_shared_network_range.py",
    "test_t3code_podman_*.py",
    "test_ci_scheduling.py",
    "test_github_ci.py",
    "test_fast_check.py",
    "test_apparmor_profile_paths.py",
    "test_apparmor_review.py",
    "test_cloudflare_access.py",
    "test_t3_worker_tunnel.py",
    "test_security_monitoring.py",
    "test_inference_scheduler_stop.py",
    "test_ssh_command_guard.py",
    "test_boot_generation_drift.py",
    "test_activate_host.py",
    "test_agent_pin_guard.py",
    "test_private_source_owner.py",
    "test_owner_identity.py",
    "test_secret_projection_identity.py",
    "test_container_restarts.py",
    "test_container_image_identity.py",
    "test_container_runtime_identity.py",
    "test_mcp_runtime_entrypoint.py",
    "test_t3code_image_identity.py",
    "test_t3code_source_sync.py",
    "test_t3code_restart_guard.py",
    "test_t3code_recovery.py",
    "test_t3code_recovery_units.py",
    "test_t3code_candidate_receipt.py",
    "test_t3code_boot_environment.py",
    "test_test_fixture_lint.py",
    "test_siem_alerts.py",
    "test_siem_grafana.py",
    "test_siem_podman_snapshot.py",
    "test_siem_watchdog.py",
    "test_siem_grafana_plugins.py",
    "test_newsletter_health.py",
    "test_ghostship_notify.py",
    "test_ai_usage_collector.py",
    "test_ai_usage_ranking.py",
    "test_ai_usage_model_selection.py",
    "test_ai_usage_reported_limits.py",
    "test_ai_usage_worker_eligibility.py",
    "test_ai_usage_pools.py",
    "test_ai_usage_short_windows.py",
    "test_ai_usage_outcome_value.py",
    "test_ai_usage_quality_score.py",
    "test_ai_usage_threed.py",
    "test_ai_usage_snapshot.py",
    "test_ai_usage_routing.py",
    "test_ai_usage_ranking_bounds.py",
    "test_ai_usage_frontier_surplus.py",
    "test_ai_usage_privacy.py",
    "test_ai_usage_workload.py",
    "test_ai_usage_facts.py",
    "test_ai_usage_boundaries.py",
    "test_ai_usage_integration.py",
    "test_ai_usage_aa_normalize.py",
    "test_ai_usage_aa_pull.py",
    "test_ai_usage_gate.py",
    "test_ai_usage_providers_page.py",
    "test_ai_usage_free_pool.py",
    "test_ai_usage_pool_recent_jobs.py",
    "test_ai_usage_duplicate_series.py",
    "test_ai_usage_quota.py",
    "test_ai_usage_headroom.py",
    "test_ai_usage_retired_routes.py",
    "test_ai_usage_retired_records.py",
    "test_ai_usage_opencode_reader.py",
    "test_ai_usage_pool_reader.py",
    "test_ai_usage_inference.py",
    "test_ai_usage_inference_wiring.py",
    "test_ai_usage_inferred_publication.py",
    "test_ai_usage_outcomes.py",
    "test_ai_usage_pace_state.py",
    "test_ai_usage_trust_order.py",
    "test_ai_usage_free_selection.py",
    "test_ai_usage_not_offered_reason.py",
    "test_ai_usage_pool_unavailable_reason.py",
    "test_ai_usage_probe_field.py",
)

# Nix module evaluation and a real VictoriaMetrics fixture are integration
# checks. Nightly config-tests retains them alongside full host evaluation.
POST_MERGE_CLASSES = {
    "test_agent_pin_guard.PinGuardTests",  # real Git repositories and source fetches
    "test_agent_pin_guard.PullRequestEventTests",  # Git/CLI event integration
    "test_newsletter_health.DeliveryTests",  # pinned coordinator, HTTP and notifier processes
    "test_ai_usage_routing.RoutingSwitchModuleTests",
    "test_ai_usage_providers_page.WorkedCasesTests",
}

# Real Git command chains and socket/process lifecycles run in config-tests.
POST_MERGE_MODULES = {"test_t3code_podman_api_relay", "test_t3code_podman_ports"}

# Measured wall times: providers-page 14.34s; OpenCode reader 8.81s. These
# fixture-heavy unit modules retain a bounded margin; other modules get 10s.
MODULE_BUDGETS = {"test_ai_usage_providers_page": 20, "test_ai_usage_opencode_reader": 15}


def unit_cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from unit_cases(test)
        elif test.id().rsplit(".", 1)[0] not in POST_MERGE_CLASSES:
            yield test


def run_module(path, loader, runner, *, clock=time.monotonic):
    started = clock()
    result = runner.run(unittest.TestSuite(unit_cases(loader.discover(str(ROOT / "tests"), pattern=path.name))))
    elapsed = clock() - started
    budget = MODULE_BUDGETS.get(path.stem, 10)
    within_budget = elapsed <= budget
    ok = result.wasSuccessful() and within_budget
    print(f"{'PASS' if ok else 'FAIL'} {path.name}: {elapsed:.3f}s / {budget}s", flush=True)
    return ok


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "tests"))
    from check_podman_runtime import RuntimePolicy, findings

    violations = findings(ROOT)
    if violations:
        print("\n".join(violations))
        sys.exit(1)
    loader = unittest.TestLoader()
    runner = unittest.TextTestRunner(verbosity=0)
    ok = runner.run(loader.loadTestsFromTestCase(RuntimePolicy)).wasSuccessful()
    paths = dict.fromkeys(path for pattern in TESTS for path in sorted((ROOT / "tests").glob(pattern)))
    for path in paths:
        if path.stem in POST_MERGE_MODULES:
            continue
        ok = run_module(path, loader, runner) and ok
    sys.exit(not ok)
