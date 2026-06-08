V-switch configureren en instellen

Noodzakelijke componenten:

    VLAN-interface: enp0s31f6.4000
    Private vSwitch-IP: 192.168.100.2/24
    Public vSwitch-IP: 46.225.195.186/29
    vSwitch gateway: 46.225.195.185
    Routing table: vswitch
    Policy rule voor verkeer vanaf 46.225.195.186
    CONNMARK-regels voor HTTP/HTTPS-retourverkeer
    Docker bridge: vooraf controleren
    Traefik container-IP: vooraf controleren

Niet-noodzakelijke brede routingregels worden niet gebruikt.

Specifiek niet gebruiken:

    brede bridge-route via iif br-... table vswitch
    generieke packet mark-regels voor al het Docker-verkeer

Validatie na instellen:

    ip addr show dev enp0s31f6.4000
    ip rule show
    ip route show table vswitch
    controle actueel Traefik container-IP
    controle CONNMARK counters
    externe HTTP/HTTPS-test op het publieke vSwitch-IP

Documentbeheer:

    Eigenaar:
    Versie:
    Datum:
    Laatste wijziging:
    Goedgekeurd door:

Hetzner vSwitch IP + Docker/Traefik policy routing fix
Doel

Deze configuratie maakt een VLAN-interface aan op de bestaande netwerkkaart enp0s31f6 voor de Hetzner vSwitch.

De VLAN-interface is:
```
enp0s31f6.4000
```
Op deze interface worden twee IP-adressen gezet:
```
192.168.100.2/24    # private vSwitch IP
46.225.195.186/29   # public vSwitch IP
```
IP-informatie

In Hetzner Robot staat:
```
IP/Subnet:  46.225.195.184
Gateway:    46.225.195.185
Netmask:    255.255.255.248
Broadcast:  46.225.195.191
```
Omdat 255.255.255.248 gelijk is aan /29, betekent dit:
```
46.225.195.184  = netwerkadres, niet gebruiken als host-IP
46.225.195.185  = gateway
46.225.195.186  = bruikbaar IP
46.225.195.187  = bruikbaar IP
46.225.195.188  = bruikbaar IP
46.225.195.189  = bruikbaar IP
46.225.195.190  = bruikbaar IP
46.225.195.191  = broadcast, niet gebruiken als host-IP
```
Daarom wordt 46.225.195.186/29 gebruikt op de server en niet 46.225.195.184.
Netplan-configuratie
```
network:
  version: 2
  renderer: networkd

  ethernets:
    eno1:
      addresses:
        - 95.217.76.70/32
        - 2a01:4f9:4a:1bdf::2/64
      routes:
        - on-link: true
          to: 0.0.0.0/0
          via: 95.217.76.65
        - to: default
          via: fe80::1
      nameservers:
        addresses:
          - 185.12.64.2
          - 2a01:4ff:ff00::add:1
          - 185.12.64.1
          - 2a01:4ff:ff00::add:2

    enp0s31f6:
      dhcp4: no

  vlans:
    enp0s31f6.4000:
      id: 4000
      link: enp0s31f6
      mtu: 1400
      addresses:
        - 192.168.100.2/24
        - 46.225.195.186/29

      routes:
        - to: default
          via: 46.225.195.185
          table: 1

      routing-policy:
        - from: 46.225.195.186
          table: 1
        - to: 46.225.195.186
          table: 1
```
Configuratie toepassen

Test de configuratie eerst:
```
sudo netplan try
```
Pas de configuratie daarna toe:
```
sudo netplan apply
```
Controleren

Controleer of de IP-adressen op de VLAN-interface staan:
```
ip addr show enp0s31f6.4000
```
Controleer de routing policy:
```
ip rule show
```
Controleer routing table 1:
```
ip route show table 1
```
Verwachte route:
```
default via 46.225.195.185 dev enp0s31f6.4000
```
SSH

Normaal beheer van de host blijft via het hoofd-IP:
```
ssh ubuntu@95.217.76.70
```
SSH via het public vSwitch-IP kan via:
```
ssh ubuntu@46.225.195.186
```
Als SSH niet werkt, controleer of SSH luistert en of de firewall open staat:
```
sudo ss -tlnp | grep ':22'
sudo ufw status verbose
```
Controleer ook of de Hetzner Robot firewall 22/tcp toestaat naar 46.225.195.186.


Part 2 (nadat de vswitch-ip up en running is op de host)
Situatie

De server heeft twee publieke paden:

Hoofd/direct server-IP-pad:
```
95.217.76.70 via eno1
```
vSwitch/publiek gerouteerd IP-pad:
```
46.225.195.186 via enp0s31f6.4000
gateway/table route via 46.225.195.185
```
Het vSwitch-IP is geconfigureerd op:
```
enp0s31f6.4000
46.225.195.186/29
```
De bestaande veilige routingregel is:
```
from 46.225.195.186 lookup vswitch
```
Die regel moet blijven staan.

