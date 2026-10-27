"""
Функции для извлечения пути каталога бэкапов из файла Sls_Serv.cpy.

Файл Sls_Serv.cpy содержит бинарные данные, внутри которых может встречаться
ASCII‑строка с путём вида:

    C:\Some\Backup\Directory

Функция extract_backup_root_from_cpy ищет такой путь, используя регулярное выражение,
и возвращает его как pathlib.Path.
"""

__version__ = '3.0.5'

from logging import getLogger
from re import search as re_search
from pathlib import Path
from typing import Optional

log = getLogger('extractor')

# Максимальная длина пути в Windows (260 символов).
WIN_MAX_PATH = 260

# Читаем вдвое больше, чтобы гарантированно захватить путь даже при смещении.
READ_LIMIT = WIN_MAX_PATH * 2


def extract_backup_root_from_cpy(cpy_file: Path) -> Optional[Path]:
    """
    Извлечь путь каталога бэкапов из файла Sls_Serv.cpy.

    Функция:
        1) Проверяет существование файла.
        2) Читает первые READ_LIMIT байт (достаточно для поиска пути).
        3) Декодирует данные в текст (latin‑1, игнорируя ошибки).
        4) Ищет Windows‑путь вида "C:\\..." с помощью регулярного выражения.
        5) Возвращает найденный путь как Path или None, если путь не найден.

    Ограничения:
        - Ищется только первый подходящий путь.
        - Путь должен быть ASCII‑совместимым (latin‑1 decode).
        - Путь должен соответствовать шаблону: буква диска + обратные слэши.

    :param cpy_file: Путь к файлу Sls_Serv.cpy.
    :return: Path к каталогу бэкапов или None, если путь не найден или произошла ошибка.
    """
    try:
        if not cpy_file.exists():
            log.warning('Sls_Serv.cpy not found: %s', cpy_file)
            return None

        # Читаем ограниченный объём данных
        data = cpy_file.read_bytes()[:READ_LIMIT]

        # Декодируем максимально безопасно
        text = data.decode('latin-1', errors='ignore')

        # Регулярка для поиска Windows-пути
        pattern = r'[A-Za-z]:\\[^"\'<>|\x00-\x1f]+'
        m = re_search(pattern, text)
        if not m:
            log.warning('Backup path not found in %s', cpy_file)
            return None

        backup_root = Path(m.group(0).strip())
        log.info('Extracted backup root from cpy: %s', backup_root)
        return backup_root

    except Exception as e:
        log.error('Error parsing %s: %s', cpy_file, e)
        return None
