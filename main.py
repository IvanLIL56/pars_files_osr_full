#!/usr/bin/env python3
"""
Основная точка входа приложения для загрузки и обработки документов.

Поддерживает два режима работы:
1. Загрузка из Excel файла со списком URL договоров
2. Обработка уже скачанных файлов

Примеры использования:
    python main.py --excel contracts.xlsx
    python main.py --process-downloaded
    python main.py --excel contracts.xlsx --skip-download
"""

import argparse
import sys
from pathlib import Path

from config import settings
from utils.logger import setup_logger

default_logger = setup_logger(__name__)
from db.repository import DatabaseRepository
from ingest.excel_ingester import ExcelIngester
from processors.file_scanner import FileScanner


def parse_args() -> argparse.Namespace:
    """Парсинг аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description='Система загрузки и обработки документов',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s --excel contracts.xlsx              # Загрузить и обработать файлы из Excel
  %(prog)s --process-downloaded                # Обработать уже скачанные файлы
  %(prog)s --excel contracts.xlsx --dry-run    # Проверка без реального скачивания
        """
    )
    
    parser.add_argument(
        '--excel', '-e',
        type=str,
        default=settings.EXCEL_FILE_PATH,
        help=f'Путь к Excel файлу со списком URL (по умолчанию: {settings.EXCEL_FILE_PATH})'
    )
    
    parser.add_argument(
        '--column', '-c',
        type=str,
        default=settings.EXCEL_URL_COLUMN,
        help=f'Имя колонки с URL в Excel файле (по умолчанию: {settings.EXCEL_URL_COLUMN})'
    )
    
    parser.add_argument(
        '--process-downloaded', '-p',
        action='store_true',
        help='Обработать уже скачанные файлы без загрузки новых'
    )
    
    parser.add_argument(
        '--skip-download',
        action='store_true',
        help='Пропустить этап скачивания, только обработка'
    )
    
    parser.add_argument(
        '--skip-processing',
        action='store_true',
        help='Только скачать файлы, без обработки'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Режим проверки: показать что будет сделано, но не выполнять'
    )
    
    parser.add_argument(
        '--output-report',
        type=str,
        default=None,
        help='Путь к JSON файлу для сохранения отчёта о выполнении'
    )
    
    parser.add_argument(
        '--max-workers',
        type=int,
        default=settings.MAX_PARALLEL_DOWNLOADS,
        help=f'Максимальное количество параллельных воркеров (по умолчанию: {settings.MAX_PARALLEL_DOWNLOADS})'
    )
    
    return parser.parse_args()


def ensure_directories():
    """Создание необходимых директорий."""
    dirs_to_create = [
        settings.DOWNLOAD_DIR,
        'logs',
        'data'
    ]
    for dir_path in dirs_to_create:
        Path(dir_path).mkdir(parents=True, exist_ok=True)


def run_excel_ingestion(args: argparse.Namespace) -> dict:
    """
    Выполнение загрузки из Excel файла.
    
    Returns:
        dict: Статистика выполнения
    """
    logger = default_logger
    logger.info("=" * 70)
    logger.info("ЗАПУСК ЗАГРУЗКИ ИЗ EXCEL ФАЙЛА")
    logger.info("=" * 70)
    
    excel_path = Path(args.excel)
    if not excel_path.exists():
        logger.error(f"Excel файл не найден: {excel_path}")
        return {'success': False, 'error': 'File not found'}
    
    ingester = ExcelIngester(
        excel_path=str(excel_path),
        url_column=args.column,
        max_workers=args.max_workers
    )
    
    try:
        stats = ingester.download_all(
            dry_run=args.dry_run,
            skip_processing=args.skip_processing
        )
        
        if args.output_report:
            import json
            report_path = Path(args.output_report)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"Отчёт сохранён: {report_path}")
        
        return stats
        
    except KeyboardInterrupt:
        logger.warning("Процесс прерван пользователем")
        return {'success': False, 'error': 'Interrupted by user'}
    except Exception as e:
        logger.exception(f"Критическая ошибка при загрузке: {e}")
        return {'success': False, 'error': str(e)}


