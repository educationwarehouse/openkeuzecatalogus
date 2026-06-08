"""Project task runner commands."""

import enum
import os
import pathlib
import random
import shlex
import shutil
import socket
import tempfile
import textwrap
import typing as t
import uuid
import warnings
from pathlib import Path

import edwh
import edwh.tasks
from dotenv import load_dotenv
from edwh import DOCKER_COMPOSE
from edwh.helpers import run_pty
from ewok import Context, task
from termcolor import cprint
from termcolor._types import Color
from tqdm import tqdm

SHARED_CODE = Path("shared_code")
BOOTSTRAP_PATH = SHARED_CODE / "modules/css/bootstrap/"
DEFAULT_UNSAFE_PASSWORD = "test"


class classproperty[T](property):
    """Combining classmethod + property was removed in 3.13 for some reason."""

    # https://stackoverflow.com/questions/128573/using-property-on-classmethods
    def __get__(self, owner_self: object | None, owner_cls: type[t.Any]) -> T:
        """Called when the classproperty is accessed on a class or instance; resolves value from `owner_cls`."""
        if fget := getattr(self, "fget", None):
            # fget should exist but type checker says it could be none.
            return t.cast(t.Callable[[type[t.Any]], T], fget)(owner_cls)
        else:
            raise AttributeError("Unreadable classproperty: missing fget")


class StateOfDevelopment(enum.Enum):
    """Environment mode enum used to gate behavior across development and production-like states."""

    ONT = "Ontwikkel"
    DEMO = "Demo"
    TEST = "Test"
    UAT = "User Acceptance Testing"
    PRD = "Productie"

    @classmethod
    def from_env(cls) -> t.Self:
        """Load enum value from `STATE_OF_DEVELOPMENT` key in .env."""
        return cls[edwh.get_env_value("STATE_OF_DEVELOPMENT")]

    @classmethod
    def from_key(cls, key: str) -> t.Self:
        """Get the enum value from a string key; same as StateOfDevelopment['ONT']."""
        return cls[key]

    @classmethod
    def from_value(cls, value: str) -> t.Self:
        """Get the enum value from a string value; same as StateOfDevelopment('Ontwikkel')."""
        return cls(value)

    @classproperty
    def options(cls) -> list[str]:
        """Return the enum options."""
        return getattr(cls, "_member_names_", [])

    def __str__(self) -> str:
        """Use with `str(sod)`."""
        return self.name

    def __repr__(self) -> str:
        """Use with `repr(sod)`."""
        return f"StateOfDevelopment({self.value})"

    def is_productie(self) -> bool:
        """Is the state of development production-like?"""
        return self.name in ("DEMO", "UAT", "PRD")

    def is_ontwikkel(self) -> bool:
        """Is the state of development testing-like?"""
        return self.name in ("ONT", "TEST")


def download_with_files_plugin(c: Context, download_url: str, output_file: Path, unpack: bool = False) -> bool:
    """Download a file/directory via `edwh-files-plugin` if available."""
    try:
        from edwh_files_plugin.files_plugin import download as file_download
    except ImportError:
        warnings.warn("`edwh-files-plugin` not installed, can't download setup bootstrap data.", stacklevel=2)
        return False

    file_download(c, download_url=download_url, output_file=output_file, unpack=unpack)
    return True


@task()
def generate_jwt_key(c: Context, overwrite: bool = False) -> str:
    """Generate a random JWT key."""
    shared_keys = Path("shared_keys")
    shared_keys.mkdir(exist_ok=True)

    edwh.tasks.set_permissions(c, str(shared_keys))

    key_file = shared_keys / "jwt.key"

    if overwrite:
        key_file.unlink(missing_ok=True)

    try:
        private_key = key_file.read_text()
    except FileNotFoundError:
        private_key = random.randbytes(4096).hex()
        key_file.touch()
        key_file.write_text(private_key)

    return private_key