Traefik/Docker luistert correct op:
```
0.0.0.0:80
0.0.0.0:443
[::]:80
[::]:443
```
Probleem

Requests naar 46.225.195.186:80/443 kwamen aan op de server, maar de TCP-handshake werd niet voltooid.

De packet flow was effectief:
```
Client -> 46.225.195.186:80
Docker DNAT -> Traefik container 172.19.0.2:80
Traefik reply starts from 172.19.0.2
Host routing sends reply via eno1 instead of vSwitch
Client never receives valid reply
```
Dit is bevestigd met:
```
ip route get 188.212.113.139 from 172.19.0.2 iif br-117840a2ed55
```
Dit gaf terug:
```
via 95.217.76.65 dev eno1
```
Dat is correct voor normaal Docker-verkeer, maar fout voor replies op verbindingen die oorspronkelijk binnenkwamen via 46.225.195.186.

Een brede fix zoals deze werkte deels, maar was onveilig:
```
sudo ip rule add iif br-117840a2ed55 table vswitch priority 1000
```
omdat daarmee al het verkeer vanaf die Docker bridge via de vSwitch werd gerouteerd. Dat brak andere productieservices die de directe server-IP-route moeten gebruiken.
Gerichte fix

Alleen verbindingen die oorspronkelijk binnenkwamen op:
```
46.225.195.186:80
46.225.195.186:443
```
moeten teruggaan via de vswitch routing table.

Gebruik CONNMARK om die verbindingen te onthouden, en herstel de mark alleen op reply-packets van Traefik.

Huidige waarden uit deze sessie:
```
vSwitch IP:           46.225.195.186
vSwitch table:        vswitch
mark:                 0x4000
Docker bridge:        br-117840a2ed55
Traefik container IP: 172.19.0.2
```
Controleer actuele Traefik container-IP
```
docker inspect -f '{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' $(docker ps -q) | grep -i traefik
```
Verwacht voorbeeld:
```
/traefik 172.19.0.2
```
Daarna pas de restore-mark regel invullen met het gevonden IP:
```
sudo iptables -t mangle -A PREROUTING \
  -i br-117840a2ed55 \
  -s 172.19.0.2/32 \
  -m connmark --mark 0x4000 \
  -j CONNMARK --restore-mark
```
Fix toepassen
```
sudo iptables -t mangle -A PREROUTING \
  -d 46.225.195.186/32 \
  -p tcp -m multiport --dports 80,443 \
  -j CONNMARK --set-mark 0x4000
```
```
sudo iptables -t mangle -A PREROUTING \
  -i br-117840a2ed55 \
  -s 172.19.0.2/32 \
  -m connmark --mark 0x4000 \
  -j CONNMARK --restore-mark
```
```
sudo ip rule add fwmark 0x4000 table vswitch priority 1000
```
```
sudo ip route flush cache
```
Gebruik niet de eerdere brede bridge-regel:
```
sudo ip rule add iif br-117840a2ed55 table vswitch priority 1000
```
Gebruik niet de eerdere packet mark-regel:
```
-j MARK --set-mark 0x4000
```
De werkende aanpak is connection marking met CONNMARK.
Verificatie
1. Ongemarkeerd Docker-verkeer moet nog steeds de normale route gebruiken
```
ip route get 188.212.113.139 from 172.19.0.2 iif br-117840a2ed55
```
Verwacht:
```
via 95.217.76.65 dev eno1
```
Dat betekent dat normaal/direct-IP Docker-verkeer nog steeds onaangetast is.
2. Gemarkeerd Docker-return-verkeer moet de vSwitch-route gebruiken
```
ip route get 188.212.113.139 from 172.19.0.2 iif br-117840a2ed55 mark 0x4000
```
Verwacht:
```
via 46.225.195.185 dev enp0s31f6.4000 table vswitch mark 0x4000
```
3. Test vanaf je Mac
```
curl -4 -v --connect-timeout 5 http://iptest.edwh.nl
```
Verwacht resultaat:
```
Connected to iptest.edwh.nl (46.225.195.186) port 80
HTTP/1.1 301 Moved Permanently
Location: https://iptest.edwh.nl/
```
4. Controleer counters
```
sudo iptables -t mangle -L PREROUTING -n -v --line-numbers
```
De CONNMARK-regels zouden oplopende packet counters moeten tonen.
Rollback

