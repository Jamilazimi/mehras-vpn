import logging
import logging.handlers
import sys

from app.config import LOG_FILE

_logger = None


def get_logger():
    global _logger
    if _logger is not None:
        return _logger
    _logger = logging.getLogger("mehras")
    _logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # فایل چرخشی تا لاگ بی‌نهایت رشد نکند
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, encoding="utf-8", maxBytes=1_000_000, backupCount=2)
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    _logger.addHandler(fh)

    # کنسول فقط وقتی واقعاً وجود دارد (pythonw → stderr=None)
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.setLevel(logging.INFO)
        _logger.addHandler(sh)
    return _logger


log = get_logger()
