"""Class to read KNXProj ZIP files."""
from __future__ import annotations

import base64
from collections.abc import Iterator
from contextlib import contextmanager
import logging
from pathlib import Path
import re
from typing import IO
from zipfile import Path as ZipPath, ZipFile, ZipInfo

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import pyzipper

from xknxproject.exceptions import (
    InvalidPasswordException,
    ProjectNotFoundException,
    UnexpectedFileContent,
)
from xknxproject.util import is_ets4_project, is_ets6_project

_LOGGER = logging.getLogger("xknxproject.log")


class KNXProjContents:
    """Class for holding the contents of a KNXProj file."""

    def __init__(
        self,
        root_zip: ZipFile,
        project_archive: ZipFile,
        project_relative_path: str,
        xml_namespace: str,
    ):
        """Initialize a KNXProjContents."""
        self._project_archive = project_archive
        self._project_relative_path = project_relative_path
        self.root = root_zip
        self.root_path = ZipPath(root_zip)
        self.xml_namespace = xml_namespace

    def open_project_0(self) -> IO[bytes]:
        """Open the project 0.xml file."""
        return self._project_archive.open(
            f"{self._project_relative_path}0.xml",
            mode="r",
        )

    def open_project_meta(self) -> IO[bytes]:
        """Open the project.xml file."""
        schema_version = _get_schema_version(self.xml_namespace)
        project_filename = (
            "Project.xml" if is_ets4_project(schema_version) else "project.xml"
        )
        return self._project_archive.open(
            f"{self._project_relative_path}{project_filename}",
            mode="r",
        )


@contextmanager
def extract(
    archive_path: Path, password: str | None = None
) -> Iterator[KNXProjContents]:
    """Provide the contents of a KNXProj file."""
    _LOGGER.debug('Opening KNX Project file "%s"', archive_path)
    with ZipFile(archive_path, mode="r") as zip_archive:
        project_id = _get_project_id(zip_archive)
        xml_namespace = _get_xml_namespace(zip_archive)

        password_protected: bool
        try:
            protected_info = zip_archive.getinfo(name=project_id + ".zip")
        except KeyError:
            _LOGGER.debug("Project %s is not password protected", project_id)
            password_protected = False
            # move yield out of except block to clear exception context
        else:
            _LOGGER.debug("Project %s is password protected", project_id)
            password_protected = True

        if not password_protected:
            yield KNXProjContents(
                root_zip=zip_archive,
                project_archive=zip_archive,
                project_relative_path=f"{project_id}/",
                xml_namespace=xml_namespace,
            )
            return
        # Password protected project
        schema_version = _get_schema_version(xml_namespace)
        with _extract_protected_project_file(
            zip_archive, protected_info, password, schema_version
        ) as project_zip:
            # ZipPath is not supported by pyzipper thus we use
            # string name for project_relative_path
            yield KNXProjContents(
                root_zip=zip_archive,
                project_archive=project_zip,
                project_relative_path="",
                xml_namespace=xml_namespace,
            )


def _get_project_id(zip_archive: ZipFile) -> str:
    """Get the project id."""
    for info in zip_archive.infolist():
        if info.filename.startswith("P-") and info.filename.endswith(".signature"):
            return info.filename.removesuffix(".signature")

    raise ProjectNotFoundException("Signature file not found.")


@contextmanager
def _extract_protected_project_file(
    archive_zip: ZipFile, info: ZipInfo, password: str | None, schema_version: int
) -> Iterator[ZipFile]:
    """Unzip a protected ETS5/6 project file."""
    if not password:
        raise InvalidPasswordException("Password required.")

    project_archive: ZipFile
    if not is_ets6_project(schema_version):
        try:
            project_archive = ZipFile(archive_zip.open(info, mode="r"), mode="r")
            project_archive.setpassword(password.encode("utf-8"))
            yield project_archive
        except RuntimeError as exception:
            raise InvalidPasswordException("Invalid password.") from exception
    else:
        try:
            project_archive = pyzipper.AESZipFile(
                archive_zip.open(info, mode="r"), mode="r"
            )
            project_archive.setpassword(_generate_ets6_zip_password(password))
            yield project_archive
        except RuntimeError as exception:
            raise InvalidPasswordException("Invalid password.") from exception


def _get_xml_namespace(project_zip: ZipFile) -> str:
    """Get the XML namespace of the project."""
    with project_zip.open("knx_master.xml", mode="r") as master:
        for line_number, line in enumerate(master, start=1):
            if line_number == 2:
                try:
                    namespace_match = re.match(
                        r".+ xmlns=\"(.+?)\"",
                        line.decode(),
                    )
                    namespace = namespace_match.group(1)  # type: ignore[union-attr]
                except (AttributeError, IndexError, UnicodeDecodeError):
                    _LOGGER.error("Could not parse XML namespace from %s", line)
                    raise UnexpectedFileContent("Could not parse XML namespace.")

        _LOGGER.debug("Namespace: %s", namespace)
        return namespace


def _get_schema_version(namespace: str) -> int:
    """Get the schema version of the project."""
    try:
        schema_version = int(namespace.split("/")[-1])
    except ValueError:
        _LOGGER.error("Could not parse schema version from %s", namespace)
        raise UnexpectedFileContent("Could not parse schema version.")

    _LOGGER.debug("Schema version: %s", schema_version)
    return schema_version


def _generate_ets6_zip_password(password: str) -> bytes:
    """Generate ZIP archive password."""
    return base64.b64encode(
        PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"21.project.ets.knx.org",
            iterations=65536,
        ).derive(password.encode("utf-16-le"))
    )
