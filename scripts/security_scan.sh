#!/usr/bin/env bash
# Fails if any known-sensitive token is staged for commit.
# Run as pre-commit hook or manually before pushing.
# Portable: works with bash 3.2 (macOS default) and bash 4+.
set -u

die() { echo "[security_scan] FAIL: $*" >&2; exit 1; }

# Collect files to scan: staged files if inside a git repo with staged changes,
# otherwise all tracked + untracked files (excluding ignored paths).
FILES=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if ! git diff --cached --quiet 2>/dev/null; then
    FILES="$(git diff --cached --name-only --diff-filter=ACM)"
  else
    FILES="$(git ls-files --cached --others --exclude-standard)"
  fi
else
  FILES="$(find . -type f -not -path './.git/*')"
fi

[ -z "$FILES" ] && { echo "[security_scan] no files to scan"; exit 0; }

# Newline-separated patterns (portable, no arrays needed beyond loop-over-lines)
PATTERNS='AKIA[0-9A-Z]{16}
ASIA[0-9A-Z]{16}
aws_secret_access_key[[:space:]]*=
907056532170
arn:aws:iam::[0-9]{12}:
gsn_ssm
sungminnetworks
/Users/sungminnetworks/
talkcrm24\.com
GOOGLE_API_KEY[[:space:]]*=[[:space:]]*[^[:space:]]+
gho_[A-Za-z0-9]{30,}
ghp_[A-Za-z0-9]{30,}
sk-ant-[A-Za-z0-9_-]{20,}
sk-proj-[A-Za-z0-9_-]{20,}'

FAIL=0
COUNT=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  [ -f "$f" ] || continue
  # Allowlist: the scanner itself and the archived upstream README are allowed
  # to mention patterns as reference strings.
  case "$f" in
    scripts/security_scan.sh|README.upstream.md) continue ;;
  esac
  # Skip binary files
  if ! file "$f" 2>/dev/null | grep -qE 'text|empty|ASCII|UTF-8|JSON|script'; then
    continue
  fi
  COUNT=$((COUNT + 1))
  while IFS= read -r pat; do
    [ -z "$pat" ] && continue
    if grep -EnH -- "$pat" "$f" 2>/dev/null; then
      echo "  -> pattern: $pat  file: $f" >&2
      FAIL=1
    fi
  done <<EOF
$PATTERNS
EOF
done <<EOF
$FILES
EOF

if [ "$FAIL" -ne 0 ]; then
  die "one or more files contain sensitive patterns. Remove them before committing."
fi

echo "[security_scan] OK ($COUNT text files clean)"
