# Security scan en SBOM via n8n

## Doel

Deze configuratie voegt twee controles toe aan de bestaande n8n CI-flow:

1. Security scan
   - controleert Python dependencies met `pip-audit`
   - controleert mogelijke secrets met `gitleaks`
   - voert geen dependency fixes uit
   - wijzigt niets in de repository

2. SBOM generatie
   - genereert een CycloneDX SBOM met `syft`
   - schrijft alleen `sbom/cyclonedx.json`
   - commit en pusht alleen het SBOM-bestand naar de feature branch
   - voert geen dependency updates of fixes uit

De security scan is bedoeld als controle op kwetsbaarheden en mogelijke secrets. De SBOM is bedoeld om inzicht te geven in gebruikte componenten en om op verzoek een actuele CycloneDX SBOM te kunnen leveren.

## SSD-koppeling

Deze inrichting sluit aan op **SSD-3 Veilige externe componenten**. SSD-3 stelt dat applicaties veilige en actief onderhouden externe componenten moeten gebruiken, zodat de applicatie niet kwetsbaar wordt door kwetsbaarheden of kwaadaardige logica in externe componenten. De SSD noemt hierbij ook dependency management tooling als technische ondersteuning voor lifecycle management, actualisering en patching. :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1}

De secrets scan sluit aan op **SSD-5 Authenticatie van gebruikers en systemen**, waarin onder andere wordt benoemd dat hard gecodeerde wachtwoorden niet gebruikt moeten worden. :contentReference[oaicite:2]{index=2}

Wanneer een bevinding bewust niet wordt opgelost, moet dit volgens het SSD-principe **Comply or Explain** worden onderbouwd met een risicoafweging en expliciete acceptatie. :contentReference[oaicite:3]{index=3}

## Bestanden in de repository

De volgende scripts worden toegevoegd aan de repository:

```text
n8n/scripts/security-scan.sh
n8n/scripts/sbom-generate.sh
```

De security scan maakt geen rapportbestanden in de repository. De output wordt alleen door n8n gebruikt voor de GitHub PR-comment.

De SBOM generatie schrijft alleen:

```text
sbom/cyclonedx.json
```

## n8n-flow

De bestaande CI-flow blijft ongewijzigd. De nieuwe nodes worden alleen toegevoegd aan het einde van het bestaande staging- en prd-pad.

### Staging-pad

```text
Create a review6
→ security scan uitvoeren
→ Create security scan review
→ SBOM genereren
→ Create SBOM review
→ No Operation, do nothing2
```

### Prd-pad

```text
Create a review7
→ security scan uitvoeren1
→ Create security scan review1
→ SBOM genereren1
→ Create SBOM review1
→ No Operation, do nothing2
```

## Vereisten op de server

De server waarop de n8n SSH-nodes draaien moet de volgende tools beschikbaar hebben:

```text
git
docker
python3
```

De gebruikte scans draaien via Docker containers. Er wordt dus geen `pip-audit`, `gitleaks` of `syft` lokaal op de server geïnstalleerd.

Voor het pushen van de SBOM moet de GitHub SSH-key of bot-account write access hebben op de repository.

## Script 1: security-scan.sh

Bestand:

```text
n8n/scripts/security-scan.sh
```

```bash
#!/usr/bin/env bash
set -u -o pipefail

PIP_AUDIT_EXIT=0
GITLEAKS_EXIT=0

echo "--- START REPORTING ---"

echo "Security scan gestart"
echo ""
echo "Dependency vulnerability scan:"
echo "- tool: pip-audit"
echo "- mode: controle-only, geen dependency fixes"
echo ""

if [ -f requirements-dev.txt ]; then
  docker run --rm \
    -v "$PWD:/repo" \
    -w /repo \
    python:3-slim \
    sh -c "python -m pip install --quiet --upgrade pip-audit && python -m pip_audit --requirement requirements-dev.txt" \
    2>&1

  PIP_AUDIT_EXIT=$?
else
  echo "- requirements-dev.txt niet gevonden, pip-audit overgeslagen"
  PIP_AUDIT_EXIT=0
fi

echo ""
echo "- pip-audit exit code: $PIP_AUDIT_EXIT"
echo ""

echo "Secrets scan:"
echo "- tool: gitleaks"
echo ""

docker run --rm \
  -v "$PWD:/repo" \
  -w /repo \
  ghcr.io/gitleaks/gitleaks:latest \
  git . \
  --redact \
  2>&1

GITLEAKS_EXIT=$?

echo ""
echo "- gitleaks exit code: $GITLEAKS_EXIT"
echo ""

echo "Samenvatting:"
if [ "$PIP_AUDIT_EXIT" -eq 0 ] && [ "$GITLEAKS_EXIT" -eq 0 ]; then
  echo "- Security scans: OK"
else
  echo "- Security scans: FAILED"
fi

echo "- Dependency fixes: niet uitgevoerd"
echo "- Repository wijzigingen: geen"

echo "--- END REPORTING ---"

exit 0
```

## Script 2: sbom-generate.sh

Bestand:

```text
n8n/scripts/sbom-generate.sh
```

