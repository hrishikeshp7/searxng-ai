# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frozen version info.

searx/version.py falls back to shelling out to `git` to compute the running
version, which requires both a `git` binary and the repository's history to
be present at runtime. Deployment targets that ship only the application
source (e.g. a Heroku buildpack slug) have neither, which crashes the app at
import time. This module is generated once (see `searx.version.get_information`)
and lets the runtime skip the git subprocess calls entirely.
"""

VERSION_STRING = "2026.9.25+66321ff21"
VERSION_TAG = "2026.9.25+66321ff21"
DOCKER_TAG = "2026.9.25-66321ff21"
GIT_URL = "https://github.com/hrishikeshp7/searxng-ai"
GIT_BRANCH = "master"
