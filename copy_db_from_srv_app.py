import os
import sys
import configparser
from typing import List, Tuple, Optional
import argparse
from pathlib import Path


def load_base_dir_from_config_ini() -> Optional[str]:
    """
    Попытаться считать base_dir из config.ini.
    Ищем config.ini в двух местах: текущая рабочая директория и директория скрипта.
    В config.ini ожидаем секцию [Paths] и ключ base_dir.
    """
    locations = [Path.cwd(), Path(__file__).resolve().parent]
    for loc in locations:
        ini_path = loc / 'config.ini'
        if ini_path.exists():
            parser = configparser.ConfigParser()
            try:
                parser.read(ini_path, encoding='utf-8')
            except Exception:
                continue  # пропускаем проблемные файлы
            if parser.has_section('Paths') and parser.has_option('Paths', 'base_dir'):
                return parser.get('Paths', 'base_dir')
    return None


class ConfigReader:
    def __init__(self, cfg_path: str):
        self.cfg_path = cfg_path

    def load_dbx_list(self) -> List[str]:
        if not os.path.exists(self.cfg_path):
            print(f'Error: configuration file not found: {self.cfg_path}')
            sys.exit(1)

        try:
            with open(self.cfg_path, 'r', encoding='cp866', errors='replace') as f:
                lines = f.readlines()
        except Exception as e:
            print(f'Error reading configuration file: {e}')
            sys.exit(1)

        return [line.strip() for line in lines if line.strip().upper().endswith('.DBX')]


class CmdWriter:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    @staticmethod
    def make_cmd(db_num: int) -> bytes:
        # 3 байта: 0x07, номер базы, 0x00
        return bytes([0x07, db_num & 0xFF, 0x00])

    def write_cmd_file(self, db_number: int) -> Tuple[str, bytes]:
        os.makedirs(self.base_dir, exist_ok=True)


        mon_path = os.path.join(self.base_dir, 'ZMon$tor.tmp')
        try:
            with open(mon_path, 'wb') as f:
                print(f'Create file: {path}')
                pass  # файл — нулевой длины
        except (PermissionError, OSError) as e:
            print(f'The monitor is already running!: {e}!')

        data = self.make_cmd(db_number)
        path = os.path.join(self.base_dir, 'Z_Cmnd.tmp')
        with open(path, 'wb') as f:
            f.write(data)

        print(f'Create file: {path}:\tDB #{db_number}:\tData: {data.hex()}')
        return path, data


class SimpleUI:
    @staticmethod
    def print_db_list(dbx_list: List[str]) -> None:
        print('Found database files from config:')
        for i, line in enumerate(dbx_list, start=1):
            print(f'{i}. {line}')

    @staticmethod
    def select_from_list(dbx_list: List[str]) -> int:
        while True:
            try:
                choice = input(f'Select database number (1-{len(dbx_list)}): ').strip()
            except (EOFError, KeyboardInterrupt):
                print()
                sys.exit(1)

            if not choice:
                print('No input. Using default: 1')
                return 1

            try:
                idx = int(choice)
            except ValueError:
                print('Please enter a number.')
                SimpleUI.print_db_list(dbx_list)
                continue

            if 1 <= idx <= len(dbx_list):
                return idx
            else:
                print('Invalid selection number.')
                SimpleUI.print_db_list(dbx_list)


class App:
    def __init__(self, base_dir: str, cfg_filename: str = 'SLS_SERV.CFG'):
        self.base_dir = base_dir
        self.cfg_path = os.path.join(base_dir, cfg_filename)

    def run(self, db_number: Optional[int] = None) -> None:
        reader = ConfigReader(self.cfg_path)
        dbx_list = reader.load_dbx_list()

        if not dbx_list:
            print('No database files found in configuration. Exiting.')
            sys.exit(1)

        SimpleUI.print_db_list(dbx_list)

        selected: Optional[int] = None
        if db_number is not None:
            if 1 <= db_number <= len(dbx_list):
                selected = db_number
            else:
                print('Provided DB number is not in the list.')

        if selected is None:
            selected = SimpleUI.select_from_list(dbx_list)

        writer = CmdWriter(self.base_dir)
        writer.write_cmd_file(selected)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Create a single Z_Cmnd.tmp with a command for one database number.'
    )
    # base-dir может быть нам не задан явно, чтобы мы могли подтянуть из config.ini
    parser.add_argument(
        '-b', '--base-dir',
        default=None,
        help='Base directory for the output file (read from config.ini as fallback)'
    )
    parser.add_argument(
        '-n', '--db-number',
        type=int,
        dest='db_number',
        help='Database number (explicit)'
    )
    parser.add_argument(
        'pos_db_number',
        nargs='?',
        type=int,
        help='Database number (positional, used if --db-number is not provided)'
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Дефолтный путь, если ничего не задано и в config.ini не нашли
    default_base_dir = r'c:\SoftLand Systems\SLS-Serv'
    config_base_dir = load_base_dir_from_config_ini()

    # Вычисляем итоговый base_dir: аргумент => конфиг.ini => дефолт
    base_dir = args.base_dir if args.base_dir is not None else (config_base_dir or default_base_dir)

    app = App(base_dir=base_dir, cfg_filename='SLS_SERV.CFG')

    db_num = None
    if args.db_number is not None:
        db_num = args.db_number
    elif args.pos_db_number is not None:
        db_num = args.pos_db_number

    app.run(db_number=db_num)


if __name__ == '__main__':
    main()
