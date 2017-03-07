#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test mender via web server and selenium"""

__authors__    = ["Ole Herman Schumacher Elgesem"]

# System
import os
import sys
import random
from time import sleep
import inspect

# strings
import re
import argparse
import getpass

# file io
import json
import pickle

# network
import requests
import selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from web_funcs import *

def function_name():
   """Returns the function name of the calling function (stack[1])"""
   return inspect.stack()[1][3]

def ui_test_banner():
    print("=== UI-TEST: {}() ===".format(inspect.stack()[1][3]))

def ui_test_success():
    print("=== SUCCESS: {}() ===".format(inspect.stack()[1][3]))


def tag_contents_xpath(tag, content):
    """Constructs an xpath matching element with tag containing content"""
    content = content.lower()
    return '//{}[contains(translate(*,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"{}")]'.format(tag, content)

class TestUI(object):
    def init_driver(self, url="https://localhost:443/"):
        self.url = url
        driver = chrome_driver()
        #driver = phantom_driver()
        driver.set_window_size(1024, 600)
        print("Getting: "+url)
        driver.get(url)
        return driver

    def destroy_driver(self, driver):
        if driver is None:
            return
        try:
            driver.close()
        except:
            pass
        finally:
            driver.quit()

    def download_images(self):
        url1 = "https://d1b0l86ne08fsf.cloudfront.net/master/vexpress-qemu/vexpress_release_1.mender"
        url2 = "https://d1b0l86ne08fsf.cloudfront.net/master/vexpress-qemu/vexpress_release_2.mender"
        path1 = "vexpress_release_1.mender"
        path2 = "vexpress_release_2.mender"
        download_if_needed(url1, path1)
        download_if_needed(url2, path2)

    def wait_for_element(self, driver, by, arg, timeout=10):
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.visibility_of_element_located(( by, arg )))
            if not element:
                print("WebDriverWait returned "+str(element))
                return None
            timer = 0.0
            while timer < timeout and not element.is_enabled():
                sleep(0.2)
                timer += 0.2
            if not element.is_enabled():
                print("Element not enabled: "+str(element))
        except selenium.common.exceptions.TimeoutException:
            print("wait_for_element timeout: " + arg)
            return None
        return element

    def attempt_click(self, element):
        try:
            if element.is_displayed():
                try:
                    element.click()
                    return True
                except:
                    return False
        except selenium.common.exceptions.StaleElementReferenceException:
            return False

    def attempt_click_timeout(self, element, timeout=10):
        time_passed = 0.0
        while time_passed < timeout:
            if self.attempt_click(element):
                return True
            sleep(0.2)
            time_passed += 0.2
        return False

    def click_button(self, driver, label, timeout=10):
        xp = tag_contents_xpath("button", label)
        element = self.wait_for_element(driver, By.XPATH, xp)
        if not element:
            print("Button not found: " + label)
            return False
        print("Clicking: {} ({})".format(label, element))
        return self.attempt_click_timeout(element, timeout)

    def click_random_button(self, driver):
        buttons = driver.find_elements_by_tag_name("button")
        if not buttons:
            return False
        random.shuffle(buttons)
        for button in buttons:
            if self.attempt_click(button):
                return True
        return False

    def upload_artifact(self, driver, path):
        element = None
        while element is None:
            #try:
            element = driver.find_element_by_class_name("dropzone")
            sleep(0.3)
