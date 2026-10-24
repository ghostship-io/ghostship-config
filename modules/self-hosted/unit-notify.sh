# Unit outcomes for ghostship-failure@ and ghostship-success@. A failure goes
# to operations; a success summary goes silently to informational and quotes
# only restic summary lines, so it never forwards arbitrary journal output.
# Every @host@ is substituted with the host name by monitoring.nix, which
# hands this file to writeShellApplication; the unit tests run it verbatim
# with stubbed systemctl and ghostship-notify.
outcome=$1
unit=$2
host=@host@
description=$(systemctl show -P Description "$unit")

# Name the failing dependency of a start job that never got to run the unit.
# Such a failure leaves the unit's own Result at success and ExecMainStatus
# at 0 because the unit never executed; the culprit is one of the
# start-propagating dependency edges that is itself failed right now. Wants=
# is deliberately excluded: a wanted job's failure does not fail this start
# job, so a failed wanted unit would misname the cause.
find_failed_dependency() {
  local unit=$1 edges line key candidate
  edges=$(systemctl show -p BindsTo,Requires,Requisite "$unit" 2>/dev/null) || edges=
  while IFS= read -r line; do
    key=${line%%=*}
    case $key in
      BindsTo|Requires|Requisite) ;;
      *) continue ;;
    esac
    # shellcheck disable=SC2086 # the unit list splits on spaces
    for candidate in ${line#*=}; do
      if [ "$candidate" = "$unit" ]; then
        continue
      fi
      if [ "$(systemctl show -P ActiveState "$candidate" 2>/dev/null)" != failed ]; then
        continue
      fi
      printf '%s\n' "$candidate"
      return 0
    done
  done <<<"$edges"
  return 1
}

case $outcome in
  failure)
    result=$(systemctl show -P Result "$unit")
    status=$(systemctl show -P ExecMainStatus "$unit")
    if [ "$result" = success ] && [ "$status" = 0 ]; then
      # The unit never executed, so reporting "success (exit status 0)" says
      # the opposite of what happened: the unit's start job failed before
      # the unit ran. Name the job outcome and the failing dependency.
      dependency=$(find_failed_dependency "$unit") || true
      if [ -n "$dependency" ]; then
        detail="start job failed: dependency $dependency failed"
      else
        detail="start job failed: a dependency failed before the unit ran"
      fi
      exec ghostship-notify --topic operations --priority 4 --source systemd --incident \
        --dedupe "$unit" --title "Service $unit failed on $host" \
        "$description: $detail. Inspect: journalctl -b -u $unit"
    fi
    exec ghostship-notify --topic operations --priority 4 --source systemd --incident \
      --dedupe "$unit" --title "Service $unit failed on $host" \
      "$description: $result (exit status $status). Inspect: journalctl -b -u $unit"
    ;;
  success)
    invocation=$(systemctl show -P InvocationID "$unit")
    if [ -n "$invocation" ]; then
      log=$(journalctl -o cat --no-pager "_SYSTEMD_INVOCATION_ID=$invocation")
    else
      log=$(journalctl -o cat --no-pager -n 200 -u "$unit")
    fi
    summary=$(grep -E '^(Added to the repository|processed |snapshot [0-9a-f]+ saved|keep [0-9]+ snapshots|remove [0-9]+ snapshots|no errors were found|this removes|unused size after prune)' <<<"$log" | tail -n 8 || true)
    exec ghostship-notify --topic informational --priority 2 --source systemd \
      --state resolved --dedupe "$unit" --title "$description succeeded on $host" \
      "${summary:-$unit finished without a summary.}"
    ;;
  *)
    echo "Usage: ghostship-unit-notify failure|success UNIT" >&2
    exit 2
    ;;
esac
