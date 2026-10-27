"""
Backup Archiver — утилита для отслеживания появления .dbx-бэкапов,
ожидания завершения их формирования и последующего архивирования.
Публичный API:
    - get_user_db_dir(db_stem)
    - ensure_user_db_dir(db_stem)
    - wait_until_creation_starts_for(db_stem)
    - wait_for_final_dbx_for(db_stem)
    - archive_file(final_dbx)
"""

__version__ = '3.1.1'  # bumped patch version for the fix

from logging import getLogger
from asyncio import get_event_loop, sleep as aio_sleep
from os import environ, pathsep
from subprocess import run as sub_run, PIPE
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from time import time as t_time

log = getLogger('backup_archiver')


class SevenZipLocator:
    """Локатор 7z.exe — остаётся вспомогательным классом."""
    @staticmethod
    def find_7z() -> Optional[Path]:
        exe = Path('7z.exe')
        for directory in (Path(p) for p in environ.get('PATH', '').split(pathsep)):
            candidate = directory / exe
            if candidate.is_file():
                return candidate
        pf = Path(environ.get('ProgramFiles', r'C:\Program Files'))
        pfx86 = Path(environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'))
        for base in (pf, pfx86):
            candidate = base / '7-Zip' / exe
            if candidate.is_file():
                return candidate
        return None


class BackupArchiver:
    """
    Управляет ожиданием и архивированием бэкапов.
    Публичный интерфейс предназначен для использования извне (app.py).
    """

    def __init__(
        self,
        backup_root: Path,
        creation_retry_interval: float,
        creation_retry_timeout: Optional[float],
        dbx_poll_interval: float,
        dbx_wait_timeout: Optional[float],
        prefer_7z: bool,
        seven_zip_compression: int,
        archive_output_dir: Optional[Path],
        search_in_user_subdir: bool = True
    ):
        self.backup_root = backup_root
        self.creation_retry_interval = creation_retry_interval
        self.creation_retry_timeout = creation_retry_timeout
        self.dbx_poll_interval = dbx_poll_interval
        self.dbx_wait_timeout = dbx_wait_timeout
        self.prefer_7z = prefer_7z
        self.seven_zip_compression = max(0, min(9, seven_zip_compression))
        self.archive_output_dir = archive_output_dir
        self.search_in_user_subdir = search_in_user_subdir

        # Internal: timestamp (epoch seconds) of the last detected candidate file.
        # Используется для того, чтобы при ожидании финального .dbx игнорировать
        # старые файлы, которые существовали до запуска команды.
        self._last_candidate_mtime: Optional[float] = None

    # -----------------------
    # Публичные вспомогательные методы
    # -----------------------
    def get_user_db_dir(self, db_stem: str) -> Path:
        """Возвращает директорию, где ожидаются файлы базы."""
        return (self.backup_root / 'USER' / db_stem) if self.search_in_user_subdir else (self.backup_root / db_stem)

    def ensure_user_db_dir(self, db_stem: str) -> None:
        """Создаёт директорию для базы, если её нет."""
        user_db_dir = self.get_user_db_dir(db_stem)
        user_db_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------
    # Поиск кандидатов и ожидание .dbx
    # -----------------------
    @staticmethod
    def _find_candidates(root: Path, stem_ci: str) -> List[Path]:
        if not root.exists():
            return []
        res = []
        for p in root.rglob('*'):
            if p.is_file():
                ext_ci = p.suffix.casefold()
                if ext_ci in ('.dbx', '.db-') and p.stem.casefold() == stem_ci:
                    res.append(p)
        return res

    @staticmethod
    def _latest_by_mtime(paths: List[Path]) -> Optional[Path]:
        if not paths:
            return None
        return max(paths, key=lambda x: x.stat().st_mtime)

    async def wait_until_creation_starts_for(self, db_stem: str) -> Path:
        """
        Ждать появления кандидата (.dbx/.db-) для базы с указанным stem.
        Возвращает путь к последнему найденному кандидату.

        Важное изменение (фикс бага):
        При старте ожидания фиксируем текущее время (epoch seconds) и игнорируем
        все файлы с mtime меньше этой метки. Это предотвращает ситуацию, когда
        уже существующий старый .dbx воспринимается как новый.
        """
        user_db_dir = self.get_user_db_dir(db_stem)
        stem_ci = db_stem.casefold()
        # фиксируем порог времени — все файлы старше этого порога будут игнорироваться
        since_ts = t_time()
        start = get_event_loop().time()
        while True:
            candidates = self._find_candidates(user_db_dir, stem_ci)
            # фильтруем по mtime, чтобы учитывать только файлы, созданные/изменённые
            # после начала ожидания
            fresh_candidates = []
            for p in candidates:
                try:
                    m = p.stat().st_mtime
                except Exception as e:
                    log.debug('%s', e)
                    # если не удалось получить stat — пропускаем файл
                    continue
                if m >= since_ts:
                    fresh_candidates.append(p)
            if fresh_candidates:
                latest = self._latest_by_mtime(fresh_candidates)
                # сохраняем mtime кандидата для последующего ожидания финального .dbx
                try:
                    self._last_candidate_mtime = latest.stat().st_mtime
                except Exception as e:
                    log.debug('%s', e)
                    self._last_candidate_mtime = t_time()
                log.info('Detected backup start (fresh): %s', latest)
                return latest
            await aio_sleep(self.creation_retry_interval)
            if self.creation_retry_timeout and self.creation_retry_timeout > 0:
                if get_event_loop().time() - start > self.creation_retry_timeout:
                    raise TimeoutError('Timeout waiting for backup creation to start')

    async def wait_for_final_dbx_for(self, db_stem: str) -> Path:
        """
        Ждать появления финального .dbx для базы с указанным stem.
        Возвращает путь к финальному .dbx.

        Изменение: при поиске финального .dbx учитываем mtime, не меньший
        чем mtime последнего найденного кандидата (если он известен).
        Это предотвращает архивирование старых файлов, которые уже лежали в папке.
        """
        user_db_dir = self.get_user_db_dir(db_stem)
        stem_ci = db_stem.casefold()
        # если у нас есть mtime кандидата — используем его как порог,
        # иначе используем текущее время на входе (чтобы не подобрать старый файл)
        if self._last_candidate_mtime:
            since_micro_time = self._last_candidate_mtime
        else:
            since_micro_time = t_time()
        start = get_event_loop().time()
        while True:
            for p in user_db_dir.rglob('*'):
                try:
                    if not p.is_file():
                        continue
                    if p.suffix.casefold() != '.dbx':
                        continue
                    if p.stem.casefold() != stem_ci:
                        continue
                    m = p.stat().st_mtime
                    if m < since_micro_time:
                        # файл старый — игнорируем
                        continue
                    log.info('Final .dbx detected: %s', p)
                    return p
                except Exception as e:
                    log.debug('%s', e)
                    # если при stat или проверках произошла ошибка — пропускаем файл
                    continue
            await aio_sleep(self.dbx_poll_interval)
            if self.dbx_wait_timeout and self.dbx_wait_timeout > 0:
                if get_event_loop().time() - start > self.dbx_wait_timeout:
                    raise TimeoutError('Timeout waiting for .dbx to appear')

    # -----------------------
    # Архивация
    # -----------------------
    @staticmethod
    def _ts_for_file(p: Path) -> str:
        dt = datetime.fromtimestamp(p.stat().st_mtime)
        return dt.strftime('%Y.%m.%d_%H.%M')

    def _timestamped_filename(self, p: Path) -> str:
        ts = self._ts_for_file(p)
        return f'{p.stem}_{ts}{p.suffix}'

    def _resolve_archive_output_7z(self, src_file: Path) -> Path:
        base_dir = self.archive_output_dir if self.archive_output_dir else src_file.parent
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        return Path(base_dir) / f'{self._timestamped_filename(src_file)}.7z'

    def _resolve_archive_output_zip(self, src_file: Path) -> Path:
        base_dir = self.archive_output_dir if self.archive_output_dir else src_file.parent
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        return Path(base_dir) / f'{self._timestamped_filename(src_file)}.zip'

    def _archive_with_7z(self, seven_zip: Path, src_file: Path) -> Path:
        archive_path = self._resolve_archive_output_7z(src_file)
        cmd = [
            str(seven_zip),
            'a',
            '-t7z',
            f'-mx={self.seven_zip_compression}',
            str(archive_path),
            str(src_file)
        ]
        log.info('Creating 7z archive: %s', archive_path)
        result = sub_run(cmd, stdout=PIPE, stderr=PIPE, text=True)
        if result.returncode != 0:
            log.error('7z failed: %s', result.stderr)
            raise RuntimeError('7z archiving failed')
        return archive_path

    def _archive_with_zip(self, src_file: Path) -> Path:
        from shutil import which
        zip_path = self._resolve_archive_output_zip(src_file)
        base_name = zip_path.with_suffix('')
        pwsh = which('powershell') or which('pwsh')
        if pwsh:
            cmd = [
                pwsh,
                '-NoProfile',
                '-Command',
                (
                    f'Compress-Archive -LiteralPath "{str(src_file)}" '
                    f'-DestinationPath "{str(zip_path)}" -Force'
                )
            ]
            log.info('Creating ZIP via PowerShell: %s', zip_path)
            result = sub_run(cmd, stdout=PIPE, stderr=PIPE, text=True)
            if result.returncode != 0:
                log.error('Compress-Archive failed: %s', result.stderr)
                raise RuntimeError('ZIP archiving failed')
        else:
            from tempfile import TemporaryDirectory
            from shutil import copy2, make_archive
            with TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)
                copied = tmpdir_path / src_file.name
                copy2(src_file, copied)
                make_archive(str(base_name), 'zip', root_dir=str(tmpdir_path))
        return zip_path

    def archive_file(self, final_dbx: Path) -> Path:
        """
        Архивировать указанный финальный .dbx и удалить исходник.
        Возвращает путь к созданному архиву.
        """
        seven_zip_path: Optional[Path] = None
        if self.prefer_7z:
            seven_zip_path = SevenZipLocator.find_7z()

        if seven_zip_path:
            archive_path = self._archive_with_7z(seven_zip_path, final_dbx)
        else:
            log.warning('7z not found or not preferred. Using ZIP.')
            archive_path = self._archive_with_zip(final_dbx)

        # Попытка удалить исходный файл; ошибка логируется, но не прерывает процесс
        try:
            final_dbx.unlink()
            log.info('Source file removed: %s', final_dbx)
        except Exception as e:
            log.error('Failed to remove source file %s: %s', final_dbx, e)

        return archive_path