#            TODO: Add timeout
        element = element.find_element_by_tag_name("input")
        element.send_keys(os.path.abspath(path))
        sleep(1)

    def wait_for_xpath(self, driver, xp, timeout=10):
        return self.wait_for_element(driver, By.XPATH, xp, timeout)

    def upload_artifacts(self, driver):
        self.upload_artifact(driver, "vexpress_release_1.mender")
        self.upload_artifact(driver, "vexpress_release_2.mender")
        sleep(10)
        artifacts = []
        xpaths = ["//table/tbody[@class='clickable']/tr[1]/td[1]",
                  "//table/tbody[@class='clickable']/tr[2]/td[1]"]
        # NOTE: These xpaths match the first clickable table
        # TODO: Can search the page more extensively in case more
        #       clickable tables are added.
        elements = [self.wait_for_xpath(driver, x) for x in xpaths]
        assert len(elements) == 2
        contents = [x.text for x in elements]
        assert "release-1" in contents and "release-2" in contents

    def login(self, driver):
        if "login" not in driver.current_url:
            return
        mock_email    = "mock_email@cfengine.com"
        mock_password = "seleniumfoxrainbowdog"
        print("Logging in with credentials:")
        print("Email: "+ mock_email)
        print("Password: "+ mock_password)
        email_field = driver.find_element_by_id("email")
        email_field.click()
        email_field.send_keys(mock_email)
        password_field = driver.find_element_by_id("password")
        password_field.click()
        password_field.send_keys(mock_password)
        clicked = self.click_button(driver, "log in")
        if not clicked:
            clicked = self.click_button(driver, "create user")
        assert clicked
        xp = tag_contents_xpath("button", "Dashboard")
        element = self.wait_for_element(driver, By.XPATH, xp)
        assert element

    def test_login_create_user(self):
        ui_test_banner()
        try:
            driver = self.init_driver()
            self.login(driver)
            ui_test_success()
        finally:
            self.destroy_driver(driver)

    def test_click_header_buttons(self):
        ui_test_banner()
        try:
            driver = self.init_driver()
            self.login(driver)
            assert self.click_button(driver, "Dashboard")
            assert self.click_button(driver, "Devices")
            assert self.click_button(driver, "Artifacts")
            assert self.click_button(driver, "Deployments")
            ui_test_success()
        finally:
            self.destroy_driver(driver)

    def test_artifact_upload(self):
        ui_test_banner()
        self.download_images()
        try:
            driver = self.init_driver()
            self.login(driver)
            assert self.click_button(driver, "Artifacts")
            self.upload_artifacts(driver)
            ui_test_success()
        finally:
            self.destroy_driver(driver)

    def test_authorize_all(self):
        ui_test_banner()
        driver = self.init_driver()
        self.login(driver)
        assert self.click_button(driver, "Devices")
        self.click_button(driver, "Authorize 1 device")
        xp = "//table/tbody[@class='clickable']/tr/td[3]/div"
        authorized_device = self.wait_for_element(driver, By.XPATH, xp)
        assert authorized_device
        time_passed = 0.0
        while authorized_device.text != "vexpress-qemu":
            sleep(0.2)
            time_passed += 0.2
            if time_passed > 10.0:
                break
        print("Found authorized_device: '" + authorized_device.text + "'")
        assert authorized_device.text == "vexpress-qemu"
        ui_test_success()
        self.destroy_driver(driver)

    def test_deploy(self):
        ui_test_banner()
        driver = self.init_driver()
        self.login(driver)
        assert self.click_button(driver, "Deployments")
        assert self.click_button(driver, "Create a Deployment")

        # Locate and click the select artifact drop down:
        xp = "//div[@id='selectArtifact']/div[1]"
        artifact_drop_down = self.wait_for_element(driver, By.XPATH, xp)
        assert artifact_drop_down
        assert self.attempt_click_timeout(artifact_drop_down)

        # Locate and click the artifact we want to deploy "release-2":
        xp = "/html/body[@class='box-sizing']/div[3]/div/div/div/div[1]/span/div/div/div"
        target_artifact = self.wait_for_element(driver, By.XPATH, xp)
        assert target_artifact
        assert target_artifact.text == "release-2"
        assert self.attempt_click_timeout(target_artifact)

        # Locate and click the select group drop down:
        xp = "//div[@id='selectGroup']/div[1]"
        group_drop_down = self.wait_for_element(driver, By.XPATH, xp)
        assert group_drop_down
        assert self.attempt_click_timeout(group_drop_down)

        # Locate and click the "All devices" group in this drop down:
        xp = "/html/body[@class='box-sizing']/div[3]/div/div/div/div/span/div/div/div"
        first_option = self.wait_for_element(driver, By.XPATH, xp)
        assert first_option
        assert self.attempt_click_timeout(first_option)
        assert self.click_button(driver, "Create Deployment")
        ui_test_success()
        self.destroy_driver(driver)

def get_args():
    argparser = argparse.ArgumentParser(description='Test UI of mender web server')
    argparser.add_argument('--url', '-u', help='URL (default="https://localhost:8080/")', type=str, default='https://localhost:8080/')
    args = argparser.parse_args()
    return args

# For running without pytest:
if __name__ == '__main__':
    args = get_args()
    test = TestUI()
    test.test_login_create_user()
    test.test_click_header_buttons()
    test.test_artifact_upload()
    test.test_authorize_all()
    test.test_deploy()
    #pytest.main(args=[os.path.realpath(__file__)])#, "--url", args.url])
