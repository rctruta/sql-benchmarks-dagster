#!/bin/sh
# gates_report — a dated snapshot of where the gates stand, across repositories.
#
#   gates_report.sh ~/Projects/* > reports/gates-$(date -u +%F).md
#
# The committed, low-volume record. Four columns, because four things are worth
# knowing and the rest is noise:
#
#   version     how far behind the seed a repository is
#   baselined   findings accepted at adoption. A backlog. If it never shrinks,
#               it is a rule nobody intends to honour, and worth saying so.
#   open        findings not baselined — these block
#   blocked     times a gate actually stopped something, from .gates/ledger.jsonl
#
# That last column is the one that decides whether a gate earns its place. A
# gate that has never blocked anything is either prevention working or dead
# weight, and the count is the only way to tell them apart.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SEED_VERSION="$(cat "$HERE/VERSION")"

echo "# Gates: where they stand"
echo
echo "Generated $(date -u +%Y-%m-%dT%H:%M:%SZ) by gates_report.sh. Seed version $SEED_VERSION."
echo
echo "| repository | version | gate | baselined | open | blocked |"
echo "|---|---|---|---|---|---|"

for repo in "$@"; do
  [ -d "$repo/.git" ] || continue
  [ -d "$repo/.gates" ] || continue
  name="$(basename "$repo")"
  ver="$([ -f "$repo/.gates/VERSION" ] && cat "$repo/.gates/VERSION" || echo "?")"
  for g in "$repo"/.gates/*.py; do
    b="$(basename "$g" .py)"
    case "$b" in _*|check_version) continue;; esac
    base="$repo/.gates/baseline/$b.txt"
    nbase=0; [ -f "$base" ] && nbase="$(grep -cv '^#' "$base" 2>/dev/null | head -1)"
    open="$(python3 "$g" 2>/dev/null | grep -cE '^  [^ ]' 2>/dev/null | head -1)"
    blocked=0
    [ -f "$repo/.gates/ledger.jsonl" ] && blocked="$(grep -c "\"gate\": \"$b\".*blocked" "$repo/.gates/ledger.jsonl" 2>/dev/null | head -1)"
    printf '| %s | %s | `%s` | %s | %s | %s |\n' "$name" "$ver" "$b" "$nbase" "$open" "$blocked"
  done
done

echo
echo "A baseline that has not shrunk since adoption is a backlog nobody is working."
echo "A gate with no blocks and no open findings may be prevention, or may be dead;"
echo "\`prove_gates.sh\` shows it still CAN fire."
