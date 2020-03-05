import logging
import time
import os
import pytest
import subprocess
import time
import stripe

import pymongo

from testutils.common import mongo, mongo_cleanup, clean_mongo, create_org, randstr
from testutils.common import User
import testutils.api.useradm as useradm
import testutils.api.tenantadm as tenantadm_v1
import testutils.api.tenantadm_v2 as tenantadm_v2
import testutils.integration.stripe as stripeutils
from testutils.api.client import ApiClient

api_tadm_v1 = ApiClient(tenantadm_v1.URL_MGMT)
api_tadm_v2 = ApiClient(tenantadm_v2.URL_MGMT)

api_uadm = ApiClient(useradm.URL_MGMT)
stripe.api_key = os.environ.get("TENANTADM_STRIPE_API_KEY")
if stripe.api_key is None:
    raise RuntimeError("provide the TENANTADM_STRIPE_API_KEY variable!")


class TestCreateOrganizationV2EnterpriseNew:
    """ Test the 'new tenant' workflow.
    
    - registration on v2 endpoint -> tenant secret
    - UI collects card, does extra SCA confirmation as necessary (with secret)
    - account is completely unusable for now
    - UI sets tenant status to 'active':
        - the confirmed payment method is assigned to tenant's stripe customer
        - users can log in now

    Most of the UI work is emulated, see comments.
    """

    def test_ok_non_sca_cards(self, clean_mongo):
        """ Basic test card numbers.

        These cards won't trigger extra auth flows, but still have to work with the SCA-ready workflow.
        They are actually the only cards we can use to test the whole flow on the backend side.

        See https://stripe.com/docs/testing#cards.

        Some of these are omitted - they are in fact being rejected with:
        'Please use a Visa, MasterCard, or American Express card'
        """

        for card in [
            "pm_card_visa",
            "pm_card_visa_debit",
            "pm_card_mastercard",
            "pm_card_mastercard_debit",
            "pm_card_mastercard_prepaid",
            "pm_card_amex",
            "pm_card_br",
            "pm_card_ca",
            "pm_card_mx",
        ]:

            tenant = "tenant{}".format(randstr())
            uname, upass = "user@{}.com".format(tenant), "asdfqwer1234"
            payload = {
                "request_id": "123456",
                "organization": tenant,
                "email": uname,
                "password": upass,
                "g-recaptcha-response": "foobar",
            }

            res = api_tadm_v2.call(
                "POST",
                tenantadm_v2.URL_CREATE_ORG_TENANT,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=payload,
            )
            assert res.status_code == 200

            secret = res.json()["secret"]
            assert len(secret) > 0
            tid = res.json()["id"]

            # user can't log in until the org is activated
            r = api_uadm.call("POST", useradm.URL_LOGIN, auth=(uname, upass))
            assert r.status_code == 401

            # we're emulating CC collection (and setup intent confirmation)
            # setup intent cofirm is the last step normally done by the stripe ui components
            seti = stripeutils.find_setup_intent(secret)

            stripeutils.confirm(card, seti["id"])

            # tenant can be activated now
            res = api_tadm_v2.call(
                "PUT",
                tenantadm_v2.URL_TENANT_STATUS,
                path_params={"id": tid},
                body={"status": "active"},
            )
            assert res.status_code == 202

            # wait for create org workflow, try login
            try_login(api_uadm, uname, upass)

            # verify that tenant's customer has an attached
            # payment method/default payment method
            cust = stripeutils.customer_for_tenant(uname)
            stripeutils.customer_has_pm(cust)

            # cleanup
            # setup intents can't be cleaned up apparently, cancel doesn't work
            stripeutils.delete_cust(cust["id"])

    def test_ok_sca_cards(self, clean_mongo):
        """ Regulatory test card numbers.

        These regulatory cards that will trigger the 3D Secure SCA checks.
        The UI check here is mandatory, and can't be cheated around - 
        so just verify that without it, tenant can't be activated at all.

        Actually, it's just a couple cards from the test set. Others allow
        confirming the card without extra steps. They were selected by trial and error.

        See https://stripe.com/docs/testing#three-ds-cards.

        """

        for card in [
            "pm_card_authenticationRequiredOnSetup",
            "pm_card_authenticationRequired",
            "pm_card_threeDSecure2Required",
        ]:
            tenant = "tenant{}".format(randstr())
            uname, upass = "user@{}.com".format(tenant), "asdfqwer1234"

            payload = {
                "request_id": "123456",
                "organization": tenant,
                "email": uname,
                "password": upass,
                "g-recaptcha-response": "foobar",
            }

            res = api_tadm_v2.call(
                "POST",
                tenantadm_v2.URL_CREATE_ORG_TENANT,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=payload,
            )
            assert res.status_code == 200

            secret = res.json()["secret"]
            assert len(secret) > 0
            tid = res.json()["id"]

            # user can't log in until the org is activated
            r = api_uadm.call("POST", useradm.URL_LOGIN, auth=(uname, upass))
            assert r.status_code == 401

            # we're emulating CC collection (and setup intent confirmation)
            # setup intent cofirm is the last step normally done by the stripe ui components
            seti = stripeutils.find_setup_intent(secret)

            # this will pass, because it's a test mode - but still the card will be unconfirmed/unusable
            stripeutils.confirm(card, seti["id"])

            # tenant *cannot* be activated
            # because the auth was not completed
            res = api_tadm_v2.call(
                "PUT",
                tenantadm_v2.URL_TENANT_STATUS,
                path_params={"id": tid},
                body={"status": "active"},
            )

            # looks weird be we *do* expect this
            # we don't propagate this stripe error to users, nobody has
            # any business calling this EP on an unverfied card
            # internal error: Credit card not verified yet
            assert res.status_code == 500

            # verify that the user can't log in (ever, actually)
            r = api_uadm.call("POST", useradm.URL_LOGIN, auth=(uname, upass))
            assert r.status_code == 401


