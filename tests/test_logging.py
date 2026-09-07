import io
import logging
import re

from buffetbot.logging import RedactingFormatter, Redactor


def test_messages_structured_fields_and_exception_text_are_redacted():
    secret = 'DUMMY_SECRET_WITH_"QUOTE_AND_NEWLINE\nEND'
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(Redactor([secret]), "run-123"))
    logger = logging.Logger("buffetbot.test")
    logger.addHandler(handler)
    logger.warning("api_key=%s", "DUMMY_UNREGISTERED_FIELD", extra={"job_id": "job-456"})
    logger.info("Authorization: Bearer DUMMY_AUTH_HEADER")
    logger.info("headers %r", {"Authorization": "Bearer DUMMY_STRUCTURED_AUTH"})
    logger.info("request %r", {"api_key": "DUMMY_ESCAPED_'QUOTE"})
    logger.info("payload %r", {"api_secret": secret})
    try:
        raise ValueError(secret)
    except ValueError:
        logger.exception("Operation failed")
    output = stream.getvalue()
    assert "DUMMY_" not in output
    assert "[REDACTED]" in output
    assert "Traceback" in output
    assert "WARNING buffetbot.test run=run-123 job=job-456" in output
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", output)


def test_redaction_does_not_hide_normal_diagnostics():
    assert (
        Redactor()("Account unavailable; reconnect later.")
        == "Account unavailable; reconnect later."
    )


def test_redaction_is_idempotent_for_known_unquoted_fields():
    redactor = Redactor(["DUMMY_KEY"])
    result = redactor("api_key=DUMMY_KEY")
    assert result == "api_key=[REDACTED]"
    assert redactor(result) == result
