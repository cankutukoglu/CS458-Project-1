import json
import logging
from urllib import request as url_request, error as url_error, parse as url_parse

from config import RECAPTCHA_SITE_KEY, RECAPTCHA_SECRET_KEY, RECAPTCHA_VERIFY_URL

log = logging.getLogger(__name__)


class ReCaptchaService:
    def __init__(self):
        self.site_key = RECAPTCHA_SITE_KEY
        self.secret_key = RECAPTCHA_SECRET_KEY
        self.verify_url = RECAPTCHA_VERIFY_URL

    def is_enabled(self):
        return bool(self.site_key and self.secret_key)

    def verify_token(self, token, remote_ip):
        if not self.is_enabled():
            return True, None

        if not token:
            return False, "Please complete the reCAPTCHA challenge."

        payload = {"secret": self.secret_key, "response": token}
        if remote_ip:
            payload["remoteip"] = remote_ip

        encoded_payload = url_parse.urlencode(payload).encode("utf-8")
        verify_request = url_request.Request(
            self.verify_url,
            data=encoded_payload,
            method="POST",
        )

        try:
            with url_request.urlopen(verify_request, timeout=5) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (url_error.URLError, TimeoutError, ValueError) as exc:
            log.warning("reCAPTCHA verification failed due to upstream/network issue: %s", exc)
            return False, "Could not verify reCAPTCHA. Please try again."

        if not result.get("success", False):
            log.info(
                "reCAPTCHA validation rejected token with errors: %s",
                result.get("error-codes", []),
            )
            return False, "reCAPTCHA challenge failed. Please try again."

        return True, None
