"""Explicit, single-attempt booking for one private operator account. No retries."""

import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from .parser import SessionExpired, SourceError, document, parse_times
from .source import KST, ORIGIN

HISTORY_PATH = "/seminar_use_history_list.mir"
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
INFO = re.compile(r"seminar_use_info\('/seminar_use_info\.mir',\s*'DJUL',\s*'([CSZ])',\s*'(\d+)'\)")


def booking_history(html, room, day, start, end):
    soup = document(html)
    prefix = f"{room['name']} {day} {start}~{end} "
    for link in soup.select("a[onclick]"):
        match = INFO.search(link["onclick"])
        text = " ".join(link.get_text(" ", strip=True).split())
        if (
            match
            and match[1] == room["group"]
            and text.startswith(prefix)
            and text[len(prefix) :].strip() == "예약중"
        ):
            return {
                "status": "confirmed",
                "reservation_id": match[2],
                "room": room["name"],
                "date": day,
                "start": start,
                "end": end,
                "message": "공식 예약 내역에서 확인했어.",
            }
    return None


def js_date(day, value):
    stamp = datetime.fromisoformat(f"{day}T{value}:00").replace(tzinfo=KST)
    return stamp.astimezone(timezone.utc).strftime(
        "%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)"
    )


class BookingService:
    def __init__(
        self,
        client_factory,
        schedule,
        state_path,
        now=lambda: datetime.now(KST),
        pause=lambda: time.sleep(0.5),
    ):
        self.client_factory, self.schedule, self.state_path = client_factory, schedule, state_path
        self.now, self.pause = now, pause
        self.tickets, self.previews = {}, deque()
        self.confirmations = deque()

    def _validate_start(self, day, start):
        try:
            parsed = date.fromisoformat(day)
            if parsed.isoformat() != day or not TIME.fullmatch(start):
                raise ValueError
            stamp = datetime.fromisoformat(f"{day}T{start}:00").replace(tzinfo=KST)
            if not 0 <= (parsed - self.now().date()).days <= 6 or stamp <= self.now():
                raise ValueError
        except (ValueError, TypeError):
            raise SourceError(
                "오늘부터 7일 이내의 아직 지나지 않은 시작 시간을 선택해 줘."
            ) from None

    @staticmethod
    def _identity(client):
        material = sorted((c.domain, c.name, c.value) for c in client.cookies.jar)
        return hashlib.sha256(json.dumps(material).encode()).hexdigest()

    def _read(self, client, path, data=None):
        if path not in {
            "/seminar_resv.mir",
            "/seminar_end_time_list.mir",
            HISTORY_PATH,
            "/seminar_resv_check.mir",
        }:
            raise SourceError("허용되지 않은 예약 준비 경로야.")
        self.pause()
        try:
            response = client.post(ORIGIN + path, data=data or {"sloc_code": "DJUL"})
        except httpx.HTTPError as exc:
            raise SourceError("학교 연결에 실패했어. 자동 재시도하지 않아.") from exc
        if response.is_redirect or response.status_code == 401:
            raise SessionExpired("로그인이 만료됐어. 운영자의 세션 갱신이 필요해.")
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise SourceError("학교가 요청을 처리하지 못했어. 추가 요청을 중단했어.")
        document(response.text)  # Also reject a login page returned as HTTP 200.
        return response.text

    def prepare(self, day, code, start):
        self._validate_start(day, start)
        with self.schedule.lock:
            now = self.now().timestamp()
            self.tickets = {k: v for k, v in self.tickets.items() if v["expires"] > now}
            while self.previews and now - self.previews[0] >= 3600:
                self.previews.popleft()
            if len(self.previews) >= 12:
                raise SourceError("예약 준비 조회의 시간당 한도에 도달했어. 잠시 후 시도해 줘.")
            cached = self.schedule.cache.get(day)
            room = (
                next((r for r in cached[1]["rooms"] if r["code"] == code), None) if cached else None
            )
            if not room:
                raise SourceError("시간표를 먼저 조회하고 표시된 호실을 선택해 줘.")
            self.previews.append(now)
            with self.client_factory() as client:
                identity = self._identity(client)
                parsed = date.fromisoformat(day)
                html = self._read(
                    client,
                    "/seminar_resv.mir",
                    {
                        "sloc_code": "DJUL",
                        "group_code": room["group"],
                        "seminar_code": code,
                        "seminar_name": room["name"],
                        "resv_datev": day,
                        "year": str(parsed.year),
                        "month": f"{parsed.month:02d}",
                        "day": f"{parsed.day:02d}",
                        "min_personnel": str(room["minimum"]),
                        "max_personnel": str(room["capacity"]),
                    },
                )
                times = parse_times(html, expected_day=parsed)
                soup = document(html)
                count = re.search(r"initPersonNumber\s*=\s*(\d+)\s*;", html)
                name = soup.select_one("[name=seminar_name]")
                limit = soup.select_one("#resv_able_end_time")
                if (
                    not count
                    or count[1] != "0"
                    or not name
                    or name.get("value", "").split("→")[-1].strip() != room["name"]
                    or not limit
                    or not soup.select_one("#use_purpose")
                ):
                    raise SourceError(
                        "추가 참여자 등 별도 입력이 필요한 양식이야. 공식 화면에서 예약해 줘."
                    )
                if start not in times["starts"]:
                    raise SourceError("선택한 시작 시간이 더 이상 가능하지 않아.")
                html = self._read(
                    client,
                    "/seminar_end_time_list.mir",
                    {
                        "sloc_code": "DJUL",
                        "group_code": room["group"],
                        "seminar_code": code,
                        "resv_start_timev": start,
                        "resv_datev": day,
                        "service_term": str(times["step_minutes"]),
                        "resv_able_end_time": limit["value"],
                    },
                )
                select = document(html).select_one("#end_time")
                ends = (
                    sorted(
                        {
                            o.get("value", o.get_text()).strip()
                            for o in select.select("option")
                            if not o.has_attr("disabled")
                            and not o.find_parent("optgroup", disabled=True)
                            and TIME.fullmatch(o.get("value", o.get_text()).strip())
                        }
                    )
                    if select and not select.has_attr("disabled")
                    else []
                )
                start_dt = datetime.fromisoformat(f"{day}T{start}")
                ends = [
                    e
                    for e in ends
                    if 0
                    < (datetime.fromisoformat(f"{day}T{e}") - start_dt).total_seconds()
                    <= 10800
                ]
                if not ends:
                    raise SourceError("선택 가능한 종료 시간이 없어. 다른 시작 시간을 골라 줘.")
                rental = "".join(
                    f"{e.get('value', '')}^N▒"
                    for e in soup.select("input[type=checkbox][id^=rental_item]")
                )
                ticket = secrets.token_urlsafe(24)
                self.tickets[ticket] = dict(
                    room=dict(room),
                    day=day,
                    start=start,
                    ends=ends,
                    rental=rental,
                    identity=identity,
                    expires=now + 120,
                )
                return {
                    "ticket": ticket,
                    "room": room["name"],
                    "date": day,
                    "start": start,
                    "ends": ends,
                    "expires_in_seconds": 120,
                    "account_notice": "연결된 운영자 본인 계정으로 예약돼. 인원 필터는 수용 인원 검색용이야.",
                }

    def _journal(self):
        path = Path(self.state_path())
        try:
            if not path.exists():
                return {}
            if os.name == "posix" and path.stat().st_mode & 0o077:
                raise ValueError("permissions")
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or len(value) > 1024:
                raise ValueError("shape")
            if any(
                not isinstance(k, str)
                or not isinstance(v, dict)
                or v.get("status") not in {"pending", "unknown", "confirmed"}
                for k, v in value.items()
            ):
                raise ValueError("record shape")
            return value
        except (OSError, ValueError) as exc:
            raise SourceError(
                "중복 예약 방지 기록을 읽을 수 없어. 예약 전 운영자 확인이 필요해."
            ) from exc

    def _save(self, value):
        path = Path(self.state_path())
        tmp = None
        try:
            if len(value) > 1024:
                raise OSError("journal full")
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as f:
                tmp = Path(f.name)
                json.dump(value, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            raise SourceError(
                "중복 예약 방지 기록을 저장하지 못했어. 내역 확인 전 다시 예약하지 마."
            ) from exc
        finally:
            if tmp and tmp.exists():
                tmp.unlink()

    def confirm(self, ticket, end, purpose, confirmed):
        if confirmed is not True:
            raise SourceError("최종 예약 확인이 필요해.")
        if not isinstance(purpose, str) or not 1 <= len(purpose.strip()) <= 300:
            raise SourceError("사용 목적을 1~300자로 입력해 줘.")
        with self.schedule.lock:
            q = self.tickets.get(ticket)
            if not q or q["expires"] <= self.now().timestamp():
                raise SourceError("예약 준비가 만료됐어. 시간 칸을 다시 선택해 줘.")
            if end not in q["ends"]:
                raise SourceError("공식 목록에 있는 종료 시간만 선택할 수 있어.")
            self._validate_start(q["day"], q["start"])
            now = self.now().timestamp()
            while self.confirmations and now - self.confirmations[0] >= 3600:
                self.confirmations.popleft()
            if len(self.confirmations) >= 12:
                raise SourceError("예약 확인 요청의 시간당 한도에 도달했어. 자동 재시도하지 않아.")
            self.confirmations.append(now)
            key = "|".join((q["day"], q["room"]["code"], q["start"], end))
            with self.client_factory() as client:
                if self._identity(client) != q["identity"]:
                    raise SessionExpired("로그인 세션이 바뀌었어. 시간 칸부터 다시 선택해 줘.")
                journal = self._journal()
                prior = journal.get(key)
                before = booking_history(
                    self._read(client, HISTORY_PATH), q["room"], q["day"], q["start"], end
                )
                if before:
                    journal[key] = before
                    self._save(journal)
                    return before
                uncertain_day = any(
                    k.startswith(q["day"] + "|") and v["status"] in {"pending", "unknown"}
                    for k, v in journal.items()
                )
                if prior or uncertain_day:
                    return {
                        "status": "unknown",
                        "message": "당일 이전 제출 결과가 미확인이야. 공식 내역 확인 전 새 예약을 제출하지 않아.",
                    }
                payload = {
                    "sloc_code": "DJUL",
                    "group_code": q["room"]["group"],
                    "seminar_code": q["room"]["code"],
                    "member_user_id": "",
                    "member_user_name": "",
                    "member_count": "0",
                    "resv_use_start_date": js_date(q["day"], q["start"]),
                    "resv_use_end_date": js_date(q["day"], end),
                    "use_purpose": purpose.strip(),
                    "rental_item_list_yn": q["rental"],
                }
                message = self._read(client, "/seminar_resv_check.mir", payload).strip()
                if message:
                    return {
                        "status": "rejected",
                        "message": document(message).get_text(" ", strip=True)[:1000],
                    }
                journal[key] = {"status": "pending"}
                self._save(journal)  # Persist BEFORE the single mutation attempt.
                result = {
                    "status": "unknown",
                    "message": "제출 결과를 확정하지 못했어. 중복 제출하지 말고 공식 예약 내역을 확인해 줘.",
                }
                try:
                    self.pause()
                    response = client.post(
                        ORIGIN + "/seminar_resv_prss.mir", data=payload
                    )  # NEVER retry or follow redirects.
                    if response.status_code in {200, 302, 303}:
                        verified = booking_history(
                            self._read(client, HISTORY_PATH), q["room"], q["day"], q["start"], end
                        )
                        if verified:
                            result = verified
                except (httpx.HTTPError, SourceError):
                    pass  # A timeout may have committed; leave a durable ambiguous outcome.
                journal[key] = result
                self._save(journal)
                self.schedule.cache.pop(q["day"], None)
                return result
