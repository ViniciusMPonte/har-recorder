import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mitmproxy.http import HTTPFlow, Request, Response

from har_env import HAR_OUTPUT_PATH_ENV_VAR


class HarAddon:

    def __init__(self) -> None:
        self.output_path: Path = self._resolve_output_path()
        self.entries: List[Dict[str, Any]] = []

    @staticmethod
    def _resolve_output_path() -> Path:
        raw_path: Optional[str] = os.environ.get(HAR_OUTPUT_PATH_ENV_VAR)
        if raw_path is None:
            raise RuntimeError(f"{HAR_OUTPUT_PATH_ENV_VAR} não está definida no ambiente do mitmdump.")
        return Path(raw_path)

    def response(self, flow: HTTPFlow) -> None:
        if flow.response is None:
            return
        self.entries.append(self._build_entry(flow.request, flow.response))

    def done(self) -> None:
        document: Dict[str, Any] = {
            "log": {
                "version": "1.2",
                "creator": {"name": "har-recorder", "version": "0.1.0"},
                "entries": self.entries,
            }
        }
        self.output_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def _build_entry(self, request: Request, response: Response) -> Dict[str, Any]:
        return {
            "startedDateTime": self._started_date_time(request),
            "request": self._build_request(request),
            "response": self._build_response(response),
        }

    @staticmethod
    def _started_date_time(request: Request) -> str:
        moment: datetime = datetime.fromtimestamp(request.timestamp_start, tz=timezone.utc)
        return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _build_request(self, request: Request) -> Dict[str, Any]:
        req_data: Dict[str, Any] = {
            "method": request.method,
            "url": request.url,
            "headers": self._headers_list(request.headers.items(multi=True)),
            "cookies": self._request_cookies_list(request),
        }
        post_data: Optional[Dict[str, Any]] = self._build_post_data(request)
        if post_data is not None:
            req_data["postData"] = post_data
        return req_data

    def _build_response(self, response: Response) -> Dict[str, Any]:
        res_data: Dict[str, Any] = {
            "status": response.status_code,
            "headers": self._headers_list(response.headers.items(multi=True)),
            "cookies": self._response_cookies_list(response),
            "content": self._build_content(response),
        }
        redirect_url: Optional[str] = response.headers.get("location")
        if redirect_url is not None:
            res_data["redirectUrl"] = redirect_url
        return res_data

    @staticmethod
    def _headers_list(items: List[Tuple[str, str]]) -> List[Dict[str, str]]:
        return [{"name": name, "value": value} for name, value in items]

    @staticmethod
    def _request_cookies_list(request: Request) -> List[Dict[str, str]]:
        return [{"name": name, "value": value} for name, value in request.cookies.items(multi=True)]

    @staticmethod
    def _response_cookies_list(response: Response) -> List[Dict[str, str]]:
        cookies_list: List[Dict[str, str]] = []
        for name, (value, _attrs) in response.cookies.items(multi=True):
            cookies_list.append({"name": name, "value": value})
        return cookies_list

    @staticmethod
    def _build_post_data(request: Request) -> Optional[Dict[str, Any]]:
        if not request.raw_content:
            return None
        text: str = request.raw_content.decode("utf-8", errors="replace")
        return {"text": text}

    @staticmethod
    def _build_content(response: Response) -> Dict[str, Any]:
        mime_type: str = response.headers.get("content-type", "")
        content: Optional[bytes] = response.get_content(strict=False)

        if not content:
            return {"text": "", "mimeType": mime_type, "size": 0}

        try:
            text: str = content.decode("utf-8")
            return {"text": text, "mimeType": mime_type, "size": len(content)}
        except UnicodeDecodeError:
            encoded_text: str = base64.b64encode(content).decode("ascii")
            return {"text": encoded_text, "mimeType": mime_type, "encoding": "base64", "size": len(content)}


addons = [HarAddon()]
