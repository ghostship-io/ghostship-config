"""Agent desktop update pipeline: trust, candidate policy, drain, cookies and phases."""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import unittest.mock
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "agent_desktop_update", Path(__file__).resolve().parents[1] / "modules/self-hosted/agent-desktop-update.py")
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)

DAY = 86400.0
NOW = 1_800_000_000.0
CURRENT = {
    "base": {"image": "lscr.io/linuxserver/webtop:ubuntu-lxqt", "digest": "sha256:" + "a" * 64},
    "chrome": {"version": "155.0.8059.84-1", "sha256": {"arm64": "1" * 64, "amd64": "2" * 64}},
    "bladebro": {"version": "4.6.4", "sha256": {"arm64": "3" * 64, "amd64": "4" * 64}},
}


def chrome(version, age):
    return {"version": version, "sha256": {"arm64": "5" * 64, "amd64": "6" * 64}, "released": NOW - age}


def blade(version, age):
    return {"version": version, "sha256": {"arm64": "7" * 64, "amd64": "8" * 64}, "released": NOW - age}


def base(digest, created_age, current_age=10 * DAY):
    return {"digest": digest, "created": NOW - created_age, "current_created": NOW - current_age,
            "released": NOW - created_age}


class ChromeTrustTests(unittest.TestCase):
    def test_chrome_version_comes_only_from_a_packages_file_the_signed_release_lists(self):
        """Catches a tampered or unlisted Packages file, a non-Google signer, or a beta build taken as stable."""
        packages = (
            "Package: google-chrome-beta\nVersion: 157.0.8103.6-1\nSHA256: " + "b" * 64 + "\n\n"
            "Package: google-chrome-stable\nVersion: 155.0.8059.84-1\n"
            "Filename: pool/main/g/google-chrome-stable/google-chrome-stable_155.0.8059.84-1_arm64.deb\n"
            "SHA256: " + "c" * 64 + "\n\n"
            "Package: google-chrome-unstable\nVersion: 158.0.8106.0-1\n").encode()
        release = ("Origin: Google LLC\nMD5Sum:\n 00 1 main/binary-arm64/Packages\nSHA256:\n"
                   f" {hashlib.sha256(packages).hexdigest()} {len(packages)} main/binary-arm64/Packages\n"
                   f" {'d' * 64} 10 main/binary-amd64/Packages\n")
        entries = update.release_sha256(release)
        update.verify_indexed(entries, "main/binary-arm64/Packages", packages)
        for path, data in (("main/binary-arm64/Packages", packages + b"\n"),
                           ("main/binary-arm64/Packages", packages.replace(b"155.0.8059.84", b"999.0.0.0")),
                           ("main/binary-armhf/Packages", packages)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                update.verify_indexed(entries, path, data)
        stanza = update.packages_stanza(packages.decode(), "google-chrome-stable")
        self.assertEqual((stanza["Version"], stanza["SHA256"]), ("155.0.8059.84-1", "c" * 64))

        good = ("[GNUPG:] NEWSIG\n[GNUPG:] GOODSIG FD533C07C264648F Google\n"
                "[GNUPG:] VALIDSIG 0E225917414670F4442C250DFD533C07C264648F 2026-10-20 1792489508 0 4 0 1 8 01 "
                "EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796\n")
        self.assertEqual(update.validsig_primary(good), update.GOOGLE_PRIMARY_FPR)
        self.assertIsNone(update.validsig_primary("[GNUPG:] BADSIG FD533C07C264648F Google\n"))
        self.assertNotEqual(update.validsig_primary(good.replace("EB4C1BFD", "0000AAAA")), update.GOOGLE_PRIMARY_FPR)


class CandidatePolicyTests(unittest.TestCase):
    def test_candidates_are_newer_soaked_unrejected_and_one_bad_component_cannot_block_others(self):
        """Catches downgrades, unsoaked or rejected releases reaching a canary, and a rejected bundle stalling forever."""
        new_base = "sha256:" + "f" * 64
        rejected_bundle = {update.candidate_key({"bladebro": blade("4.6.5", 2 * DAY),
                                                 "chrome": chrome("155.0.8059.100-1", 2 * DAY)}): {}}
        cases = [
            ("numeric, not string, version order", {"chrome": chrome("155.0.8059.100-1", 2 * DAY)}, {}, ["chrome"]),
            ("chrome downgrade", {"chrome": chrome("155.0.8059.39-1", 2 * DAY)}, {}, []),
            ("same chrome", {"chrome": chrome("155.0.8059.84-1", 2 * DAY)}, {}, []),
            ("chrome inside soak", {"chrome": chrome("156.0.1.1-1", DAY / 2)}, {}, []),
            ("bladebro downgrade", {"bladebro": blade("4.2.2", 2 * DAY)}, {}, []),
            ("bladebro newer", {"bladebro": blade("4.10.0", 2 * DAY)}, {}, ["bladebro"]),
            ("rejected alone", {"bladebro": blade("4.6.5", 2 * DAY)},
             {update.candidate_key({"bladebro": blade("4.6.5", 0)}): {}}, []),
            ("older webtop build", {"base": base(new_base, 2 * DAY, current_age=DAY)}, {}, []),
            ("newer webtop build", {"base": base(new_base, 2 * DAY)}, {}, ["base"]),
            ("all together", {"chrome": chrome("155.0.8059.100-1", 2 * DAY), "bladebro": blade("4.6.5", 2 * DAY),
                              "base": base(new_base, 2 * DAY)}, {}, ["base", "bladebro", "chrome"]),
            ("rejected bundle splits", {"chrome": chrome("155.0.8059.100-1", 2 * DAY),
                                        "bladebro": blade("4.6.5", 2 * DAY)}, rejected_bundle, ["bladebro"]),
        ]
        for name, found, rejected, expected in cases:
            with self.subTest(name):
                plan = update.plan_candidate(CURRENT, {"chrome": None, "bladebro": None, "base": None, **found},
                                             NOW, DAY, rejected)
                self.assertEqual(sorted(plan), expected)

        def release(tag, age, **extra):
            return {"tag_name": tag, "published_at": update.dt.datetime.fromtimestamp(
                NOW - age, update.dt.timezone.utc).isoformat().replace("+00:00", "Z"), "assets": [], **extra}
        releases = [release("v4.7.0", DAY / 2), release("v4.6.9", 2 * DAY, prerelease=True),
                    release("v4.6.8", 2 * DAY, draft=True), release("v4.6.6", 3 * DAY), release("v4.6.5", 4 * DAY)]
        self.assertEqual(update.pick_bladebro(releases, "4.6.4", NOW, DAY, {})["tag_name"], "v4.6.6")
        self.assertEqual(update.pick_bladebro(releases, "4.6.4", NOW, DAY,
                                              {"bladebro=4.6.6": {}})["tag_name"], "v4.6.5")
        self.assertIsNone(update.pick_bladebro(releases, "4.6.6", NOW, DAY, {}))


class DrainTests(unittest.TestCase):
    def test_restart_waits_only_for_live_agent_leases_and_human_pauses(self):
        """Catches a restart under an active agent run or a person's takeover, or waiting on expired leases forever."""
        anchor = "about:blank#ghostship-window-{}.{}".format
        cases = [
            ("no runs", set(), set(), ["https://example.test/"], []),
            ("live lease", {"r1"}, set(), [anchor("r1", int(NOW + 60))], ["active agent run r1"]),
            ("expired lease", {"r1"}, set(), [anchor("r1", int(NOW - 1))], []),
            ("anchor without registry", set(), set(), [anchor("r1", int(NOW + 60))], []),
            ("person paused a run", set(), {"r2"}, [], ["paused run r2"]),
        ]
        for name, registry, pauses, urls, expected in cases:
            with self.subTest(name):
                self.assertEqual(update.drain_blockers(registry, pauses, urls, NOW), expected)


class CookieTests(unittest.TestCase):
    def test_lost_sign_ins_are_detected_but_session_and_expiring_cookies_are_not_counted(self):
        """Catches a profile that lost cookies passing, or a healthy restart failing on session cookies."""
        cookies = [
            {"domain": ".google.com", "session": False, "expires": NOW + 30 * DAY},
            {"domain": "google.com", "session": False, "expires": NOW + 30 * DAY},
            {"domain": ".example.test", "session": True, "expires": -1},
            {"domain": ".example.test", "session": False, "expires": NOW + 60},
        ]
        before = update.cookie_counts(cookies, NOW + 3600)
        self.assertEqual(before, {"google.com": 2})
        after = update.cookie_counts(cookies[:1] + cookies[2:], NOW + 3600)
        self.assertEqual(update.cookie_shortfall(before, after, exact=False), {"google.com": [2, 1]})
        self.assertEqual(update.cookie_shortfall(before, {"google.com": 3}, exact=False), {})
        self.assertEqual(update.cookie_shortfall(before, {"google.com": 3}, exact=True), {"google.com": [2, 3]})


class FingerprintTests(unittest.TestCase):
    def test_baseline_tracks_only_the_chrome_version_change(self):
        """Catches every Chrome update failing parity, or a version rebase hiding other signal changes."""
        baseline = {"userAgent": "Mozilla/5.0 (X11; Linux aarch64) Chrome/155.0.0.0 Safari/537.36",
                    "uaData": {"fullVersionList": [{"brand": "Google Chrome", "version": "155.0.8059.39"}]},
                    "fonts": ["Arial"]}
        rebased, allow = update.rebase_fingerprint(baseline, "155.0.8059.39-1", "155.0.8059.84-1")
        self.assertEqual(allow, [])
        self.assertEqual(rebased["uaData"]["fullVersionList"][0]["version"], "155.0.8059.84")
        self.assertEqual(rebased["fonts"], ["Arial"])
        rebased, allow = update.rebase_fingerprint(baseline, "155.0.8059.39-1", "156.0.8100.1-1")
        self.assertEqual(allow, ["uaData"])
        self.assertIn("Chrome/156.0.0.0", rebased["userAgent"])


class PhaseTests(unittest.TestCase):
    def test_only_canary_tested_candidates_reach_main_and_interrupted_promotions_resume(self):
        """Catches pushing without a passing canary, and a restart abandoning an unverified deploy."""
        phase = "idle"
        for event in ("candidate", "pass", "pushed", "deployed", "fail", "restored"):
            phase = update.transition(phase, event)
        self.assertEqual(phase, "idle")
        for phase, event in (("idle", "pushed"), ("canary", "pushed"), ("idle", "pass"), ("rollback-failed", "candidate")):
            with self.subTest(phase=phase, event=event), self.assertRaises(ValueError):
                update.transition(phase, event)
        self.assertEqual([update.resume_action(p) for p in ("canary", "deploying", "verifying", "rolling-back",
                                                             "rollback-failed")],
                         ["start", "deploy", "deploy", "rollback", "halt"])


    def test_resumed_deploy_keeps_the_pre_update_snapshot_and_cookie_baseline(self):
        """Catches a resumed promotion replacing the rollback snapshot with already-migrated profiles."""
        candidate = {"snapshot": "/srv/.ghostship-snapshots/agent-desktop-first", "pre_cookies": {"a.com": 3},
                     "summary": "chrome", "tag": "t", "updates": ["chrome"]}
        state = {"phase": "deploying", "candidate": candidate, "rejected": {}, "history": []}
        with patch.object(update, "take_snapshot", side_effect=AssertionError("snapshot retaken")), \
                patch.object(update, "production_cookie_counts", side_effect=AssertionError("baseline retaken")), \
                patch.object(update, "drain"), patch.object(update, "deploy"), \
                patch.object(update, "verify_production"), patch.object(update, "write_baseline"), \
                patch.object(update, "save_state"), patch.object(update, "record"):
            update.deploy_and_verify(state, unittest.mock.Mock(), None)
        self.assertEqual(candidate["snapshot"], "/srv/.ghostship-snapshots/agent-desktop-first")
        self.assertEqual(candidate["pre_cookies"], {"a.com": 3})
        self.assertEqual(state["phase"], "idle")


class CommitTests(unittest.TestCase):
    def test_commit_rebases_onto_moved_main_but_never_ships_an_untested_build_context(self):
        """Catches pushing a tag the canary never tested after main changed the desktop build context."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin, seed = root / "origin.git", root / "seed"

            def git(cwd, *args):
                subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                               check=True, capture_output=True)
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
            subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
            (seed / "containers/agent-desktop").mkdir(parents=True)
            (seed / update.VERSIONS).write_text(json.dumps(CURRENT))
            (seed / "VERSION").write_text("1.2.3\n")
            (seed / "CHANGELOG.md").write_text("# Changelog\n\n## [1.2.3] - 2026-01-01\n\n- old\n")
            git(seed, "add", "-A")
            git(seed, "commit", "-qm", "seed")
            git(seed, "push", "-q", "origin", "HEAD:main")

            def fake_tag(repo):
                files = sorted((repo.path / update.CONTEXT).rglob("*"))
                digest = hashlib.sha256(b"".join(p.read_bytes() for p in files if p.is_file())).hexdigest()
                return "localhost/ghostship-agent-desktop:" + digest[:12], "/nix/store/x"

            with patch.object(update, "image_tag", fake_tag):
                repo = update.Repo(root / "work", str(origin), "main", None)
                base_commit = repo.sync()
                candidate = update.apply_updates(CURRENT, {"bladebro": blade("4.6.5", 2 * DAY)})
                update.write_versions(repo, candidate)
                tested_tag, _ = fake_tag(repo)

                (seed / "README").write_text("unrelated\n")
                git(seed, "add", "-A")
                git(seed, "commit", "-qm", "unrelated change")
                git(seed, "push", "-q", "origin", "HEAD:main")
                update.commit_change(repo, base_commit, candidate, tested_tag, "chore(agent-desktop): update",
                                     "line", push=True)
                shipped = subprocess.run(["git", "-C", str(origin), "show", f"main:{update.VERSIONS}"],
                                         capture_output=True, text=True, check=True).stdout
                self.assertEqual(json.loads(shipped)["bladebro"]["version"], "4.6.5")
                version = subprocess.run(["git", "-C", str(origin), "show", "main:VERSION"],
                                         capture_output=True, text=True, check=True).stdout
                self.assertEqual(version.strip(), "1.2.4")

                git(seed, "pull", "-q", "origin", "main")
                (seed / "containers/agent-desktop/Containerfile").write_text("FROM changed\n")
                git(seed, "add", "-A")
                git(seed, "commit", "-qm", "context change")
                git(seed, "push", "-q", "origin", "HEAD:main")
                before = subprocess.run(["git", "-C", str(origin), "rev-parse", "main"],
                                        capture_output=True, text=True, check=True).stdout
                newer = update.apply_updates(candidate, {"bladebro": blade("4.6.6", 2 * DAY)})
                with self.assertRaises(update.Abort):
                    update.commit_change(repo, base_commit, newer, tested_tag, "m", "line", push=True)
                after = subprocess.run(["git", "-C", str(origin), "rev-parse", "main"],
                                       capture_output=True, text=True, check=True).stdout
                self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