@task()
def bundler_build(c: Context) -> None:
    """Run `bundle.build` if the edwh-bundler-plugin is installed."""
    try:
        from edwh_bundler_plugin import build
    except ImportError:
        warnings.warn("`edwh-bundler-plugin` not installed, can't perform static file building.", stacklevel=2)
        return

    try:
        ensure_bootstrap(c)

        build(c)
    except Exception as e:
        # failing build may not hinder the rest of setup
        warnings.warn(f"bundle.build failed ({e})", source=e, category=RuntimeWarning, stacklevel=2)


@task()
def uptimerobot_autoadd(c: Context) -> None:
    """Runs `auto-add` from the edwh-uptime-plugin.

    Only warns if that plugin is not installed (instead of stopping the program via an exception).
    """
    try:
        from edwh_uptime_plugin import tasks as edwh_uptime
    except ImportError:
        warnings.warn("`edwh-uptime-plugin` not installed, can't perform UptimeRobot auto-add.", stacklevel=4)
        return

    edwh_uptime.auto_add(c, quiet=True)


@task()
def pip_bump_all(c: Context) -> None:
    """Bump all .txt files using `edwh pip.upgrade`."""
    c.run("edwh pip.upgrade py4web,migrate,pgq,playwright")


@task()
def setup_smtp(_: Context, dotenv_path: Path, sod: str = "") -> None:
    """Ask the required .env keys to work with SMTP."""
    is_fake = (
        edwh.check_env(
            "SMTP_FAKE",
            "1" if sod in ("ONT", "TEST") else "0",
            "Set to 1 if you don't want to use an actual SMTP server.",
        )
        == "1"
    )

    if is_fake:
        # not much more to do then
        return

    smtp_server = edwh.check_env("SMTP_SERVER", "smtp.eu.mailgun.org:587", "SMTP Server with or without port")

    if ":" in smtp_server:
        server_part, port_part = smtp_server.split(":")
        edwh.set_env_value(dotenv_path, "SMTP_SERVER", server_part)
        edwh.set_env_value(dotenv_path, "SMTP_PORT", port_part)
    else:
        edwh.check_env("SMTP_PORT", "587", "SMTP Port")

    sender = edwh.check_env("SMTP_SENDER", "automaat@mail.onzeleermiddelen.nl", "Email address to send mail from.")
    edwh.check_env("SMTP_USER", sender, "SMTP Login User")

    edwh.check_env("SMTP_PASSWORD", "", "SMTP Login Password")
    edwh.check_env("SMTP_TLS", "0", "Use (start)TLS? (1 for yunohost)")
    edwh.check_env("SMTP_SSL", "0", "Use SSL? (0 for yunohost)")


@task()
def fix_default_py4web_apps(c: Context) -> None:
    """Run `py4web setup` within the docker container to get default apps like `_dashboard`."""
    c.run(f"{DOCKER_COMPOSE} run --rm py4web py4web setup --yes apps")


@task()
def setup_sync(_: Context) -> None:
    """Ask the required .env keys to work with the poorman's sync."""
    edwh.check_env(
        key="DELEN_SYNC_ENDPOINT",
        default="https://delen.meteddie.nl/sync",
        comment="Poorman's Sync Endpoint",
    )

    edwh.check_env(
        key="DELEN_SYNC_JWT",
        default="",
        comment="JWT Token for Poorman's Sync",
    )

    edwh.check_env(
        key="DELEN_SYNC_PLATFORM",
        default="",
        comment="Platform the JWT token was provisioned to",
    )

    edwh.check_env(
        key="DELEN_SYNC_POLICY",
        default="all_known",
        comment=textwrap.dedent("""
            Determines how to handle first time syncing:
                  - 'full_history': Import all history for all records
                  - 'all_known': Start from each of the model rows currently known including deleted ones
                  - 'from_now': Start from the currently existing truth (filtered out removed rows)
                  """),
        allowed_values=("full_history", "all_known", "from_now"),
    )


