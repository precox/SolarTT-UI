"""Small GitHub API client shared by release discovery and health reporting."""
import http.client
import json
import time
import urllib.error
import urllib.request

DOWNSTREAM = "precox/SolarTT-UI"


class GitHubError(RuntimeError):
    pass


class GitHubAPI:
    def __init__(self, token=None):
        self.token = token

    def request(self, method, path, payload=None):
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "SolarTT-UI-upstream-watch"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request("https://api.github.com" + path,
                                         data=data, headers=headers, method=method)
        # Only reads may be retried. An ambiguous POST can already have created
        # an issue; fail and let the next serialized run rediscover it.
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                # Rate limits fail immediately for a later workflow rerun; do
                # not retry ahead of GitHub's Retry-After/reset window.
                retryable = 500 <= error.code <= 599 and not error.headers.get("Retry-After")
                if retryable and attempt + 1 < attempts:
                    time.sleep(2 ** attempt)
                    continue
                hint = " (rate limit; retry the workflow later)" if error.code in (403, 429) else ""
                raise GitHubError(f"GitHub {method} {path}: HTTP {error.code}{hint}") from None
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
                if attempt + 1 < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise GitHubError(f"GitHub {method} {path}: network failure") from None
            except (ValueError, UnicodeError):
                raise GitHubError(f"GitHub {method} {path}: invalid JSON") from None

    def pages(self, path):
        """Read every page, including closed issues; never use search indexing."""
        separator = "&" if "?" in path else "?"
        for page in range(1, 1001):
            items = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise GitHubError(f"GitHub {path}: expected an array of objects")
            yield from items
            if len(items) < 100:
                return
        raise GitHubError(f"GitHub {path}: pagination safety limit reached")