def run_file_processing(args: argparse.Namespace) -> dict:
    """
    Обработка уже скачанных файлов.
    
    Returns:
        dict: Статистика выполнения
    """
    logger = default_logger
    logger.info("=" * 70)
    logger.info("ЗАПУСК ОБРАБОТКИ СКАЧАННЫХ ФАЙЛОВ")
    logger.info("=" * 70)
    
    scanner = FileScanner(
        root_dir=settings.DOWNLOAD_DIR,
        supported_extensions=['.pdf', '.docx', '.doc', '.txt', '.jpg', '.jpeg', '.png']
    )
    
    try:
        files = scanner.scan_directory()
        logger.info(f"Найдено файлов для обработки: {len(files)}")
        
        if args.dry_run:
            logger.info("[DRY RUN] Файлы для обработки:")
            for file_path in files[:10]:
                logger.info(f"  - {file_path}")
            if len(files) > 10:
                logger.info(f"  ... и ещё {len(files) - 10} файлов")
            return {'success': True, 'files_found': len(files), 'dry_run': True}
        
        repo = DatabaseRepository()
        processed_count = 0
        error_count = 0
        
        for file_path in files:
            try:
                from processors.content_extractor import ContentExtractor
                extractor = ContentExtractor()
                
                result = extractor.process_file(file_path)
                
                if result.get('success'):
                    repo.save_document_result(result)
                    processed_count += 1
                    logger.info(f"Обработан файл: {file_path}")
                else:
                    error_count += 1
                    logger.error(f"Ошибка обработки {file_path}: {result.get('error')}")
                    
            except Exception as e:
                error_count += 1
                logger.exception(f"Исключение при обработке {file_path}: {e}")
        
        stats = {
            'success': True,
            'files_processed': processed_count,
            'files_error': error_count,
            'total_files': len(files)
        }
        
        logger.info("=" * 70)
        logger.info(f"ОБРАБОТКА ЗАВЕРШЕНА: {processed_count} успешно, {error_count} ошибок")
        logger.info("=" * 70)
        
        return stats
        
    except KeyboardInterrupt:
        logger.warning("Процесс прерван пользователем")
        return {'success': False, 'error': 'Interrupted by user'}
    except Exception as e:
        logger.exception(f"Критическая ошибка при обработке: {e}")
        return {'success': False, 'error': str(e)}


def print_summary(stats: dict):
    """Вывод итоговой статистики."""
    logger = default_logger
    
    logger.info("\n" + "=" * 70)
    logger.info("ИТОГОВАЯ СТАТИСТИКА")
    logger.info("=" * 70)
    
    if stats.get('success'):
        if 'contracts_downloaded' in stats:
            logger.info(f"Договоров обработано: {stats.get('contracts_total', 0)}")
            logger.info(f"Файлов скачано: {stats.get('files_downloaded', 0)}")
            logger.info(f"Файлов пропущено (существуют): {stats.get('files_skipped', 0)}")
            logger.info(f"Ошибок при скачивании: {stats.get('files_error', 0)}")
            
        if 'files_processed' in stats:
            logger.info(f"Файлов обработано: {stats.get('files_processed', 0)}")
            logger.info(f"Ошибок при обработке: {stats.get('files_error', 0)}")
    else:
        logger.error(f"Выполнено с ошибкой: {stats.get('error', 'Неизвестная ошибка')}")
    
    logger.info("=" * 70)


def main():
    """Основная функция приложения."""
    args = parse_args()
    
    ensure_directories()
    
    logger = get_shared_file_handler()
    
    logger.info("Запуск приложения...")
    logger.info(f"Режим: download={not args.skip_download and not args.process_downloaded}, "
                f"processing={not args.skip_processing}, dry_run={args.dry_run}")
    
    final_stats = {'success': True}
    
    try:
        if args.process_downloaded or args.skip_download:
            stats = run_file_processing(args)
            final_stats.update(stats)
        else:
            stats = run_excel_ingestion(args)
            final_stats.update(stats)
            
            if stats.get('success') and not args.skip_processing:
                proc_stats = run_file_processing(args)
                final_stats['processing'] = proc_stats
        
        print_summary(final_stats)
        
        sys.exit(0 if final_stats.get('success') else 1)
        
    except Exception as e:
        logger.exception(f"Необработанное исключение: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
