from adaptive_synth_eval.artifacts.fingerprints import (
    _secret_safe_payload,
    fingerprint_payload,
)


def test_operational_token_fields_are_included_in_fingerprints():
    baseline = {
        "reserve_tokens": 100,
        "max_tokens": 200,
        "prompt_tokens": 10,
        "completion_tokens": 20,
    }

    for field in baseline:
        changed = {**baseline, field: baseline[field] + 1}
        assert fingerprint_payload(changed) != fingerprint_payload(baseline), field


def test_credential_fields_are_redacted_but_env_field_names_are_not():
    first = {
        "token": "token-first",
        "access_token": "access-first",
        "refresh_token": "refresh-first",
        "api_key": "key-first",
        "client_secret": "secret-first",
        "password": "password-first",
        "authorization": "Bearer first",
        "api_key_env": "PROVIDER_API_KEY",
    }
    second = {
        **first,
        "token": "token-second",
        "access_token": "access-second",
        "refresh_token": "refresh-second",
        "api_key": "key-second",
        "client_secret": "secret-second",
        "password": "password-second",
        "authorization": "Bearer second",
    }

    safe = _secret_safe_payload(first)

    assert fingerprint_payload(first) == fingerprint_payload(second)
    assert safe["api_key_env"] == "PROVIDER_API_KEY"
    assert not any(
        secret in repr(safe)
        for secret in (
            "token-first",
            "access-first",
            "refresh-first",
            "key-first",
            "secret-first",
            "password-first",
            "Bearer first",
        )
    )


def test_auth_mapping_preserves_behavior_config_and_redacts_only_credentials():
    baseline = {
        "auth": {
            "type": "bearer",
            "env_var": "CHATBOT_API_TOKEN",
            "token_env": "CHATBOT_FALLBACK_TOKEN",
            "header_name": "Authorization",
            "scheme": "Bearer",
            "prefix": "Token ",
            "value": "literal-first",
            "credential": "credential-first",
        }
    }
    safe = _secret_safe_payload(baseline)

    assert safe["auth"] == {
        "type": "bearer",
        "env_var": "CHATBOT_API_TOKEN",
        "token_env": "CHATBOT_FALLBACK_TOKEN",
        "header_name": "Authorization",
        "scheme": "Bearer",
        "prefix": "Token ",
        "value": "<redacted>",
        "credential": "<redacted>",
    }
    for field, changed_value in (
        ("type", "api_key"),
        ("env_var", "OTHER_API_TOKEN"),
        ("token_env", "OTHER_FALLBACK_TOKEN"),
        ("header_name", "x-api-key"),
        ("scheme", "Token"),
        ("prefix", "ApiKey "),
    ):
        changed = {"auth": {**baseline["auth"], field: changed_value}}
        assert fingerprint_payload(changed) != fingerprint_payload(baseline), field

    changed_secrets = {
        "auth": {
            **baseline["auth"],
            "value": "literal-second",
            "credential": "credential-second",
        }
    }
    assert fingerprint_payload(changed_secrets) == fingerprint_payload(baseline)


def test_value_fields_outside_auth_are_not_generically_redacted():
    first = {"rule": {"value": "behavior-one", "credential": "safe-label-one"}}
    second = {"rule": {"value": "behavior-two", "credential": "safe-label-two"}}

    assert _secret_safe_payload(first) == first
    assert fingerprint_payload(first) != fingerprint_payload(second)
