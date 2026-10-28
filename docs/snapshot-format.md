# Provisional frozen snapshot format

**Provisional:** organizers have not announced their offline test format. This is
our local replay format, not a claim of compatibility with the judge's snapshot.
The swap point for the official format is `SnapshotSourceClient` in
`backend/app/services/pubmed.py`. The three `SourceClient` methods and API remain
the same.

```json
{
  "version": 1,
  "queries": {
    "sertraline[tiab] and placebo[tiab]": {
      "count": 378,
      "pmids": ["42888376", "42766718"]
    }
  },
  "records": {
    "42888376": {
      "pmid": "42888376",
      "doi": "10.1234/example",
      "title": "A placebo-controlled trial of sertraline",
      "abstract": "Adults were randomly assigned to sertraline or placebo.",
      "authors": ["Example A"],
      "year": 2024,
      "journal": "Example Journal",
      "language": "eng",
      "pub_types": ["Randomized Controlled Trial"],
      "mesh": ["Humans"],
      "source": "pubmed"
    }
  }
}
```

Query keys are normalized by lowercasing and collapsing whitespace; punctuation,
field tags, and Boolean syntax are otherwise unchanged. An unknown query returns
count 0, translation `not in snapshot`, and no IDs. It is unsupported by the
snapshot; this does not assert that PubMed has zero matching papers.

`count` is the captured live hit count. `pmids` can contain only the first
`FETCH_CAP` IDs, so `count` may exceed the number available to pull. When the
manifest is complete (`count` equals the number of PMIDs), the adapter reports
the count after filtering. Otherwise it keeps the captured count, which cannot
be accurately filtered from a partial manifest. IDs with a `year` are filtered
inclusively by the requested start/end **years**; IDs without a year remain
eligible because their publication date is unknown. Day/month precision and
date-filtered counts from incomplete manifests are not available.

Set `SOURCE_MODE=snapshot` and `SNAPSHOT_PATH` to the JSON file. No network
requests occur in this mode. To capture a local provisional file, put one PubMed
query per line in a UTF-8 text file, configure `NCBI_EMAIL`, then run:

```powershell
.\.venv\Scripts\python.exe scripts/make_snapshot.py queries.txt sample-snapshot.json --date-from 2016-01-01 --date-to 2026-10-27
```

Capture uses the existing paced live PubMed client, respects `FETCH_CAP`, and
refuses to overwrite an existing file. A live search in the future can return
different results; replay is limited to this captured file.
