# n8n

## Inleiding

Wij gebruiken n8n als automatiseringsplatform voor interne processen.  
n8n koppelt verschillende systemen aan elkaar en voert workflows automatisch uit op basis van triggers, zoals webhooks, GitHub-events of geplande taken.

n8n wordt onder andere gebruikt voor:

- het automatiseren van back-ups;
- het synchroniseren van repositories;
- het koppelen van GitHub en Forgejo;
- het uitvoeren of starten van interne workflows;
- het automatiseren van terugkerende taken.

Het uitgangspunt is dat n8n vooral de orkestratie doet. Waar mogelijk voert het doelsysteem zelf de daadwerkelijke taak uit.  
Bijvoorbeeld: n8n start een mirror-sync, maar Forgejo voert de repository-synchronisatie zelf uit.

## Documentatie

Specifieke workflows worden apart gedocumenteerd.

Voorbeelden:

- GitHub naar Forgejo mirror-sync
- CI workflow
- Back-up workflows

Per workflow beschrijven we minimaal:

- het doel van de workflow;
- de trigger;
- de betrokken systemen;
- de gebruikte credentials;
- de belangrijkste stappen;
- aandachtspunten rondom security en beheer.

---

# GitHub naar Forgejo mirror-sync

## Doel

GitHub wordt gebruikt als primaire Git-hosting. Forgejo wordt gebruikt als self-hosted backup/mirror-omgeving.

Bij iedere push naar GitHub moet automatisch een synchronisatie worden gestart naar de bijbehorende Forgejo mirror repository.

De flow is:

```text
GitHub Push Event
    ↓
n8n GitHub Trigger node
    ↓
n8n HTTP Request node
    ↓
Forgejo mirror-sync API
    ↓
Forgejo synchroniseert de mirror vanuit GitHub
```

n8n voert zelf geen Git-commando’s uit. Forgejo blijft verantwoordelijk voor de daadwerkelijke mirror-sync.

## Forgejo repository

De Forgejo repository moet als pull mirror zijn aangemaakt.

Voorbeeldstructuur:

```text
https://<FORGEJO_HOST>/<FORGEJO_OWNER>/<REPOSITORY_NAME>
```

Waarbij:

```text
<FORGEJO_HOST>       = Forgejo domein of hostnaam
<FORGEJO_OWNER>      = Forgejo user of organisatie
<REPOSITORY_NAME>    = naam van de mirror repository
```

Belangrijk: een Forgejo repository moet bij het aanmaken of migreren als mirror worden ingesteld. Een normale repository is niet automatisch een mirror.

## Forgejo API endpoint

De mirror-sync API-call heeft deze vorm:

```text
POST https://<FORGEJO_HOST>/api/v1/repos/<FORGEJO_OWNER>/<REPOSITORY_NAME>/mirror-sync
```

## Benodigde tokens

Er kunnen twee soorten tokens nodig zijn.

### Forgejo token voor n8n

Deze token wordt gebruikt door n8n om de Forgejo API aan te roepen.

De token moet worden aangemaakt onder een Forgejo-user die toegang heeft tot de mirror repository.

Benodigde rechten:

```text
repository: read + write
```

De HTTP-header moet exact zo worden ingesteld:

```text
Authorization: token <FORGEJO_TOKEN>
```

Let op: het woord `token` vóór de tokenwaarde is verplicht.

Correct:

```text
Authorization: token <FORGEJO_TOKEN>
```

Fout:

```text
Authorization: <FORGEJO_TOKEN>
```

### GitHub token voor Forgejo mirror

Als de GitHub repository private is, heeft Forgejo ook GitHub credentials nodig om de repository te kunnen pullen.

Deze credentials worden ingesteld in de Forgejo mirror-configuratie.

Gebruik bij voorkeur een aparte service-account of bot-account met minimale leesrechten op de benodigde repositories.

## n8n workflow

De minimale workflow bestaat uit twee nodes:

```text
GitHub Trigger
    ↓
HTTP Request
```

## Node 1: GitHub Trigger

Gebruik de node:

```text
GitHub Trigger
```

Instellingen:

```text
Event: Push
Repository owner: <GITHUB_OWNER>
Repository name: <REPOSITORY_NAME>
```

Deze node start de workflow automatisch zodra er een push-event plaatsvindt op GitHub.

## Node 2: HTTP Request

Gebruik de node:

```text
HTTP Request
```

Instellingen:

```text
Method: POST
URL: https://<FORGEJO_HOST>/api/v1/repos/<FORGEJO_OWNER>/<REPOSITORY_NAME>/mirror-sync
```

Headers:

