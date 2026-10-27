package main

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

var binary string

func TestMain(m *testing.M) {
	if os.Getenv("MCP_ROLLOUT_FIXTURE") != "" {
		os.Exit(m.Run())
	}
	dir, _ := os.MkdirTemp("", "mcp-rollout-binary-")
	defer os.RemoveAll(dir)
	binary = filepath.Join(dir, "mcp-rollout")
	cmd := exec.Command("go", "build", "-cover", "-covermode=atomic", "-o", binary, ".")
	cmd.Stderr = os.Stderr
	if cmd.Run() != nil {
		os.Exit(1)
	}
	if root := os.Getenv("MCP_ROLLOUT_PROOF"); root != "" {
		b, err := os.ReadFile(binary)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if err := os.WriteFile(filepath.Join(root, "binary"), b, 0700); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if err := os.WriteFile(filepath.Join(root, "binary.sha256"), []byte(fmt.Sprintf("%x\n", sha256.Sum256(b))), 0600); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

// Only the external unchanged publisher and MCP server are doubled. All
// rollout orchestration, file effects, stage decisions and recovery run in
// the real native binary, concurrently in separate disposable directories.
func TestExternalProcess(t *testing.T) {
	dir := os.Getenv("MCP_ROLLOUT_FIXTURE")
	if dir == "" {
		return
	}
	args := os.Args[slices.Index(os.Args, "--")+1:]
	if slices.Contains(args, "--mcp") {
		dec, enc := json.NewDecoder(os.Stdin), json.NewEncoder(os.Stdout)
		for {
			var req struct {
				ID     int    `json:"id"`
				Method string `json:"method"`
				Params struct {
					Name string `json:"name"`
				} `json:"params"`
			}
			if dec.Decode(&req) != nil {
				os.Exit(0)
			}
			if req.ID == 0 {
				continue
			}
			var result any
			switch req.Method {
			case "initialize":
				result = map[string]any{"protocolVersion": "2025-03-26"}
			case "tools/call":
				if req.Params.Name != "integration_status" {
					os.Exit(4)
				}
				result = map[string]any{"structuredContent": map[string]any{"connector_version": "source-fixture", "catalogue_hash": strings.Repeat("a", 64), "implementation": "go"}}
			case "tools/list":
				result = map[string]any{"tools": []map[string]string{{"name": "t3_project_list"}, {"name": "t3_thread_list"}, {"name": "t3_thread_read"}}}
			default:
				os.Exit(5)
			}
			enc.Encode(map[string]any{"jsonrpc": "2.0", "id": req.ID, "result": result})
		}
	}
	var result any
	appID := "asdk_app_fixture"
	if os.Getenv("MCP_ROLLOUT_WRONG_APP") == "1" {
		appID = "asdk_app_wrong"
	}
	switch {
	case slices.Contains(args, "package"):
		path := filepath.Join(dir, "package-record.json")
		save(path, map[string]any{"chatgpt": map[string]string{"content_digest": strings.Repeat("b", 64)}})
		result = map[string]any{"ok": true, "record": path}
	case slices.Contains(args, "publish-chatgpt"):
		if os.Getenv("MCP_ROLLOUT_PAUSE_PUBLISH") == "1" {
			os.WriteFile(filepath.Join(dir, "publisher-waiting"), []byte("waiting"), 0600)
			deadline := time.Now().Add(5 * time.Second)
			for {
				if _, err := os.Stat(filepath.Join(dir, "publisher-release")); err == nil {
					break
				}
				if time.Now().After(deadline) {
					os.Exit(8)
				}
				time.Sleep(5 * time.Millisecond)
			}
		}
		if os.Getenv("MCP_ROLLOUT_DELAY_APPLY") == "1" {
			f, _ := os.OpenFile(filepath.Join(dir, "attempts"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600)
			f.WriteString("upload\n")
			f.Close()
			os.Exit(6)
		}
		action := "unchanged"
		f, e := os.OpenFile(filepath.Join(dir, "uploaded"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if e == nil {
			action = "updated"
			f.WriteString("one upload\n")
			f.Close()
			if os.Getenv("MCP_ROLLOUT_LOST_ACK") == "1" {
				os.Exit(6)
			}
		}
		result = map[string]any{"ok": true, "plugin_id": "Plugin_fixture", "release_id": "release-fixture", "action": action}
	case slices.Contains(args, "verify-chatgpt"):
		if os.Getenv("MCP_ROLLOUT_DELAY_APPLY") == "1" {
			if _, err := os.Stat(filepath.Join(dir, "foreign-published")); err != nil {
				result = map[string]any{"ok": false, "plugin_id": "Plugin_fixture", "release_id": "old-release"}
				break
			}
		}
		result = map[string]any{"ok": true, "plugin_id": "Plugin_fixture", "release_id": "release-fixture", "app_ids": []string{appID}, "skills_match": true, "apps_match": true, "content_match": true}
	default:
		os.Exit(7)
	}
	json.NewEncoder(os.Stdout).Encode(result)
	os.Exit(0)
}

func TestNativeToolSet(t *testing.T) {
	good := []string{"t3_project_list", "t3_thread_list", "t3_thread_read"}
	if !nativeTools(good) || nativeTools(good[:2]) || nativeTools(append(slices.Clone(good), "t3")) {
		t.Fatal("native/retired catalogue boundary")
	}
}

func TestNativeRolloutRecovery(t *testing.T) {
	for _, scenario := range []string{"complete-restart", "pending-discovery", "pending-consumer", "wrong-app", "lost-ack", "stale-consumer", "stale-server", "snapshot-failure", "early-startup", "invalid-time", "unresolved-later-apply", "overlap-startup"} {
		t.Run(scenario, func(t *testing.T) {
			t.Parallel()
			dir := t.TempDir()
			if root := os.Getenv("MCP_ROLLOUT_PROOF"); root != "" {
				dir = filepath.Join(root, scenario)
				os.MkdirAll(dir, 0700)
			}
			self, _ := os.Executable()
			shell, _ := exec.LookPath("sh")
			adapter := filepath.Join(dir, "external-adapter")
			os.WriteFile(adapter, []byte("#!"+shell+"\nexec '"+self+"' -test.run=TestExternalProcess -- \"$@\"\n"), 0700)
			configDir := filepath.Join(dir, "repo/config/skills")
			os.MkdirAll(configDir, 0700)
			save(filepath.Join(configDir, "chatgpt-plugin.json"), map[string]any{"plugin_id": "Plugin_fixture", "identity": "personal", "app_binding": map[string]string{"id": "asdk_app_fixture"}})
			startTime := time.Now().Add(-time.Hour).UTC()
			started := startTime.Format(time.RFC3339Nano)
			startedInput := started
			if scenario == "complete-restart" {
				startedInput = startTime.String()
			} // Actual Podman format.
			run := func(expect int, env []string, args ...string) {
				t.Helper()
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				cmd := exec.CommandContext(ctx, binary, args...)
				cmd.Env = append(os.Environ(), append([]string{"MCP_ROLLOUT_FIXTURE=" + dir}, env...)...)
				if root := os.Getenv("MCP_ROLLOUT_PROOF"); root != "" {
					cov := filepath.Join(dir, "coverage")
					os.MkdirAll(cov, 0700)
					cmd.Env = append(cmd.Env, "GOCOVERDIR="+cov)
				}
				began := time.Now()
				out, err := cmd.CombinedOutput()
				code := 0
				if err != nil {
					if e, ok := err.(*exec.ExitError); ok {
						code = e.ExitCode()
					} else {
						t.Fatal(err)
					}
				}
				if code != expect {
					t.Fatalf("exit %d expected%d: %s", code, expect, out)
				}
				save(filepath.Join(dir, "execution.json"), map[string]any{"scenario": scenario, "last_exit": code, "duration_us": time.Since(began).Microseconds(), "external_boundary": "publisher and connector only"})
			}
			server := filepath.Join(dir, "server.json")
			run(0, nil, "snapshot", "--out", server, "--started-at", startedInput, "--program", adapter, "--", "--mcp")
			want := binding{ServerVersion: "source-fixture", CatalogueHash: strings.Repeat("a", 64), StartedAt: started, PluginID: "Plugin_fixture", AppID: "asdk_app_fixture", ReleaseID: "release-fixture", ContentDigest: strings.Repeat("b", 64)}
			proof := evidence{binding: want, ObservedAt: time.Now().UTC().Format(time.RFC3339Nano), EvidenceRef: "https://github.com/example/repo/issues/1#issuecomment-1", Refreshed: true, NativeTools: []string{"t3_project_list", "t3_thread_list", "t3_thread_read"}, RetiredFacadesAbsent: true, ReadTool: "t3_project_list", ReadOutcome: "returned"}
			if scenario != "pending-discovery" {
				save(filepath.Join(dir, "discovery.json"), proof)
			}
			if scenario != "pending-consumer" {
				save(filepath.Join(dir, "consumer.json"), proof)
			}
			if scenario == "stale-consumer" {
				proof.ReleaseID = "old-release"
				save(filepath.Join(dir, "consumer.json"), proof)
			}
			args := []string{"reconcile", "--skills-cli", adapter, "--repo", filepath.Join(dir, "repo"), "--source-sha", strings.Repeat("c", 40), "--server", server, "--expect-version", "source-fixture", "--state", dir}
			if scenario == "overlap-startup" {
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				env := append(os.Environ(), "MCP_ROLLOUT_FIXTURE="+dir, "MCP_ROLLOUT_PAUSE_PUBLISH=1")
				if root := os.Getenv("MCP_ROLLOUT_PROOF"); root != "" {
					cov := filepath.Join(dir, "coverage")
					os.MkdirAll(cov, 0700)
					env = append(env, "GOCOVERDIR="+cov)
				}
				rc := exec.CommandContext(ctx, binary, args...)
				rc.Env = env
				if err := rc.Start(); err != nil {
					t.Fatal(err)
				}
				defer os.WriteFile(filepath.Join(dir, "publisher-release"), []byte("release"), 0600)
				deadline := time.Now().Add(5 * time.Second)
				for {
					if _, err := os.Stat(filepath.Join(dir, "publisher-waiting")); err == nil {
						break
					}
					if time.Now().After(deadline) {
						t.Fatal("publisher did not pause")
					}
					time.Sleep(5 * time.Millisecond)
				}
				begin := exec.CommandContext(ctx, binary, "begin", "--out", server)
				begin.Env = env
				if err := begin.Start(); err != nil {
					t.Fatal(err)
				}
				beginDone := make(chan error, 1)
				go func() { beginDone <- begin.Wait() }()
				var early bool
				select {
				case <-beginDone:
					early = true
				case <-time.After(150 * time.Millisecond):
				}
				if err := os.WriteFile(filepath.Join(dir, "publisher-release"), []byte("release"), 0600); err != nil {
					t.Fatal(err)
				}
				if err := rc.Wait(); err != nil {
					t.Fatalf("reconcile: %v", err)
				}
				if !early {
					if err := <-beginDone; err != nil {
						t.Fatalf("begin: %v", err)
					}
				}
				var final report
				if readJSON(filepath.Join(dir, "rollout.json"), &final) != nil || final.Complete {
					t.Fatal("overlapping invalidation left stale completion")
				}
				if _, err := os.Stat(server); !os.IsNotExist(err) {
					t.Fatal("server snapshot survived begin")
				}
				if early {
					t.Fatal("begin did not wait for reconciliation")
				}
				save(filepath.Join(dir, "execution.json"), map[string]any{"scenario": scenario, "last_exit": 0, "external_boundary": "publisher and connector only", "begin_waited": true})
				return
			}
			if scenario == "unresolved-later-apply" {
				env := []string{"MCP_ROLLOUT_DELAY_APPLY=1"}
				run(1, env, args...)
				run(1, env, args...)
				attempts, _ := os.ReadFile(filepath.Join(dir, "attempts"))
				if string(attempts) != "upload\n" {
					t.Fatalf("unresolved attempt was resent: %q", attempts)
				}
				// A different writer makes matching content visible; the original
				// request can still apply later, so projection is not its receipt.
				if err := os.WriteFile(filepath.Join(dir, "foreign-published"), []byte("matching projection from another writer"), 0600); err != nil {
					t.Fatal(err)
				}
				run(1, env, args...)
				attempts, _ = os.ReadFile(filepath.Join(dir, "attempts"))
				if string(attempts) != "upload\n" {
					t.Fatal("delayed apply caused duplicate upload")
				}
				if _, err := os.Stat(filepath.Join(dir, "publication-intent.json")); err != nil {
					t.Fatal("matching projection cleared unresolved original request")
				}
				return
			}
			if scenario == "early-startup" || scenario == "invalid-time" {
				run(0, nil, args...)
				var before report
				if readJSON(filepath.Join(dir, "rollout.json"), &before) != nil || !before.Complete {
					t.Fatal("fixture did not complete")
				}
				if scenario == "early-startup" {
					run(0, nil, "begin", "--out", server)
				} else {
					run(2, nil, "snapshot", "--out", server, "--started-at", "invalid", "--program", adapter, "--", "--mcp")
				}
				var after report
				if readJSON(filepath.Join(dir, "rollout.json"), &after) != nil || after.Complete {
					t.Fatal("failed startup retained completion")
				}
				if _, err := os.Stat(server); !os.IsNotExist(err) {
					t.Fatal("failed startup retained server snapshot")
				}
				return
			}
			expect := 0
			var env []string
			switch scenario {
			case "pending-discovery", "pending-consumer", "stale-consumer":
				expect = 3
			case "wrong-app":
				expect = 1
				env = []string{"MCP_ROLLOUT_WRONG_APP=1"}
			case "lost-ack":
				expect = 1
				env = []string{"MCP_ROLLOUT_LOST_ACK=1"}
			case "snapshot-failure":
				run(1, nil, "snapshot", "--out", server, "--started-at", started, "--program", "/nonexistent")
				expect = 1
			case "stale-server":
				var stale snapshot
				readJSON(server, &stale)
				stale.ObservedAt = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
				save(server, stale)
				expect = 1
			}
			run(expect, env, args...)
			var r report
			if readJSON(filepath.Join(dir, "rollout.json"), &r) != nil {
				t.Fatal("missing durable report")
			}
			if r.Complete != (expect == 0) {
				t.Fatal("false completion")
			}
			if scenario == "snapshot-failure" || scenario == "stale-server" {
				if _, e := os.Stat(filepath.Join(dir, "uploaded")); !os.IsNotExist(e) {
					t.Fatal("published after failed readback")
				}
				return
			}
			if scenario == "complete-restart" || scenario == "lost-ack" {
				if scenario == "lost-ack" {
					run(1, nil, args...)
				} else {
					run(0, nil, args...)
				}
				b, _ := os.ReadFile(filepath.Join(dir, "uploaded"))
				if string(b) != "one upload\n" {
					t.Fatal("duplicate upload")
				}
			}
			if scenario == "stale-consumer" {
				if r.Discovery.Status != "verified" || r.Consumer.Status == "verified" {
					t.Fatal("stale acceptance reused")
				}
			}
		})
	}
}
