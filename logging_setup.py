__version__ = '3.0.5'

import logging
from pathlib import Path
from typing import Optional


def setup_logging(level: str = 'ERROR', logfile: Optional[str] = None) -> None:
    """
    Настроить систему логирования приложения.

    Функция конфигурирует logging.basicConfig с двумя возможными типами выводов:
        • потоковый вывод (stdout) — всегда включён;
        • вывод в файл — включается, если указан параметр logfile.

    Особенности:
        • директория для файла лога создаётся автоматически;
        • уровень логирования задаётся строкой (INFO, DEBUG, WARNING и т.д.);
        • формат сообщений включает имя файла, номер строки, время, уровень, логгер и имя функции.

    :param level:
        Строка с уровнем логирования (например: "INFO", "DEBUG", "ERROR").
        Регистр не важен. Если уровень неизвестен — используется INFO.

    :param logfile:
        Путь к файлу лога или None.
        Если None — лог пишется только в консоль.

    :return:
        None. Настройка применяется глобально через logging.basicConfig().
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]

    if logfile:
        log_path = Path(logfile)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding='utf-8'))

    logging.basicConfig(
        level=numeric_level,
        format=(
            '%(filename)-18s:%(lineno)-4d '
            '| %(asctime)-20s | %(levelname)-8s | %(name)-15s | %(funcName)-28s | %(message)s'
        ),
        handlers=handlers
    )