```text
Authorization: token <FORGEJO_TOKEN>
Accept: application/json
```

Sla de Forgejo-token op als n8n credential. Zet de token niet direct zichtbaar in de node-configuratie als platte tekst.

## Dynamische repositorynaam

Als de GitHub repository exact dezelfde naam heeft als de Forgejo mirror repository, kan de repo-naam dynamisch uit de GitHub Trigger payload worden gehaald.

Voorbeeld:

```text
https://<FORGEJO_HOST>/api/v1/repos/<FORGEJO_OWNER>/{{$json.repository.name}}/mirror-sync
```

Gebruik dit alleen wanneer de naamgeving tussen GitHub en Forgejo consistent is.

Als repositorynamen kunnen afwijken, gebruik dan een expliciete mapping in n8n.

## Branches en tags

Er hoeft geen specifieke branch aan n8n te worden meegegeven.

Bij een mirror-sync haalt Forgejo de repository-status op uit GitHub. Branches, tags en commits worden door Forgejo zelf bijgewerkt.

Voor een backup-oplossing is het advies om niet op specifieke branches te filteren, zodat alle relevante Git-data wordt meegenomen.

## Meerdere pushes tegelijk

Wanneer meerdere mensen kort na elkaar pushen, kan n8n meerdere workflow executions starten.

Aanbevolen setup:

```text
n8n queue mode
worker concurrency = 1
```

Hierdoor worden mirror-sync requests netjes één voor één verwerkt.

Dit voorkomt dat meerdere syncs tegelijk tegen dezelfde Forgejo mirror worden gestart.

## Testen

### Forgejo API toegang testen

Gebruik een GET request:

```text
GET https://<FORGEJO_HOST>/api/v1/repos/<FORGEJO_OWNER>/<REPOSITORY_NAME>
```

Header:

```text
Authorization: token <FORGEJO_TOKEN>
```

Verwachte uitkomst:

```text
200 OK
```

Als dit een 404 geeft, kan dat betekenen dat:

```text
- De repository niet bestaat onder deze owner/repo naam.
- De repository private is en de token-user geen toegang heeft.
- De Authorization header niet goed is ingesteld.
- De token onder de verkeerde user is aangemaakt.
```

### Mirror-sync handmatig testen

Gebruik een POST request:

```text
POST https://<FORGEJO_HOST>/api/v1/repos/<FORGEJO_OWNER>/<REPOSITORY_NAME>/mirror-sync
```

Header:

```text
Authorization: token <FORGEJO_TOKEN>
```

Verwachte uitkomst:

```text
De mirror-sync wordt gestart.
```

### Volledige flow testen

1. Zet de n8n workflow op active.
2. Push een testcommit naar GitHub.
3. Controleer de execution in n8n.
4. Controleer in Forgejo of de commit is binnengekomen.
5. Verwijder testcommits of testbranches indien nodig volgens het interne Git-proces.

## Veelvoorkomende fouten

### 404: The target couldn't be found

Mogelijke oorzaken:

```text
- De repository bestaat niet onder deze owner/repo naam.
- De repository is private en de token-user heeft geen toegang.
- De Authorization header is fout ingesteld.
- De repository is geen echte Forgejo pull mirror.
- De token is aangemaakt onder de verkeerde Forgejo-user.
```

Controleer vooral of de header zo staat:

```text
Authorization: token <FORGEJO_TOKEN>
```

Niet:

```text
Authorization: <FORGEJO_TOKEN>
```

### Header name must be a valid HTTP token

Dit betekent dat de header name verkeerd is ingevuld.

Correct:

```text
Name: Authorization
Value: token <FORGEJO_TOKEN>
```

Fout:

```text
Name: Forgejo token
Value: <FORGEJO_TOKEN>
```

## Samenvatting

De uiteindelijke flow:

```text
GitHub push
    ↓
n8n GitHub Trigger
    ↓
HTTP Request:
POST https://<FORGEJO_HOST>/api/v1/repos/<FORGEJO_OWNER>/<REPOSITORY_NAME>/mirror-sync
Authorization: token <FORGEJO_TOKEN>
    ↓
Forgejo synchroniseert de mirror vanuit GitHub
```

Deze setup zorgt ervoor dat elke push naar GitHub automatisch wordt meegenomen naar Forgejo, zonder dat n8n zelf Git-commando’s hoeft uit te voeren.

---

# CI Workflow Forgejo / GitHub in n8n

## Doel

Deze n8n-workflow automatiseert het testen van pull requests voor een GitHub repository.

Wanneer er een nieuwe pull request wordt geopend, controleert de workflow:

