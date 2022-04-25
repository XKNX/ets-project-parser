"""Class to read KNXProj ZIP files."""
from __future__ import annotations

import base64
from os.path import exists
import shutil
from zipfile import ZipFile, ZipInfo

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import pyzipper

from xknxproject.const import ETS6_SCHEMA_VERSION
from xknxproject.exceptions import InvalidPasswordException


class KNXProjExtractor:
    """Class for reading a KNX Project file."""

    extraction_path = "/tmp/xknxproj/"

    def __init__(self, archive_name: str, password: str | None = None):
        """Initialize a KNXProjReader class."""
        self.archive_name = archive_name
        self.password = password

    def extract(self, extract_secure_project: bool = True) -> None:
        """Read the ZIP file."""
        with ZipFile(self.archive_name) as zip_archive:
            zip_archive.extractall(self.extraction_path)
            infos: list[ZipInfo] = zip_archive.infolist()
            for info in infos:
                if ".zip" in info.filename and self.password and extract_secure_project:
                    self.unzip_protected_project_file(info)

    def cleanup(self) -> None:
        """Cleanup the extracted files."""
        if exists(self.extraction_path):
            shutil.rmtree(self.extraction_path)

    def unzip_protected_project_file(self, info: ZipInfo) -> None:
        """Unzip a protected ETS5/6 project file."""
        if not self.password:
            raise InvalidPasswordException()

        if not self._is_project_ets6():
            try:
                with ZipFile(self.extraction_path + info.filename) as project_file:
                    project_file.extractall(
                        self.extraction_path + info.filename.replace(".zip", ""),
                        pwd=self.password.encode("utf-8"),
                    )
                return
            except Exception as exception:
                raise InvalidPasswordException from exception

        if self._is_project_ets6():
            try:
                with pyzipper.AESZipFile(self.extraction_path + info.filename) as file:
                    file.pwd = self.generate_ets6_zip_password()
                    file.extractall(
                        self.extraction_path + info.filename.replace(".zip", ""),
                        pwd=self.generate_ets6_zip_password(),
                    )
            except Exception as exception:
                raise InvalidPasswordException from exception

    def _is_project_ets6(self) -> bool:
        """Check if the project is an ETS6 project."""
        with open(self.extraction_path + "knx_master.xml", encoding="utf-8") as master:
            for value in [next(master) for _ in range(2)]:
                if ETS6_SCHEMA_VERSION in value:
                    return True

        return False

    def generate_ets6_zip_password(self) -> bytes:
        """Generate ZIP archive password."""
        if not self.password:
            return bytes()

        return base64.b64encode(
            PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"21.project.ets.knx.org",
                iterations=65536,
            ).derive(self.password.encode("utf-16-le"))
        )
