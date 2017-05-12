#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Various isolated selenium/requests functions"""

__authors__    = ["Ole Herman Schumacher Elgesem"]

import requests
from selenium import webdriver
import os

def session_get(url, driver):
    session = requests.Session()
    cookies = driver.get_cookies()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])
    return session.get(url)

def download_if_needed(url, path):
    if os.path.exists(path):
        print("{} already exists - skipping download.".format(path))
        return
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(os.path.dirname(path), exist_ok = True)
    print("Downloading: "+url)
    r = requests.get(url)
    print("Writing: "+path)
    with open(path, "wb") as f:
        f.write(r.content)

# Kept as an example:
def print_source(driver):
    print(driver.page_source)

def phantom_driver():
    return webdriver.PhantomJS(service_args=["--ignore-ssl-errors=true", "--web-security=false"])

def firefox_driver():
    # Doesn't work with geckodriver! :(
    capabilities = webdriver.DesiredCapabilities().FIREFOX
    capabilities['acceptSslCerts'] = True

    profile = webdriver.FirefoxProfile()
    profile.accept_untrusted_certs = True

    return webdriver.Firefox(firefox_profile=profile, capabilities=capabilities)

def chrome_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--ignore-certificate-errors')

    return webdriver.Chrome(chrome_options=options)
