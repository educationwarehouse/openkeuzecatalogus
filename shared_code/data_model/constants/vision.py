"""Vision theme constants shared by data-model definitions."""

THEMES_METADATA = {
    # todo: make this metadata dynamic
    "opbouw-leerdoelen": {
        "title": "Opbouw en leerdoelen",
        "info_link": "https://onzeleermiddelen.nl/opbouw-en-leerdoelen/",
        "info_note": (
            "De structuur van een leermiddel (hoofdstukken, paragrafen, lesvolgorde) en de expliciete, "
            "taal- en positioneringswijze van leerdoelen bepalen inzicht, vakintegratie en de selectie ervan."
        ),
    },
    "diversiteit-differentieren": {
        "title": "Diversiteit en differentieren",
        "info_link": "https://onzeleermiddelen.nl/diversiteit-en-differentieren/",
        "info_note": (
            "Bij het kiezen van leermiddelen moet men de differentiatie- en arrangemogelijkheden beoordelen, "
            "flexibele versus vaste methodes vergelijken, en waar nodig open materiaal integreren voor alle niveaus."
        ),
    },
    "kwaliteit-effectiviteit": {
        "title": "Kwaliteit en effectiviteit",
        "info_link": "https://onzeleermiddelen.nl/kwaliteit-en-effectiviteit/",
        "info_note": (
            "Hoogwaardige, effectieve leermiddelen, gebaseerd op actuele wetenschap, moeten aansluiten bij schoolvisie "
            "en didactiek, om leerprocessen, motivatie en brede ontwikkeling doelgericht te ondersteunen."
        ),
    },
    "evalueren-toetsen": {
        "title": "Evalueren en toetsen",
        "info_link": "https://onzeleermiddelen.nl/evalueren-en-toetsen/",
        "info_note": (
            "Evaluatie- en toetsopties van leermiddelen varieren in vorm, moment en ondersteuning, "
            "bieden formatieve en "
            "summatieve, inclusieve keuzes (schriftelijk, mondeling, creatief, digitaal) afgestemd op leerling- en "
            "docentbehoeften."
        ),
    },
    "vormgeving-toegankelijkheid": {
        "title": "Vormgeving en toegankelijkheid",
        "info_link": "https://onzeleermiddelen.nl/vormgeving-en-toegankelijkheid/",
        "info_note": (
            "Vormgeving en toegankelijkheid van leermiddelen bepalen hun kwaliteit en geschiktheid "
            "voor diverse doelgroepen, "
            "waarbij ontwerp, contrast, lettergrootte en ondersteunende technologie essentieel zijn."
        ),
    },
    "belevingswereld-leefomgeving": {
        "title": "Belevingswereld en (leef)omgeving",
        "info_link": "https://onzeleermiddelen.nl/belevingswereld-en-leefomgeving/",
        "info_note": (
            "Leermateriaal moet aansluiten op zowel de belevingswereld als de leefomgeving van "
            "leerlingen: hun ervaringen, "
            "waarden, cultuur, identiteit en voorkennis, met passende representatie en herkenbare "
            "contexten, eventueel aangevuld."
        ),
    },
    "aanpasbaarheid-actualiteit": {
        "title": "Aanpasbaarheid en actualiteit",
        "info_link": "https://onzeleermiddelen.nl/aanpasbaarheid-en-actualiteit/",
        "info_note": (
            "De aanpasbaarheid en actualiteit van leermiddelen bepalen hun flexibiliteit, zodat "
            "onderwijs sneller inspeelt op "
            "context, wensen, nieuwe ontwikkelingen en veranderende doelen, met een passende leraarrol."
        ),
    },
    "materiaalvormen-technologie": {
        "title": "Materiaalvormen en technologie",
        "info_link": "https://onzeleermiddelen.nl/materiaalvormen-en-technologie/",
        "info_note": (
            "Materiaalvormen (boeken, werkbladen, digitaal) en technologie (digitaal lesmateriaal, "
            "AI) varieren per school, "
            "vak, doelgroep en leraar; kies passend volgens effectiviteit voor leerlingondersteuning."
        ),
    },
    "co-creatie-doorontwikkeling": {
        "title": "Co-creatie en (door)ontwikkeling",
        "info_link": "https://onzeleermiddelen.nl/co-creatie-en-doorontwikkeling/",
        "info_note": (
            "Co-creatie betekent dat leraren, leerlingen en makers samen leermiddelen ontwikkelen en doorontwikkelen, "
            "waarbij methoden varieren van feedbackknoppen tot focusgroepen, en de mate hiervan "
            "beinvloedt de materiaalkeuze."
        ),
    },
    "onafhankelijkheid-dataveiligheid": {
        "title": "Onafhankelijkheid en data-veiligheid",
        "info_link": "https://onzeleermiddelen.nl/onafhankelijkheid-en-data-veiligheid/",
        "info_note": (
            "Onafhankelijkheid en dataveiligheid bepalen hoe sterk scholen afhankelijk zijn van leveranciers, waarbij "
            "verticale en horizontale integratie keuzemogelijkheden beperken en privacy, transparantie "
            "en controle over "
            "persoonsgegevens cruciaal zijn."
        ),
    },
    "transparant-eerlijk": {
        "title": "Transparant en eerlijk",
        "info_link": "https://onzeleermiddelen.nl/transparant-en-eerlijk/",
        "info_note": (
            "Transparantie en eerlijkheid bij leermiddelen betekenen duidelijke kosten- en "
            "ontwikkelingsinformatie, geen "
            "verborgen verplichtingen, en inzicht in herinvestering versus winst, zodat scholen "
            "bewuste partners kiezen."
        ),
    },
    "verantwoord-duurzaam": {
        "title": "Verantwoord en duurzaam",
        "info_link": "https://onzeleermiddelen.nl/verantwoord-en-duurzaam/",
        "info_note": (
            "Verantwoord gebruik van leermiddelen vraagt bewuste materiaal- en productkeuzes, waarbij "
            "zowel de duurzame "
            "ontwikkeling door makers als het efficiente, afval-beperkende gebruik door gebruikers wordt meegewogen."
        ),
    },
}

THEMES = {theme_key: theme_meta["title"] for theme_key, theme_meta in THEMES_METADATA.items()}
