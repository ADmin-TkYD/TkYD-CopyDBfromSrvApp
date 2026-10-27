"""
UI — Таблица с подстрокой для деталей и интерактивным выбором.

Поведение:
  - select_from_list(dbx_list) — показывает нумерованный список полных путей и
    запрашивает выбор пользователя (числа через запятую или ALL).
  - start(selection, dbx_list) — инициализирует таблицу только для выбранных баз.
  - render() — очищает экран и рисует таблицу; очистка экрана реализована
    кроссплатформенно (ANSI + fallback на cls/clear).
  - set_status / mark_done / mark_error — обновляют состояние и перерисовывают экран.

Изменения:
  - Статусы и WinAPI‑константы оформлены как Enum/IntEnum.
  - В краткой строке теперь выводится только имя файла (basename), а не весь путь.
  - Для путей используется pathlib.Path там, где это уместно.
  - Добавлено подробное логирование в ключевых местах.
"""

__version__ = '3.1.5'

from enum import Enum, IntEnum
from logging import getLogger
from os import name as os_name, system as os_system
from sys import exit as sys_exit, stdout
from typing import List, Dict, Optional, Union
from shutil import get_terminal_size
from pathlib import Path

log = getLogger('ui')

DEFAULT_SHORT_LEN = 40


class Status(Enum):
    """Статусы записей UI (строковые значения используются для отображения)."""
    WAITING = 'Ожидание'
    CMD_SENT = 'Команда отправлена'
    CANDIDATE = 'Кандидат найден'
    WAIT_DBX = 'Ожидание .dbx'
    ARCHIVING = 'Архивирование'
    DONE = 'Готово'
    ERROR = 'Ошибка'


class WinConsoleConst(IntEnum):
    """
    WinAPI constants used for console mode manipulation.
    IntEnum позволяет безопасно использовать значения как целые числа.
    """
    STD_OUTPUT_HANDLE = -11
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def _enable_vt_mode_on_windows() -> None:
    """
    Попытка включить поддержку виртуального терминала (ANSI escape sequences)
    в консоли Windows.

    Использует WinConsoleConst. В случае неудачи логирует причину и не выбрасывает
    исключение — вызывающий код использует fallback (os.system('cls')).
    """
    if os_name != 'nt':
        return

    try:
        import ctypes
        from ctypes import byref, c_uint

        kernel32 = ctypes.windll.kernel32
        std_handle = WinConsoleConst.STD_OUTPUT_HANDLE.value
        vt_flag = WinConsoleConst.ENABLE_VIRTUAL_TERMINAL_PROCESSING.value

        h = kernel32.GetStdHandle(std_handle)
        if h is None or h == 0:
            log.debug('GetStdHandle returned invalid handle: %s', h)
            return

        mode = c_uint()
        if not kernel32.GetConsoleMode(h, byref(mode)):
            err = ctypes.GetLastError()
            log.debug('GetConsoleMode failed (GetLastError=%s)', err)
            return

        new_mode = mode.value | vt_flag
        if not kernel32.SetConsoleMode(h, new_mode):
            err = ctypes.GetLastError()
            log.debug(
                'SetConsoleMode failed (GetLastError=%s). Current mode: %s, attempted: %s',
                err, mode.value, new_mode
            )
            return

        log.info('Windows VT mode enabled (ENABLE_VIRTUAL_TERMINAL_PROCESSING set).')
    except Exception as e:
        log.debug('Failed to enable Windows VT mode: %s', e)


def _clear_screen() -> None:
    """
    Кроссплатформенная очистка экрана.

    Алгоритм:
      1) Попытаться включить VT на Windows (чтобы ANSI-последовательности работали).
      2) Попробовать очистить экран ANSI-последовательностью '\033[2J\033[H'.
      3) Если ANSI не сработал — выполнить системную команду 'cls' (Windows) или 'clear' (POSIX).
    """
    _enable_vt_mode_on_windows()

    # try:
    #     stdout.write('\033[2J\033[H')
    #     stdout.flush()
    #     log.debug('Screen cleared using ANSI escape sequences.')
    #     return
    # except Exception as e:
    #     log.debug('ANSI clear failed: %s', e)

    try:
        if os_name == 'nt':
            os_system('cls')
        else:
            os_system('clear')
        log.debug('Screen cleared using system command.')
    except Exception as e:
        log.error('Failed to clear screen using system command: %s', e)


