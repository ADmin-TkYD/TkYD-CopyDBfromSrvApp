"""
Главный модуль приложения.

Запуск:
    python app.py [-b BASE_DIR] [-n "1,3,5"] [positional_numbers]

Этот модуль:
    - разбирает аргументы командной строки;
    - загружает конфигурацию;
    - формирует список обрабатываемых баз;
    - последовательно отправляет команду на создание бэкапа, ждёт появления и завершения .dbx, архивирует файл и
    обновляет UI.
"""

__version__ = '3.1.3'

from argparse import ArgumentParser, Namespace
from asyncio import run as aio_run
from logging import getLogger
from pathlib import Path
from typing import List, Optional

from logging_setup import setup_logging
from config_loader import load_config
from cfg_reader import ConfigReader
from cmd_writer import CmdWriter
from extractor import extract_backup_root_from_cpy
from backup_archiver import BackupArchiver
from ui import UIManager, Status

log = getLogger('app')


def parse_args() -> Namespace:
    """
    Разобрать аргументы командной строки.

    Поддерживаемые опции:
      -b, --base-dir    — директория с SLS_SERV.CFG и временными файлами;
      -n, --db-number   — строка с номерами баз через запятую или "ALL";
      pos_db_number     — позиционный аргумент, альтернативный -n.

    :return: Namespace с полями base_dir, db_number, pos_db_number.
    """
    parser = ArgumentParser(
        description='Queue DB backups one-by-one, wait for .dbx creation, then archive.'
    )
    parser.add_argument('-b', '--base-dir', default=None, help='Directory with SLS_SERV.CFG and tmp files')
    parser.add_argument('-n', '--db-number', type=str, dest='db_number', help='DB number(s), comma-separated')
    parser.add_argument('pos_db_number', nargs='?', type=str, help='Positional DB number(s), comma-separated')
    return parser.parse_args()


def parse_selection_list(raw: Optional[str], total: int, dbx_list: List[str]) -> List[int]:
    """
    Разобрать список выбора баз (1-based индексы).

    Поведение:
        - Если raw задан и равен "ALL" (регистронезависимо) — возвращает все индексы [1..total].
        - Если raw задан как "1,3,5" — парсит числа, игнорирует пустые части и индексы вне диапазона.
          При ошибке формата возвращает [1].
        - Если raw не задан — запускает интерактивный выбор через UIManager.

    :param raw: Строка выбора (например "1,2" или "ALL") или None.
    :param total: Общее количество доступных баз (должно быть >= 1).
    :param dbx_list: Список доступных баз (используется для интерактивного выбора).
    :return: Список выбранных индексов (1-based). Гарантированно непустой.
    """
    if raw:
        if raw.strip().upper() == 'ALL':
            return list(range(1, total + 1))
        try:
            indices: List[int] = []
            for part in raw.split(','):
                part = part.strip()
                if not part:
                    continue
                idx = int(part)
                if 1 <= idx <= total:
                    indices.append(idx)
                else:
                    log.warning('Ignoring out-of-range index: %s', part)
            return indices or [1]
        except ValueError:
            log.warning('Invalid format for selection. Using first element.')
            return [1]
    else:
        from ui import UIManager
        ui = UIManager(short_len=60)
        return ui.select_from_list(dbx_list)


