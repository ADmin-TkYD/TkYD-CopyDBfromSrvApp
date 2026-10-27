__version__ = '3.0.5'

from configparser import ConfigParser
from pathlib import Path
from typing import Optional, Dict, List


class Config:
    """
    Обёртка над ConfigParser, предоставляющая удобные методы
    для получения параметров из config.ini.

    Каждый метод возвращает словарь строковых значений,
    которые затем преобразуются вызывающим кодом (в float, int, Path и т.д.).
    """

    def __init__(self, parser: ConfigParser):
        """
        Инициализация объекта конфигурации.

        :param parser: Загруженный ConfigParser.
        """
        self._p = parser

    def get_paths(self) -> Dict[str, Optional[str]]:
        """
        Получить параметры секции [Paths].

        Возвращает:
            base_dir — путь к директории с SLS_SERV.CFG и tmp-файлами;
            backup_root — путь к каталогу бэкапов (если задан).

        Значения возвращаются как строки или None.

        :return: dict с ключами 'base_dir' и 'backup_root'.
        """
        base_dir = self._p.get('Paths', 'base_dir', fallback=None)
        backup_root = self._p.get('Paths', 'backup_root', fallback=None)
        return {'base_dir': base_dir, 'backup_root': backup_root}

    def get_backup(self) -> Dict[str, Optional[str]]:
        """
        Получить параметры секции [Backup].

        Все значения возвращаются как строки, даже если они числовые.
        Преобразование выполняется вызывающим кодом.

        Параметры:
            creation_retry_interval — интервал опроса появления .dbx/.db-;
            creation_retry_timeout  — таймаут ожидания начала создания;
            dbx_poll_interval       — интервал опроса появления финального .dbx;
            dbx_wait_timeout        — таймаут ожидания финального .dbx;
            search_in_user_subdir   — искать ли базы в USER/<stem>.

        :return: dict с параметрами секции Backup.
        """
        return {
            'creation_retry_interval': self._p.get('Backup', 'creation_retry_interval', fallback='3'),
            'creation_retry_timeout': self._p.get('Backup', 'creation_retry_timeout', fallback='0'),
            'dbx_poll_interval': self._p.get('Backup', 'dbx_poll_interval', fallback='2'),
            'dbx_wait_timeout': self._p.get('Backup', 'dbx_wait_timeout', fallback='0'),
            'search_in_user_subdir': self._p.get('Backup', 'search_in_user_subdir', fallback='true'),
        }

    def get_archive(self) -> Dict[str, Optional[str]]:
        """
        Получить параметры секции [Archive].

        Параметры:
            prefer_7z             — использовать ли 7z, если найден;
            seven_zip_compression — уровень сжатия 7z (0–9);
            archive_output_dir    — директория для сохранения архивов.

        Все значения возвращаются как строки.

        :return: dict с параметрами секции Archive.
        """
        return {
            'prefer_7z': self._p.get('Archive', 'prefer_7z', fallback='true'),
            'seven_zip_compression': self._p.get('Archive', 'seven_zip_compression', fallback='9'),
            'archive_output_dir': self._p.get('Archive', 'archive_output_dir', fallback=''),
        }

    def get_logging(self) -> Dict[str, Optional[str]]:
        """
        Получить параметры секции [Logging].

        Параметры:
            level — уровень логирования (INFO, DEBUG, WARNING...);
            file  — путь к файлу лога (или пустая строка).

        :return: dict с параметрами секции Logging.
        """
        return {
            'level': self._p.get('Logging', 'level', fallback='ERROR'),
            'file': self._p.get('Logging', 'file', fallback=''),
        }


def load_config(ini_locations: List[Path]) -> Config:
    """
    Загрузить config.ini из списка возможных директорий.

    Перебирает переданные пути и ищет файл config.ini.
    Первый найденный файл загружается и используется.

    Если файл не найден ни в одном месте:
        — создаётся пустой ConfigParser,
        — все параметры будут возвращаться как значения по умолчанию.

    :param ini_locations: Список директорий, где искать config.ini.
    :return: Объект Config, обёртывающий загруженный или пустой ConfigParser.
    """
    parser = ConfigParser()
    for loc in ini_locations:
        ini_path = loc / 'config.ini'
        if ini_path.exists():
            parser.read(ini_path, encoding='utf-8')
            return Config(parser)

    # Если не нашли, создаём пустой парсер — значения будут по умолчанию
    return Config(parser)