@task()
def setup_testing_snapshot(c: Context, use_default: bool = False) -> str:
    """Configure and bootstrap `migrate/data/testing.snapshot`."""
    testing_snapshot_url = edwh.check_env(
        key="TESTING_SNAPSHOT_URL",
        default="",
        comment="Optional URL to fetch testing.snapshot data for test fixtures. Empty creates an empty directory.",
        force_default=use_default,
    )

    testing_snapshot_dir = Path("migrate/data/testing.snapshot")
    if testing_snapshot_dir.exists():
        print(f"Snapshot directory exists: {testing_snapshot_dir}")
    elif not testing_snapshot_url.strip():
        testing_snapshot_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created empty snapshot directory: {testing_snapshot_dir}")
    else:
        if not download_with_files_plugin(
            c,
            download_url=testing_snapshot_url,
            output_file=testing_snapshot_dir,
            unpack=True,
        ):
            print(f"Skipped snapshot download for {testing_snapshot_dir}")

    return testing_snapshot_url


@task()
def setup_migrate_seed(_: Context, use_default: bool = False) -> str | None:
    """Configure old-server seed import settings for migrate."""
    migrate_seed_base_url = edwh.check_env(
        key="MIGRATE_SEED_BASE_URL",
        default="https://wizard.onzeleermiddelencatalogus.nl",
        comment="Optional base URL for old-server seed endpoints (migration fetches /seed/{table}).",
        force_default=use_default,
    )
    edwh.check_env(
        key="MIGRATE_SEED_BEARER_TOKEN",
        default="",
        comment="Optional bearer token for old-server seed endpoints.",
    )

    if not migrate_seed_base_url.strip():
        print("No MIGRATE_SEED_BASE_URL configured; seed migration will skip.")
        return None

    return migrate_seed_base_url


@task()
def setup_grist(_: Context, use_default: bool = False) -> None:
    """Ask the required .env keys to work with the Grist API."""
    edwh.check_env(
        key="GRIST_API",
        default="",
        comment="Optional API Key from Grist (via 'Profile Settings')",
        force_default=False,
    )

    edwh.check_env(
        key="GRIST_HOST",
        # default="education-warehouse.getgrist.com",
        default="grist.edwh.nl",
        comment="Domain (excl. http) where Grist is running",
        force_default=use_default,
    )

    edwh.check_env(
        "GRIST_DOCUMENT",
        # default="7GRXvFCr8qqn",
        default="4mBd3uMQEATC",
        comment="Grist Document ID to import from",
        force_default=use_default,
    )


@task()
def setup_py4web_password(c: Context, use_default: bool = False) -> None:
    """Set or generate a py4web password and store it in local env config."""
    if Path("py4web/password.txt").exists():
        print("Py4web password already set, rm password.txt to update/generate a new password. ")
        return

    with c.cd("py4web"):
        default_passwd = edwh.tasks.generate_password(c, silent=True)
        if use_default:
            password = default_passwd
        else:
            password = input(f"Py4web password (leave empty to accept '{default_passwd}'): ").strip() or default_passwd

        c.run(f"uvenv run py4web set_password -- --password {password}")
        edwh.set_env_value(Path(".env"), "PY4WEB_PASSWORD", password)
        print(f'Password set to: "{password}", keep it safe!')


def download_framework_from_git(url: str, git_directory: str, target_path: Path, tag: str | None = None) -> None:
    """Download a framework repository subtree into a local target directory."""
    from plumbum.cmd import git

    if not url.startswith("http"):
        url = f"https://github.com/{url}.git"

    with tempfile.TemporaryDirectory() as d:
        git_path = Path(d)
        git_path.mkdir(exist_ok=True)
        target_path.mkdir(exist_ok=True, parents=True)

        cmd = git["clone", "--branch", tag, "--depth", "1", url, git_path] if tag else git["clone", url, git_path]

        print("$", cmd)
        cmd()

        print("$ copy to", target_path)

        items = list((git_path / git_directory).iterdir())

        for item in tqdm(items):
            shutil.move(item, target_path)

        (target_path / ".gitignore").write_text("*")


