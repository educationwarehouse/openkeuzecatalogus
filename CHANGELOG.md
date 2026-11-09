# CHANGELOG

## 09-11-2026

### Features

#### Publieke website en vormgeving

- Nieuwe publieke homepage met uitleg over de Open Keuzecatalogus, het keuzeproces en het leermiddelenaanbod
- Interactieve tijdlijn toegevoegd met bijdragen uit blogs, pers, rapporten en sociale media, inclusief uitgebreide beschrijvingen
- Doorzoekbare FAQ en privacyverklaring toegevoegd
- Vernieuwde vormgeving voor catalogus, authenticatie en gedeelde navigatie, met aangepaste mobiele weergaven
- Laadindicatoren, paginaovergangen en animaties toegevoegd met ondersteuning voor verminderde beweging
- Toetsenbordbediening, focusbeheer en toegankelijkheid van selecties, filters en navigatie verbeterd

#### Catalogus, zoeken en vergelijken

- Product- en methodedetailpagina’s vernieuwd met afbeeldingen, aanbiedersinformatie, thematische inzichten en leesbare specificaties
- Vergelijkbare leermiddelen toegevoegd op basis van overlap in vakgebieden en niveaus, met een configureerbaar aantal aanbevelingen
- Meldmogelijkheid voor onjuiste catalogusgegevens toegevoegd aan detailpagina’s
- Catalogusoverzichten vernieuwd met compacte resultaatweergaven en duidelijkere vergelijkacties
- Vergelijkselectie uitgebreid met een gedeeld selectieoverzicht en acties vanuit overzichten en detailpagina’s
- Vergelijkpagina’s verbeterd met consistente weergave van kenmerken, visies en externe links
- Grote filterlijsten voorzien van zoeken en paginering, met behoud van geselecteerde opties
- Catalogusnavigatie verbeterd met herstel van zoekresultaten en filterinstellingen bij terugnavigeren
- Laadstatussen en foutmeldingen voor zoekresultaten verduidelijkt

#### Favorieten

- Persoonlijke favorieten toegevoegd voor producten en methoden
- Favorieten toevoegen en verwijderen vanuit detailpagina’s, met een eigen overzicht per leermiddeltype
- Recent opgeslagen favorieten beschikbaar gemaakt in een compact overzicht
- Historische namen beschikbaar gehouden voor favorieten waarvan het leermiddel niet meer in het actuele aanbod voorkomt

#### Backend voor Keuzecanvas en keuzeprocessen

- Gedeelde backend toegevoegd ter ondersteuning van de private Keuzecanvas-app
- Vakgroepen gekoppeld aan vestigingen, met eigen vakgebieden, niveaus en leerjaren
- Gegevensmodel en proceslogica toegevoegd voor keuzeprocessen per vakgroep en schooljaar, met een projectleider en aanpasbare selectiecriteria
- Ondersteuning toegevoegd voor zoeken en selecteren van leermiddelen binnen een keuzeproces
- Opslag en verwerking van voor- en nadelen toegevoegd per deelnemer en leermiddel, inclusief bewerken, dupliceren en verwijderen
- Koppelen van beoordelingen aan thema’s en opslaan van gezamenlijke themasamenvattingen ondersteund
- Gedeelde kaders en adviezen van besturen en scholen beschikbaar gemaakt voor onderliggende keuzeprocessen
- Prioriteren van themasamenvattingen en opslaan van de gezamenlijke visie toegevoegd aan de proceslogica
- Aanbevelingen toegevoegd voor passende producten en methoden op basis van de procescriteria en geselecteerde leermiddelen
- Zoeken, filteren en sorteren binnen visieaanbevelingen ondersteund, met behoud van de vastgelegde vakgebieden en niveaus
- Backendondersteuning toegevoegd voor export van de afgeronde visie naar PDF
- Archiveren en heropenen van keuzeprocessen ondersteund, met behoud van procesgegevens en audittrail
- Toegang tot keuzeprocessen ingericht via vakgroep-, vestigings-, school- en bestuurslidmaatschappen

#### AI-ondersteuning voor Keuzecanvas

- Optionele AI-verwerking toegevoegd voor het verbeteren van themasamenvattingen, met een gebruikslimiet per keuzeproces
- Backend voor een LLM-playground toegevoegd voor het vergelijken van modellen en prompts met dezelfde procescontext
- Opslaan van promptconcepten en activeren van een vaste model- en promptconfiguratie voor productie ondersteund
- Modelcatalogus uitgebreid met prijsinformatie en suggesties op basis van beschikbare modelgegevens
- OpenRouter-integratie voorzien van controles op gegevensverzameling en zero data retention

