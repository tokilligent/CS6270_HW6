# HW6 – Widget Request Consumer (Python)

## Setup
```
conda activate cs5270
pip install -r requirements.txt
```

## Run
```
python -m consumer --help
python -m consumer -rb usu-cs5270-toki-requests -s s3 -wb usu-cs5270-toki-web
python -m consumer -rb usu-cs5270-toki-requests -s dynamodb -dwt widgets -mit 10000
```
`-mrt/--max-runtime` and `-mit/--max-idle` (ms, 0 = unlimited) are stop conditions; Ctrl-C also stops cleanly.
The log goes to `consumer.log` (change with `-l`) and to stderr.

## Tests
```
python -m pytest --cov=consumer --cov-branch --cov-report=term-missing
```
Each test file's docstring lists the paths (path testing) and input partitions (input validation
testing) it covers. AWS clients are faked with botocore's `Stubber`; the loop uses in-memory fakes
and a fake clock.

## Design
| Module | Responsibility |
|---|---|
| `models.py` | `WidgetRequest`, `Widget`; `parse_request()` parses JSON and validates against the Appendix A schema (jsonschema) |
| `sources.py` | `RequestSource` interface; `S3RequestSource` lists one key (smallest first), gets it, deletes it |
| `storage.py` | `WidgetStore` interface; `S3WidgetStore` (JSON at `widgets/{owner}/{id}`), `DynamoWidgetStore` (one attribute per property) |
| `processor.py` | `RequestProcessor` dispatches create/update/delete to handlers; update/delete are logged and skipped until HW7 |
| `loop.py` | `Consumer` polling loop: get request → process → repeat; wait `--poll-interval` (100 ms) when there's none |
| `cli.py` | click command-line parsing, logging setup, and wiring of the concrete source/store |

The `Consumer` depends only on the `RequestSource` and `WidgetStore` abstractions. To read from a queue later,
add a new `RequestSource` subclass and choose it in `cli.build_source`; nothing else changes. The sleep
function and clock are injected, so the loop can be unit tested without waiting in real time.

Libraries used: boto3 (AWS), click (CLI), jsonschema + json (parsing/validation), logging (log file), pytest.

## System test logs
`logs/producer-*.log` and `logs/consumer-*.log`: one run storing widgets in S3 and one storing them in DynamoDB.
