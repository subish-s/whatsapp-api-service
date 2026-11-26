import os
import sys

# Determine project root logs/ folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

try:
    from loguru import logger

    # Reset default logger configuration
    logger.remove()

    # 1. Console handler
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
    )

    # 2. Main application log file in logs/
    logger.add(
        os.path.join(LOGS_DIR, "app_{time:YYYY-MM-DD}.log"),
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # 3. Dedicated error log file in logs/
    logger.add(
        os.path.join(LOGS_DIR, "error_{time:YYYY-MM-DD}.log"),
        rotation="10 MB",
        retention="30 days",
        level="WARNING",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

except ImportError:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(LOGS_DIR, "app.log"), encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("whatsapp_api")