@task()
def get_bootstrap(_: Context) -> None:
    """Fetch the Bootstrap SCSS sources used by the app theme."""
    version = edwh.check_env("BOOTSTRAP_VERSION", "v5.3.3", "Should match git tag on `twbs/bootstrap`")

    if not version.startswith("v"):
        version = f"v{version}"

    download_framework_from_git("twbs/bootstrap", "scss", BOOTSTRAP_PATH, tag=version)


@task()
def ensure_bootstrap(_: Context) -> None:
    """Ensure the Bootstrap SCSS sources exist locally before builds run."""
    if not (BOOTSTRAP_PATH / "bootstrap.scss").exists():
        get_bootstrap(_)


@task()
def setup(c: Context) -> None:
    """Setup or update the ontwikkel_omgeving environment."""
    print("Setting up/updating ontwikkel_omgeving ...")

    dotenv_path = Path(".env")
    if not dotenv_path.exists():
        dotenv_path.touch()

    # hostname for defaults
    hostname = os.getenv("HOSTNAME") or socket.gethostname()

    # Core env vars
    hosting_domain = edwh.check_env(
        key="HOSTINGDOMAIN",
        default="localhost",
        comment="Hostname like meteddie.nl; edwh.nl; localhost; robin.edwh.nl",
    )
    hosting_name = edwh.check_env(
        key="APPLICATION_NAME",
        default="catalogus",
        comment="Used for routing traefik. [www.]<applicationname>.<hostingdomain>, "
        "alongside py4web which is also registered.",
    )
    project = edwh.check_env(
        key="PROJECT",
        default=os.getcwd().rsplit("/", 1)[-1].replace(".", "-"),
        comment="Name of the current directory (used for docker and traefik prefixes/suffixes, "
        "to make containers unique)",
    )

    _state_of_development = edwh.check_env(
        key="STATE_OF_DEVELOPMENT",
        default="",
        comment="ontwikkel: ONT|test: TEST|demo: DEMO |user acceptance testing: UAT|productie: PRD",
        allowed_values=StateOfDevelopment.options,
    )

    state_of_development = StateOfDevelopment.from_key(_state_of_development)

    internet_accessible = (
        edwh.check_env(
            key="INTERNET_ACCESSIBLE",
            default="1" if state_of_development.is_productie() else "0",
            comment="If local you may use default (unsafe) passwords, but not if it is publicly accessible",
            allowed_values=("0", "1"),
        )
        == "1"
    )

    edwh.check_env(
        key="CERTRESOLVER",
        default="letsencrypt" if internet_accessible else "default",
        comment="which certresolver to use - default|staging|letsencrypt. See reverse proxy setup for options",
        allowed_values=("default", "staging", "letsencrypt"),
    )

    if is_dev := state_of_development.is_ontwikkel():
        use_default = (
            edwh.check_env(
                key="ACCEPT_DEFAULTS",
                default="1",
                comment="Do you want to accept default (development) values for the rest of the env variables?",
                allowed_values=("1", "0"),
            )
            == "1"
        )
    else:
        use_default = False

    # Debug / replicas
    debug_mode = (
        edwh.check_env(
            key="PY4WEB_DEBUG_MODE",
            default="1" if is_dev else "0",
            comment="'1' in ontwikkeling, '0' in productie.",
            force_default=use_default,
        )
        == "1"
    )
    edwh.check_env(
        key="PY4WEB_REPLICAS",
        default="1" if debug_mode else "3",
        comment="Number of replicas for p4w. 1 in development, 3 in production.",
        force_default=use_default,
    )

    # Schema + secrets
    edwh.set_env_value(dotenv_path, "SCHEMA_VERSION", edwh.tasks.calculate_schema_hash())

    edwh.check_env(
        key="PY4WEB_SUBDOMAIN",
        # todo: hoe heet de keuzemodule nou tegenwoordig? Voor nu draait ie op subdomein `wizard`
        default="wizard",
        comment="Op welk subdomein moet py4web (keuze visie webapp module canvas wizard) draaien?",
        force_default=use_default,
    )

    # applog keys
    for app in ("PY4WEB", "TOOLS"):
        edwh.check_env(
            key=f"{app}_APPLOG_ID",
            default=f"{app}_{hosting_domain.strip().replace('.', '_').upper()}",
            comment=f"{app} applog id, should be registered at applog when transferred over HTTPS.",
            force_default=use_default,
        )
        edwh.check_env(
            key=f"{app}_APPLOG_KEY",
            default=random.randbytes(32).hex(),
            comment=f"{app} applog key, should be registered at applog when transferred over HTTPS.",
            force_default=use_default,
        )

    edwh.check_env(
        key="EMAIL_VERIFICATION_SEED",
        default=edwh.tasks.generate_password(c, silent=True),
        comment="Seed used for email verification code hashing.",
        force_default=use_default,
    )
    edwh.check_env(
        key="DEFAULT_FROM_ADDRESS",
        default=f"{hosting_name}@{hosting_domain}",
        comment="From address for various emails",
        force_default=use_default,
    )

    # Notifications
    edwh.check_env(
        key="NTFY_ERROR_URL",
        default=f"EDWH-DEV-ERROR-{hostname}",
        comment="Ntfy.sh error channel, use production-specific channel in production.",
        prefix="https://ntfy.sh/",
        force_default=use_default,
    )
    edwh.check_env(
        key="NTFY_WARNING_URL",
        default=f"EDWH-DEV-WARNING-{hostname}",
        comment="Ntfy.sh warning channel.",
        prefix="https://ntfy.sh/",
        force_default=use_default,
    )
    edwh.check_env(
        key="NTFY_SORT_URL",
        default=f"EDWH-DEV-SORTEERHOED-{hostname}",
        comment="Ntfy.sh sorteerhoed channel.",
        prefix="https://ntfy.sh/",
        force_default=use_default,
    )

    # Redis + Postgres
    edwh.check_env(
        key="REDIS_PORT",
        default=str(edwh.tasks.next_value(c, "REDIS_PORT", 6379)),
        comment="Port to host Redis on. Avoid collisions when using multiple projects, auto-discovered default",
        force_default=use_default,
    )
    postgres_username = edwh.check_env(
        key="POSTGRES_USERNAME",
        default="postgres",
        comment="Username to use with the postgres database",
        force_default=use_default,
    )
    postgres_password = edwh.check_env(
        key="POSTGRES_PASSWORD",
        default="password" if is_dev else edwh.tasks.generate_password(c, silent=True),
        comment="Password for pgpool/postgres to access the backend database",
        force_default=use_default,
    )
    pgpool_port = edwh.check_env(
        key="PGPOOL_PORT",
        default=str(edwh.tasks.next_value(c, "PGPOOL_PORT", 5432)),
        comment="Port to host pgpool on. Avoid collisions when using multiple projects, auto-discovered default",
        force_default=use_default,
    )
    postgres_database = edwh.check_env(
        key="POSTGRES_DATABASE",
        default="backend",
        comment="Name of the database for the backend database",
        force_default=use_default,
    )

    edwh.check_env(
        key="INSIDE_DOCKER_POSTGRES_URI",
        default=f"postgres://{postgres_username}:{postgres_password}@pgpool:5432/{postgres_database}",
        comment="The pydal compatible URI used to connect to the database, WITHIN the docker environment",
        force_default=use_default,
    )
    edwh.check_env(
        key="OUTSIDE_DOCKER_POSTGRES_URI",
        default=f"postgres://{postgres_username}:{postgres_password}@127.0.0.1:{pgpool_port}/{postgres_database}",
        comment="The pydal compatible URI used to connect to the database, OUTSIDE the docker environment",
        force_default=use_default,
    )
    edwh.check_env(
        key="INSIDE_DOCKER_PG_DUMP_URI",
        default=f"postgres://{postgres_username}:{postgres_password}@pg-0:5432/{postgres_database}",
        comment="The pydal compatible URI used for pg_dump inside docker",
        force_default=use_default,
    )

    edwh.check_env(
        key="PGSTATS_PORT",
        default=str(edwh.tasks.next_value(c, "PGSTATS_PORT", 4000)),
        comment="Port to host pgstats exporter on. Avoid collisions when using multiple projects.",
        force_default=use_default,
    )

    # Object storage
    edwh.check_env(
        key="B2_ATTACHMENTS_BUCKETNAME",
        default="nl-edwh-onix-prd",
        comment="Backblaze B2 bucket to store attachments",
        force_default=use_default,
    )
    edwh.check_env(
        key="B2_ATTACHMENTS_KEYID",
        default="0030834038a6da40000000018" if not use_default else "",
        comment="Keyid of the Backblaze b2",
        force_default=use_default,
    )
    edwh.check_env(
        key="B2_ATTACHMENTS_KEY",
        default="K00xxxxxxxxxxxxxxxxxxxxxxxNMs" if not use_default else "",
        comment="Secret key for given backblaze account",
        force_default=use_default,
    )

    edwh.check_env(
        key="B2_HASH_SALT",
        default="Haziness...Unmade",
        comment="Salt to make unique+reproducible prefix for filenames.",
        force_default=use_default,
    )

    # Mailgun
    edwh.check_env(
        key="MAILGUN_DOMAIN",
        default="mg.edwh.nl",
        comment="Mailgun url to send email, used to craft https://api.mailgun.net/v3/MAILGUN_DOMAIN/messages",
        force_default=use_default,
    )
    edwh.check_env(
        key="MAILGUN_API_KEY",
        default="bd1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx31a",
        comment="Mailgun API authentication",
        force_default=use_default,
    )
    edwh.check_env(
        key="MAILGUN_NEXT_RETRY_DELAY_EXPRESSION",
        default="10",
        comment="Mailgun retry backoff expression, '10' for dev, '1.7**retries' in production",
        force_default=use_default,
    )
    edwh.check_env(
        key="MAILGUN_MAX_RETRIES",
        default="15",
        comment="Max retries per Mailgun job, 100 for dev, 20 in production",
        force_default=use_default,
    )

    # Upload retry settings
    edwh.check_env(
        key="UPLOAD_MAX_RETRIES",
        default="100",
        comment="Max retries per upload job, 100 in dev, maybe more in production",
        force_default=use_default,
    )
    edwh.check_env(
        key="UPLOAD_NEXT_RETRY_DELAY_EXPRESSION",
        default="1.3**retries",
        comment="Exponential backoff for uploads, '1.3**retries' in dev",
        force_default=use_default,
    )

    # Docker tag
    edwh.check_env(
        key="DOCKER_TAG",
        default=f"{project}_latest",
        comment="'latest' in ontwikkeling, 'PRD' in productie.",
        force_default=use_default,
    )

    # Extra sync/export (from second setup)
    # setup_sync(c)

    # Misc
    edwh.check_env(
        key="EDDIE_EMAIL",
        default="eddie@edwh.nl",
        comment="Email address of the Eddie shared inbox for notifications. "
        "Use your own in development or eddie@educationwarehouse.nl in production.",
        force_default=use_default,
    )

    edwh.check_env(
        key="PGQ_WORKERS",
        default="3",
        comment="Amount of pgq workers. Please use at least 3!",
        force_default=use_default,
    )

    edwh.check_env(
        key="PY4WEB_SESSION_SECRET",
        default=str(uuid.uuid4()),
        comment="Session gid for py4web",
        force_default=use_default,
    )
    edwh.check_env(
        key="ENTREE_CLIENT_ENDPOINT",
        default="oidcng.entree.kennisnet.nl" if state_of_development.is_productie() else "oidcng.entree-s.kennisnet.nl",
        comment="Kennisnet Entree OIDC endpoint "
        "(oidcng.entree.kennisnet.nl for production, oidcng.entree-s.kennisnet.nl for development).",
        force_default=use_default,
    )
    edwh.check_env(
        key="ENTREE_CLIENT_ID",
        default="",
        comment="Kennisnet Entree Client ID for OIDC authentication.",
    )
    edwh.check_env(
        key="ENTREE_CLIENT_SECRET",
        default="",
        comment="Kennisnet Entree Client Secret for OIDC authentication.",
    )

    setup_migrate_seed(c, use_default=use_default)
    setup_testing_snapshot(c, use_default=use_default)

    # setup_grist(c, use_default=use_default)
    setup_py4web_password(c, use_default=use_default)

    setup_smtp(c, dotenv_path, str(state_of_development))
    uptimerobot_autoadd(c)

    # Permissions and setup
    print("Setting file and directory permissions")
    c.sudo("chown -R 1050:1050 migrate/flags")
    c.sudo("chown -R 1050:1050 migrate/data")
    c.sudo("chown -R 1050:1050 shared_cache")

    edwh.tasks.set_permissions(c, "py4web/apps")
    edwh.tasks.set_permissions(c, "shared_cache", filepermissions=666, directorypermissions=777)
    edwh.tasks.set_permissions(c, "shared_applog")
    edwh.tasks.set_permissions(c, "shared_user_storage")

    generate_jwt_key(c)
    bundler_build(c)

    print("Use `edwh up` to start docker containers.")