Gebruik dit als de wijziging problemen veroorzaakt:
```
sudo ip rule del fwmark 0x4000 table vswitch priority 1000 2>/dev/null || true
```
```
sudo iptables -t mangle -D PREROUTING \
  -i br-117840a2ed55 \
  -s 172.19.0.2/32 \
  -m connmark --mark 0x4000 \
  -j CONNMARK --restore-mark 2>/dev/null || true
```
```
sudo iptables -t mangle -D PREROUTING \
  -d 46.225.195.186/32 \
  -p tcp -m multiport --dports 80,443 \
  -j CONNMARK --set-mark 0x4000 2>/dev/null || true
```
```
sudo ip route flush cache
```
Verifieer de rollback:
```
ip rule show | grep -E '0x4000|vswitch'
```
```
sudo iptables -t mangle -S PREROUTING | grep -E '46.225.195.186|0x4000|br-117840a2ed55'
```
Na de rollback zou alleen deze originele regel moeten overblijven:
```
from 46.225.195.186 lookup vswitch
```
Belangrijke productie-opmerking

Deze fix is afhankelijk van het gelijk blijven van deze twee Docker-waarden:
```
Docker bridge:        br-117840a2ed55
Traefik container IP: 172.19.0.2
```
Als Docker het netwerk opnieuw aanmaakt of Traefik een ander container-IP krijgt, moet de mangle restore-regel worden bijgewerkt.

Om de huidige container-IP’s te inspecteren:
```
docker inspect -f '{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' $(docker ps -q)
```
Om het routegedrag opnieuw te inspecteren:
```
ip route get 188.212.113.139 from 172.19.0.2 iif br-117840a2ed55
```
```
ip route get 188.212.113.139 from 172.19.0.2 iif br-117840a2ed55 mark 0x4000
```
Het doel is:
```
Unmarked Docker/direct-IP traffic -> eno1
Marked vSwitch HTTP/HTTPS replies -> enp0s31f6.4000 via table vswitch
```
Swap-procedure publiek IP tussen twee servers
Doel

Het publieke IP-adres wordt tijdelijk verwijderd van server 1 en daarna actief gemaakt op server 2.

Het interne vSwitch-IP blijft actief.

Interface:
```
enp0s31f6.4000
```
Publiek IP:
```
<publiek-ip>/<prefix>
```
Voorbeeld:
```
46.225.195.186/29
```
1. Acties op server 1 — oude actieve server
1.1 Controleer huidige IP-adressen

Log in op server 1 en controleer of het publieke IP actief is:
```
ip addr show dev enp0s31f6.4000
```
Controleer dat zowel het interne vSwitch-IP als het publieke IP zichtbaar zijn.
1.2 Verwijder het publieke IP van server 1

Verwijder alleen het publieke IP-adres:
```
sudo ip addr del <publiek-ip>/<prefix> dev enp0s31f6.4000
```
Voorbeeld:
```
sudo ip addr del 203.0.113.10/24 dev enp0s31f6.4000
```
1.3 Controleer of het publieke IP weg is
```
ip addr show dev enp0s31f6.4000
```
Het publieke IP mag nu niet meer zichtbaar zijn.

Het interne vSwitch-IP moet nog wel actief zijn.
2. Acties op server 2 — nieuwe actieve server
2.1 Controleer de interface

Log in op server 2 en controleer de interface:
```
ip addr show dev enp0s31f6.4000
```
Controleer of het interne vSwitch-IP actief is.
2.2 Activeer het publieke IP via Netplan

Pas de Netplan-configuratie toe op server 2:
```
sudo netplan apply
```
Hiermee wordt het publieke IP actief gemaakt, mits het publieke IP in de Netplan-config van server 2 staat.
2.3 Controleer of het publieke IP actief is
```
ip addr show dev enp0s31f6.4000
```
Het publieke IP moet nu zichtbaar zijn op server 2.

Controleer eventueel ook de routing:
```
ip route
```
3. Controle na de swap

Controleer vanaf een externe locatie of het publieke IP bereikbaar is:
```
ping <publiek-ip>
```
Of test de betreffende dienst, bijvoorbeeld SSH, HTTP of HTTPS:
```
ssh user@<publiek-ip>
```
4. Terug-swappen indien nodig

Als het publieke IP terug moet naar server 1, doe je de stappen omgekeerd.
Op server 2
```
sudo ip addr del <publiek-ip>/<prefix> dev enp0s31f6.4000
```
Controleer:
```
ip addr show dev enp0s31f6.4000
```
Op server 1
```
sudo netplan apply
```
Controleer:
```
ip addr show dev enp0s31f6.4000
```
Belangrijke aandachtspunten

Voer de stappen altijd in deze volgorde uit:

    Eerst publiek IP verwijderen op server 1.
    Daarna publiek IP activeren op server 2.

Zo voorkom je dat hetzelfde publieke IP tegelijk op twee servers actief is.

Let op met SSH: als je via het publieke IP bent ingelogd op server 1, kan je verbinding wegvallen zodra je het publieke IP verwijdert. Gebruik bij voorkeur het interne vSwitch-IP of console-toegang tijdens de swap.
