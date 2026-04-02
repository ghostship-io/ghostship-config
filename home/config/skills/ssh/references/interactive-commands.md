# interactive SSH command patterns

Use these patterns when the remote command needs prompt handling or a
persistent interactive shell.

## Standard pattern

Use this sequence for prompt-driven remote work:

1. Start the interactive command in a detached tmux session so the SSH command
   returns immediately.
2. Read the current pane output with `capture-pane`.
3. Send the next input with `send-keys`.
4. Repeat `capture-pane` and `send-keys` until the task is done.

Every SSH command in this flow must return on its own.

## Start the interactive command detached

```fish
ssh <host> "tmux new-session -d -s <name> 'cd <repo> && <command>'"
```

Use a stable session name so later `capture-pane`, `send-keys`, and
`kill-session` calls target the same process.

## Read the current output

```fish
ssh <host> 'tmux capture-pane -pt <name> -S -120'
```

Use this before each follow-up input so you know which prompt is active.

## Send input to the running tmux session

Use this when the remote program is waiting for input.

```fish
ssh <host> "tmux send-keys -t <name> '<input>' Enter"
```

## Check whether the session still exists

```fish
ssh <host> 'tmux has-session -t <name>'
```

## Exit cleanly

- Avoid running prompt-driven commands as the top-level SSH command. They block
  the agent until the remote process exits.
- Avoid plain `ssh <host>` shells in agent workflows. They do not return until
  the shell exits.
- Avoid `tmux attach` in agent workflows. It does not end on its own and assumes
  a human can detach manually.

## Guidance

- Prefer tmux for prompt-driven commands, REPLs, installers, and anything that
  may need later input.
- Start the interactive command in the initial detached `tmux new-session`
  invocation so the SSH call returns immediately.
- Use `capture-pane` to inspect state and `send-keys` to continue the session.
- Prefer remote commands that return immediately. Non-terminating commands block
  the agent from continuing the workflow.
- Keep remote command strings short; once quoting becomes fragile, switch to an
  interactive shell or a checked-in script.