class TestCreateOrganizationV2EnterpriseExisting:
    def test_ok(self, clean_mongo):
        name = "existing-tenant" + randstr()
        email = "user@{}.com".format(name)
        res = create_org_v1(name, email, "asdfqwer1234", "tok_visa")

        # wait for create org workflow
        utok = try_login(api_uadm, email, "asdfqwer1234")

        # what's the tenant id?
        res = api_tadm_v1.with_auth(utok).call("GET", tenantadm_v1.URL_MGMT_THIS_TENANT)
        assert res.status_code == 200

        tid = res.json()["id"]

        res = api_tadm_v2.with_auth(utok).call("POST", tenantadm_v2.URL_TENANT_SECRET)
        assert res.status_code == 200
        secret = res.json()["secret"]

        # UI uses the secret to collect card and confirm the setup intent
        # let's use a different card
        seti = stripeutils.find_setup_intent(secret)
        stripeutils.confirm("pm_card_mastercard", seti["id"])

        res = api_tadm_v2.call(
            "PUT",
            tenantadm_v2.URL_TENANT_STATUS,
            path_params={"id": tid},
            body={"status": "active"},
        )
        assert res.status_code == 202

        # verify the old source is detached and new one attached
        cust = stripeutils.customer_for_tenant(email)

        assert cust["default_source"] == None
        assert len(cust["sources"]) == 0

        stripeutils.customer_has_pm(cust)

        # cleanup
        # setup intents can't be cleaned up apparently, cancel doesn't work
        stripeutils.delete_cust(cust["id"])


def create_org_v1(name, email, pwd, card_token):
    args = {
        "organization": name,
        "email": email,
        "password": pwd,
        "token": card_token,
        "name": "dummy name",
        "g-recaptcha-response": "dummy",
    }

    res = api_tadm_v1.call(
        "POST",
        tenantadm_v1.URL_MGMT_TENANTS,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=args,
    )
    assert res.status_code == 202
    return res


def try_login(api, name, pwd, timeout_secs=60):
    for i in range(timeout_secs):
        rsp = api.call("POST", useradm.URL_LOGIN, auth=(name, pwd))
        if rsp.status_code == 200:
            return rsp.text
        time.sleep(1)

    assert False, "user couldn't log in in {} secs".format(timeout_secs)