#### Gebruikers, beheer en rapportages

- Backendondersteuning toegevoegd voor CSV-import van gebruikers binnen een vestiging, met validatie vooraf en koppeling aan meerdere vakgroepen
- Optioneel aanmaken van ontbrekende vakgroepen tijdens gebruikersimport ondersteund
- Uitnodigingsafhandeling uitgebreid met herkenning van bestaande accounts en controle op dubbele directe lidmaatschappen
- Persistente instellingen toegevoegd voor gedeelde catalogusfunctionaliteit
- Tijdlijnbijdragen en definities van visiethema’s ondergebracht in persistente gegevensmodellen voor beheer
- Rapportagemodel toegevoegd voor productgebruik binnen keuzeprocessen per vestiging, inclusief vakgroepen, schooljaren en processtatussen

#### Kennisnet en importverwerking

- Import vanuit de gedeelde Kennisnet Edu-V-catalogus toegevoegd voor versies 1 en 2
- Gezamenlijke catalogusimport voor meerdere leveranciers toegevoegd, inclusief synchronisatie van afbeeldingen
- Lokale Kennisnet-cataloguscache toegevoegd voor doorzoeken en inspecteren van brongegevens
- Importrapportage uitgebreid met voortgang, leveranciersdekking en waarschuwingen met product- en leverancierscontext
- Nachtelijke Kennisnet-import toegevoegd via de achtergrondplanner
- Ondersteuning toegevoegd voor het herstellen van oudere methode-OLID’s met behoud van bestaande koppelingen

### Internals

#### Achtergrondverwerking en performance

- Gedeelde infrastructuur toegevoegd voor uitgestelde taken en het ophalen van taakresultaten
- Afzonderlijke PDF-worker toegevoegd voor asynchrone WeasyPrint-verwerking
- Periodieke achtergrondtaken ondergebracht in een aparte scheduler
- Detectie en foutregistratie toegevoegd voor verlaten achtergrondtaken en vastgelopen import-runs
- Cache-infrastructuur toegevoegd met Redis-, PostgreSQL- en geheugenbackends, inclusief ondersteuning voor gecombineerde backends
- Automatische cache-invalidatie ingericht op basis van geraadpleegde tabellen en records
- Catalogusfilteropties voorzien van caching en ondersteuning voor gelijktijdige cache-aanvragen
- Routemetingen toegevoegd voor verwerkingstijd, templaterendering en requestvarianten
- Backendondersteuning toegevoegd voor het rangschikken van cache-kandidaten op basis van veelgebruikte, kostbare routes
- Ontwikkelhulpmiddelen toegevoegd voor gedetailleerde performancemetingen, benchmarks en Locust-belastingstests

#### Kwaliteit, beveiliging en beheer

- Same-origincontrole toegevoegd voor aangepaste mutatieverzoeken vanuit de browser
- Gedeelde helpers toegevoegd voor instellingen, uploads, statische bestandshashes, rendering en beheergrids
- Playwright-dekking uitgebreid voor toegankelijkheid, catalogusgeschiedenis, navigatie, selecties, laadstatussen en de private Keuzecanvas-flows
- Testdekking uitgebreid voor keuzeprocessen, autorisatie, favorieten, aanbevelingen, AI, PDF-verwerking, caching en imports
- Sigrid-feedback op pull requests toegevoegd voor onderhoudbaarheid, afhankelijkheden en beveiliging
- Superset-dashboarddefinities toegevoegd voor gebruik, datakwaliteit, imports, prestaties en support
- Scripts toegevoegd voor back-up en herstel van bestanden en datastromen
- Architectuur-, performance-, deployment- en frontendvalidatiedocumentatie uitgebreid

## 10-09-2026

### Features

- Publieke product- en methodepagina’s uitgebreid met detailweergave, vergelijkfunctionaliteit en bewerkbare statische inhoud
- Zoekresultaten voorzien van configureerbare relevantiescores en beheerbare zoekrangschikking
- Magic-login via e-mail toegevoegd als alternatief voor Entree-login
- Leveranciersgebruikers uitgebreid met selfservice voor eigen leveranciers- en catalogusgegevens
- Auditlogviewer toegevoegd voor beheerders, inclusief filters en gekoppelde evidence

### Internals

- Error signals en error tickets toegevoegd met queue-based verwerking en notificatie-integratie
- Onderhoudsqueue toegevoegd voor e-mailverzending en periodieke refresh van materialized views
- Automatische security scans en CycloneDX SBOM-generatie toegevoegd aan de CI-workflow
- Publieke payloadtypes, database-tabellen en migratieondersteuning verder gestandaardiseerd

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