1. of het event een geopende pull request is;
2. of de pull request vanaf een toegestane branch komt;
3. of de branch `staging` of `prd` is;
4. welke servermap gebruikt moet worden;
5. of de code succesvol getest en gelint kan worden;
6. waarna de resultaten als review/comment op de pull request worden geplaatst.

De workflow draait de tests en lintchecks op een externe server via SSH.

## Globale flow

De workflow bestaat grofweg uit deze stappen:

```text
GitHub Trigger
  ↓
Controle: is de pull request geopend?
  ↓
Controle: komt de PR vanaf staging of prd?
  ↓
Switch: staging of prd
  ↓
Git pull op de juiste servermap
  ↓
Pytest uitvoeren
  ↓
Test-output verwerken
  ↓
Review/comment plaatsen op de pull request
  ↓
Linttest uitvoeren
  ↓
Lint-output plaatsen als review/comment
```

## Trigger

De workflow start met de node:

```text
GitHub Trigger
```

Deze node luistert naar het event:

```text
pull_request
```

Voor de repository:

```text
<GITHUB_OWNER>/<REPOSITORY_NAME>
```

Zodra er een pull request-event binnenkomt, wordt de workflow gestart.

## Controle op pull request actie

Na de trigger komt een `If` node.

Deze node controleert of de actie van de pull request gelijk is aan:

```text
opened
```

De gebruikte waarde is:

```text
$json.body.action
```

Alleen wanneer de pull request net geopend is, gaat de workflow verder.

Wanneer het event geen geopende pull request is, stopt de workflow via een `No Operation` node.

## Controle op toegestane branches

Daarna controleert de workflow vanaf welke branch de pull request komt.

De workflow kijkt naar:

```text
$json.body.pull_request.head.ref
```

Toegestane branches zijn:

```text
staging
prd
```

Als de pull request niet vanaf `staging` of `prd` komt, stopt de workflow via een `No Operation` node.

## Branch-routering met Switch

Na de branchcontrole komt een `Switch` node.

Deze node bepaalt welk pad de workflow moet volgen:

```text
staging → staging-pad
prd     → prd-pad
```

De switch kijkt opnieuw naar:

```text
$json.body.pull_request.head.ref
```

Op basis daarvan kiest de workflow de juiste servermap en testnodes.

---

## Staging-pad

### Code ophalen op staging

Wanneer de pull request vanaf `staging` komt, wordt via SSH de staging-code bijgewerkt.

Voorbeeldcommando:

```bash
git stash && git pull
```

Working directory:

```text
<STAGING_SERVER_PATH>
```

Hiermee wordt de staging-code op de server bijgewerkt voordat de tests worden uitgevoerd.

### Tests uitvoeren op staging

Na het ophalen van de code voert de workflow de tests uit.

Voorbeeldcommando:

```bash
. ./venv/bin/activate && <TEST_COMMAND>
```

Working directory:

```text
<STAGING_SERVER_PATH>
```

Hierbij wordt eerst de Python virtual environment geactiveerd. Daarna wordt het testcommando uitgevoerd.

### Test-output verwerken

Na de test wordt de relevante output verwerkt.

De workflow maakt een veld aan:

```text
test_report
```

De waarde wordt uit `stdout` gehaald. De workflow pakt alleen het gedeelte tussen:

```text
--- START REPORTING ---
```

en:

```text
--- END REPORTING ---
```

De gebruikte expressie is:

```js
$json.stdout.replace(/\r/g, '').split('--- START REPORTING ---')[1].split('--- END REPORTING ---')[0].trim()
```

Hierdoor wordt alleen het relevante testverslag gebruikt voor de review op de pull request.

### Pytest-review plaatsen

Daarna maakt de workflow een comment/review aan op de pull request.

De pull request wordt opgehaald via:

```text
$('Github Trigger').item.json.body.number
```

De body van de review bevat:

```text
Pytest:
{{ $json.test_report }}
```

Hiermee komt de testoutput direct als comment op de pull request terecht.

### Linttest uitvoeren op staging

Na de pytest-review wordt via SSH de lintcheck uitgevoerd.

Voorbeeldcommando:

```bash
. ./venv/bin/activate && <INSTALL_COMMAND> && <LINT_COMMAND>
```

Working directory:

```text
<STAGING_SERVER_PATH>
```

Deze stap installeert of initialiseert het project waar nodig en voert daarna de lintcheck uit.

### Lint-review plaatsen

Na de linttest plaatst de workflow de lintoutput als review/comment op de pull request.

De body van de review is:

```text
Linttest:
{{ $json.stdout }}
```

Daarmee wordt de lintoutput uit de SSH node toegevoegd aan de pull request.

