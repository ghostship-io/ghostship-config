// mcp-rollout completes the existing skills publisher with explicit deployment,
// discovery and consumer receipts. It never dispatches work or widens access.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"time"
)

type snapshot struct {
	ObservedAt    string   `json:"observed_at"`
	ServerVersion string   `json:"connector_version"`
	CatalogueHash string   `json:"catalogue_hash"`
	StartedAt     string   `json:"started_at"`
	Tools         []string `json:"tools"`
}
type binding struct {
	ServerVersion string `json:"connector_version"`
	CatalogueHash string `json:"catalogue_hash"`
	StartedAt     string `json:"started_at"`
	PluginID      string `json:"plugin_id"`
	AppID         string `json:"app_id"`
	ReleaseID     string `json:"release_id"`
	ContentDigest string `json:"content_digest"`
}
type evidence struct {
	binding
	ObservedAt           string   `json:"observed_at"`
	EvidenceRef          string   `json:"evidence_ref"`
	Refreshed            bool     `json:"refreshed"`
	NativeTools          []string `json:"native_tools"`
	RetiredFacadesAbsent bool     `json:"retired_facades_absent"`
	ReadTool             string   `json:"read_tool"`
	ReadOutcome          string   `json:"read_outcome"`
}
type stage struct {
	Status string `json:"status"`
	Detail string `json:"detail"`
}
type report struct {
	binding
	Server            stage  `json:"server_deployed"`
	Publication       stage  `json:"plugin_published"`
	Discovery         stage  `json:"discovery_refreshed"`
	Consumer          stage  `json:"consumer_verified"`
	Complete          bool   `json:"complete"`
	PublicationAction string `json:"publication_action,omitempty"`
}
type stringsFlag []string

func (s *stringsFlag) String() string     { return strings.Join(*s, " ") }
func (s *stringsFlag) Set(v string) error { *s = append(*s, v); return nil }

