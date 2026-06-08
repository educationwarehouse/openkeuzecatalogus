# CHANGELOG

## 08-06-2026

### Features

- Eerste database tabellen en basis van de backend
- Product-, methode-, aanbieder- en visiemodellen, inclusief effective-dated bron-tabellen en materialized views
- Auth-uitbreiding met lokaal accountbeheer, RBAC-koppeling en synchronisatie van identities bij registratie/wijzigingen
- Login via lokale accounts en Kennisnet Entree, inclusief Entree userinfo-normalisatie en login-logging
- Email-verificatie en wachtwoord-reset met vervaltermijn van 72 uur
- Centrale mailafhandeling met fake/SMTP-transport en queue-based verzending
- Applog-pipeline voor auth-events, inclusief deque/file-implementaties en persistente signal/evidence-tabellen

### Internals

- Seed-import vanuit oude JSON-bronnen
- Migratie-infrastructuur voor bootstrap en herstel
- Opbouw interne tooling zoals migrations, tests, CI