class UIManager:
    """
    Управляет отображением таблицы с подстроками деталей и интерактивным выбором.

    Основные методы:
      - start(selected_indices, dbx_list): инициализация записей для выбранных индексов.
      - render(): полная перерисовка таблицы.
      - set_status(idx, status, action): обновление статуса и детали.
      - mark_done(idx, archive_path): пометить запись как завершённую.
      - mark_error(idx, message): пометить запись как ошибочную.
      - select_from_list(dbx_list): статический интерактивный выбор баз (1-based индексы).

    Поля:
      - entries: словарь {index: {'full_path': Path, 'status', 'detail', 'archive'}}
      - order: список индексов в порядке отображения
      - short_len: длина сокращённого имени файла в основной строке
    """

    def __init__(self, short_len: int = DEFAULT_SHORT_LEN):
        """
        :param short_len: Максимальная длина сокращённого имени файла в основной строке.
        """
        self.entries: Dict[int, Dict[str, Optional[Union[str, Path]]]] = {}
        self.order: List[int] = []
        self.short_len = short_len
        log.debug('UIManager initialized with short_len=%d', short_len)

    # -----------------------
    # Рендеринг
    # -----------------------
    @staticmethod
    def _term_width() -> int:
        """
        Получить ширину терминала в символах. При ошибке возвращает 80.
        """
        try:
            return get_terminal_size().columns
        except Exception as e:
            log.debug('Failed to get terminal size: %s', e)
            return 80

    @staticmethod
    def _shorten_name(name: str, length: int) -> str:
        """
        Сократить имя файла, сохранив начало и конец.

        :param name: Имя файла (basename).
        :param length: Желаемая максимальная длина.
        :return: Сокращённая строка.
        """
        if len(name) <= length:
            return name
        head_len = max(3, length // 2)
        tail_len = max(3, length - head_len - 3)
        return f'{name[:head_len]}...{name[-tail_len:]}'

    def render(self) -> None:
        """
        Полная перерисовка экрана: заголовок, строки записей и детали.

        В краткой колонке отображается только имя файла (basename), а полный путь
        выводится в подстроке ниже.
        """
        if not self.order:
            log.debug('Render called but no entries to display.')
        _clear_screen()
        width = self._term_width()
        header = f'{"№":>3} | {"СТАТУС":^15} | {"Имя файла":<{max(20, self.short_len)}}'
        print(header)
        print('-' * min(width, max(len(header), 60)))

        for idx in self.order:
            entry = self.entries.get(idx, {})
            full_path: Path = entry.get('full_path') or Path('')
            status = entry.get('status') or ''
            # краткая строка — только имя файла
            name = full_path.name if isinstance(full_path, Path) else str(full_path)
            short = self._shorten_name(name, self.short_len)
            # Основная строка
            print(f'{idx:>3} | {status:^15} | {short}')
            # Подстрока: полный путь
            print(f'    ├ {"Полный путь:":^15} | {str(full_path)}')
            # Подстрока: действие / архив / сообщение
            detail = entry.get('detail') or ''
            if detail:
                print(f'    └ {detail}')
            # Разделитель между записями
            print()
        # Гарантируем немедленный вывод
        try:
            stdout.flush()
        except Exception as e:
            log.debug('Failed to flush stdout: %s', e)

    # -----------------------
    # Инициализация и обновления
    # -----------------------
    def start(self, selected_indices: List[int], dbx_list: List[str]) -> None:
        """
        Инициализация списка записей для выбранных индексов.

        Внутри full_path сохраняется pathlib.Path для удобной работы с именем и строковым представлением.

        :param selected_indices: Список 1-based индексов.
        :param dbx_list: Список полных путей к базам.
        """
        self.entries.clear()
        self.order = []
        for idx in selected_indices:
            try:
                full = Path(dbx_list[idx - 1])
            except IndexError:
                log.error('start(): index out of range: %d', idx)
                continue
            self.entries[idx] = {
                'full_path': full,
                'status': Status.WAITING.value,
                'detail': 'Ожидание обработки...',
                'archive': None
            }
            self.order.append(idx)
        log.info('UI started for indices: %s', self.order)
        self.render()

    def set_status(self, idx: int, status: Union[Status, str], action: Optional[str] = None) -> None:
        """
        Обновить статус и (опционально) краткое действие/сообщение для записи.

        :param idx: 1-based индекс записи.
        :param status: Статус (Status enum или строка).
        :param action: Дополнительная деталь/сообщение.
        """
        if idx not in self.entries:
            log.warning('set_status(): unknown index %s', idx)
            return
        status_str = status.value if isinstance(status, Status) else str(status)
        self.entries[idx]['status'] = status_str
        if action is not None:
            self.entries[idx]['detail'] = action
        log.debug('Status updated for %d: %s', idx, status_str)
        self.render()

    def mark_done(self, idx: int, archive_path: str) -> None:
        """
        Пометить запись как завершённую и записать путь к архиву.

        :param idx: 1-based индекс записи.
        :param archive_path: Путь к созданному архиву.
        """
        if idx not in self.entries:
            log.warning('mark_done(): unknown index %s', idx)
            return
        self.entries[idx]['status'] = Status.DONE.value
        self.entries[idx]['archive'] = archive_path
        self.entries[idx]['detail'] = f'{"Архив:":^15} | {archive_path}'
        log.info('Marked done for %d: %s', idx, archive_path)
        self.render()

    def mark_error(self, idx: int, message: str) -> None:
        """
        Пометить запись как ошибочную и показать сообщение.

        :param idx: 1-based индекс записи.
        :param message: Текст ошибки.
        """
        if idx not in self.entries:
            log.warning('mark_error(): unknown index %s', idx)
            return
        self.entries[idx]['status'] = Status.ERROR.value
        self.entries[idx]['detail'] = f'Ошибка: {message}'
        log.error('Marked error for %d: %s', idx, message)
        self.render()

    def close(self) -> None:
        """
        Финальная отрисовка (может быть вызвана при завершении программы).
        """
        log.debug('UIManager closing, performing final render.')
        self.render()

    # -----------------------
    # Интерактивный выбор
    # -----------------------
    @staticmethod
    def select_from_list(dbx_list: List[str]) -> List[int]:
        """
        Показать нумерованный список полных путей и запросить выбор у пользователя.

        Возвращает список индексов (1-based). При Ctrl+C/EOF — завершает программу.

        :param dbx_list: Список полных путей к базам.
        :return: Список выбранных индексов (1-based).
        """
        _clear_screen()
        sep = '=' * 6
        print(f'{sep} Список доступных баз: {sep}')
        for i, p in enumerate(dbx_list, start=1):
            print(f'{i}. {p}')
        total = len(dbx_list)

        while True:
            choice = ''
            try:
                choice = input(
                    f'\nВведите номер одной базы (1-{total}) '
                    f'или нескольких баз через запятую, или ALL: '
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                log.info('User cancelled selection (EOF/KeyboardInterrupt). Exiting.')
                sys_exit(1)

            if not choice:
                print('Пустой ввод. Повторите.')
                continue

            if choice.upper() == 'ALL':
                log.debug('User selected ALL.')
                return list(range(1, total + 1))

            try:
                indices: List[int] = []
                for part in choice.split(','):
                    part = part.strip()
                    if not part:
                        continue
                    idx = int(part)
                    if 1 <= idx <= total:
                        indices.append(idx)
                    else:
                        print(f'Неверный номер: "{idx}".')
                        log.debug('User entered out-of-range index: %s', idx)
                if indices:
                    log.info('User selected indices: %s', indices)
                    return indices
                else:
                    print('Не выбрано ни одной корректной базы.')
            except ValueError:
                print('Неверный формат. Введите числа через запятую или ALL.')
                log.debug('User entered invalid selection string: %s', choice)
