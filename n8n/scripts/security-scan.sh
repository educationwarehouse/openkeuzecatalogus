#!/usr/bin/env bash
set -u -o pipefail

UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

PIP_AUDIT_EXIT=0
GITLEAKS_EXIT=0

PIP_AUDIT_RESULT="niet uitgevoerd"
GITLEAKS_RESULT="niet uitgevoerd"

PIP_AUDIT_IGNORE_ARGS=()
if [ -f .pip-audit-ignore ]; then
  while IFS= read -r vulnerability_id; do
    case "$vulnerability_id" in
      "" | \#*) continue ;;
    esac

    PIP_AUDIT_IGNORE_ARGS+=(--ignore-vuln "$vulnerability_id")
  done < .pip-audit-ignore
fi

echo "--- START REPORTING ---"

echo "Security scan gestart"
echo ""

echo "Dependency vulnerability scan:"
echo "- tool: pip-audit"

if [ ! -x "$UV" ]; then
  PIP_AUDIT_EXIT=127
  PIP_AUDIT_RESULT="uv niet gevonden op $UV"
elif [ ! -f requirements-dev.txt ]; then
  PIP_AUDIT_RESULT="requirements-dev.txt niet gevonden, scan overgeslagen"
else
  "$UV" tool run pip-audit \
    --requirement requirements-dev.txt \
    "${PIP_AUDIT_IGNORE_ARGS[@]}" \
    2>&1

  PIP_AUDIT_EXIT=$?

  if [ "$PIP_AUDIT_EXIT" -eq 0 ]; then
    PIP_AUDIT_RESULT="geen bekende kwetsbaarheden gevonden"
  else
    PIP_AUDIT_RESULT="kwetsbaarheden gevonden of pip-audit mislukt"
  fi
fi

echo ""
echo "Resultaat pip-audit:"
echo "- status: $PIP_AUDIT_RESULT"
echo "- exit code: $PIP_AUDIT_EXIT"
echo ""

echo "Secrets scan:"
echo "- tool: gitleaks"

GITLEAKS_OUTPUT=$(docker run --rm \
  -e NO_COLOR=1 \
  -v "$PWD:/repo" \
  -w /repo \
  ghcr.io/gitleaks/gitleaks:latest \
  git . \
  --redact \
  --no-banner \
  --verbose \
  2>&1)

GITLEAKS_EXIT=$?

if [ "$GITLEAKS_EXIT" -eq 0 ]; then
  GITLEAKS_RESULT="geen secrets gevonden"
elif [ "$GITLEAKS_EXIT" -eq 1 ]; then
  GITLEAKS_RESULT="mogelijk secret gevonden"
else
  GITLEAKS_RESULT="gitleaks scan mislukt"
fi

echo ""
echo "Resultaat gitleaks:"
echo "- status: $GITLEAKS_RESULT"
echo "- exit code: $GITLEAKS_EXIT"

if [ "$GITLEAKS_EXIT" -eq 1 ]; then
  echo ""
  echo "Gevonden locatie:"

  LOCATIONS=$(printf '%s\n' "$GITLEAKS_OUTPUT" |
    grep -Ei '^[[:space:]]*(file|line|startline|commit):' |
    sed 's/^[[:space:]]*/- /' || true)

  if [ -n "$LOCATIONS" ]; then
    echo "$LOCATIONS"
  else
    echo "- locatie kon niet uit de Gitleaks-output worden gehaald"
  fi
elif [ "$GITLEAKS_EXIT" -gt 1 ]; then
  echo ""
  echo "Gitleaks-fout:"
  printf '%s\n' "$GITLEAKS_OUTPUT"
fi

echo ""
echo "Samenvatting:"

if [ "$PIP_AUDIT_EXIT" -eq 0 ]; then
  echo "- pip-audit: OK"
else
  echo "- pip-audit: FAILED"
fi

if [ "$GITLEAKS_EXIT" -eq 0 ]; then
  echo "- gitleaks: OK"
else
  echo "- gitleaks: FAILED"
fi

if [ "$PIP_AUDIT_EXIT" -eq 0 ] && [ "$GITLEAKS_EXIT" -eq 0 ]; then
  echo "- Security scans: OK"
else
  echo "- Security scans: FAILED"
fi

echo "--- END REPORTING ---"

exit 0
