# OL standby: IP-swap en n8n devdb-sync

Deze documentatie beschrijft hoe OL2 als standby-server wordt bijgehouden en hoe het dedicated IP handmatig wordt
omgezet van OL1 naar OL2.

> Deze documentatie bevat interne infrastructuurgegevens zoals IP-adressen en servernamen.
> Deel dit document alleen intern en zet het niet in een publieke repository.
> Secrets zoals SSH keys, tokens, `.env` waardes, pop URL's en delete URL's mogen nooit in deze documentatie worden
> opgeslagen.

## Situatie

| Server | Rol               | Private vSwitch IP |
|--------|-------------------|--------------------|
| OL1    | Actieve productie | `192.168.100.2`    |
| OL2    | Standby           | `192.168.100.1`    |

Dedicated public IP:

```text
46.225.195.186/29
```

vSwitch gateway:

```text
46.225.195.185
```

Website:

```text
https://openkeuzecatalogus.edwh.nl
```

> Let op: zet `46.225.195.186` nooit tegelijk op OL1 en OL2.  
> Haal het IP altijd eerst van de actieve server af voordat je het op de andere server toevoegt.

---

## 1. n8n devdb-sync

De n8n workflow zorgt ervoor dat OL2 regelmatig een recente databasekopie krijgt van OL1.

De workflow draait via SSH-commando’s. Hiervoor wordt key-based SSH gebruikt. De gebruikte SSH-user mag alleen de
benodigde devdb-commando’s uitvoeren.

### Workflow-overzicht

```text
Schedule Trigger
  -> SSH node naar OL1
  -> Edit Fields
  -> SSH node naar OL2
  -> IF node
      -> true: SSH node om delete URL aan te roepen
```

### Stap 1: Schedule Trigger

De workflow start automatisch via een n8n Schedule Trigger.

Deze trigger bepaalt hoe vaak OL2 wordt bijgewerkt met een recente databasekopie van OL1.

### Stap 2: SSH node naar OL1

De eerste SSH node draait op OL1 de devdb-commando’s.

Op OL1 wordt eerst een snapshot gemaakt:

```bash
~/.local/bin/edwh devdb.snapshot
```

Daarna wordt de snapshot gepusht:

```bash
~/.local/bin/edwh devdb.push
```

In n8n gebruiken we bewust het volledige pad:

```bash
~/.local/bin/edwh
```

Dit voorkomt problemen omdat n8n via SSH soms een andere `$PATH` heeft dan wanneer je handmatig bent ingelogd.

`devdb.push` geeft in de output een pop URL en meestal ook een delete URL terug.

### Stap 3: Edit Fields

De Edit Fields node haalt de benodigde waardes uit de output van de SSH node naar OL1.

Hier worden minimaal deze velden klaargezet:

```text
pop_url
delete_url
```

De `pop_url` wordt gebruikt om de snapshot op OL2 binnen te halen.

De `delete_url` wordt later gebruikt om de tijdelijke devdb-upload op te ruimen.

De pop URL en delete URL worden behandeld als geheim, omdat de devdb-snapshot databasegegevens kan bevatten.

### Stap 4: SSH node naar OL2

De tweede SSH node draait op OL2 de reset met de pop URL.

Op OL2 wordt de database vervangen door de snapshot van OL1:

```bash
~/.local/bin/edwh devdb.reset --yes --pop "<POP_URL>"
```

`printf 'yes\n'` is nodig omdat `devdb.reset` om bevestiging vraagt.

Let op: dit wist de bestaande database op OL2 en vult deze opnieuw met de snapshot van OL1.

### Stap 5: IF node

De IF node controleert of er een delete URL beschikbaar is.

Als er een delete URL is, gaat de workflow door naar de SSH node die de tijdelijke upload verwijdert.

Als er geen delete URL is, gaat de workflow naar de Do Nothing node.

### Stap 6: SSH node om delete URL aan te roepen

Als de delete URL beschikbaar is, wordt deze aangeroepen om de tijdelijke devdb-upload te verwijderen.

Voorbeeldcommando:

```bash
curl -fsS "<DELETE_URL>"
```

Dit is belangrijk zodat tijdelijke snapshots niet onnodig blijven bestaan.

### Stap 7: Do Nothing node

Als er geen delete URL beschikbaar is, doet de workflow niets extra’s.

De database-sync is dan al uitgevoerd, maar de tijdelijke upload kon niet automatisch worden verwijderd. Dit moet
zichtbaar blijven in de n8n-run, zodat dit eventueel handmatig gecontroleerd kan worden.

---

## 2. SSD-beveiligingsafspraken

Voor deze standby-opzet gelden de volgende beveiligingsafspraken:

