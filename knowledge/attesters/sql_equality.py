"""Attester for BigQuery computations: the SQL BigQuery executed must equal the sanctioned file.

Both texts are canonicalised the same way before comparing: comments removed, whitespace collapsed, reserved keywords
upper-cased, a trailing semicolon dropped. String literals and backtick identifiers are kept verbatim, and identifiers
keep their case because BigQuery table names are case-sensitive. No model is involved.
"""

KEYWORDS = frozenset(
    """ALL AND ANY ARRAY AS ASC ASSERT_ROWS_MODIFIED AT BETWEEN BY CASE CAST COLLATE CONTAINS CREATE CROSS CUBE CURRENT
    DEFAULT DEFINE DESC DISTINCT ELSE END ENUM ESCAPE EXCEPT EXCLUDE EXISTS EXTRACT FALSE FETCH FOLLOWING FOR FROM FULL
    GROUP GROUPING GROUPS HASH HAVING IF IGNORE IN INNER INTERSECT INTERVAL INTO IS JOIN LATERAL LEFT LIKE LIMIT LOOKUP
    MERGE NATURAL NEW NO NOT NULL NULLS OF ON OR ORDER OUTER OVER PARTITION PRECEDING PROTO QUALIFY RANGE RECURSIVE
    RESPECT RIGHT ROLLUP ROWS SELECT SET SOME STRUCT TABLESAMPLE THEN TO TREAT TRUE UNBOUNDED UNION UNNEST USING WHEN
    WHERE WINDOW WITH WITHIN""".split()
)


def _quoted_end(sql: str, start: int) -> int:
    """Index just past the literal or backtick identifier that opens at start."""
    quote = sql[start]
    if quote in "'\"" and sql.startswith(quote * 3, start):
        end = sql.find(quote * 3, start + 3)
        return len(sql) if end < 0 else end + 3
    i = start + 1
    while i < len(sql):
        if sql[i] == "\\" and quote != "`":
            i += 2
            continue
        if sql[i] == quote:
            return i + 1
        i += 1
    return len(sql)


def canonical(sql: str) -> str:
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i) or c == "#":
            end = sql.find("\n", i)
            i = n if end < 0 else end
            out.append(" ")
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
        elif c in "'\"`":
            end = _quoted_end(sql, i)
            out.append(sql[i:end])
            i = end
        elif c.isspace():
            out.append(" ")
            i += 1
        elif c.isalpha() or c == "_":
            end = i
            while end < n and (sql[end].isalnum() or sql[end] == "_"):
                end += 1
            word = sql[i:end]
            out.append(word.upper() if word.upper() in KEYWORDS else word)
            i = end
        else:
            out.append(c)
            i += 1
    return " ".join("".join(out).split()).rstrip(";").rstrip()


def verify(sanctioned: str, executed: str) -> tuple[bool, str | None]:
    a, b = canonical(sanctioned), canonical(executed)
    if a == b:
        return True, None
    at = next(
        (k for k, (x, y) in enumerate(zip(a, b, strict=False)) if x != y),
        min(len(a), len(b)),
    )
    return (
        False,
        f"executed SQL differs from the sanctioned file at canonical offset {at}: {b[at : at + 40]!r}",
    )
