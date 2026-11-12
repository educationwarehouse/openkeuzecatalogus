# Documentatie: Gatus monitoring

## Doel

Gatus wordt gebruikt als self-hosted monitoringtool voor het controleren van websites, API's en health-check endpoints. De tool voert periodiek ingestelde checks uit en toont de status hiervan in een webdashboard.

Gatus draait als Docker-container en wordt geconfigureerd via een aparte `config.yml`.

## Onderdelen

De inrichting bestaat uit de volgende onderdelen:

| Onderdeel            | Functie                                                        |
| -------------------- | -------------------------------------------------------------- |
| `gatus`              | De applicatie die endpoints controleert en het dashboard toont |
| `gatus-postgres`     | Database waarin Gatus data kan opslaan                         |
| `docker-compose.yml` | Definieert de containers, netwerken, volumes en Traefik-labels |
| `config.yml`         | Bevat de monitoringconfiguratie                                |
| `tasks.py`           | Bevat projecttaken om de Docker Compose setup te beheren       |

## Werking

Gatus leest bij het opstarten de configuratie uit `config.yml`. In deze configuratie staan één of meerdere `endpoints`.

Een endpoint is een URL die periodiek gecontroleerd wordt. Voor ieder endpoint wordt ingesteld:

- welke URL gecontroleerd wordt;
- hoe vaak de controle uitgevoerd wordt;
- aan welke voorwaarden de response moet voldoen.

Wanneer een endpoint niet voldoet aan de ingestelde voorwaarden, markeert Gatus deze als ongezond.

Voorbeelden van voorwaarden zijn:

- de HTTP-status moet `200` zijn;
- de response time moet lager zijn dan een ingestelde waarde;
- het SSL-certificaat moet nog minimaal een bepaalde tijd geldig zijn.

## Configuratiebestand

De configuratie staat in:

```text
config.yml
```

In `docker-compose.yml` wordt dit bestand in de container gemount:

```yaml
volumes:
    - ./config.yml:/config/config.yml:ro
```

De Gatus-container gebruikt dit bestand via:

```yaml
environment:
    GATUS_CONFIG_PATH: /config/config.yml
```

## Basisconfiguratie

Een minimale configuratie bevat minimaal één endpoint.

```yaml
endpoints:
    - name: example
      group: test
      url: "https://example.org"
      interval: 1m
      conditions:
          - "[STATUS] == 200"
```

Zonder endpoint start Gatus niet op. De foutmelding is dan meestal:

```text
configuration should contain at least one endpoint or suite
```

## Endpoint toevoegen

Een nieuwe check voeg je toe door een extra item onder `endpoints:` te plaatsen.

Voorbeeld:

```yaml
endpoints:
    - name: website-health
      group: websites
      url: "https://example.nl/health"
      interval: 1m
      conditions:
          - "[STATUS] == 200"
          - "[RESPONSE_TIME] < 1000"
```

### Velden

| Veld         | Uitleg                                       |
| ------------ | -------------------------------------------- |
| `name`       | Naam van de check in het Gatus-dashboard     |
| `group`      | Groep waarin de check getoond wordt          |
| `url`        | URL die gecontroleerd wordt                  |
| `interval`   | Frequentie waarmee Gatus de check uitvoert   |
| `conditions` | Voorwaarden waaraan de response moet voldoen |

## Voorbeelden van checks

### Website controleren

```yaml
- name: website
  group: websites
  url: "https://example.nl"
  interval: 1m
  conditions:
      - "[STATUS] == 200"
```

### Health endpoint controleren

```yaml
- name: website-health
  group: websites
  url: "https://example.nl/health"
  interval: 1m
  conditions:
      - "[STATUS] == 200"
      - "[RESPONSE_TIME] < 1000"
```

### API controleren

```yaml
- name: api-health
  group: apis
  url: "https://api.example.nl/health"
  interval: 1m
  conditions:
      - "[STATUS] == 200"
      - "[RESPONSE_TIME] < 1500"
```

### SSL-certificaat controleren

```yaml
- name: website-ssl
  group: certificates
  url: "https://example.nl"
  interval: 6h
  conditions:
      - "[STATUS] == 200"
      - "[CERTIFICATE_EXPIRATION] > 168h"
```

## Wijzigingen toepassen

Na een wijziging in `config.yml` moet Gatus opnieuw gestart worden.

```bash
docker compose restart gatus
```

Controleer daarna of Gatus goed gestart is:

```bash
docker compose logs -f gatus
```

## Beheercommando's

Containers starten:

```bash
docker compose up -d
```

Containers stoppen:

```bash
docker compose down
```

Status bekijken:

```bash
docker compose ps
```

Logs bekijken:

```bash
docker compose logs -f gatus
```

## Aandachtspunten

- Gatus heeft minimaal één endpoint nodig om te starten.
- Na wijzigingen in `config.yml` moet de Gatus-container opnieuw gestart worden.
- Gebruik duidelijke namen en groepen voor endpoints.
- Gebruik voor health checks bij voorkeur specifieke `/health` endpoints in plaats van alleen de homepage.
- Controleer na iedere wijziging de logs om configuratiefouten snel te vinden.
