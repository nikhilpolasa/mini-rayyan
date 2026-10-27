"""CSV serialization of caller-selected studies; database filtering stays upstream."""

import csv
import io

CSV_FIELDS = ("pmid", "doi", "title", "abstract", "year", "journal", "label", "reason")


def to_csv(rows: list[dict]) -> str:
    """Return quoted CSV text carrying one UTF-8 BOM, including a header when empty.

    The str contract is preserved. Encode the result with utf-8 for download or
    write with encoding='utf-8'; the BOM is already present. Input rows should
    already be filtered to visible, effectively Included studies by the caller.
    """
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows or []:
        writer.writerow(row if isinstance(row, dict) else {})
    return output.getvalue().encode("utf-8-sig").decode("utf-8")
