"""Configuration shared by Kennisnet catalogue integrations."""

import os

from yayarl import URL

KENNISNET_CATALOGUE_BASE_URL = URL(
    os.environ.get("KENNISNET_CATALOGUE_BASE_URL", "https://catalogus.edu-v.kennisnet.nl").rstrip("/")
)
