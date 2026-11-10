"""Public sharing metadata for the integrated Open Keuzecatalogus platform."""

import typing as t

SITE_NAME = "Open Keuzecatalogus Leermiddelen"
SITE_URL = "https://openkeuzecatalogus.nl"
SOCIAL_IMAGE = f"{SITE_URL}/static/landing/images/okl-social-preview.png"
SOCIAL_TITLE = f"{SITE_NAME} | Vind en vergelijk"
SOCIAL_DESCRIPTION = (
    "Vind en vergelijk leermiddelen in de Open Keuzecatalogus. Werk als schoolteam aan jullie onderwijsvisie "
    "en onderbouw samen jullie leermiddelenkeuze."
)


class PageMetadata(t.TypedDict):
    """Values used by the shared HTML, Open Graph and Twitter tags."""

    title: str
    social_title: str
    description: str
    canonical: str
    image: str
    robots: str


def material_description(title: str) -> str:
    """Describe an individual learning material within the social preview limit."""
    description = (
        f"Bekijk {title} in de Open Keuzecatalogus Leermiddelen "
        "en vergelijk dit leermiddel vanuit jullie onderwijsvisie."
    )
    if len(description) > 160:
        return description[:159].rstrip() + "…"

    return description


def page_metadata(path: str, title: str | None = None) -> PageMetadata:
    """Resolve route metadata without copying private titles or query parameters into social previews."""
    path = path.split("?", 1)[0].rstrip("/") or "/"
    if path == "/index":
        path = "/"
    elif path == "/faq.html":
        path = "/faq"

    root = path.removeprefix("/").partition("/")[0]
    canonical_path = path
    public = path in {"/", "/methodes", "/producten", "/faq", "/privacyverklaring"}
    social_title = SOCIAL_TITLE
    description = SOCIAL_DESCRIPTION

    if root == "private":
        canonical_path = "/private/keuzecanvas"
    elif root == "auth":
        canonical_path = "/auth/login"
    elif root in {"methode", "product", "supplier", "compare"}:
        public = True
        if root in {"methode", "product"} and title:
            social_title = f"{title} | {SITE_NAME}"
            description = material_description(title)
    elif not public:
        canonical_path = "/"

    document_title = SOCIAL_TITLE
    if title:
        document_title = f"{title} | {SITE_NAME}"

    return PageMetadata(
        title=document_title,
        social_title=social_title,
        description=description,
        canonical=f"{SITE_URL}{canonical_path}",
        image=SOCIAL_IMAGE,
        robots="index, follow, max-image-preview:large" if public else "noindex, nofollow",
    )
