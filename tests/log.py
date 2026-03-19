# Copyright 2021 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import os
import logging
import unicodedata
import re
import errno

TEST_LOGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "mender_test_logs"
)

# Create dir if does not exist
try:
    os.makedirs(TEST_LOGS_PATH)
except OSError as e:
    if e.errno != errno.EEXIST:
        raise

# Default logger default level to DEBUG
logging.getLogger().setLevel(logging.DEBUG)


def setup_test_logger(test_name, worker_id=None):
    """Sets the default test logger

    The  logger contains two handlers:
    - An INFO level console handler
    - A DEBUG level file handler, with a filename being an slug of the test name
    """

    # Get the default logger and remove previous handlers
    logger = logging.getLogger()
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    # Define format. For console logging, prepend the test name
    base_log_format = "%(asctime)s [%(levelname)s]: >> %(message)s"
    if worker_id is not None:
        console_log_format = "[{}] {} -- {}".format(
            worker_id, test_name, base_log_format
        )
    else:
        console_log_format = "{} -- {}".format(test_name, base_log_format)

    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(console_log_format)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Add file handler
    filename = os.path.join(TEST_LOGS_PATH, slugify(test_name) + ".log")
    file_handler = logging.FileHandler(filename)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(base_log_format)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)


_re_slugify_pass1_sub = re.compile(r"[^\w\s-]").sub
_re_slugify_pass2_sub = re.compile(r"[-\s]+").sub


def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.

    Inspired by Django framework:
    https://github.com/django/django/blob/3.0.2/django/utils/text.py#L393
    """

    value = str(value)
    value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    value = _re_slugify_pass1_sub("", value).strip().lower()
    return _re_slugify_pass2_sub("-", value)
