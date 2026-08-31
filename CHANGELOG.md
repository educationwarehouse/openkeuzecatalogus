# CHANGELOG

## 31-08-2026

### Features

- Publiek catalogusoverzicht voor producten en methoden met zoeken, dynamische filters, sortering, paginering en verschillende weergaven
- JSON-import in de beheeromgeving met sjabloondownload, validatie, preview en verwerking
- Edu-V-importer uitgebreid met ondersteuning voor catalogusversies 1.1.0 en 2.0.0, inclusief product-, methode- en afbeeldingsverwerking
- Gebruikers uitnodigen en koppelen aan organisaties en aanbieders verder uitgewerkt

### Internals

- Queue-verwerking, scraper-imports en import-runrapportage verder gestandaardiseerd en uitgebreid
- S3/MinIO-gebaseerde afbeeldingsopslag toegevoegd met lokale testimplementatie
- Databasecontexten, catalogusrapportages en datakwaliteitsrapporten toegevoegd
- Architectuur-, deployment-, integratie- en ontwikkel-documentatie uitgebreid

## 20-07-2026

### Features

- Organisatiemodel voor besturen, scholen en vestigingen, inclusief onderlinge relaties en toegangsbeheer
- Uitgebreid aanbiedermodel met e-maildomeinen en Edu-V-endpointconfiguratie
- Automatische rol- en lidmaatschapstoekenning voor aanbieders en organisaties op basis van het e-maildomein van gebruikers
- Edu-V-importer voor aanbieders, uitgevoerd via de achtergrondqueue, met registratie van importresultaten, statistieken en validatiefouten
- Stabiele OLID-identificaties voor geïmporteerde aanbieders, producten, methoden en visies
- Uitgebreid productdatamodel met aanvullende metadata, zoals beschikbaarheid, licentie- en apparaatondersteuning

### Internals

- Effectieve-datering uitgebreid met organisatie- en relatiegegevens, en verbeterde verwerking van bronprioriteiten
- RBAC- en autorisatielaag losgekoppeld van py4web en centraal ingericht voor webverzoeken, achtergrondtaken en migraties
- Persistente rapportage voor import-runs en verbeterde auditlogging
- Gedeelde py4web-runtime, healthcheck en gecontroleerde container-restart ingericht
- Database-, migratie-, test-, monitoring- en deploymentdocumentatie uitgebreid

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
