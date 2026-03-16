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
import stripe


stripe.api_key = os.environ.get("TENANTADM_STRIPE_API_KEY")
if stripe.api_key is None:
    raise RuntimeError("provide the TENANTADM_STRIPE_API_KEY variable!")


def find_setup_intent(seti_secret):
    """ Retrieve SetupIntent."""
    res = stripe.SetupIntent.list()
    found = [seti for seti in res["data"] if seti["client_secret"] == seti_secret]
    assert len(found) == 1
    return found[0]


def confirm(cc, seti_id):
    """ Confirm a SetupIntent."""
    stripe.SetupIntent.confirm(seti_id, payment_method=cc)


def customer_for_tenant(email):
    """ Get customer associated with the tenant."""
    stripe_custs = stripe.Customer.list(email=email)
    assert len(stripe_custs.data) == 1
    found = stripe_custs.data[0]
    return found


def customer_has_pm(cust):
    """ Verify that a payment method is attached to the customer. """
    res = stripe.PaymentMethod.list(customer=cust["id"], type="card")

    method = [d for d in res["data"]]
    assert len(method) == 1
    method = method[0]

    assert cust["invoice_settings"]["default_payment_method"] == method["id"]


def delete_cust(cust_id):
    """ Doesn't really delete the customer.
        It's not possible in stripe; customers will accumulate.
        This only sets a 'deleted' flag, but maybe that's a good idea?
        Perhaps stripe uses this as a hint to remove stale
        customers at least in the staging env.
    """
    stripe.Customer.delete(cust_id)