@task()
def queue_pgq(ctx: Context, entrypoint: str, payload: str = "{}", container: str = "pgq-scrapers") -> None:
    """Enqueue an entrypoint with optional payload in the pgq job system."""
    ctx.run(f"{DOCKER_COMPOSE} exec -T {container} pgskewer enqueue {shlex.quote(entrypoint)} {shlex.quote(payload)}")


def find_ty() -> str:
    """Use ty's own logic to find the required binary."""
    from ty import __main__ as ty

    return ty.find_ty_bin()


@task()
def lint(ctx: Context) -> None:
    """Extend `edwh lint` with `ty check`."""
    ty = find_ty()

    command = [ty, "check", "--quiet"]

    success = bool(run_pty(ctx, *command))
    color: Color = "green" if success else "red"
    cprint("⬤ ty", color=color)

    if not success:
        raise SystemExit(1)


def build_rsync_command(source: Path, test: bool = False, files: bool = False) -> str:
    """Create the `rsync` command for the requested params."""
    public_target = os.getenv("PUBLIC_TARGET", "")
    private_apps = os.getenv("PRIVATE_APPS", "")
    target = pathlib.Path(__file__).parent.parent.resolve() / public_target
    exclude = "--exclude .git/ "

    if not public_target:
        target = pathlib.Path(__file__).parent.parent.resolve() / "onzeleermiddelen-public"

    for app in private_apps.split(","):
        exclude += f"--exclude py4web/apps/{app} "

    params = "-rn" if test else "-r"
    params += "v" if files else ""

    return f"rsync {params} {exclude} --filter=':- .gitignore'  {source}/ {target}"


@task()
def prepare_public(c: Context, test: bool = False, files: bool = False) -> None:
    """Prepares local repo for public release.

    Args:
        c: Invoke context.
        test: Enable dry-run mode (execute steps without changing files).
        files: Show all copied files in command output.

    """
    source = pathlib.Path(__file__).parent.resolve()
    dotenv_path = source / ".env"
    load_dotenv(dotenv_path=dotenv_path)

    rsync = build_rsync_command(source, test=test, files=files)
    c.run(rsync)
