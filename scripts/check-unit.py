#!/usr/bin/env python3
"""Fast local regression tests; host and container evaluation runs on main."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "test_seerr.py",
    "test_shared_network_range.py",
    "test_t3code_podman_*.py",
    "test_ci_scheduling.py",
    "test_apparmor_profile_paths.py",
    "test_apparmor_review.py",
    "test_cloudflare_access.py",
    "test_t3_worker_tunnel.py",
    "test_security_monitoring.py",
    "test_inference_scheduler_stop.py",
    "test_opencode_model_catalog.py",
    "test_configuration_drift.py",
    "test_ssh_command_guard.py",
    "test_boot_generation_drift.py",
    "test_activate_host.py",
    "test_agent_pin_guard.py",
    "test_private_source_owner.py",
    "test_owner_identity.py",
    "test_t3code_restart_guard.py",
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
    "test_ai_usage_outcome_value.py",
    "test_ai_usage_quality_score.py",
    "test_ai_usage_threed.py",
    "test_ai_usage_snapshot.py",
    "test_ai_usage_routing.py",
    "test_ai_usage_ranking_bounds.py",
    "test_ai_usage_frontier_surplus.py",
    "test_ai_usage_t3client.py",
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
# checks. scripts/check keeps them on main alongside the full host evaluation.
POST_MERGE_CLASSES = {
    "test_ai_usage_routing.RoutingSwitchModuleTests",
    "test_ai_usage_providers_page.WorkedCasesTests",
}


def unit_cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from unit_cases(test)
        elif test.id().rsplit(".", 1)[0] not in POST_MERGE_CLASSES:
            yield test


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "tests"))
    from check_podman_runtime import RuntimePolicy, findings

    violations = findings(ROOT)
    if violations:
        print("\n".join(violations))
        sys.exit(1)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(RuntimePolicy))
    for pattern in TESTS:
        suite.addTests(unit_cases(loader.discover(str(ROOT / "tests"), pattern=pattern)))
    sys.exit(not unittest.TextTestRunner().run(suite).wasSuccessful())