```bash
#!/usr/bin/env bash
set -u -o pipefail

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
SYFT_EXIT=0
SBOM_RESULT="niet uitgevoerd"

echo "--- START REPORTING ---"

echo "SBOM generatie gestart"
echo ""
echo "Branch:"
echo "- $BRANCH"
echo ""

if [ "$BRANCH" = "staging" ] || [ "$BRANCH" = "prd" ]; then
  echo "Gestopt: dit script commit nooit direct naar staging of prd."
  echo "--- END REPORTING ---"
  exit 0
fi

mkdir -p sbom

echo "SBOM genereren:"
echo "- tool: syft"
echo "- formaat: CycloneDX JSON"
echo "- mode: SBOM mag worden bijgewerkt, dependency fixes niet"
echo ""

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
  SBOM_RESULT="SBOM genereren mislukt"
else
  python3 - "$PWD/sbom/cyclonedx.raw.json" "$PWD/sbom/cyclonedx.json" <<'PY'
import json
import sys

source = sys.argv[1]
target = sys.argv[2]

with open(source) as f:
    data = json.load(f)

data.pop("serialNumber", None)

metadata = data.get("metadata")
if isinstance(metadata, dict):
    metadata.pop("timestamp", None)

with open(target, "w") as f:
    json.dump(data, f, indent=2, sort_keys=True)
    f.write("\n")
PY

  NORMALIZE_EXIT=$?
  rm -f sbom/cyclonedx.raw.json

  if [ "$NORMALIZE_EXIT" -ne 0 ]; then
    SYFT_EXIT=$NORMALIZE_EXIT
    SBOM_RESULT="SBOM normaliseren mislukt"
  else
    git add sbom/cyclonedx.json

    if git diff --cached --quiet; then
      SBOM_RESULT="SBOM is al actueel"
    else
      git config user.name "edwh-sbom-bot"
      git config user.email "sbom-bot@educationwarehouse.nl"

      git commit -m "Update CycloneDX SBOM" 2>&1
      COMMIT_EXIT=$?

      if [ "$COMMIT_EXIT" -ne 0 ]; then
        SYFT_EXIT=$COMMIT_EXIT
        SBOM_RESULT="SBOM commit mislukt"
      else
        git push origin "HEAD:$BRANCH" 2>&1
        PUSH_EXIT=$?

        if [ "$PUSH_EXIT" -ne 0 ]; then
          SYFT_EXIT=$PUSH_EXIT
          SBOM_RESULT="SBOM push mislukt"
        else
          SBOM_RESULT="SBOM bijgewerkt en gepusht naar feature branch"
        fi
      fi
    fi
  fi
fi

echo ""
echo "Samenvatting:"
if [ "$SYFT_EXIT" -eq 0 ]; then
  echo "- SBOM: OK"
else
  echo "- SBOM: FAILED"
fi

echo "- resultaat: $SBOM_RESULT"
echo "- bestand: sbom/cyclonedx.json"
echo "- dependency fixes: niet uitgevoerd"

echo "--- END REPORTING ---"

exit 0
```

## n8n SSH-node: security scan

Maak een SSH-node aan na `Create a review6` voor staging en na `Create a review7` voor prd.

### Naam staging

```text
security scan uitvoeren
```

### Naam prd

```text
security scan uitvoeren1
```

### Command

```bash
./n8n/scripts/security-scan.sh
```

### CWD staging

```text
/home/ubuntu/onzeleermiddelen-staging
```

### CWD prd

```text
/home/ubuntu/onzeleermiddelen-prd
```

## n8n GitHub review-node: security scan

Maak na de security SSH-node een GitHub review-node aan.

### Naam staging

```text
Create security scan review
```

### Naam prd

```text
Create security scan review1
```

### Instellingen

```text
Resource: review
Event: comment
Pull Request Number:
={{ $('Github Trigger').item.json.body.number }}
```

### Body

```text
=Security scan:
{{ $json.stdout.replace(/\r/g, '').split('--- START REPORTING ---')[1].split('--- END REPORTING ---')[0].trim() }}
```

## n8n SSH-node: SBOM generatie

Maak na de security review-node een SSH-node aan.

### Naam staging

```text
SBOM genereren
```

### Naam prd

```text
SBOM genereren1
```

### Command

```bash
./n8n/scripts/sbom-generate.sh
```

### CWD staging

```text
/home/ubuntu/onzeleermiddelen-staging
```

### CWD prd

```text
/home/ubuntu/onzeleermiddelen-prd
```

## n8n GitHub review-node: SBOM

Maak na de SBOM SSH-node een GitHub review-node aan.

### Naam staging

```text
Create SBOM review
```

### Naam prd

```text
Create SBOM review1
```

### Instellingen

```text
Resource: review
Event: comment
Pull Request Number:
={{ $('Github Trigger').item.json.body.number }}
```

### Body

```text
=SBOM:
{{ $json.stdout.replace(/\r/g, '').split('--- START REPORTING ---')[1].split('--- END REPORTING ---')[0].trim() }}
```

## Gedrag bij bevindingen

Wanneer `pip-audit` kwetsbaarheden vindt of `gitleaks` mogelijke secrets vindt, wordt dit zichtbaar in de GitHub PR-comment. Er worden geen dependency updates uitgevoerd en er worden geen bestanden aangepast door de security scan.

Wanneer de SBOM gewijzigd is, wordt alleen `sbom/cyclonedx.json` gecommit naar de feature branch. Er wordt nooit direct naar `staging` of `prd` gepusht.

## Gedrag bij release naar prd

Bij een PR richting `prd` moet de security scan zichtbaar zijn in de PR-comment. Als er kwetsbaarheden of mogelijke secrets worden gevonden, moet dit worden opgelost of bewust worden geaccepteerd volgens Comply or Explain.

De SBOM moet aanwezig en actueel zijn als `sbom/cyclonedx.json`. Dit bestand kan op verzoek worden gedeeld als CycloneDX SBOM.
