# Docker Logger

Deze service verzamelt de logs van Docker containers op de server en schrijft deze weg naar lokale logbestanden in de map `./logs`.

De logger gebruikt de Docker socket om containers te vinden en hun output uit te lezen. De logs worden geroteerd op basis van de instellingen in `.env`, zoals maximale bestandsgrootte, aantal bestanden en maximale bewaartijd.

De service wordt beheerd met de EDWH tooling:

```bash
ew build
ew up
```
Voor leesbare logs staat JSON-output uit:
```
JSON=false
```
De logger sluit zichzelf uit met:
```
EXCLUDE=logger
```
Meer informatie over installatie, configuratie en veelgebruikte commands staat in de README van de edwh-docker-logger repository.
