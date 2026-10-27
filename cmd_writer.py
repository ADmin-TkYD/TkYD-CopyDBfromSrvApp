"""
CmdWriter — модуль для генерации управляющих файлов команд,
используемых внешними процессами (например, монитором или сервисом),
которые отслеживают появление файлов ZMon$tor.tmp и Z_Cmnd.tmp.

Формат команды:
    [0x07, <db_number>, 0x00]
"""

__version__ = '3.0.5'

from logging import getLogger
from pathlib import Path
from typing import Tuple

log = getLogger('cmd_writer')


class CmdWriter:
    """
    Класс для создания управляющих файлов в указанной директории.

    Создаёт два файла:
        - ZMon$tor.tmp — пустой файл-маркер, сигнализирующий мониторингу о наличии команды.
        - Z_Cmnd.tmp — файл с бинарной командой, содержащей номер базы.
    """

    def __init__(self, base_dir: Path):
        """
        Инициализация генератора команд.

        :param base_dir: Директория, в которую будут записываться управляющие файлы.
                         Создаётся автоматически, если отсутствует.
        """
        self.base_dir = base_dir

    @staticmethod
    def make_cmd(db_num: int) -> bytes:
        """
        Сформировать бинарную команду для указанного номера базы.

        Формат команды:
            0x07 — код операции
            db_num & 0xFF — номер базы (ограниченный до одного байта)
            0x00 — завершающий байт

        :param db_num: Номер базы (0–255; значения выше будут усечены до младшего байта).
        :return: Байт-строка команды.
        """
        return bytes([0x07, db_num & 0xFF, 0x00])

    def write_cmd_file(self, db_number: int) -> Tuple[Path, bytes]:
        """
        Создать управляющие файлы для указанного номера базы.

        Действия:
            1) Создаёт директорию base_dir, если её нет.
            2) Пытается создать пустой файл ZMon$tor.tmp.
               Если файл занят или уже существует — пишет debug-сообщение.
            3) Создаёт файл Z_Cmnd.tmp и записывает в него бинарную команду.
            4) Возвращает путь к файлу команды и сами данные.

        :param db_number: Номер базы, для которой формируется команда.
        :return: (путь к файлу команды, бинарные данные команды)
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)

        mon_path = self.base_dir / 'ZMon$tor.tmp'
        try:
            # Создаём пустой файл-маркер
            with open(mon_path, 'wb'):
                log.debug(f'Created monitor file (zero-length): "{mon_path}"')
        except (PermissionError, OSError) as e:
            # Если монитор уже работает или файл заблокирован — это нормальная ситуация
            log.debug(f'Monitor is already running or cannot create file: "{e}"')

        data = self.make_cmd(db_number)
        path = self.base_dir / 'Z_Cmnd.tmp'

        # Записываем команду
        with open(path, 'wb') as f:
            f.write(data)

        log.info(
            'Command file created: %s | DB #%d | Data: %s',
            path, db_number, data.hex()
        )

        return path, data
