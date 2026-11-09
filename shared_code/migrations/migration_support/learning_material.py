"""Migration manager for the learning-material catalog read model."""

from edwh_migrate import ViewMigrationManager
from pydal import DAL

from .core import upsert_index_v1
from .method import MethodModelWithPrio_V1
from .product import ProductModelWithPrio_V1


def enable_fuzzy_finding_on_learning_material_v1(db: DAL) -> None:
    """Create the trigram support used by material-picker search queries."""
    db.executesql("""
    CREATE EXTENSION IF NOT EXISTS pg_trgm;

    CREATE INDEX trgm_idx_learning_material_name
        ON learning_material
            USING gin (name gin_trgm_ops);

    CREATE INDEX trgm_idx_learning_material_olid
        ON learning_material
            USING gin (olid gin_trgm_ops);
    """)


# noinspection PyPep8Naming
class LearningMaterial_V1(ViewMigrationManager):
    """Maintain the materialized catalog relation used by the decision process."""

    uses = (MethodModelWithPrio_V1, ProductModelWithPrio_V1)

    since = "create_learning_material_view_20260803_002"

    def up(self) -> None:
        """Create and index the materialized union of current catalog rows."""
        self.db.executesql("""
        CREATE MATERIALIZED VIEW learning_material AS
        SELECT ROW_NUMBER() OVER (ORDER BY olid) AS id
             , gid
             , name
             , olid
             , origin
        FROM (
            SELECT product_model_current.name AS name
                 , product_model_current.gid AS gid
                 , product_model_current.olid AS olid
                 , 'product' AS origin
            FROM product_model product_model_current
            UNION ALL
            SELECT method_model_current.name AS name
                 , method_model_current.gid AS gid
                 , method_model_current.olid AS olid
                 , 'method' AS origin
            FROM method_model method_model_current
        ) combined_data;
        """)
        enable_fuzzy_finding_on_learning_material_v1(self.db)
        upsert_index_v1(self.db, "learning_material", ["origin", "gid"], unique=True)

    def down(self) -> None:
        """Drop the materialized view before rebuilding it."""
        self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS learning_material;")
