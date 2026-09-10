"""Generate static types from runtime model metadata."""

from edwh import DOCKER_COMPOSE
from ewok import Context, task

GENERATED_VOLUME = "--volume ./shared_code/generated:/pythonpath/shared_code/generated"
FIELDS_MODULE = "shared_code.data_model.fields"
IMPORT_TYPES_MODULE = f"{FIELDS_MODULE}.import_types"
PUBLIC_TYPES_MODULE = f"{FIELDS_MODULE}.public_types"


def _run_generator(c: Context, command: str, container: str = "migrate") -> None:
    """Run a type generator in the selected runtime container."""
    c.run(f'{DOCKER_COMPOSE} run --rm {GENERATED_VOLUME} {container} sh -c "{command}"')


@task()
def generate_importtypes(c: Context) -> None:
    """Generate importer payload types from runtime model metadata."""
    _run_generator(c, f"python3 -m {IMPORT_TYPES_MODULE}")


@task()
def generate_publictypes(c: Context) -> None:
    """Generate public payload types from runtime model metadata."""
    _run_generator(c, f"python3 -m {PUBLIC_TYPES_MODULE}")


@task(name="generate")
def generate(c: Context) -> None:
    """Generate all static types."""
    generate_importtypes(c)
    generate_publictypes(c)
