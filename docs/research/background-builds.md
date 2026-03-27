# Documented Background Build Procedure for Chill Penguin

This document outlines the repeatable, background-safe method for building the NixOS system and kernel on the Mac Studio (`chill-penguin`).

## 1. Why this method?
Fedora Asahi's default SSH and session management can sometimes kill background processes on disconnect. Using `tmux` with a **custom socket path** ensures the session persists and remains accessible regardless of the SSH state.

## 2. Starting a New Build
Always use a unique session name and log file to prevent overlapping with previous attempts.

### Method A: tmux (Preferred)
Using `tmux` with a **custom socket path** ensures the session persists and remains accessible regardless of the SSH state.

```bash
# SSH to the host
ssh root@chill-penguin

# Define session parameters
set SESSION "build-v26"  # Increment this for new attempts
set LOG "/root/nixos-config/build_$SESSION.log"

# Start the build in a detached tmux session with a custom socket
tmux -S /tmp/nix-tmux new-session -d -s "$SESSION" \
  "cd /root/nixos-config && nix build .#nixosConfigurations.chill-penguin.config.system.build.toplevel --print-build-logs 2>&1 | tee \"$LOG\""
```

### Method B: nohup (Fallback if tmux is missing)
If `tmux` is not available on the minimal bootstrap system, use `nohup`.

```bash
# Define log file (Current successful pattern)
set LOG "/home/nixos/nixos-config/build_v44_rust184_final.log"

# Start the build in background
cd ~/nixos-config
nohup nix build .#nixosConfigurations.chill-penguin.config.system.build.toplevel \
  --print-build-logs --impure --show-trace > "$LOG" 2>&1 &
```

## 3. Monitoring the Build
### Method A: tmux
```bash
# List active sessions
tmux -S /tmp/nix-tmux list-sessions

# Tail the log file
tail -f /root/nixos-config/build_v26.log
```

### Method B: nohup
```bash
# Check if nix is still running
ps aux | grep nix

# Tail the log file
tail -f /home/nixos/nixos-config/build_rust_v3.log
```

## 4. Interacting with the Session
If you need to provide input or see the live console:

```bash
# Attach to the session
tmux -S /tmp/nix-tmux attach -t build-v26

# To detach safely, press: Ctrl+B followed by D
```

## 5. Verifying the Result
Once the build completes (the tmux session will usually close if the command finishes, or remain if you configured it otherwise), check the log for success and locate the result:

```bash
# Check if the result symlink was created
ls -l /root/nixos-config/result

# Verify the kernel binary alignment (critical for M1 Ultra)
# The file should be ~18MB and the header should match Fedora's layout
ls -lh /root/nixos-config/result/kernel
```
