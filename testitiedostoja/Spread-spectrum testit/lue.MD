# Kehitysongelmia äänen pakkaamisessa

Tässä hakemistossa on testeja Spread-spectrum salauksella. ENC_ alkuiset toimivat siksi, että niissä on kovia ääniä. Salattu-alkuiset kohisevat selvästi.

Spread-spectrum (adaptive alpha + windowing + cutoff 600–1000 Hz) ym. ja erilaisia sekamuotoja kokeiltu, mutta tuloksena on huono äänenlaatu ja käytännössä tilaa salaamiselle ei ole.

Aluksi oli seuraavia ongelmia:

- Kiinteä alpha → liian voimakas hiljaisissa kohdissa → audible low-frequency rumble (300 Hz cutoff teki siitä korreloitunutta "hengitystä").
- Ei adaptive masking → ei mukautunut äänen paikalliseen voimakkuuteen tai taajuusmaskeeraukseen.
- Chip-segmenttien normitus → joissain segmenteissä embedding-voima kasvoi odottamattomasti.
- Transientit ilman ikkunointia → pieniä klikkejä segmenttien rajoilla.


MDCT-domain upotus ei tuo tähän mitään lisäarvoa, vaikka se voisi muuten olla hyvä.

Tästä syystä palasin alkuperäiseen vanhaan LSB-metodiin, joka ei kestä mp3 pakkausta:

MP3 (ja AAC, Opus jne.) on häviöllinen pakkaus, joka poistaa dataa psychoacoustic-mallin perusteella:

Kvantisaatio pyöristää MDCT-kertoimia karkeammalle asteikolle → matalat bitit (erityisesti LSB) muuttuvat tai katoavat kokonaan.
Huffman-koodaus ja bit-reservoir tekevät muutoksista epälineaarisia: pieni muutos yhdessä kohdassa voi vaikuttaa laajalle alueelle.
High-frequency cutoff (esim. >16 kHz 128 kbps:lla) poistaa taajuuksia, joihin LSB-muutokset usein osuvat.
Pre-echo / temporal smearing transienttien ympärillä muuttaa sample-arvoja ajallisesti.

Tyypillinen LSB (1–4 bittiä/sample PCM:ssä) menettää 50–100 % payloadista jo 192–256 kbps MP3:lla. 128 kbps:lla tai VBR:ssa (esim. -V 5) menetys on lähes täydellinen. Tämä on klassinen ongelma kaikissa puhtaissa time-domain LSB -toteutuksissa.

Voit kokeilla 320 kbit/s stremilla kestääkö 

2.3.2026 - Jari Hiltunen