"""Template fixture for editable and projected static HTML content."""

import typing as t

import bs4
import soup5ever  # noqa: F401 - used to register the feature for bs4.BeautifulSoup
from py4web.core import HTTP, Fixture, Template
from typedal.types import Query

from common.models.backend import auth, db, session
from py4web import request
from shared_code.data_model import AnyDict, StaticContent
from shared_code.util.exceptions import throw

TAG_EDWH_EDITABLE = "edwh-editable"
TAG_EDWH_CONTENT = "edwh-content"


class ScopeSectionQuery(t.NamedTuple):
    """Return value for `ContentEditableV2._query`."""

    query: Query
    scope: str
    section: str


class ContentEditableV2(Template):
    """Fixture that replaces <edwh-editable> and <edwh-content> with dynamic data.

    Works as a Template on top of YATL.
    """

    _table = StaticContent
    _html_tags = frozenset((TAG_EDWH_EDITABLE, TAG_EDWH_CONTENT))

    def __init__(
        self,
        filename: str,
        scope: str | None = None,
        path: str | None = None,
        delimiters: str = "[[ ]]",
    ) -> None:
        """Initialize the template fixture and its database prerequisites."""
        # Deliberately NOT [session, db, auth]:
        # py4web's action.uses() topologically sorts a fixture *after* its prerequisites, and
        # on_success runs the list in reverse. So declaring 'auth' here would move auth ahead of
        # this template in the order, meaning AppAuth.on_success (which injects 'auth' into the
        # output dict) would run *after* this template has already rendered -- templates would
        # then see auth=None. 'db' and 'auth' are reached through the module-level singletons
        # instead; the surrounding common()/admin() chain already requests them as fixtures.
        self.__prerequisites__: list[Fixture] = [session]

        super().__init__(filename, path=path, delimiters=delimiters)

        self.scope = (scope or filename).removesuffix(".html")
        self.session = session
        self.auth = auth

    def on_request(self, context: AnyDict) -> None:
        """Store the current request path in the session before rendering."""
        super().on_request(context)
        self.session["path"] = request.path
        self.session.save()

    @classmethod
    def contenteditable_allowed(cls, scope: str) -> bool:
        """Return whether the current user may edit content in `scope`."""
        return auth.auth_context.is_admin()

    def on_success(self, context: AnyDict) -> None:
        """Replace content-editable and content-projection tags in rendered HTML."""
        # deprecation warning:
        output = context.setdefault("output", {})

        scope = self.scope % request.url_args

        if isinstance(output, dict):
            output["ContentEditable"] = lambda section, *a, **kw: throw(
                # throw = raise but functional, so it works in a lambda
                ValueError(
                    f"ERR: Using deprecated ContentEditable syntax in {self.scope}:{section}",
                ),
            )

            output["contenteditable-allowed"] = self.contenteditable_allowed(scope)

        # turns output from dict to html:
        super().on_success(context)

        html = str(context["output"])

        if not any(tag in html for tag in self._html_tags):
            return

        doc = self.parse_document(html)

        source_fallbacks = self.process_edwh_editable(doc, scope=scope)
        self.process_edwh_content(doc, scope=scope, source_fallbacks=source_fallbacks)

        context["output"] = str(doc)

    @staticmethod
    def parse_document(html: str) -> bs4.BeautifulSoup:
        """Parse the rendered page into the tree a browser would build from it.

        The whole page is serialized back from this tree, so a parser that repairs
        broken markup differently from a browser changes what the visitor sees.
        """
        # previous: html5lib was slow; lxml is html4; html5-parser should be fast and html5-supporting.
        # this compatibility is validated in:
        # test_content_editable_parsing:test_parse_document_carries_open_formatting_into_the_next_block
        return bs4.BeautifulSoup(html, "soup5ever-experimental")

    @staticmethod
    def parse_fragment(html: str) -> bs4.BeautifulSoup:
        """Parse content for insertion into an existing element, without page wrappers."""
        # These editor snippets only need detached child nodes for insertion into
        # the already parsed page. html.parser keeps those fragment roots, while
        # parse_document would add html/head/body wrappers around the content.
        return bs4.BeautifulSoup(html, "html.parser")

    def process_edwh_editable(self, doc: bs4.BeautifulSoup, scope: str) -> dict[str, str]:
        """Transform editable tags and collect their fallback content by section."""
        source_fallbacks: dict[str, str] = {}
        sections_used = set()
        for tag in doc.find_all(TAG_EDWH_EDITABLE):
            if isinstance(section := tag.get("id"), str) and section:
                source_fallbacks[section] = " ".join(str(child) for child in tag.contents)

            self.content_editable_transform(scope, tag, sections_used=sections_used)

        return source_fallbacks

    def process_edwh_content(self, doc: bs4.BeautifulSoup, scope: str, source_fallbacks: dict[str, str]) -> None:
        """Transform read-only content tags using stored or editable fallback content."""
        for tag in doc.find_all(TAG_EDWH_CONTENT):
            self.content_projection_transform(scope, tag, source_fallbacks=source_fallbacks)

    def content_editable_transform(self, scope: str, elt: bs4.Tag, sections_used: set[str]) -> None:
        """Convert one editable tag to a stored, editable HTML section."""
        section = elt.get("id")
        if not isinstance(section, str) or not section:
            raise ValueError(f"Content Editable Section has no ID:\n {elt}")

        if section in sections_used:
            raise ValueError(
                f"Duplicate 'sections' in one scope ({scope}:{section})! Please make the sections unique.",
            )

        sections_used.add(section)

        identifier = scope + "#" + section

        elt.name = "div"
        elt["data-editable"] = "true"
        elt["data-name"] = identifier
        class_list = elt.get_attribute_list("class")
        class_list.append("is-content-editable")
        elt["class"] = class_list

        content = self.read_value(identifier)

        if content is None:
            content = " ".join(str(_) for _ in elt.contents)
            content = self.normalize_fallback_content(content)

        # set innerHTML:
        elt.clear()
        fragment = self.parse_fragment(content)
        elt.extend(fragment.contents)

    def content_projection_transform(
        self,
        scope: str,
        elt: bs4.Tag,
        source_fallbacks: dict[str, str],
    ) -> None:
        """Replace a read-only projection with stored or fallback content."""
        section = elt.get("id")
        if not isinstance(section, str) or not section:
            raise ValueError(f"Content projection has no ID:\n {elt}")

        content = self.read_value(f"{scope}#{section}")
        if content is None:
            content = source_fallbacks.get(section) or " ".join(str(_) for _ in elt.contents)
            content = self.normalize_fallback_content(content)

        fragment = self.parse_fragment(content)
        nodes = list(fragment.contents)
        if elt.has_attr("inline"):
            nodes = [node for node in nodes if not isinstance(node, bs4.NavigableString) or node.strip()]
            if len(nodes) == 1 and isinstance(nodes[0], bs4.Tag) and nodes[0].name == "p":
                nodes = list(nodes[0].contents)

        elt.replace_with(*nodes)

    @staticmethod
    def normalize_fallback_content(content: str) -> str:
        """Wrap plain-text fallbacks in a paragraph."""
        if not content.strip().startswith("<"):
            return f"<p>{content}</p>"

        return content

    @classmethod
    def _query(cls, identifier: str) -> ScopeSectionQuery:
        """Convert a block identifier (scope#section) into a query result.

        1. a query for the contenteditable table
        2. the scope
        3. the section
        """
        table = cls._table

        scope, section = identifier.split("#")

        # noinspection PyTypeChecker
        query: Query = table.scope == scope
        query &= table.section == section

        return ScopeSectionQuery(query, scope, section)

    @classmethod
    def read_value(cls, identifier: str) -> str | None:
        """Read the value from the database for identifier (scope#section)."""
        sope_section = cls._query(identifier)

        row = db(sope_section.query).select(cls._table.content).first()

        return row.content if row else None

    @classmethod
    def write_value(cls, identifier: str, content: str) -> None:
        """Write `content` as the value for identifier (scope#section)."""
        sope_section = cls._query(identifier)

        if not cls.contenteditable_allowed(sope_section.scope):
            raise HTTP(403, "Saving not allowed for scope.")

        cls._table.update_or_insert(
            sope_section.query,
            scope=sope_section.scope,
            section=sope_section.section,
            content=content,
        )
