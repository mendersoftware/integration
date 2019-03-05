#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test mender via web server and selenium"""

# System
import os
import random
import time
import inspect
import subprocess
import sys

# strings
import argparse


# network
import selenium
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from web_funcs import *
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import Helpers
from MenderAPI import authentication
import logging

selenium_logger = logging.getLogger('selenium.webdriver.remote.remote_connection')
selenium_logger.setLevel(logging.INFO)


__authors__ = ["Ole Herman Schumacher Elgesem", "Gregorio Di Stefano"]
auth = authentication.Authentication()

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
    def init_driver(self, url="https://dev-gui.mender.io"):
        self.url = url
        driver = webdriver.Chrome()
        driver.set_window_size(1024, 600)
        driver.implicitly_wait(10)
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

    def wait_for_element(self, driver, by, arg, visibiliy=True, timeout=10):
        try:
            if visibiliy:
                element = WebDriverWait(driver, timeout).until(
                    EC.visibility_of_element_located((by, arg)))
            else:
                element = WebDriverWait(driver, timeout).until(
                    EC.invisibility_of_element_located((by, arg)))

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
            time.sleep(0.2)
            time_passed += 0.2
        return False

    def click_button(self, driver, label, timeout=30):
        xp = tag_contents_xpath("button", label)
        element = self.wait_for_element(driver, By.XPATH, xp, timeout=timeout)
        if not element:
            print("Button not found: " + label)
            return False
        print("Clicking: {} ({})".format(label, element))
        return self.attempt_click_timeout(element, timeout=timeout)

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
        attempts = 0
        while attempts < 10:
            element = driver.find_element_by_css_selector("input[type='file']")
            if element is not None:
                break
            attempts += 1
            time.sleep(3)

        assert os.path.exists(os.path.abspath(path))
        driver.save_screenshot('screen.png')
        element.send_keys(os.path.abspath(path))

    def wait_for_xpath(self, driver, xp, timeout=10):
        return self.wait_for_element(driver, By.XPATH, xp, timeout)

    def upload_artifacts(self, driver):
        self.upload_artifact(driver, "qemux86-64_release_1.mender")
        time.sleep(60)
        xpaths = ["//table/tbody[@class='clickable']/tr[1]/td[1]"]
        # NOTE: These xpaths match the first clickable table
        # TODO: Can search the page more extensively in case more
        #       clickable tables are added.
        elements = [self.wait_for_xpath(driver, x) for x in xpaths]
        assert len(elements) == 1
        contents = [x.text for x in elements]
        assert "release1" in contents

    def login(self, driver):
        if "login" not in driver.current_url:
            return
        mock_email    = auth.email
        mock_password = auth.password
        print("Logging in with credentials:")
        print("Email: " + mock_email)
        print("Password: " + mock_password)
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
        self.create_artifacts()
        ui_test_banner()

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
        self.click_button(driver, "Authorize 1 device", timeout=600)
        xp = "//table/tbody[@class='clickable']/tr/td[3]/div"
        authorized_device = self.wait_for_element(driver, By.XPATH, xp, timeout=600)
        assert authorized_device
        authorized_device.click()
        timeout = time.time() + (60*5)

        while time.time() < timeout:
            time.sleep(0.2)
            if self.wait_for_element(driver, By.XPATH, xp).text == "qemux86-64":
                break
        else:
            raise Exception("Device never appeared for authorization")

        print("Found authorized_device: '" + authorized_device.text + "'")
        assert authorized_device.text == "qemux86-64"
        ui_test_success()
        self.destroy_driver(driver)

    def test_basic_inventory(self):
        ui_test_banner()
        driver = self.init_driver()
        self.login(driver)
        assert self.click_button(driver, "Devices")
        authorized_device = self.wait_for_element(driver, By.CSS_SELECTOR, "div.rightFluid.padding-right tbody.clickable > tr")
        assert authorized_device
        authorized_device.click()
        assert "qemux86-64" in authorized_device.text
        assert "mender-image-master" in authorized_device.text

        # make sure basic inventory items are there
        assert self.wait_for_element(driver, By.XPATH, "//*[contains(text(),'Linux version')]")
        assert self.wait_for_element(driver, By.XPATH, "//*[contains(text(),'eth0')]")
        assert self.wait_for_element(driver, By.XPATH, "//*[contains(text(),'ARM')]")
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

        # Locate and click the artifact we want to deploy "release-1":
        xp = "/html/body[@class='box-sizing']/div[3]/div/div/div/div[1]/span/div/div/div"
        target_artifact = self.wait_for_element(driver, By.XPATH, xp)
        assert target_artifact
        assert target_artifact.text == "release1"
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

    def test_deployment_in_progress(self):
        ui_test_banner()
        driver = self.init_driver()
        self.login(driver)
        assert self.click_button(driver, "Deployments")

        timeout = time.time() + 60*5
        while time.time() < timeout:
                e = self.wait_for_element(driver, By.CSS_SELECTOR, "span.status.inprogress")
                if e.text == '1':
                    break
                time.sleep(1)
        else:
            raise Exception("Deployment never in progress")

        ui_test_success()
        self.destroy_driver(driver)

    def test_deployment_successful(self):
        ui_test_banner()
        driver = self.init_driver()
        self.login(driver)
        assert self.click_button(driver, "Deployments")

        timeout = time.time() + 60*5
        while time.time() < timeout:
                e = self.wait_for_element(driver, By.CSS_SELECTOR, "span.status.success")
                if e.text == '1':
                    break
                time.sleep(1)
        else:
            raise Exception("Deployment never completed")

        ui_test_success()
        self.destroy_driver(driver)

    def create_artifacts(self):
        Helpers.artifact_id_randomize("core-image-full-cmdline-qemux86-64.ext4", specific_image_id="release1")
        subprocess.call("mender-artifact write rootfs-image -f core-image-full-cmdline-qemux86-64.ext4 -t qemux86-64 -n release1 -o qemux86-64_release_1.mender", shell=True)
        logging.debug("done creating arifacts")

def get_args():
    argparser = argparse.ArgumentParser(description='Test UI of mender web server')
    argparser.add_argument('--url', '-u', help='URL (default="https://localhost:8080/")', type=str, default='https://localhost:8080/')
    args = argparser.parse_args()
    return args


# For running without pytest:
if __name__ == '__main__':
    args = get_args()
    test = TestUI()
    test.create_artifacts()
    test.test_login_create_user()
    test.test_click_header_buttons()
    test.test_artifact_upload()
    test.test_authorize_all()
    test.test_basic_inventory()
    test.test_deploy()
    test.test_deployment_in_progress()
    test.test_deployment_successful()
    #pytest.main(args=[os.path.realpath(__file__)])#, "--url", args.url])
