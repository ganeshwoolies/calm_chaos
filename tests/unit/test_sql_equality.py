import pytest

from app.attest import _attester
from tests.knowledge_copy import REPO_BUNDLE

attester = _attester(REPO_BUNDLE, "/attesters/sql_equality.py")

SANCTIONED = """-- lineage
SELECT batch_id, code FROM batches
WHERE product_id = @product_id AND code IN UNNEST(@codes)  # inline comment
ORDER BY code"""


@pytest.mark.parametrize(
    "executed",
    [
        SANCTIONED,
        "select batch_id, code from batches where product_id = @product_id and code in unnest(@codes) order by code",
        "SELECT batch_id,\n  code\nFROM batches /* block */ WHERE product_id = @product_id AND code IN UNNEST(@codes)\n"
        "ORDER BY code;",
    ],
)
def test_equal_under_comments_whitespace_and_keyword_case(executed) -> None:
    assert attester.verify(SANCTIONED, executed) == (True, None)


@pytest.mark.parametrize(
    "executed",
    [
        SANCTIONED.replace("batches", "Batches"),  # table names are case-sensitive
        SANCTIONED.replace(
            "@codes", "['B2026-091']"
        ),  # a literal instead of the parameter
        SANCTIONED + " LIMIT 1",
        SANCTIONED.replace("product_id = @product_id AND ", ""),
    ],
)
def test_unequal_when_the_query_changes(executed) -> None:
    ok, reason = attester.verify(SANCTIONED, executed)
    assert not ok and "differs" in reason


def test_string_literals_are_kept_verbatim() -> None:
    a = "SELECT 'Select -- not a comment' AS x"
    assert attester.verify(a, a)[0]
    assert not attester.verify(a, "SELECT 'select -- not a comment' AS x")[0]
