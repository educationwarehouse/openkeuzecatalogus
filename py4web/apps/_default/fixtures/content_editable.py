import typing as t

import bs4
from common.models import auth, db, session
from py4web.core import HTTP, Fixture, Template
from typedal.types import Query

from py4web import request
from shared_code.data_model import StaticContent
from shared_code.util.exceptions import throw


class ScopeSectionQuery(t.NamedTuple):
    """Return value for `ContentEditableV2._query`."""

    query: Query
    scope: str
    section: str


class ContentEditableV2(Template):
    """Fixture that replaces <edwh-editable> with dynamic data.

    Works as a Template on top of YATL.
    """

    _table = StaticContent
    _html_tag = "edwh-editable"

    def __init__(
        self,
        filename: str,
        scope: str | None = None,
        path: str | None = None,
        delimiters: str = "[[ ]]",
    ) -> None:
        self.__prerequisites__: list[Fixture] = [session, db, auth]

        super().__init__(filename, path=path, delimiters=delimiters)

        self.scope = (scope or filename).removesuffix(".html")
        self.session = session
        self.auth = auth

    def on_request(self, context: dict[str, t.Any]) -> None:
        super().on_request(context)
        self.session["path"] = request.path
        self.session.save()

    @classmethod
    def contenteditable_allowed(cls, scope: str) -> bool:
        return auth.auth_context.is_admin()

    def on_success(self, context: dict[str, t.Any]) -> None:
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

        if self._html_tag in html:
            doc = bs4.BeautifulSoup(html, "html5lib")

            sections_used = set()
            for tag in doc.find_all(self._html_tag):
                self.content_editable_transform(scope, tag, sections_used=sections_used)

            context["output"] = str(doc)

    def content_editable_transform(self, scope: str, elt: bs4.Tag, sections_used: set[str]) -> None:
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
            if not content.strip().startswith("<"):
                content = f"<p>{content}</p>"

        # set innerHTML:
        elt.clear()
        fragment = bs4.BeautifulSoup(content, "html.parser")
        elt.extend(fragment.contents)

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
