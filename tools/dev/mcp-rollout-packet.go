// The native rollout runner calls this only after its tests and coverage finish.
// It records observed artifacts, not installed acceptance or a review decision.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func read(path string) []byte { b, e := os.ReadFile(path); must(e); return b }
func git(args ...string) string {
	b, e := exec.Command("git", args...).Output()
	must(e)
	return strings.TrimSpace(string(b))
}
func digest(b []byte) string { d := sha256.Sum256(b); return hex.EncodeToString(d[:]) }

type block struct{ statements, hits int }

func profile(path string) map[string]block {
	out := map[string]block{}
	for _, line := range strings.Split(string(read(path)), "\n") {
		f := strings.Fields(line)
		if len(f) != 3 {
			continue
		}
		n, e := strconv.Atoi(f[1])
		must(e)
		h, e := strconv.Atoi(f[2])
		must(e)
		if _, exists := out[f[0]]; exists {
			must(fmt.Errorf("duplicate coverage block %s", f[0]))
		}
		out[f[0]] = block{n, h}
	}
	if len(out) == 0 {
		must(fmt.Errorf("empty profile %s", path))
	}
	return out
}

func main() {
	if len(os.Args) != 3 {
		must(fmt.Errorf("usage: mcp-rollout-packet RUN OWNER/REPO#ISSUE@REV:SHA256"))
	}
	run, ref := os.Args[1], os.Args[2]
	m := regexp.MustCompile(`^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*)@([1-9][0-9]*):([0-9a-f]{64})$`).FindStringSubmatch(ref)
	if m == nil {
		must(fmt.Errorf("invalid frozen contract reference"))
	}
	rev, e := strconv.Atoi(m[2])
	must(e)
	head, base := git("rev-parse", "HEAD"), git("rev-parse", "origin/main")
	if git("status", "--porcelain") != "" || strings.TrimSpace(string(read(filepath.Join(run, "source-head")))) != head || len(read(filepath.Join(run, "worktree.patch"))) != 0 {
		must(fmt.Errorf("source changed during run"))
	}
	must(exec.Command("git", "merge-base", "--is-ancestor", base, head).Run())
	binary := read(filepath.Join(run, "binary"))
	binaryHash := digest(binary)
	if binaryHash != strings.TrimSpace(string(read(filepath.Join(run, "binary.sha256")))) {
		must(fmt.Errorf("binary digest mismatch"))
	}
	unit, integration, union := profile(filepath.Join(run, "unit.out")), profile(filepath.Join(run, "integration.out")), profile(filepath.Join(run, "coverage.out"))
	if len(unit) != len(union) || len(integration) != len(union) {
		must(fmt.Errorf("coverage denominators differ"))
	}
	total, covered, unitCovered, integrationCovered, overlap := 0, 0, 0, 0, 0
	for key, u := range union {
		a, okU := unit[key]
		b, okI := integration[key]
		if !okU || !okI || a.statements != u.statements || b.statements != u.statements || (u.hits > 0) != (a.hits > 0 || b.hits > 0) {
			must(fmt.Errorf("inconsistent coverage block %s", key))
		}
		total += u.statements
		if u.hits > 0 {
			covered += u.statements
		}
		if a.hits > 0 {
			unitCovered += u.statements
		}
		if b.hits > 0 {
			integrationCovered += u.statements
		}
		if a.hits > 0 && b.hits > 0 {
			overlap += u.statements
		}
	}
	log := string(read(filepath.Join(run, "tests.log")))
	names := []string{"complete-restart", "pending-discovery", "pending-consumer", "pending-skill", "stale-skill", "stale-schema", "missing-reference", "corrupt-reference", "corrupt-archive", "wrong-source", "dirty-source", "wrong-version", "wrong-app", "lost-ack", "stale-consumer", "stale-server", "snapshot-failure", "early-startup", "invalid-time", "unresolved-later-apply", "overlap-startup"}
	profiles := map[string]map[string]block{}
	for _, name := range names {
		profiles[name] = profile(filepath.Join(run, name, "coverage.out"))
	}
	scenarios := []map[string]any{}
	for _, name := range names {
		if !strings.Contains(log, "--- PASS: TestNativeRolloutRecovery/"+name+" ") {
			must(fmt.Errorf("missing passing test %s", name))
		}
		var execution map[string]any
		must(json.Unmarshal(read(filepath.Join(run, name, "execution.json")), &execution))
		if execution["scenario"] != name {
			must(fmt.Errorf("scenario identity mismatch %s", name))
		}
		unique := 0
		for key, b := range profiles[name] {
			if b.hits == 0 {
				continue
			}
			other := unit[key].hits > 0
			for _, n := range names {
				if n != name && profiles[n][key].hits > 0 {
					other = true
				}
			}
			if !other {
				unique += b.statements
			}
		}
		scenarios = append(scenarios, map[string]any{"scenario_id": name, "result": "PASS", "execution": execution, "unique_statements_excluding_unit_and_other_scenarios": unique, "artifacts": name + "/", "coverage": name + "/coverage.out"})
	}
	artifacts := map[string]string{}
	must(filepath.WalkDir(run, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(run, path)
		if err != nil {
			return err
		}
		if rel == "packet.json" {
			return nil
		}
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		artifacts[rel] = digest(b)
		return nil
	}))
	sort.Strings(names)
	packet := map[string]any{"schema": "mcp-rollout-native-proof/v1", "feature_sha": head, "epic_sha": base, "main_sha": base, "binary_sha": binaryHash, "run_id": filepath.Base(run), "generated_at": time.Now().UTC().Format(time.RFC3339Nano), "feature_contract": map[string]any{"issue": m[1], "revision": rev, "sha256": m[3]}, "environment": map[string]any{"dirty": false, "go": strings.TrimSpace(gitVersion()), "flake_lock_sha256": digest(read("flake.lock"))}, "scenarios": scenarios, "union_coverage": map[string]any{"statements": total, "covered": covered, "unit_covered": unitCovered, "integration_covered": integrationCovered, "overlap": overlap}, "performance": map[string]any{"result": "UNVERIFIED", "reason": "single execution timings only; no controlled baseline or p95"}, "unverified": []string{"Contract reference supplied by caller: reviewer must validate frozen record.", "Per-unit-test coverage attribution and incremental test ledger not measured.", "Installed revised unit and rollback not tested; live observations are separate historical evidence."}, "result": "PASS_WITH_UNVERIFIED", "artifacts_sha256": artifacts, "replay": "MCP_ROLLOUT_CONTRACT=" + ref + " nix develop .#mcp-rollout -c ./tools/dev/mcp-rollout"}
	b, e := json.MarshalIndent(packet, "", "  ")
	must(e)
	b = append(b, '\n')
	must(os.WriteFile(filepath.Join(run, "packet.json"), b, 0600))
	fmt.Printf("packet: %s\npacket_sha256: %s\n", filepath.Join(run, "packet.json"), digest(b))
}

func gitVersion() string { b, e := exec.Command("go", "version").Output(); must(e); return string(b) }
