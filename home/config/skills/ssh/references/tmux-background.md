# tmux background patterns

Use these patterns when a remote command must keep running after SSH exits.

## Start detached

Use a stable session name and an explicit log path.

```fish
ssh <host> "tmux new-session -d -s <name> 'cd <repo> && <command> > <log> 2>&1'"
```

```fish
ssh chill-penguin-root "tmux new-session -d -s rebuild 'cd /home/nixos/nixos-config && nixos-rebuild build --flake .#chill-penguin -L > /tmp/chill-penguin-build.log 2>&1'"
```

## Check whether it is still running

```fish
ssh <host> 'tmux has-session -t <name>'
```

## List sessions

```fish
ssh <host> 'tmux ls'
```

## Read recent output without attaching

```fish
ssh <host> 'tmux capture-pane -pt <name> -S -200'
```

Use the log file for the full output:

```fish
ssh <host> 'tail -n 200 <log>'
```

## Stop it

```fish
ssh <host> 'tmux kill-session -t <name>'
```

## Guidance

- Prefer one session per task.
- Use descriptive names such as `build`, `deploy`, or the host name.
- Redirect stdout and stderr to a log file when the result matters after the
  session ends.
- Put `cd <repo> && <command>` in the initial `tmux new-session` invocation for
  repeatable builds, deploys, and interactive programs that must keep running
  after the SSH call returns.
- Prefer `capture-pane` or `tail` for inspection so the SSH command always
  returns.
