import argparse
from typing import Any
from unittest.mock import Mock

import pytest
from deploy import zitadel_security


def args(**values: Any) -> argparse.Namespace:
    return argparse.Namespace(**{"apply": True, "password": 5, "otp": 5, **values})


def test_lockout_adds_an_organization_policy_over_the_default() -> None:
    client = Mock()
    client.call.return_value = {"policy": {"isDefault": True}}
    zitadel_security.lockout(client, "token", "org", args())
    client.call.assert_called_with(
        "POST",
        "/management/v1/policies/lockout",
        {"maxPasswordAttempts": 5, "maxOtpAttempts": 5},
        token="token",
        org="org",
    )


@pytest.mark.parametrize(
    ("policy", "apply"),
    [({"maxPasswordAttempts": "5", "maxOtpAttempts": "5"}, True), ({}, False)],
)
def test_lockout_writes_only_changes_when_applied(
    policy: dict[str, Any], apply: bool
) -> None:
    client = Mock()
    client.call.return_value = {"policy": policy}
    zitadel_security.lockout(client, "token", "org", args(apply=apply))
    assert client.call.call_count == 1


def test_force_mfa_keeps_the_rest_of_the_login_policy() -> None:
    policy = {
        "isDefault": True,
        "details": {"sequence": "1"},
        "allowRegister": True,
        "allowUsernamePassword": True,
        "passwordCheckLifetime": "864000s",
        "secondFactors": ["SECOND_FACTOR_TYPE_OTP"],
        "multiFactors": [],
    }
    client = Mock()
    client.call.return_value = {"policy": policy}
    zitadel_security.force_mfa(client, "token", "org", args())
    method, path, body = client.call.call_args.args
    assert (method, path) == ("POST", "/management/v1/policies/login")
    assert body == {
        "allowRegister": True,
        "allowUsernamePassword": True,
        "passwordCheckLifetime": "864000s",
        "forceMfa": True,
        "secondFactors": ["SECOND_FACTOR_TYPE_OTP"],
        "multiFactors": [],
    }
