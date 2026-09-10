#!/usr/bin/env bash
set -u -o pipefail

BRANCH="${1:-$(git branch --show-current)}"
RESULT_EXIT=0
SBOM_RESULT="niet uitgevoerd"
SBOM_CHANGED=false

echo "--- START REPORTING ---"

echo "SBOM generatie gestart"
echo ""
echo "Branch:"
echo "- $BRANCH"
echo ""

case "$BRANCH" in
  staging|prd|*/staging|*/prd)
    echo "Gestopt: dit script commit nooit direct naar staging of prd."
    echo "--- END REPORTING ---"
    exit 0
    ;;
esac

mkdir -p sbom

echo "SBOM genereren:"
echo "- tool: syft"
echo "- formaat: CycloneDX JSON"

docker run --rm \
  -v "$PWD:/repo" \
  -w /repo \
  anchore/syft:latest \
  scan dir:. \
  --exclude './.git/**' \
  --exclude './sbom/**' \
  -o cyclonedx-json=sbom/cyclonedx.raw.json \
  2>&1

SYFT_EXIT=$?

if [ "$SYFT_EXIT" -ne 0 ]; then
  RESULT_EXIT=$SYFT_EXIT
  SBOM_RESULT="SBOM genereren mislukt"
else
  python3 - "$PWD/sbom/cyclonedx.raw.json" "$PWD/sbom/cyclonedx.json" <<'PY'
import json
import sys

source = sys.argv[1]
target = sys.argv[2]

with open(source, encoding="utf-8") as file:
    data = json.load(file)

data.pop("serialNumber", None)

metadata = data.get("metadata")
if isinstance(metadata, dict):
    metadata.pop("timestamp", None)

with open(target, "w", encoding="utf-8") as file:
    json.dump(data, file, indent=2, sort_keys=True)
    file.write("\n")
PY

  NORMALIZE_EXIT=$?
  rm -f sbom/cyclonedx.raw.json

  if [ "$NORMALIZE_EXIT" -ne 0 ]; then
    RESULT_EXIT=$NORMALIZE_EXIT
    SBOM_RESULT="SBOM normaliseren mislukt"
  else
    git add -f sbom/cyclonedx.json

    if git diff --cached --quiet; then
      SBOM_RESULT="SBOM is al actueel"
    else
      SBOM_CHANGED=true

      git config user.name "edwh-sbom-bot"
      git config user.email "sbom-bot@educationwarehouse.nl"

      git commit -m "Update CycloneDX SBOM" 2>&1
      COMMIT_EXIT=$?

      if [ "$COMMIT_EXIT" -ne 0 ]; then
        RESULT_EXIT=$COMMIT_EXIT
        SBOM_RESULT="SBOM commit mislukt"
      else
        SBOM_RESULT="SBOM gecommit"
      fi
    fi

    if [ "$RESULT_EXIT" -eq 0 ]; then
      echo ""
      echo "Git push:"
      echo "- lokale branch: $(git branch --show-current)"
      echo "- doelbranch: $BRANCH"

      git push origin "HEAD:refs/heads/$BRANCH" 2>&1
      PUSH_EXIT=$?

      if [ "$PUSH_EXIT" -ne 0 ]; then
        RESULT_EXIT=$PUSH_EXIT
        SBOM_RESULT="SBOM push mislukt"
      elif [ "$SBOM_CHANGED" = true ]; then
        SBOM_RESULT="SBOM bijgewerkt en gepusht naar feature branch"
      else
        SBOM_RESULT="SBOM is actueel en eventuele openstaande commit is gepusht"
      fi
    fi
  fi
fi

echo ""
echo "Samenvatting:"

if [ "$RESULT_EXIT" -eq 0 ]; then
  echo "- SBOM: OK"
else
  echo "- SBOM: FAILED"
fi

echo "- resultaat: $SBOM_RESULT"
echo "- bestand: sbom/cyclonedx.json"

echo "--- END REPORTING ---"

exit "$RESULT_EXIT"
