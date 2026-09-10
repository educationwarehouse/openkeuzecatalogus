"""Public catalogue vision resolution."""

import typing as t
from collections import defaultdict

from endow import Domain

from shared_code.data_model import Method, Supplier, Vision
from shared_code.data_model.constants import THEMES, AnyDict
from shared_code.modules.visions.types import ResolvedVision, VisionIds


class VisionBackend(Domain):
    """Resolve public visions with method values taking precedence."""

    def resolve_public_visions(
        self,
        sources: t.Mapping[str, tuple[Method, Supplier]],
    ) -> tuple[dict[str, list[ResolvedVision]], VisionIds]:
        """Resolve every theme from a method first, then its supplier."""
        olids = {olid for source in sources.values() for row in source if (olid := row.olid)}
        vision_by_olid_theme = {
            (row.olid, row.onderwijskwaliteit): row
            for row in Vision.where(Vision.olid.belongs(olids)).select(
                Vision.id,
                Vision.olid,
                Vision.onderwijskwaliteit,
                Vision.visie,
                Vision.property_bag,
            )
        }

        result: dict[str, list[ResolvedVision]] = {}
        vision_ids: VisionIds = defaultdict(list)
        for gid, (method, supplier) in sources.items():
            result[gid] = []
            for theme, theme_label in THEMES.items():
                vision = vision_by_olid_theme.get((method.olid, theme)) or vision_by_olid_theme.get(
                    (supplier.olid, theme)
                )
                source = method if vision and vision.olid == method.olid else supplier
                vision_id = t.cast(int | None, vision.id if vision else None)

                vision_ids[theme].append(vision_id)
                result[gid].append(
                    {
                        "theme": theme_label,
                        "source": source.name or "Onbekend",
                        "content": vision.visie if vision else "Nog niet gedeeld.",
                        "properties": t.cast(AnyDict, vision.property_bag if vision else {}),
                    }
                )

        return result, vision_ids
