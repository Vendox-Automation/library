import logging
from pathlib import Path
from datetime import datetime


class Logger:
    """
    File and console logging utility (daily log file under ``log_path``).

    Usage:
        from utils.logger import Logger
        logger = Logger("./logs").get_logger()
        logger.info("Message to log")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.debug("Debug message")
    """

    def __init__(self, log_path=r"logs"):
        """Ensure ``log_path`` exists and attach UTF-8 file + stream handlers to the package logger."""
        # Create and configure logger
        self.log_path = log_path
        Path(self.log_path).mkdir(parents=True, exist_ok=True)
        self.console_handler = logging.StreamHandler()
        self.console_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s")
        )
        self.file_handler = logging.FileHandler(
            filename=log_path + f"/HR_{datetime.today().strftime('%Y%m%d')}.log",
            encoding="utf-8",
        )
        self.file_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s")
        )

        # Creating an object
        self.logger = logging.getLogger("HR")
        self.logger.handlers = []
        self.logger.addHandler(self.file_handler)
        self.logger.addHandler(self.console_handler)

        # Setting the threshold of logger to DEBUG
        self.logger.setLevel(logging.DEBUG)

    def get_logger(self):
        """Return the configured ``logging.Logger``."""
        return self.logger
