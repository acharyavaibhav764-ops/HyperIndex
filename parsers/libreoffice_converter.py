import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Final

from docling_core.types.doc import DoclingDocument

from config import settings
from .base import BaseParser
from .docling_parser import DoclingParser

logger = logging.getLogger(__name__)


class LibreOfficeNotFoundError(RuntimeError):
    pass


class LibreOfficeConversionError(RuntimeError):
    pass


def find_libreoffice_binary() -> str:
    # 1. Configured path or env override
    if settings.libreoffice_binary:
        configured = Path(settings.libreoffice_binary)
        if configured.is_file():
            return str(configured)
        which = shutil.which(settings.libreoffice_binary)
        if which:
            return which

    # 2. PATH resolution
    for name in ("libreoffice", "soffice"):
        which = shutil.which(name)
        if which:
            return which

    # 3. Standard Windows install paths
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for win_path in [
        Path(program_files) / "LibreOffice" / "program" / "soffice.exe",
        Path(program_files_x86) / "LibreOffice" / "program" / "soffice.exe",
    ]:
        if win_path.is_file():
            return str(win_path)

    # 4. Standard Linux / macOS paths
    for unix_path in [
        Path("/usr/bin/libreoffice"),
        Path("/usr/bin/soffice"),
        Path("/usr/local/bin/soffice"),
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    ]:
        if unix_path.is_file():
            return str(unix_path)

    raise LibreOfficeNotFoundError(
        "LibreOffice executable not found. Legacy .doc/.ppt conversion requires "
        "LibreOffice installed on PATH or configured via LIBREOFFICE_BINARY."
    )


class LibreOfficeConverter(BaseParser):
    SUPPORTED_EXTENSIONS: Final[frozenset[str]] = frozenset({".doc", ".ppt"})
    TARGET_FORMAT_MAP: Final[dict[str, str]] = {".doc": "docx", ".ppt": "pptx"}

    def __init__(
        self,
        docling_parser: DoclingParser | None = None,
        timeout: int | None = None,
    ) -> None:
        self._docling_parser = docling_parser or DoclingParser()
        self._timeout = timeout or settings.libreoffice_timeout_seconds

    def can_handle(self, ext: str) -> bool:
        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def convert_to_openxml(self, file_bytes: bytes, filename: str) -> tuple[bytes, str]:
        source_ext = Path(filename).suffix.lower()
        if source_ext not in self.TARGET_FORMAT_MAP:
            raise ValueError(f"Unsupported legacy format: '{source_ext}'")

        target_format = self.TARGET_FORMAT_MAP[source_ext]
        target_ext = f".{target_format}"
        binary = find_libreoffice_binary()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_file = temp_path / f"input{source_ext}"
            input_file.write_bytes(file_bytes)

            # Isolated user profile prevents profile lock conflicts under concurrency
            user_profile = (temp_path / "lo_profile").as_uri()

            cmd = [
                binary,
                "--headless",
                "--invisible",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                f"-env:UserInstallation={user_profile}",
                "--convert-to",
                target_format,
                "--outdir",
                str(temp_path),
                str(input_file),
            ]

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise LibreOfficeConversionError(
                    f"LibreOffice conversion timed out after {self._timeout}s for '{filename}'"
                ) from exc
            except FileNotFoundError as exc:
                raise LibreOfficeNotFoundError(
                    f"Failed to execute LibreOffice binary: {binary}"
                ) from exc

            if proc.returncode != 0:
                err_msg = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
                raise LibreOfficeConversionError(
                    f"LibreOffice conversion failed for '{filename}': {err_msg}"
                )

            expected_output = temp_path / f"input{target_ext}"
            if not expected_output.exists() or expected_output.stat().st_size == 0:
                raise LibreOfficeConversionError(
                    f"LibreOffice failed to produce output '{expected_output.name}' for '{filename}'"
                )

            converted_bytes = expected_output.read_bytes()
            out_filename = Path(filename).with_suffix(target_ext).name
            return converted_bytes, out_filename

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        converted_bytes, target_filename = self.convert_to_openxml(file_bytes, filename)
        return self._docling_parser.parse(converted_bytes, target_filename, **kwargs)
