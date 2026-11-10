#!/usr/bin/env bash
set -u -o pipefail

BRANCH="${1:-$(git branch --show-current)}"
RESULT_EXIT=0
SBOM_RESULT="niet uitgevoerd"
SBOM_CHANGED=false

SBOM_DIR=".sigrid"
SBOM_FILE="$SBOM_DIR/sbom.json"
SBOM_RAW="$SBOM_DIR/sbom.raw.json"

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

mkdir -p "$SBOM_DIR"

echo "SBOM genereren:"
echo "- tool: syft"
echo "- formaat: CycloneDX JSON"

docker run --rm \
  -v "$PWD:/repo" \
  -w /repo \
  anchore/syft:v1.51.0 \
  scan dir:. \
  --exclude './.git/**' \
  --exclude './.sigrid/**' \
  --exclude './sbom/**' \
  -o "cyclonedx-json=$SBOM_RAW" \
  2>&1

SYFT_EXIT=$?

if [ "$SYFT_EXIT" -ne 0 ]; then
  RESULT_EXIT=$SYFT_EXIT
  SBOM_RESULT="SBOM genereren mislukt"
else
  python3 - "$PWD/$SBOM_RAW" "$PWD/$SBOM_FILE" <<'PY'
import json
import sys

source = sys.argv[1]
target = sys.argv[2]

with open(source, encoding="utf-8") as file:
    data = json.load(file)

# Verwijder waarden die iedere generatie veranderen.
data.pop("serialNumber", None)

metadata = data.get("metadata")
if isinstance(metadata, dict):
    metadata.pop("timestamp", None)

# Sorteer components deterministisch.
components = data.get("components")

if isinstance(components, list):
    for component in components:
        hashes = component.get("hashes")
        if isinstance(hashes, list):
            hashes.sort(
                key=lambda item: (
                    item.get("alg", ""),
                    item.get("content", ""),
                )
            )

        properties = component.get("properties")
        if isinstance(properties, list):
            properties.sort(
                key=lambda item: (
                    item.get("name", ""),
                    item.get("value", ""),
                )
            )

        external_references = component.get("externalReferences")
        if isinstance(external_references, list):
            external_references.sort(
                key=lambda item: (
                    item.get("type", ""),
                    item.get("url", ""),
                )
            )

        licenses = component.get("licenses")
        if isinstance(licenses, list):
            licenses.sort(
                key=lambda item: json.dumps(
                    item,
                    sort_keys=True,
                    ensure_ascii=False,
                )
            )

    components.sort(
        key=lambda component: (
            component.get("type", ""),
            component.get("name", ""),
            component.get("version", ""),
            component.get("purl", ""),
            component.get("bom-ref", ""),
        )
    )

# Sorteer dependencies deterministisch.
dependencies = data.get("dependencies")

if isinstance(dependencies, list):
    for dependency in dependencies:
        depends_on = dependency.get("dependsOn")
        if isinstance(depends_on, list):
            depends_on.sort()

        provides = dependency.get("provides")
        if isinstance(provides, list):
            provides.sort()

    dependencies.sort(
        key=lambda dependency: dependency.get("ref", "")
    )

# Schrijf altijd dezelfde JSON-opmaak.
with open(target, "w", encoding="utf-8") as file:
    json.dump(
        data,
        file,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    file.write("\n")
PY

  NORMALIZE_EXIT=$?

  rm -f "$SBOM_RAW"

  if [ "$NORMALIZE_EXIT" -ne 0 ]; then
    RESULT_EXIT=$NORMALIZE_EXIT
    SBOM_RESULT="SBOM normaliseren mislukt"
  else
    git add -f "$SBOM_FILE"

    if git diff --cached --quiet -- "$SBOM_FILE"; then
      SBOM_RESULT="SBOM is al actueel"
    else
      SBOM_CHANGED=true

      git config user.name "edwh-sbom-bot"
      git config user.email "sbom-bot@educationwarehouse.nl"

      git commit \
        -m "chore(sbom): update CycloneDX SBOM" \
        -- "$SBOM_FILE" \
        2>&1

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
echo "- bestand: $SBOM_FILE"

echo "--- END REPORTING ---"

exit "$RESULT_EXIT"
