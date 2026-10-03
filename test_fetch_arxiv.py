import io
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import fetch_arxiv


ATOM_FEED = b'''<feed xmlns="http://www.w3.org/2005/Atom"
    xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
    <opensearch:totalResults>0</opensearch:totalResults>
</feed>'''


def curl_response(command, status, body, headers):
    Path(command[command.index("--output") + 1]).write_bytes(body)
    Path(command[command.index("--dump-header") + 1]).write_text(headers)
    return subprocess.CompletedProcess(command, 0, str(status), "")


class FetchCategoryTests(unittest.TestCase):
    @patch("fetch_arxiv.time.sleep")
    @patch("fetch_arxiv.urllib.request.urlopen")
    def test_http_failure_exhausts_retries_and_raises(self, urlopen, sleep):
        def rejected(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 406, "Not Acceptable",
                                         {"Server": "edge", "Retry-After": "60"}, io.BytesIO(b""))

        urlopen.side_effect = rejected

        with self.assertRaisesRegex(fetch_arxiv.FetchError, "HTTP 406") as failure:
            fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928")

        self.assertEqual(urlopen.call_count, fetch_arxiv.MAX_RETRIES)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], list(fetch_arxiv.RETRY_DELAYS))
        self.assertIn("after 5 attempts", str(failure.exception))
        self.assertIn("'Server': 'edge'", str(failure.exception))

    @patch("fetch_arxiv.time.sleep")
    @patch("fetch_arxiv.urllib.request.urlopen")
    def test_http_406_recovery_after_retry(self, urlopen, sleep):
        rejected = urllib.error.HTTPError("https://export.arxiv.org/api/query", 406,
                                          "Not Acceptable", {}, io.BytesIO(b""))
        response = urlopen.return_value
        response.__enter__.return_value.read.return_value = ATOM_FEED
        response.__enter__.return_value.status = 200
        urlopen.side_effect = [rejected, response]

        self.assertEqual(fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928"), ([], 0))
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(fetch_arxiv.RETRY_DELAYS[0])

    @patch("fetch_arxiv.time.sleep")
    @patch("fetch_arxiv.urllib.request.urlopen")
    def test_http_503_uses_longer_retry_schedule(self, urlopen, sleep):
        def rejected(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, io.BytesIO(b""))

        urlopen.side_effect = rejected

        with self.assertRaisesRegex(fetch_arxiv.FetchError, "HTTP 503"):
            fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928")

        self.assertEqual(urlopen.call_count, fetch_arxiv.MAX_RETRIES)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], list(fetch_arxiv.RETRY_DELAYS))

    @patch("fetch_arxiv.time.sleep")
    @patch("fetch_arxiv.urllib.request.urlopen")
    def test_http_503_recovers_on_fifth_attempt(self, urlopen, sleep):
        def rejected():
            return urllib.error.HTTPError("https://export.arxiv.org/api/query", 503,
                                          "Unavailable", {}, io.BytesIO(b""))

        response = urlopen.return_value
        response.__enter__.return_value.read.return_value = ATOM_FEED
        response.__enter__.return_value.status = 200
        urlopen.side_effect = [rejected() for _ in fetch_arxiv.RETRY_DELAYS] + [response]

        self.assertEqual(fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928"), ([], 0))
        self.assertEqual(urlopen.call_count, fetch_arxiv.MAX_RETRIES)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], list(fetch_arxiv.RETRY_DELAYS))

    @patch("fetch_arxiv.subprocess.run")
    def test_curl_transport_parses_atom_feed(self, run):
        run.side_effect = lambda command, **kwargs: curl_response(
            command, 200, ATOM_FEED, "HTTP/2 200\r\ncontent-type: application/atom+xml\r\n\r\n"
        )

        self.assertEqual(fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928",
                                                   transport="curl"), ([], 0))
        self.assertIn("--globoff", run.call_args.args[0])

    @patch("fetch_arxiv.time.sleep")
    @patch("fetch_arxiv.subprocess.run")
    def test_curl_transport_retries_http_429(self, run, sleep):
        responses = iter((
            (429, b"Rate exceeded.", "HTTP/2 429\r\nserver: edge\r\n\r\n"),
            (200, ATOM_FEED, "HTTP/2 200\r\ncontent-type: application/atom+xml\r\n\r\n"),
        ))
        run.side_effect = lambda command, **kwargs: curl_response(command, *next(responses))

        self.assertEqual(fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928",
                                                   transport="curl"), ([], 0))
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(fetch_arxiv.RETRY_DELAYS[0])

    @patch("fetch_arxiv.time.sleep")
    @patch("fetch_arxiv.subprocess.run")
    def test_curl_dns_failure_exits_without_long_retries(self, run, sleep):
        run.return_value = subprocess.CompletedProcess([], 6, "000", "Could not resolve host")

        with self.assertRaisesRegex(fetch_arxiv.FetchError, "DNS resolution failed"):
            fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928",
                                       transport="curl")

        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    @patch("fetch_arxiv.urllib.request.urlopen")
    def test_valid_empty_feed_is_not_a_failure(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = ATOM_FEED
        urlopen.return_value.__enter__.return_value.status = 200

        self.assertEqual(fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928"), ([], 0))

    @patch("fetch_arxiv.urllib.request.urlopen")
    def test_missing_result_count_is_a_failure(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'<feed xmlns="http://www.w3.org/2005/Atom" />'
        urlopen.return_value.__enter__.return_value.status = 200

        with self.assertRaisesRegex(fetch_arxiv.FetchError, "no totalResults"):
            fetch_arxiv.fetch_category("cond-mat.str-el", "20260928", "20260928")


class MainTests(unittest.TestCase):
    @patch("fetch_arxiv.read_previous", return_value=("20260928", set()))
    @patch("fetch_arxiv.get_date_range", return_value=None)
    @patch("fetch_arxiv.fetch_category")
    def test_no_date_range_exits_without_fetching(self, fetch_category, date_range, previous):
        fetch_arxiv.main(transport="curl")
        fetch_category.assert_not_called()

    @patch("fetch_arxiv.load_categories", return_value=["cond-mat.str-el"])
    @patch("fetch_arxiv.get_date_range", return_value=("20260928", "20260928"))
    @patch("fetch_arxiv.fetch_category")
    def test_curl_main_writes_complete_result(self, fetch_category, date_range, categories):
        fetch_category.return_value = ([{"arxiv_id": "2609.12345"}], 1)

        with tempfile.TemporaryDirectory() as directory:
            latest = Path(directory) / "latest.json"
            latest.write_text('{"fetched_at":"previous","papers":[]}')
            with patch.object(fetch_arxiv, "OUTPUT_PATH", str(latest)):
                fetch_arxiv.main(transport="curl")
            self.assertEqual(json.loads(latest.read_text())["papers"], [{"arxiv_id": "2609.12345"}])

        fetch_category.assert_called_once_with("cond-mat.str-el", "20260928", "20260928",
                                               transport="curl")

    @patch("fetch_arxiv.time.sleep")
    @patch("fetch_arxiv.load_categories", return_value=["cond-mat.str-el", "cond-mat.stat-mech"])
    @patch("fetch_arxiv.get_date_range", return_value=("20260928", "20260928"))
    @patch("fetch_arxiv.fetch_category")
    def test_partial_fetch_does_not_replace_latest(self, fetch_category, date_range, categories, sleep):
        fetch_category.side_effect = [
            ([{"arxiv_id": "2609.12345"}], 1),
            fetch_arxiv.FetchError("cond-mat.stat-mech 20260928: HTTP 406"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            latest = Path(directory) / "latest.json"
            latest.write_text('{"fetched_at":"previous"}')
            with patch.object(fetch_arxiv, "OUTPUT_PATH", str(latest)):
                with self.assertRaises(fetch_arxiv.FetchError):
                    fetch_arxiv.main()
            self.assertEqual(latest.read_text(), '{"fetched_at":"previous"}')


if __name__ == "__main__":
    unittest.main()
