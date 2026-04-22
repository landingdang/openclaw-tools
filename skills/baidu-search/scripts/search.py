import sys
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
import urllib.request
import urllib.error


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def env_file_path() -> Path:
    return repo_root() / ".env"


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_api_key() -> str:
    env_path = env_file_path()
    load_env_file(env_path)
    api_key = os.getenv("BAIDU_API_KEY", "").strip()
    if not api_key:
        print(f"Error: BAIDU_API_KEY is missing. Put it in {env_path}")
        sys.exit(1)
    return api_key


def baidu_search(api_key, requestBody: dict):
    url = "https://qianfan.baidubce.com/v2/ai_search/web_search"

    headers = {
        "Authorization": "Bearer %s" % api_key,
        "X-Appbuilder-From": "openclaw",
        "Content-Type": "application/json"
    }

    payload = json.dumps(requestBody).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise Exception(f"HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise Exception(f"Network error: {exc.reason}") from exc

    results = json.loads(body)
    if "code" in results:
        raise Exception(results["message"])
    datas = results["references"]
    keys_to_remove = {"snippet"}
    for item in datas:
        for key in keys_to_remove:
            if key in item:
                del item[key]
    return datas


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python baidu_search.py <Json>")
        sys.exit(1)

    query = sys.argv[1]
    parse_data = {}
    try:
        parse_data = json.loads(query)
        print(f"success parse request body: {parse_data}")
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")

    if "query" not in parse_data:
        print("Error: query must be present in request body.")
        sys.exit(1)
    count = 10
    search_filter = {}
    if "count" in parse_data:
        count = int(parse_data["count"])
        if count <= 0:
            count = 10
        elif count > 50:
            count = 50
    current_time = datetime.now()
    end_date = (current_time + timedelta(days=1)).strftime("%Y-%m-%d")
    pattern = r'\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2}'
    if "freshness" in parse_data:
        if parse_data["freshness"] in ["pd", "pw", "pm", "py"]:
            if parse_data["freshness"] == "pd":
                start_date = (current_time - timedelta(days=1)).strftime("%Y-%m-%d")
            if parse_data["freshness"] == "pw":
                start_date = (current_time - timedelta(days=6)).strftime("%Y-%m-%d")
            if parse_data["freshness"] == "pm":
                start_date = (current_time - timedelta(days=30)).strftime("%Y-%m-%d")
            if parse_data["freshness"] == "py":
                start_date = (current_time - timedelta(days=364)).strftime("%Y-%m-%d")
            search_filter = {"range": {"page_time": {"gte": start_date, "lt": end_date}}}
        elif re.match(pattern, parse_data["freshness"]):
            start_date = parse_data["freshness"].split("to")[0]
            end_date = parse_data["freshness"].split("to")[1]
            search_filter = {"range": {"page_time": {"gte": start_date, "lt": end_date}}}
        else:
            print(f"Error: freshness ({parse_data['freshness']}) must be pd, pw, pm, py, or match {pattern}.")
            sys.exit(1)

    api_key = resolve_api_key()

    request_body = {
        "messages": [
            {
                "content": parse_data["query"],
                "role": "user"
            }
        ],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": count}],
        "search_filter": search_filter
    }
    try:
        results = baidu_search(api_key, request_body)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
