# KeeShare gebruiken met de gedeelde Passbolt-export

## Doel

De credentials uit Passbolt worden automatisch geëxporteerd naar een gedeelde KeePass-database:

`edwh-env.kdbx`

Deze database staat op de gedeelde Samba-server en is via Tailscale bereikbaar.

Je hoeft KeeShare maar **één keer** in te stellen. Daarna worden wijzigingen in de gedeelde database automatisch door KeePassXC ingelezen.

We gebruiken KeeShare in de modus **Import**, zodat de gedeelde credentials alleen worden ingelezen en niet vanuit de persoonlijke database teruggeschreven worden.

---

## Benodigd

Zorg dat je het volgende hebt:

- KeePassXC
- Tailscale en verbinding met het EDWH Tailscale-netwerk
- Samba-gebruikersnaam en wachtwoord
- Wachtwoord van `edwh-env.kdbx`

---

# 1. Verbind met de Samba-share

## macOS

Open **Finder** en gebruik:

`Cmd + K`

Vul in:

`smb://<TAILSCALE-IP-OF-HOSTNAME>/keepass`

Bijvoorbeeld:

`smb://utils-edwh/keepass`

Log in met de Samba-gebruikersnaam en het Samba-wachtwoord.

De share verschijnt daarna in Finder onder **Locaties**.

Het KDBX-bestand staat vervolgens bijvoorbeeld op:

`/Volumes/keepass/edwh-env.kdbx`

---

## Linux

### Optie 1: via de bestandsbeheerder

Bij de meeste Linux-distributies, zoals Ubuntu en Linux Mint, kun je de Samba-share rechtstreeks vanuit de bestandsbeheerder openen.

Open bijvoorbeeld **Files**, **Nemo** of **Dolphin**.

Kies:

**Other Locations / Andere locaties**

Vul bij **Connect to Server** in:

`smb://<TAILSCALE-IP-OF-HOSTNAME>/keepass`

Bijvoorbeeld:

`smb://utils-edwh/keepass`

Log vervolgens in met de Samba-gebruikersnaam en het Samba-wachtwoord.

De share verschijnt daarna als netwerkschijf in de bestandsbeheerder.

Je kunt vervolgens `edwh-env.kdbx` selecteren vanuit KeePassXC.

---

### Optie 2: Samba-share handmatig mounten

Installeer indien nodig ondersteuning voor CIFS:

```bash
sudo apt install cifs-utils
```

Maak een mountpunt:

```bash
sudo mkdir -p /mnt/keepass
```

Mount vervolgens de Samba-share:

```bash
sudo mount -t cifs //<TAILSCALE-IP-OF-HOSTNAME>/keepass /mnt/keepass -o username=<SAMBA-GEBRUIKER>
```

Je wordt gevraagd om het Samba-wachtwoord.

Controleer daarna:

```bash
ls /mnt/keepass
```

Hier zou onder andere moeten staan:

```text
edwh-env.kdbx
```

Het pad voor KeeShare is dan:

`/mnt/keepass/edwh-env.kdbx`

---

# 2. Open je eigen KeePassXC-database

Open KeePassXC en open je normale persoonlijke database.

De gedeelde EDWH-database vervangt je persoonlijke database dus **niet**.

Je database kan bijvoorbeeld deze structuur krijgen:

- Persoonlijke wachtwoorden
- Eigen servers
- EDWH ENV credentials ← gedeeld via KeeShare

---

# 3. KeeShare inschakelen

Ga in KeePassXC naar:

**Tools → Settings → KeeShare**

Schakel in:

**Allow import**

`Allow export` is niet nodig.

Wij gebruiken alleen **Import**, omdat de centrale database door EDWH wordt beheerd.

Collega's hoeven wijzigingen niet terug te schrijven naar de gedeelde database.

---

# 4. Maak een gedeelde groep

Maak in je persoonlijke KeePassXC-database een nieuwe groep, bijvoorbeeld:

`EDWH ENV credentials`

Rechtsklik op deze groep en kies:

**Edit Group**

Ga vervolgens naar:

**KeeShare**

---

# 5. Configureer KeeShare

Kies als Sharing mode:

**Import**

Selecteer vervolgens het gedeelde KDBX-bestand.

### macOS

Gebruik bijvoorbeeld:

`/Volumes/keepass/edwh-env.kdbx`

### Linux

Bij een handmatige mount gebruik je bijvoorbeeld:

`/mnt/keepass/edwh-env.kdbx`

Wanneer je de Samba-share via de grafische bestandsbeheerder hebt geopend, kun je het bestand via **Browse** selecteren.

Vul vervolgens het wachtwoord van de gedeelde KeePass-database in.

Sla de instellingen op.

De groep krijgt in KeePassXC een KeeShare/cloud-icoon.

---

# 6. Klaar

De situatie is nu:

`Passbolt → KDBX-export → Samba → KeeShare → jouw KeePassXC`

Wanneer de centrale:

`edwh-env.kdbx`

wordt bijgewerkt, kan KeeShare de wijzigingen opnieuw in je persoonlijke KeePassXC-database inlezen.

Je hoeft de Passbolt-export dus niet iedere keer handmatig te importeren.

---

# Belangrijk

Gebruik de gedeelde KeeShare-groep alleen om credentials te bekijken.

Pas gedeelde credentials niet lokaal aan. **Passbolt is de bron van de credentials.**

De gedeelde KDBX-database wordt opnieuw opgebouwd vanuit Passbolt, waardoor lokale wijzigingen niet bedoeld zijn om behouden te blijven.

---

# Problemen oplossen

## Geen verbinding met de Samba-share

Controleer eerst of Tailscale verbonden is.

Op Linux:

```bash
tailscale status
```

Controleer eventueel of de server bereikbaar is:

```bash
tailscale ping <TAILSCALE-IP-OF-HOSTNAME>
```

---

## macOS

Controleer in Finder onder:

**Locaties → keepass**

of de share nog verbonden is.

Het bestand hoort bijvoorbeeld bereikbaar te zijn via:

`/Volumes/keepass/edwh-env.kdbx`

---

## Linux

Bij een handmatige mount:

```bash
ls /mnt/keepass
```

Hier moet staan:

```text
edwh-env.kdbx
```

Controleer eventueel of de mount actief is:

```bash
mount | grep keepass
```

Als de share niet meer gemount is, mount hem opnieuw:

```bash
sudo mount -t cifs //<TAILSCALE-IP-OF-HOSTNAME>/keepass /mnt/keepass -o username=<SAMBA-GEBRUIKER>
```

---

## KeeShare werkt niet meer

Controleer:

1. Of Tailscale verbonden is.
2. Of de Samba-share bereikbaar is.
3. Of `edwh-env.kdbx` nog aanwezig is.
4. Of het pad dat bij KeeShare ingesteld staat nog klopt.
5. Open KeePassXC indien nodig opnieuw.

De gedeelde Samba-locatie hoort voor normale gebruikers alleen gebruikt te worden om de centrale database te lezen. Passbolt en de automatische export blijven de bron voor wijzigingen.