- SSH-toegang vanuit n8n gebeurt alleen met key-based authenticatie.
- De n8n SSH-user heeft zo min mogelijk rechten en mag alleen de benodigde devdb-acties uitvoeren.
- De pop URL en delete URL uit `devdb.push` worden als geheim behandeld.
- Tijdelijke devdb-snapshots worden na een succesvolle restore verwijderd.
- n8n logt de workflow-uitvoering, inclusief snapshot, push, reset en delete-stap.
- Fouten in de workflow moeten zichtbaar zijn, zodat mislukte restores of niet-verwijderde snapshots opgevolgd kunnen
  worden.
- De website blijft via HTTPS bereikbaar via Traefik.
- Bestandssynchronisatie is nog buiten scope. Op dit moment wordt alleen de database via devdb gesynchroniseerd.

---

## 3. IP-swap van OL1 naar OL2

Gebruik deze stappen bij een failover of test-swap.

### Stap 1: IP verwijderen van OL1

Op **OL1**:

```bash
sudo ip addr del 46.225.195.186/29 dev enp0s31f6.4000
```

Controleer of het IP weg is:

```bash
ip -br addr | grep 46.225.195.186
```

Als er geen output komt, is het IP succesvol verwijderd van OL1.

### Stap 2: IP toevoegen op OL2

Op **OL2**:

```bash
sudo ip addr add 46.225.195.186/29 dev enp0s31f6.4000
```

Controleer of het IP actief is:

```bash
ip -br addr | grep 46.225.195.186
```

Verwachte output lijkt op:

```text
enp0s31f6.4000@eno1 UP 192.168.100.1/24 46.225.195.186/29
```

### Stap 3: Route testen op OL2

Op **OL2**:

```bash
ip route get 1.1.1.1 from 46.225.195.186
```

Verwacht dat de route via de vSwitch gaat:

```text
via 46.225.195.185 dev enp0s31f6.4000 table vswitch
```

### Stap 4: Website testen

Vanaf je laptop:

```bash
curl -I https://openkeuzecatalogus.edwh.nl
```

Of open de website in de browser:

```text
https://openkeuzecatalogus.edwh.nl
```

Als de website opent of een HTTP-response teruggeeft, is de swap gelukt.

---

## 4. Terug-swap van OL2 naar OL1

Gebruik deze stappen om het dedicated IP terug te zetten naar OL1.

### Stap 1: IP verwijderen van OL2

Op **OL2**:

```bash
sudo ip addr del 46.225.195.186/29 dev enp0s31f6.4000
```

Controleer of het IP weg is:

```bash
ip -br addr | grep 46.225.195.186
```

Geen output betekent dat het IP van OL2 af is.

### Stap 2: IP terugzetten op OL1

Op **OL1**:

```bash
sudo ip addr add 46.225.195.186/29 dev enp0s31f6.4000
```

Controleer of het IP actief is:

```bash
ip -br addr | grep 46.225.195.186
```

### Stap 3: Website testen

Vanaf je laptop:

```bash
curl -I https://openkeuzecatalogus.edwh.nl
```

Of open:

```text
https://openkeuzecatalogus.edwh.nl
```

---

## 5. Snelle checklist

### Voor de swap

Controleer op beide servers waar het IP actief is:

```bash
ip -br addr | grep 46.225.195.186
```

Het IP mag maar op één server tegelijk staan.

Controleer of OL2 bereikbaar is via de vSwitch:

```bash
ping -c 4 192.168.100.1
```

Vanaf OL2 kan OL1 getest worden met:

```bash
ping -c 4 192.168.100.2
```

### Tijdens de swap

1. IP verwijderen van actieve server.
2. Controleren dat het IP daar weg is.
3. IP toevoegen op standby-server.
4. Route testen.
5. Website testen.

### Na de swap

Controleer de website:

```bash
curl -I https://openkeuzecatalogus.edwh.nl
```

Controleer eventueel of Traefik nog luistert:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' | grep -iE 'traefik|proxy'
```

Goede output bevat:

```text
0.0.0.0:80->80/tcp
0.0.0.0:443->443/tcp
```

---

## 6. Rollback

Als OL2 na de swap niet goed werkt, zet het IP terug naar OL1.

Op **OL2**:

```bash
sudo ip addr del 46.225.195.186/29 dev enp0s31f6.4000
```

Op **OL1**:

```bash
sudo ip addr add 46.225.195.186/29 dev enp0s31f6.4000
```

Test daarna:

```bash
curl -I https://openkeuzecatalogus.edwh.nl
```

---

## 7. Belangrijkste aandachtspunten

- `46.225.195.186` mag nooit tegelijk op OL1 en OL2 staan.
- De devdb-sync vervangt alleen de database op OL2.
- Bestandssynchronisatie is nog niet meegenomen.
- Pop URL en delete URL uit `devdb.push` zijn gevoelig en mogen niet gedeeld worden.
- Controleer na elke sync of n8n geen foutmelding heeft gegeven.
- Controleer na elke swap of de website via HTTPS bereikbaar is.
