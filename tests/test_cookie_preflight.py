# -*- coding: utf-8 -*-
"""Cookie 预检单元测试。"""
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from utils.utils import check_admin_cookie_valid
from webui.validators import COOKIE_EXPIRED_DETAIL, ADMIN_NETWORK_ERROR_DETAIL, validate_admin_cookie


def _mock_response(status_code: int, payload: dict):
    res = MagicMock()
    res.status_code = status_code
    res.json.return_value = payload
    return res


class TestCheckAdminCookieValid(unittest.TestCase):
    @patch("utils.utils.requests.get")
    def test_expired_cookie_returns_expired(self, mock_get):
        mock_get.return_value = _mock_response(200, {"code": 5, "msg": "请先登录", "data": None})
        ok, reason = check_admin_cookie_valid("ovsmgr_sid=test")
        self.assertFalse(ok)
        self.assertEqual(reason, "expired")

    @patch("utils.utils.requests.get")
    def test_valid_cookie_returns_ok(self, mock_get):
        mock_get.return_value = _mock_response(200, {"code": 0, "msg": "success", "data": {"role": "admin"}})
        ok, reason = check_admin_cookie_valid("ovsmgr_sid=test")
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    @patch("utils.utils.requests.get")
    def test_network_error_returns_network(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("connection refused")
        ok, reason = check_admin_cookie_valid("ovsmgr_sid=test")
        self.assertFalse(ok)
        self.assertEqual(reason, "network")

    @patch("utils.utils.requests.get")
    def test_empty_cookie_returns_expired(self, mock_get):
        ok, reason = check_admin_cookie_valid("")
        self.assertFalse(ok)
        self.assertEqual(reason, "expired")
        mock_get.assert_not_called()


class TestValidateAdminCookie(unittest.TestCase):
    @patch("webui.validators.check_admin_cookie_valid", return_value=(False, "expired"))
    def test_validate_raises_401_on_expired(self, _mock_check):
        with self.assertRaises(HTTPException) as ctx:
            validate_admin_cookie("ovsmgr_sid=test")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, COOKIE_EXPIRED_DETAIL)

    @patch("webui.validators.check_admin_cookie_valid", return_value=(False, "network"))
    def test_validate_raises_503_on_network(self, _mock_check):
        with self.assertRaises(HTTPException) as ctx:
            validate_admin_cookie("ovsmgr_sid=test")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, ADMIN_NETWORK_ERROR_DETAIL)

    @patch("webui.validators.check_admin_cookie_valid", return_value=(True, ""))
    def test_validate_passes_when_ok(self, _mock_check):
        validate_admin_cookie("ovsmgr_sid=test")


if __name__ == "__main__":
    unittest.main()