async def process_queue(
    base_dir: Path,
    dbx_list: List[str],
    selection: List[int],
    creation_retry_interval: float,
    creation_retry_timeout: Optional[float],
    dbx_poll_interval: float,
    dbx_wait_timeout: Optional[float],
    prefer_7z: bool,
    seven_zip_compression: int,
    archive_output_dir: Optional[Path],
    backup_root_override: Optional[Path],
    search_in_user_subdir: bool,
) -> None:
    """
    Последовательно обработать выбранные базы.

    Для каждой выбранной базы выполняется:
        1) отправка управляющей команды (CmdWriter);
        2) подготовка директории пользователя (archiver.ensure_user_db_dir);
        3) ожидание появления кандидата (.db- или .dbx);
        4) ожидание финального .dbx;
        5) архивирование (archiver.archive_file);
        6) обновление UI (статусы, ошибки, завершение).

    Функция использует UIManager для отображения статусов и BackupArchiver
    для операций ожидания и архивирования.

    :param base_dir: Директория с SLS_SERV.CFG и временными файлами.
    :param dbx_list: Список путей к базам (строки).
    :param selection: Список индексов (1-based) баз для обработки.
    :param creation_retry_interval: Интервал опроса появления кандидата (секунды).
    :param creation_retry_timeout: Таймаут ожидания начала создания (секунды) или None.
    :param dbx_poll_interval: Интервал опроса появления финального .dbx (секунды).
    :param dbx_wait_timeout: Таймаут ожидания финального .dbx (секунды) или None.
    :param prefer_7z: Если True — использовать 7z при наличии.
    :param seven_zip_compression: Уровень сжатия 7z (0–9).
    :param archive_output_dir: Директория для архивов или None (рядом с исходным файлом).
    :param backup_root_override: Принудительный backup_root из конфигурации или None.
    :param search_in_user_subdir: Искать базы в backup_root/USER/<stem> если True.
    :raises SystemExit: если не удалось определить backup_root (и он не задан в конфиге).
    """
    backup_config_filename = 'Sls_Serv.cpy'
    writer = CmdWriter(base_dir)

    # Determine backup root
    if backup_root_override:
        backup_root = backup_root_override
        log.info('Using backup_root from config: %s', backup_root)
    else:
        cpy_path = base_dir / backup_config_filename
        backup_root = extract_backup_root_from_cpy(cpy_path)
        if not backup_root:
            from sys import exit as sys_exit
            log.error('Backup root not determined from "%s" and not set in config', backup_config_filename)
            sys_exit(1)

    archiver = BackupArchiver(
        backup_root=backup_root,
        creation_retry_interval=creation_retry_interval,
        creation_retry_timeout=creation_retry_timeout,
        dbx_poll_interval=dbx_poll_interval,
        dbx_wait_timeout=dbx_wait_timeout,
        prefer_7z=prefer_7z,
        seven_zip_compression=seven_zip_compression,
        archive_output_dir=archive_output_dir,
        search_in_user_subdir=search_in_user_subdir
    )

    # UI manager: инициализация таблицы только для выбранных баз
    ui = UIManager(short_len=60)
    ui.start(selection, dbx_list)

    # Последовательная обработка: одна база за раз
    for idx in selection:
        selected_db_path_str = dbx_list[idx - 1]
        log.info('Processing DB #%d: %s', idx, selected_db_path_str)

        # 1) Отправляем управляющую команду
        ui.set_status(idx, Status.CMD_SENT.value, 'Отправка управляющей команды...')
        try:
            writer.write_cmd_file(idx)
            ui.set_status(idx, Status.WAITING.value, 'Команда отправлена. Ожидание появления кандидата...')
        except Exception as e:
            log.error('Failed to write command for DB #%d: %s', idx, e)
            ui.mark_error(idx, f'Не удалось записать команду: {e}')
            continue

        # 2) Подготовка директории для базы
        selected_path = Path(selected_db_path_str)
        db_stem = selected_path.stem
        try:
            # ensure_user_db_dir — публичный метод архиватора, создаёт директорию при необходимости
            archiver.ensure_user_db_dir(db_stem)
        except Exception as e:
            log.error('Cannot ensure user db dir for DB #%d (%s): %s', idx, db_stem, e)
            ui.mark_error(idx, f'Не удалось подготовить директорию: {e}')
            continue

        # 3) Ожидание появления кандидата (.db- или .dbx)
        try:
            ui.set_status(idx, Status.WAITING.value, 'Ожидание появления кандидата (.db- / .dbx)...')
            candidate = await archiver.wait_until_creation_starts_for(db_stem)
            ui.set_status(idx, Status.CANDIDATE.value, f'Кандидат найден: {candidate}')
        except TimeoutError as te:
            log.error('Timeout waiting for creation start for DB #%d: %s', idx, te)
            ui.mark_error(idx, f'Таймаут ожидания начала создания: {te}')
            continue
        except Exception as e:
            log.error('Error while waiting for creation start for DB #%d: %s', idx, e)
            ui.mark_error(idx, f'Ошибка при ожидании кандидата: {e}')
            continue

        # 4) Ожидание финального .dbx
        try:
            ui.set_status(idx, Status.WAIT_DBX.value, 'Ожидание финального .dbx...')
            final_dbx = await archiver.wait_for_final_dbx_for(db_stem)
            ui.set_status(idx, Status.ARCHIVING.value, f'Финальный .dbx найден: {final_dbx}. Начало архивирования...')
        except TimeoutError as te:
            log.error('Timeout waiting for final .dbx for DB #%d: %s', idx, te)
            ui.mark_error(idx, f'Таймаут ожидания финального .dbx: {te}')
            continue
        except Exception as e:
            log.error('Error while waiting for final .dbx for DB #%d: %s', idx, e)
            ui.mark_error(idx, f'Ошибка при ожидании .dbx: {e}')
            continue

        # 5) Архивирование через публичный метод
        try:
            ui.set_status(idx, Status.ARCHIVING.value, 'Архивирование...')
            archive_path = archiver.archive_file(final_dbx)
            ui.mark_done(idx, str(archive_path))
            log.info('Archive ready for DB #%d: %s', idx, archive_path)
        except RuntimeError as re_err:
            log.error('Archiving failed for DB #%d: %s', idx, re_err)
            ui.mark_error(idx, f'Ошибка архивации: {re_err}')
            continue
        except Exception as e:
            log.error('Unexpected error during archiving DB #%d: %s', idx, e)
            ui.mark_error(idx, f'Неожиданная ошибка: {e}')
            continue

    # Финальная отрисовка
    ui.close()


