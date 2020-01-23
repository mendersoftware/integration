import logging

def setup_custom_logger(name, testname, worker_id=None):
    log_format = "%(asctime)s [%(levelname)s]: >> %(message)s"

    logging.basicConfig(format=log_format, level=logging.INFO)
    logger = logging.getLogger(name)

    for h in list(logger.handlers):
        logger.removeHandler(h)

    consoleHandler = logging.StreamHandler()
    logFormatter = logging.Formatter(log_format)
    if worker_id is not None:
        logFormatter._fmt = "[{}] {} --".format(worker_id, testname) + logFormatter._fmt
    else:
        logFormatter._fmt = testname + " -- " + logFormatter._fmt
    consoleHandler.setFormatter(logFormatter)
    logger.addHandler(consoleHandler)
    logging.getLogger(name).addHandler(consoleHandler)
    logger.propagate = False
    return logger
