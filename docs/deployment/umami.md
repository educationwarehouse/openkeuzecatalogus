# Documentatie: Umami

## Doel

Umami is een self-hosted analytics tool voor het meten van pageviews en bezoekersstatistieken van websites.

De applicatie draait als Docker-container en gebruikt PostgreSQL als database. De configuratie gebeurt via `docker-compose.yml`.

## Onderdelen

De inrichting bestaat uit de volgende onderdelen:

| Onderdeel            | Functie                                                               |
| -------------------- | --------------------------------------------------------------------- |
| `umami`              | De applicatie met dashboard en trackingfunctionaliteit                |
| `umami-postgres`     | Database voor opslag van Umami-data                                   |
| `docker-compose.yml` | Definieert de containers, netwerken, volumes en environment variables |
| `tasks.py`           | Bevat projecttaken om de Docker Compose setup te beheren              |

## Werking

Umami verzamelt statistieken via een tracking script dat op een website wordt geplaatst.

Wanneer een bezoeker de website opent, stuurt het script data naar Umami. Deze data wordt vervolgens opgeslagen in PostgreSQL en zichtbaar gemaakt in het Umami-dashboard.

Voorbeelden van gegevens die Umami kan tonen:

- pageviews
- bezoekers
- referrers
- gebruikte pagina's
- events

## Configuratie

Umami gebruikt geen losse `config.yml`.
De configuratie staat in `docker-compose.yml` via environment variables.

Belangrijke variabelen zijn:

- `DATABASE_URL`: verbinding naar PostgreSQL
- `APP_SECRET`: geheime sleutel voor authenticatie en sessies

Voorbeeld:

```yaml
environment:
    DATABASE_URL: postgresql://${UMAMI_POSTGRES_USER}:${UMAMI_POSTGRES_PASSWORD}@umami-postgres:5432/${UMAMI_POSTGRES_DB}
    APP_SECRET: ${UMAMI_APP_SECRET}
```

## Starten

Containers starten:

```bash
docker compose up -d
```

Status bekijken:

```bash
docker compose ps
```

Logs bekijken:

```bash
docker compose logs -f umami
```

## Inloggen

Na een nieuwe installatie is de standaard login:

```text
username: admin
password: umami
```

Verander dit wachtwoord direct na de eerste login.

## Website toevoegen

Een website wordt toegevoegd via het Umami-dashboard.

Stappen:

1. Log in op Umami.
2. Ga naar **Settings**.
3. Open **Websites**.
4. Klik op **Add website**.
5. Vul de naam en het domein van de website in.
6. Sla de website op.

Na het toevoegen maakt Umami een tracking script beschikbaar.

## Tracking script plaatsen

Na het aanmaken van een website geeft Umami een script terug dat op de website geplaatst moet worden.

Voorbeeld:

```html
<script defer src="https://umami.example.nl/script.js" data-website-id="WEBSITE_ID"></script>
```

Dit script wordt meestal in de `<head>` van de website geplaatst.

## Wijzigingen toepassen

Na wijzigingen in `docker-compose.yml`:

```bash
docker compose down
docker compose up -d
```

Controleer daarna de logs:

```bash
docker compose logs -f umami
```

## Aandachtspunten

- `POSTGRES_PASSWORD` en de waarde in `DATABASE_URL` moeten overeenkomen.
- `APP_SECRET` moet een vaste, willekeurige string zijn.
- Verander het standaard admin-wachtwoord direct na de eerste login.
- Voor iedere website moet het juiste tracking script geplaatst worden.
