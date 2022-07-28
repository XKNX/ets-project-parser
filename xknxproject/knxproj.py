"""ETS Project Parser is a library to parse ETS project files."""
from __future__ import annotations

import logging

from xknxproject import __version__
from xknxproject.models import KNXProject
from xknxproject.xml import XMLParser
from xknxproject.zip.extractor import extract

logger = logging.getLogger("xknxproject.log")


class KNXProj:
    """Class for parsing ETS project files."""

    def __init__(self, archive_name: str, archive_password: str | None = None):
        """Initialize a KNXProjParser."""
        self.archive_name = archive_name
        self.password = archive_password

        self.version = __version__

    def parse(self) -> KNXProject:
        """Parse the KNX project."""
        with extract(self.archive_name, self.password) as knx_project_content:
            return XMLParser(knx_project_content).parse()
