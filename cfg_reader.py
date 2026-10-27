__version__ = '3.0.5'

from logging import getLogger
from pathlib import Path
from typing import List

log = getLogger('cfg_reader')


class ConfigReader:
    """
    Читает файл SLS_SERV.CFG и извлекает список путей к .DBX‑файлам.

    Файл конфигурации содержит строки, каждая из которых может быть путём к базе.
    Метод load_dbx_list() выбирает только строки, оканчивающиеся на ".DBX"
    (регистр не имеет значения), обрезает пробелы и возвращает список строк.
    """

    def __init__(self, cfg_path: Path):
        """
        Инициализация читателя конфигурации.

        :param cfg_path: Путь к файлу SLS_SERV.CFG.
        """
        self.cfg_path = cfg_path

    def load_dbx_list(self) -> List[str]:
        """
        Загрузить список путей к .DBX‑файлам из конфигурационного файла.

        Действия:
            1) Проверяет существование файла.
            2) Читает файл в кодировке CP866 (стандартная OEM‑кодировка для старых систем).
            3) Фильтрует строки, оставляя только те, что оканчиваются на ".DBX".
            4) Возвращает список строк без пробелов по краям.

        :return: Список строк — путей к .DBX‑файлам.
        :raises FileNotFoundError: Если файл конфигурации отсутствует.
        """
        if not self.cfg_path.exists():
            log.error('Configuration file not found: %s', self.cfg_path)
            raise FileNotFoundError(self.cfg_path)

        with open(self.cfg_path, 'r', encoding='cp866', errors='replace') as f:
            lines = f.readlines()

        dbx_list = [
            line.strip()
            for line in lines
            if line.strip().upper().endswith('.DBX')
        ]

        log.info('Loaded %d DBX entries from %s', len(dbx_list), self.cfg_path)
        return dbx_list
