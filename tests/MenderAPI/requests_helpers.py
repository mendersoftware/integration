import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Will retry on 500 Server error
def requests_retry(status_forcelist=[500, 502]):
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=status_forcelist,
        method_whitelist=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s