---

## PRD-pad

### Code ophalen op PRD

Wanneer de pull request vanaf `prd` komt, wordt via SSH de PRD-code bijgewerkt.

Voorbeeldcommando:

```bash
git stash && git pull
```

Working directory:

```text
<PRD_SERVER_PATH>
```

Hiermee wordt de PRD-code op de server bijgewerkt.

### Tests uitvoeren op PRD

Daarna voert de workflow de tests uit.

Voorbeeldcommando:

```bash
. ./venv/bin/activate && <TEST_COMMAND>
```

Working directory:

```text
<PRD_SERVER_PATH>
```

Net als bij staging wordt eerst de virtual environment geactiveerd en daarna het testcommando uitgevoerd.

### Test-output verwerken

Na de test wordt de relevante output verwerkt.

De workflow maakt een veld aan:

```text
test_report
```

Ook hier wordt alleen het gedeelte uit `stdout` gehaald tussen:

```text
--- START REPORTING ---
```

en:

```text
--- END REPORTING ---
```

De rest van de output wordt niet meegenomen in deze pytest-review.

### Pytest-review plaatsen

Daarna plaatst de workflow de testoutput op de pull request.

De body van de review gebruikt:

```text
Pytest:
{{ $json.test_report }}
```

De review wordt geplaatst op het pull requestnummer uit de oorspronkelijke trigger:

```text
$('Github Trigger').item.json.body.number
```

### Linttest uitvoeren op PRD

Na de pytest-review voert de workflow de lintcheck uit.

Voorbeeldcommando:

```bash
. ./venv/bin/activate && <INSTALL_COMMAND> && <LINT_COMMAND>
```

Working directory:

```text
<PRD_SERVER_PATH>
```

### Lint-review plaatsen

Na de linttest maakt de workflow een review/comment aan op de pull request.

De body is:

```text
Linttest:
{{ $json.stdout }}
```

Daarmee wordt de lintoutput toegevoegd aan de pull request.

---

## Einde van de workflow

Na de laatste review/comment eindigt de workflow in een `No Operation` node.

Deze node doet inhoudelijk niets en markeert alleen het einde van de flow.

## Overzicht van de belangrijkste nodes

| Node | Functie |
|---|---|
| GitHub Trigger | Start de workflow bij pull request-events |
| If | Controleert of de PR-actie `opened` is |
| Branchcontrole | Controleert of de branch `staging` of `prd` is |
| Switch | Stuurt de flow naar het staging- of PRD-pad |
| SSH: git pull staging | Haalt de nieuwste staging-code op |
| SSH: git pull PRD | Haalt de nieuwste PRD-code op |
| SSH: tests staging | Draait tests op staging |
| SSH: tests PRD | Draait tests op PRD |
| Edit Fields staging | Haalt het relevante pytest-rapport uit staging-output |
| Edit Fields PRD | Haalt het relevante pytest-rapport uit PRD-output |
| GitHub review staging tests | Plaatst pytest-resultaat voor staging |
| GitHub review PRD tests | Plaatst pytest-resultaat voor PRD |
| SSH: lint staging | Draait lintcheck op staging |
| SSH: lint PRD | Draait lintcheck op PRD |
| GitHub review staging lint | Plaatst lintresultaat voor staging |
| GitHub review PRD lint | Plaatst lintresultaat voor PRD |
| No Operation nodes | Stoppen de workflow op gecontroleerde plekken |

## Belangrijke output

De workflow plaatst twee soorten output terug op de pull request.

### Pytest-output

De pytest-output wordt niet volledig geplaatst. Alleen het rapport tussen deze markers wordt gebruikt:

```text
--- START REPORTING ---
--- END REPORTING ---
```

Deze output wordt opgeslagen als:

```text
test_report
```

en daarna als review/comment op de pull request geplaatst.

### Lint-output

De lint-output wordt direct vanuit `stdout` geplaatst:

```text
{{ $json.stdout }}
```

Deze output wordt als aparte review/comment op de pull request gezet.

## Samenvatting

Deze workflow automatiseert de CI-controle voor pull requests.

Bij een geopende pull request vanaf `staging` of `prd` wordt op de juiste servermap de code bijgewerkt, worden de tests uitgevoerd, wordt de relevante testoutput uitgelezen en wordt deze als review/comment op de pull request geplaatst.

Daarna wordt ook de lintcheck uitgevoerd en wordt de lintoutput apart toegevoegd aan dezelfde pull request.

Pull requests vanaf andere branches of pull request-events die niet `opened` zijn, worden genegeerd via een `No Operation` node.
