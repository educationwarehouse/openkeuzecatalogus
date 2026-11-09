"""WeasyPrint implementation of the PDF rendering contract."""

from .contracts import PdfRenderRequest, PdfService, PdfUnavailableError

try:
    import weasyprint
    import weasyprint.text.fonts
except ImportError, OSError:
    # ImportError: package absent, which is every image except pgq-pdf.
    # OSError: package present but its native libs are missing, i.e. a broken pgq-pdf build.
    # Importable either way, because the web tier needs this module for the base class' staging
    # helpers even though it never renders.
    weasyprint = None

# A4 with no margin, as the old app had it; the document supplies its own padding.
DEFAULT_PAGE_CSS = """
@page {
    size: A4;
    margin: 0mm;
}
"""


class WeasyPrintPdfService(PdfService):
    """Convert staged HTML to PDF with WeasyPrint.

    Runs only in the `pgq-pdf` image, which installs the native pango/cairo/gdk-pixbuf stack.
    Anywhere else `render` raises, which is intended: reaching it outside the worker means the
    deferral was bypassed.
    """

    def render(self, request: PdfRenderRequest) -> bytes:
        """Convert one staged document to PDF bytes."""
        if weasyprint is None:
            raise PdfUnavailableError(
                "WeasyPrint is not usable here; this image lacks the package or its native libraries.",
            )

        font_config = weasyprint.text.fonts.FontConfiguration()
        # The document arrives with its own CSS and images already inlined (see PdfRenderRequest),
        # so the only stylesheet added here is the engine-specific page geometry.
        stylesheets = [weasyprint.CSS(string=request.get("css") or DEFAULT_PAGE_CSS, font_config=font_config)]

        rendered = weasyprint.HTML(string=request["html"]).write_pdf(
            stylesheets=stylesheets,
            font_config=font_config,
            dpi=600,
        )
        if rendered is None:
            raise PdfUnavailableError("WeasyPrint returned no PDF bytes.")

        return rendered

    @classmethod
    def from_env(cls) -> PdfService:
        """Build the WeasyPrint implementation without recursing through the selector."""
        return cls()
