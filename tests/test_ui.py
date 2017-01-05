#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test mender via web server and selenium"""

__authors__    = ["Ole Herman Schumacher Elgesem"]

# System
import os
import sys
import random
from time import sleep

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

def tag_contents_xpath(tag, content):
    content = content.lower()
    return '//{}[contains(translate(*,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"{}")]'.format(tag, content)

class TestUI(object):
    def init_driver(self, url="https://localhost:8080/"):
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
        path1 = "mender-artifact"
        path2 = "mender-artifact2"
        download_if_needed(url1, path1)
        download_if_needed(url2, path2)

    def wait_for_element(self, driver, timeout, by, arg):
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
                    print("Could not click: " + element.text)
                    return False
        except selenium.common.exceptions.StaleElementReferenceException:
            return False

    def click_button(self, driver, label, timeout=3):
        xp = tag_contents_xpath("button", label)
        element = self.wait_for_element(driver, timeout, By.XPATH, xp)
        if not element:
            print("Button not found: " + label)
            return False
        print("Clicking: {} ({})".format(label, element))
        return self.attempt_click(element)

    def click_random_button(self, driver):
        buttons = driver.find_elements_by_tag_name("button")
        if not buttons:
            return False
        random.shuffle(buttons)
        for button in buttons:
            if self.attempt_click(button):
                return True
        return False

    def upload_artifact(self, driver, path, name, description):
        element = None
        while element is None:
            try:
                element = driver.find_element_by_name("artifactFile")
            except:
                pass
            sleep(0.2)
        element.send_keys(os.path.abspath(path))
        name_field = driver.find_element_by_id("name")
        name_field.click()
        name_field.send_keys(name)
        description_field = driver.find_element_by_id("description")
        description_field.click()
        description_field.send_keys(description)
        assert self.click_button(driver, "Save artifact")
        xp = tag_contents_xpath("tr", name)
        element = self.wait_for_element(driver, 20, By.XPATH, xp)
        assert element

    def upload_artifacts(self, driver):
        self.click_button(driver, "Upload Artifact File")
        self.upload_artifact(driver, "mender-artifact",
                                     "Test artifact name 1",
                                     "Test artifact description 1")
        self.click_button(driver, "Upload Artifact File")
        self.upload_artifact(driver, "mender-artifact2",
                                     "Test artifact name 2",
                                     "Test artifact description 2")

    def login(self, driver):
        if "login" not in driver.current_url:
            return
        mock_email    = "mock_email@cfengine.com"
        mock_password = "selenium.fox.rainbow.dog"
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
        element = self.wait_for_element(driver, 5, By.XPATH, xp)
        assert element

    def test_login_create_user(self):
        try:
            driver = self.init_driver()
            self.login(driver)
        finally:
            self.destroy_driver(driver)

    def test_click_header_buttons(self):
        try:
            driver = self.init_driver()
            self.login(driver)
            assert self.click_button(driver, "Dashboard")
            assert self.click_button(driver, "Devices")
            assert self.click_button(driver, "Artifacts")
            assert self.click_button(driver, "Deployments")
        finally:
            self.destroy_driver(driver)

    def test_artifact_upload(self):
        self.download_images()
        try:
            driver = self.init_driver()
            self.login(driver)
            assert self.click_button(driver, "Artifacts")
            self.upload_artifacts(driver)
        finally:
            self.destroy_driver(driver)

    def test_authorize_all(self):
        try:
            driver = self.init_driver()
            self.login(driver)
            assert self.click_button(driver, "Devices")
            self.click_button(driver, "Authorize all")
            xp = tag_contents_xpath("tbody", "vexpress-qemu")
            element = self.wait_for_element(driver, 20, By.XPATH, xp)
            assert element
        finally:
            self.destroy_driver(driver)

    # def test_deploy(self):
    #     try:
    #         driver = self.init_driver()
    #         self.login(driver)
    #         assert self.click_button(driver, "Deployments")
    #         assert self.click_button(driver, "Create a Deployment")
    #         xp = tag_contents_xpath("label", "Select target artifact")
    #         drop_down = self.wait_for_element(driver, 5, By.XPATH, xp)
    #         assert drop_down
    #         #drop_down.click()
    #         # Doesn't work! :(
    #         xp = tag_contents_xpath("label", "Select target artifact")
    #         xp = '//label[*="Select target artifact"]'
    #         option = self.wait_for_element(driver, 5, By.XPATH, xp)
    #         option.click()
    #
    #         # ....
    #
    #         assert test.click_button(driver, "Create Deployment")
    #     finally:
    #         self.destroy_driver(driver)

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
    #test.test_deploy()
    #pytest.main(args=[os.path.realpath(__file__)])#, "--url", args.url])
