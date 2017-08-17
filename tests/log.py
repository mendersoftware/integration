import logging


def setup_custom_logger(name, testname):
    log_format = "%(asctime)s [%(levelname)s]: >> %(message)s"

    logging.basicConfig(format=log_format, level=logging.INFO)
    logger = logging.getLogger(name)

    for h in list(logger.handlers):
        logger.removeHandler(h)

    consoleHandler = logging.StreamHandler()
    logFormatter = logging.Formatter(log_format)
    logFormatter._fmt = testname + " -- " + logFormatter._fmt
    consoleHandler.setFormatter(logFormatter)
    logger.addHandler(consoleHandler)
    logging.getLogger(name).addHandler(consoleHandler)
    logger.propagate = False
    return logger
