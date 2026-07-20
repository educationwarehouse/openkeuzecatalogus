"""Restart endpoint wiring for the py4web container."""

import os
import sys

from common.settings import RESTART_FLAG

from py4web import action, request

SUBDOMAIN = os.getenv("PY4WEB_SUBDOMAIN")  # or os.environ["APPLICATION_NAME"]


if RESTART_SECRET := os.environ.get("PY4WEB_RESTART_SECRET"):
    RESTART_URI = (
        f"https://{SUBDOMAIN}.{os.environ['HOSTINGDOMAIN']}/restart/{RESTART_SECRET}"
        if SUBDOMAIN
        else f"https://{os.environ['HOSTINGDOMAIN']}/restart/{RESTART_SECRET}"
    )
    print(
        "RESTART uri:",
        RESTART_URI,
    )

    # example usage in Pycharm:
    # Tools > File Watchers
    # + > Custom
    # name: restart py4web
    # file type: Python
    # scope: Open Files
    # program: curl
    # Arguments: -ak <RESTART_URI>

    @action("index/<secret>")
    @action("index")
    def index(secret: str | None = None) -> str:
        """Validate the restart secret and exit the container when it matches."""
        data = request.query or request.forms or request.json

        secret = secret or data.get("secret")

        # [Code in workbench voor hetstarten server wijzigen:#44@EWCore](https://taiga.edwh.nl/project/remco-ewcore/task/44)
        if secret != RESTART_SECRET:
            print("invalid secret received")
            return "invalid secret"

        # was just exit(1)
        # but that only works for one replica.
        # this file should be caught by _default's /healthcheck to restart each container:

        # touch /shared_cache/restart.flag
        RESTART_FLAG.touch()
        sys.exit(1)

    @action(RESTART_SECRET)
    def without_index() -> str:
        """Alias that forwards to the main restart handler."""
        return index(RESTART_SECRET)
