"""CSV export of effective Includes with correct quoting and Excel BOM."""

import csv
import io
from fastapi import APIRouter, Response
from .. import models as m
from ._common import DB, record_summaries

router = APIRouter(tags=["export"])


@router.get(
    "/api/export.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_csv(db: DB):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "pmid",
            "doi",
            "title",
            "abstract",
            "year",
            "journal",
            "label",
            "reason",
        ],
    )
    writer.writeheader()
    for row in record_summaries(db, label="include"):
        record = db.get(m.Record, row["id"])
        writer.writerow(
            {
                key: record.abstract if key == "abstract" else row.get(key)
                for key in writer.fieldnames
            }
        )
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="included-studies.csv"'},
    )