// Receipts are local deployment artifacts, not assistant prompt assertions.
// Refuse symlinks and world/group-writable inputs. No receipt grants authority.
func readJSON(path string, value any) error {
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil || !st.Mode().IsRegular() || st.Mode().Perm()&0022 != 0 {
		return errors.New("unsafe receipt file")
	}
	return json.NewDecoder(io.LimitReader(f, 4<<20)).Decode(value)
}
func save(path string, value any) error {
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".mcp-rollout-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if err = f.Chmod(0600); err == nil {
		_, err = f.Write(append(b, '\n'))
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err == nil {
		err = os.Rename(f.Name(), path)
	}
	if err == nil {
		d, e := os.Open(filepath.Dir(path))
		if e != nil {
			return e
		}
		err = d.Sync()
		if closeErr := d.Close(); err == nil {
			err = closeErr
		}
	}
	return err
}
func runJSON(ctx context.Context, program string, args []string, value any, artifact string) error {
	cmd := exec.CommandContext(ctx, program, args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	began := time.Now()
	out, err := cmd.Output() // Never propagate publisher stderr, tokens or private page content.
	if save(artifact, map[string]any{"stdout": string(out), "stderr": stderr.String(), "success": err == nil, "duration_us": time.Since(began).Microseconds()}) != nil {
		return errors.New("private command receipt could not be saved")
	}
	if err != nil || len(out) > 4<<20 {
		return errors.New("release command failed; inspect its private log")
	}
	if json.Unmarshal(out, value) != nil {
		return errors.New("release command returned invalid JSON")
	}
	return nil
}
func validTime(value string) (time.Time, bool) {
	t, e := time.Parse(time.RFC3339Nano, value)
	return t, e == nil
}
func bound(path string, want binding) (evidence, bool) {
	var p evidence
	if readJSON(path, &p) != nil || p.binding != want || !strings.HasPrefix(p.EvidenceRef, "https://github.com/") {
		return p, false
	}
	t, ok := validTime(p.ObservedAt)
	start, startOK := validTime(want.StartedAt)
	return p, ok && startOK && !t.Before(start) && !t.After(time.Now().Add(time.Minute))
}
func nativeTools(names []string) bool {
	for _, n := range []string{"t3_project_list", "t3_thread_list", "t3_thread_read"} {
		if !slices.Contains(names, n) {
			return false
		}
	}
	for _, n := range []string{"t3", "services", "services_call", "browser_op", "browser_raw", "browser_window"} {
		if slices.Contains(names, n) {
			return false
		}
	}
	return true
}

func reconcile(ctx context.Context, args []string) int {
	fs := flag.NewFlagSet("reconcile", flag.ContinueOnError)
	skills := fs.String("skills-cli", "", "existing pinned skills publisher")
	repo := fs.String("repo", "", "selected native connector source")
	sha := fs.String("source-sha", "", "selected source revision")
	serverFile := fs.String("server", "", "private actual server snapshot")
	expect := fs.String("expect-version", "", "selected runtime version")
	dir := fs.String("state", "", "existing skills state directory")
	if fs.Parse(args) != nil || *dir == "" || *skills == "" || *repo == "" || *sha == "" {
		return 2
	}
	lock, err := os.OpenFile(filepath.Join(*dir, "reconcile.lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return 1
	}
	defer lock.Close()
	if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX); err != nil {
		return 1
	}
	defer syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
	r := report{Server: stage{"unknown", "server readback required"}, Publication: stage{"pending", "not attempted"}, Discovery: stage{"manual_required", "Refresh tools in the existing app settings, then record discovery.json"}, Consumer: stage{"manual_required", "Verify actual consumer declarations and one read-only native call; record consumer.json. A stale host may need a fresh conversation."}}
	finish := func(code int) int {
		if save(filepath.Join(*dir, "rollout.json"), r) != nil {
			return 1
		}
		json.NewEncoder(os.Stdout).Encode(r)
		return code
	}
	var s snapshot
	if readJSON(*serverFile, &s) != nil || *expect == "" || s.ServerVersion != *expect || len(s.CatalogueHash) != 64 || !nativeTools(s.Tools) {
		return finish(1)
	}
	observed, fresh := validTime(s.ObservedAt)
	if !fresh || time.Since(observed) > 5*time.Minute || observed.After(time.Now().Add(time.Minute)) {
		return finish(1)
	}
	if _, ok := validTime(s.StartedAt); !ok {
		return finish(1)
	}
	r.binding = binding{ServerVersion: s.ServerVersion, CatalogueHash: s.CatalogueHash, StartedAt: s.StartedAt}
	r.Server = stage{"verified", "actual connector health and catalogue readback; not whole-host health"}
	var config struct {
		PluginID string `json:"plugin_id"`
		Identity string `json:"identity"`
		App      struct {
			ID string `json:"id"`
		} `json:"app_binding"`
	}
	if readJSON(filepath.Join(*repo, "config/skills/chatgpt-plugin.json"), &config) != nil || config.PluginID == "" || config.App.ID == "" || config.Identity != "personal" {
		r.Publication = stage{"failed", "existing personal plugin identity/app binding required; creation is forbidden"}
		return finish(1)
	}
	r.PluginID = config.PluginID
	r.AppID = config.App.ID
	base := []string{"--repo", *repo, "--source-sha", *sha}
	var pkg struct {
		OK     bool   `json:"ok"`
		Record string `json:"record"`
	}
	if runJSON(ctx, *skills, append(slices.Clone(base), "package", "--out", filepath.Join(*dir, "package")), &pkg, filepath.Join(*dir, "package-command.json")) != nil || !pkg.OK {
		r.Publication = stage{"failed", "package validation failed"}
		return finish(1)
	}
	var record struct {
		Chat struct {
			ContentDigest string `json:"content_digest"`
		} `json:"chatgpt"`
	}
	if readJSON(pkg.Record, &record) != nil || len(record.Chat.ContentDigest) != 64 {
		r.Publication = stage{"failed", "package content digest missing"}
		return finish(1)
	}
	r.ContentDigest = record.Chat.ContentDigest
	// A readback of old content cannot prove an in-flight upload won't apply
	// later. Persist intent before publication and never resend while unresolved.
	intentPath := filepath.Join(*dir, "publication-intent.json")
	intent := struct{ PluginID, AppID, ContentDigest, SourceSHA string }{r.PluginID, r.AppID, r.ContentDigest, *sha}
	_, statErr := os.Lstat(intentPath)
	unresolved := statErr == nil
	if statErr != nil && !os.IsNotExist(statErr) {
		r.Publication = stage{"unknown", "publication intent unreadable"}
		return finish(1)
	}
	if unresolved {
		var previous struct{ PluginID, AppID, ContentDigest, SourceSHA string }
		if readJSON(intentPath, &previous) != nil || previous != intent {
			r.Publication = stage{"unknown", "unresolved publication intent does not match selected content; inspect original outcome"}
			return finish(1)
		}
	} else if save(intentPath, intent) != nil {
		r.Publication = stage{"unknown", "publication intent could not be persisted"}
		return finish(1)
	}
	var pub struct {
		Action       string `json:"action"`
		OK           bool   `json:"ok"`
		PluginID     string `json:"plugin_id"`
		ReleaseID    string `json:"release_id"`
		Verification struct {
			ReleaseID string `json:"release_id"`
		} `json:"verification"`
	}
	if !unresolved {
		if runJSON(ctx, *skills, append(slices.Clone(base), "publish-chatgpt"), &pub, filepath.Join(*dir, "publication-command.json")) != nil || !pub.OK || pub.PluginID != r.PluginID || !slices.Contains([]string{"unchanged", "updated"}, pub.Action) {
			r.Publication = stage{"unknown", "publication outcome unresolved; read back original intent without another upload"}
			return finish(1)
		}
	} else {
		pub.Action = "reconciled"
	}
	r.PublicationAction = pub.Action
	var verify struct {
		OK        bool     `json:"ok"`
		Skills    bool     `json:"skills_match"`
		Apps      bool     `json:"apps_match"`
		Content   bool     `json:"content_match"`
		PluginID  string   `json:"plugin_id"`
		ReleaseID string   `json:"release_id"`
		AppIDs    []string `json:"app_ids"`
	}
	if runJSON(ctx, *skills, append(slices.Clone(base), "verify-chatgpt"), &verify, filepath.Join(*dir, "verification-command.json")) != nil || !verify.OK || !verify.Skills || !verify.Apps || !verify.Content || verify.PluginID != r.PluginID || len(verify.AppIDs) != 1 || verify.AppIDs[0] != r.AppID || verify.ReleaseID == "" || (pub.ReleaseID != "" && pub.ReleaseID != verify.ReleaseID) {
		r.Publication = stage{"unknown", "publication unresolved; matching release readback required before retry"}
		return finish(1)
	}
	if err := os.Remove(intentPath); err != nil {
		r.Publication = stage{"unknown", "verified publication intent could not be cleared"}
		return finish(1)
	}
	stateDir, err := os.Open(*dir)
	if err != nil {
		return finish(1)
	}
	err = stateDir.Sync()
	stateDir.Close()
	if err != nil {
		return finish(1)
	}
	r.ReleaseID = verify.ReleaseID
	r.Publication = stage{"verified", "existing publisher readback matched content and app binding; normalized version may differ"}
	refresh, ok := bound(filepath.Join(*dir, "discovery.json"), r.binding)
	if !ok || !refresh.Refreshed {
		return finish(3)
	}
	r.Discovery = stage{"verified", refresh.EvidenceRef}
	consumer, ok := bound(filepath.Join(*dir, "consumer.json"), r.binding)
	if !ok || !consumer.RetiredFacadesAbsent || !nativeTools(consumer.NativeTools) || consumer.ReadTool != "t3_project_list" || consumer.ReadOutcome != "returned" {
		return finish(3)
	}
	ct, _ := validTime(consumer.ObservedAt)
	rt, _ := validTime(refresh.ObservedAt)
	if ct.Before(rt) {
		return finish(3)
	}
	r.Consumer = stage{"verified", consumer.EvidenceRef}
	r.Complete = true
	return finish(0)
}

// invalidate is called before readiness and again before parsing the start time.
// Write the incomplete report first so a failed snapshot removal cannot leave
// a previous success visible.
func invalidate(out string) error {
	if err := save(filepath.Join(filepath.Dir(out), "rollout.json"), report{Server: stage{"unknown", "server snapshot in progress"}, Publication: stage{"pending", "not checked"}, Discovery: stage{"manual_required", "discovery receipt required"}, Consumer: stage{"manual_required", "real consumer receipt required"}}); err != nil {
		return err
	}
	if err := os.Remove(out); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

func begin(args []string) int {
	fs := flag.NewFlagSet("begin", flag.ContinueOnError)
	out := fs.String("out", "", "private server receipt")
	if fs.Parse(args) != nil || *out == "" {
		return 2
	}
	if invalidate(*out) != nil {
		return 1
	}
	return 0
}

// snapshot uses only MCP initialize, tools/list and integration_status. The
// host invokes the existing private socket proxy inside the same-UID container.
func probe(ctx context.Context, args []string) int {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	fs := flag.NewFlagSet("snapshot", flag.ContinueOnError)
	program := fs.String("program", "", "trusted private socket proxy command")
	out := fs.String("out", "", "private server receipt")
	started := fs.String("started-at", "", "actual container start time")
	if fs.Parse(args) != nil || *program == "" || *out == "" {
		return 2
	}
	if invalidate(*out) != nil {
		return 1
	}
	start, ok := validTime(*started)
	if !ok { // Podman's Go-template Time.String representation.
		var err error
		start, err = time.Parse("2006-01-02 15:04:05.999999999 -0700 MST", *started)
		if err != nil {
			return 2
		}
	}
	*started = start.UTC().Format(time.RFC3339Nano)
	cmd := exec.CommandContext(ctx, *program, fs.Args()...)
	in, e := cmd.StdinPipe()
	if e != nil {
		return 1
	}
	stdout, e := cmd.StdoutPipe()
	if e != nil {
		return 1
	}
	if cmd.Start() != nil {
		return 1
	}
	defer func() { in.Close(); cmd.Process.Kill(); cmd.Wait() }()
	enc, dec := json.NewEncoder(in), json.NewDecoder(io.LimitReader(stdout, 64<<20))
	id := 0
	rpc := func(method string, params any, result any) error {
		id++
		if err := enc.Encode(map[string]any{"jsonrpc": "2.0", "id": id, "method": method, "params": params}); err != nil {
			return err
		}
		for {
			var v struct {
				ID     int             `json:"id"`
				Result json.RawMessage `json:"result"`
				Error  json.RawMessage `json:"error"`
			}
			if dec.Decode(&v) != nil {
				return errors.New("connector response unavailable")
			}
			if v.ID == id {
				if len(v.Error) > 0 {
					return errors.New("connector refused read")
				}
				return json.Unmarshal(v.Result, result)
			}
		}
	}
	var init struct {
		Protocol string `json:"protocolVersion"`
	}
	if rpc("initialize", map[string]any{"protocolVersion": "2025-03-26", "capabilities": map[string]any{}, "clientInfo": map[string]any{"name": "GhostShip rollout readback", "version": "1"}}, &init) != nil || init.Protocol != "2025-03-26" {
		return 1
	}
	enc.Encode(map[string]any{"jsonrpc": "2.0", "method": "notifications/initialized"})
	var health struct {
		IsError bool `json:"isError"`
		Data    struct {
			Version        string `json:"connector_version"`
			Hash           string `json:"catalogue_hash"`
			Stale          bool   `json:"catalogue_refresh_failed"`
			Implementation string `json:"implementation"`
		} `json:"structuredContent"`
	}
	if rpc("tools/call", map[string]any{"name": "integration_status", "arguments": map[string]any{}}, &health) != nil || health.IsError || health.Data.Stale || health.Data.Implementation != "go" {
		return 1
	}
	s := snapshot{ObservedAt: time.Now().UTC().Format(time.RFC3339Nano), ServerVersion: health.Data.Version, CatalogueHash: health.Data.Hash, StartedAt: *started}
	cursor := ""
	seen := map[string]bool{}
	for {
		var page struct {
			Tools []struct {
				Name string `json:"name"`
			} `json:"tools"`
			Next string `json:"nextCursor"`
		}
		if rpc("tools/list", map[string]any{"cursor": cursor}, &page) != nil {
			return 1
		}
		for _, t := range page.Tools {
			s.Tools = append(s.Tools, t.Name)
		}
		if page.Next == "" {
			break
		}
		if seen[page.Next] {
			return 1
		}
		seen[page.Next] = true
		cursor = page.Next
	}
	if !nativeTools(s.Tools) || save(*out, s) != nil {
		return 1
	}
	return 0
}
func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	code := 2
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "begin":
			code = begin(os.Args[2:])
		case "snapshot":
			code = probe(ctx, os.Args[2:])
		case "reconcile":
			code = reconcile(ctx, os.Args[2:])
		}
	}
	if code == 2 {
		fmt.Fprintln(os.Stderr, "usage: mcp-rollout begin|snapshot|reconcile (see --help)")
	}
	os.Exit(code)
}