# --- вспомогательные функции ---
def to_float_or_zero(value):
    """
    Преобразовать значение в float или вернуть 0.0, если значение пустое.

    Используется при чтении конфигурации, где пустая строка означает "отключено" (0).

    :param value: Строка с числом или пустая строка/None.
    :return: float(value) если value непустое, иначе 0.0.
    """
    return float(value) if value else 0.0


def positive_or_none(value):
    """
    Вернуть значение, если оно положительное, иначе None.

    Полезно для преобразования таймаутов: 0 или отрицательное значение
    трактуется как "без таймаута" (None).

    :param value: Число или None.
    :return: value если value > 0, иначе None.
    """
    if value is not None and value > 0:
        return value
    return None


def to_path_or_none(value: Optional[str]) -> Optional[Path]:
    """
    Преобразовать строку в Path или вернуть None для пустых значений.

    Убирает пробелы и возвращает None для пустой строки или None.

    :param value: Строка с путём или None.
    :return: Path(value) или None.
    """
    if value and value.strip():
        return Path(value)
    return None


def main() -> None:
    """
    Точка входа приложения.

    Последовательность действий:
        1) Загрузить config.ini (из текущей директории или директории модуля).
        2) Настроить логирование.
        3) Разобрать аргументы командной строки.
        4) Определить base_dir и загрузить список баз из SLS_SERV.CFG.
        5) Определить selection (аргументы или интерактивно).
        6) Прочитать параметры backup/archive из конфигурации.
        7) Запустить асинхронную обработку очереди process_queue.

    :return: None
    """
    # Load config.ini
    ini_locations = [Path.cwd(), Path(__file__).resolve().parent]
    cfg = load_config(ini_locations)

    # Setup logging
    log_cfg = cfg.get_logging()
    setup_logging(level=log_cfg.get('level') or 'INFO', logfile=log_cfg.get('file') or None)

    args = parse_args()

    # Resolve base_dir: arg -> config -> default
    paths_cfg = cfg.get_paths()
    default_base_dir = Path(r'c:\SoftLand Systems\SLS-Serv')
    base_dir = Path(args.base_dir) if args.base_dir else Path(paths_cfg.get('base_dir') or default_base_dir)

    reader = ConfigReader(base_dir / 'SLS_SERV.CFG')
    dbx_list = reader.load_dbx_list()
    log.info('Available DBs: %d', len(dbx_list))

    raw_selection = args.db_number or args.pos_db_number
    selection = parse_selection_list(raw_selection, len(dbx_list), dbx_list)
    log.info('Selected indices: %s', selection)
    print('Выбранные номера баз: ', selection)

    # Backup/Archive settings
    backup_cfg = cfg.get_backup()
    creation_retry_interval = float(backup_cfg['creation_retry_interval'])
    creation_retry_timeout = to_float_or_zero(backup_cfg['creation_retry_timeout'])
    dbx_poll_interval = float(backup_cfg['dbx_poll_interval'])
    dbx_wait_timeout = to_float_or_zero(backup_cfg['dbx_wait_timeout'])
    search_in_user_subdir = (backup_cfg['search_in_user_subdir'].strip().lower() == 'true')

    arch_cfg = cfg.get_archive()
    prefer_7z = (arch_cfg['prefer_7z'].strip().lower() == 'true')
    seven_zip_compression = int(arch_cfg['seven_zip_compression'])
    archive_output_dir = to_path_or_none(arch_cfg['archive_output_dir'])

    backup_root_override = to_path_or_none(paths_cfg['backup_root'])

    # Run asyncio loop
    aio_run(
        process_queue(
            base_dir=base_dir,
            dbx_list=dbx_list,
            selection=selection,
            creation_retry_interval=creation_retry_interval,
            creation_retry_timeout=positive_or_none(creation_retry_timeout),
            dbx_poll_interval=dbx_poll_interval,
            dbx_wait_timeout=positive_or_none(dbx_wait_timeout),
            prefer_7z=prefer_7z,
            seven_zip_compression=seven_zip_compression,
            archive_output_dir=archive_output_dir,
            backup_root_override=backup_root_override,
            search_in_user_subdir=search_in_user_subdir
        )
    )


if __name__ == '__main__':
    main()
