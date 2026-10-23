#!/usr/bin/env python3
"""Katteni Ranking: lightweight real-time party game server (polling, no database)."""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

try:
    import qrcode
except ImportError:
    qrcode = None

BASE = Path(__file__).resolve().parent
ROOMS: dict[str, dict] = {}
LOCK = threading.RLock()
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EXPIRY_SECONDS = 8 * 60 * 60
MAX_PARTICIPANTS = 40
TOPICS = [("この中で一番面白いのは誰？？", "みんなが選んだNo.1")]


def error(message: str, status: int = 400):
    return status, {"error": message}


def now() -> float:
    return time.time()


def cleanup() -> None:
    old = [code for code, room in ROOMS.items() if now() - room["updated"] > EXPIRY_SECONDS]
    for code in old:
        ROOMS.pop(code, None)


def generate_code() -> str:
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(5))
        if code not in ROOMS:
            return code


def new_room() -> dict:
    cleanup()
    code = generate_code()
    host_token = secrets.token_urlsafe(28)
    room = {
        "code": code, "host_token": host_token, "created": now(), "updated": now(),
        "status": "lobby", "round": 0, "topic_index": None,
        "used_topics": [], "participants": {}, "candidate_ids": [], "voter_ids": [],
        "votes": {}, "version": 1,
    }
    ROOMS[code] = room
    _, joined = join_room(room, {"name": "橋野"})
    room["host_participant_token"] = joined["participantToken"]
    return {"code": code, "hostToken": host_token, **joined}


def touch(room: dict) -> None:
    room["updated"] = now()
    room["version"] += 1


def validate_name(value):
    if not isinstance(value, str):
        return None
    name = re.sub(r"\s+", " ", value).strip()
    if not 1 <= len(name) <= 14 or any(ord(c) < 32 for c in name):
        return None
    return name


def join_room(room: dict, body: dict):
    name = validate_name(body.get("name"))
    if not name:
        return error("名前は1〜14文字で入力してください。")
    token = body.get("participantToken")
    if isinstance(token, str) and token in room["participants"]:
        person = room["participants"][token]
        if any(p["name"].casefold() == name.casefold() and t != token
               for t, p in room["participants"].items()):
            return error("その名前はすでに使われています。")
        person["name"] = name
        touch(room)
        return 200, {"participantToken": token}
    if len(room["participants"]) >= MAX_PARTICIPANTS:
        return error("参加人数の上限（40人）に達しています。")
    if any(p["name"].casefold() == name.casefold() for p in room["participants"].values()):
        return error("その名前はすでに使われています。")
    token = secrets.token_urlsafe(20)
    room["participants"][token] = {"id": token, "name": name, "joined": now()}
    touch(room)
    return 200, {"participantToken": token}


def choose_topic(room: dict) -> None:
    topic_count = len(TOPICS)
    unused = [i for i in range(topic_count) if i not in room["used_topics"]]
    if not unused:
        room["used_topics"] = []
        unused = list(range(topic_count))
    index = secrets.choice(unused)
    room["used_topics"].append(index)
    room["topic_index"] = index
    room["round"] += 1
    room["candidate_ids"] = list(room["participants"])
    room["voter_ids"] = list(room["participants"])
    room["votes"] = {}
    room["status"] = "voting"
    touch(room)


def rankings(room: dict) -> list:
    counts = Counter(room["votes"].values())
    ranked = [{"id": tid, "name": room["participants"][tid]["name"], "votes": counts[tid]}
              for tid in room["candidate_ids"] if tid in room["participants"]]
    ranked.sort(key=lambda p: (-p["votes"], p["name"].casefold()))
    position = 0
    prior = None
    for i, person in enumerate(ranked):
        if person["votes"] != prior:
            position = i + 1
        person["rank"] = position
        prior = person["votes"]
    return ranked


def get_state(room: dict, token: str) -> dict:
    is_host = token == room["host_token"]
    participant_token = room["host_participant_token"] if is_host else token
    person = room["participants"].get(participant_token)
    topics = TOPICS
    topic = topics[room["topic_index"]] if room["topic_index"] is not None else None
    participants = [{"id": p["id"], "name": p["name"]} for p in room["participants"].values()]
    payload = {
        "code": room["code"], "status": room["status"], "round": room["round"],
        "version": room["version"], "isHost": is_host,
        "me": {"id": person["id"], "name": person["name"]} if person else None,
        "participants": participants,
        "candidateIds": room["candidate_ids"],
        "eligible": bool(person and person["id"] in room["voter_ids"]),
        "myVote": room["votes"].get(participant_token) if person else None,
        "votedCount": len(room["votes"]), "voterCount": len(room["voter_ids"]),
        "topic": {"question": topic[0], "award": topic[1]} if topic else None,
    }
    if room["status"] == "revealed":
        payload["results"] = rankings(room)
        payload["hostWinner"] = any(
            p["id"] == room["host_participant_token"] and p["rank"] == 1 and p["votes"] > 0
            for p in payload["results"]
        )
    return payload


def update_room(room: dict, action: str, body: dict):
    if action == "join":
        return join_room(room, body)
    if action == "vote":
        token = body.get("participantToken")
        candidate = body.get("candidateId")
        if room["status"] != "voting":
            return error("現在は投票を受け付けていません。")
        if token not in room["voter_ids"]:
            return error("次のお題から投票できます。")
        if candidate not in room["candidate_ids"]:
            return error("投票先を選び直してください。")
        if token == candidate:
            return error("自分以外の人に投票してください。")
        room["votes"][token] = candidate
        touch(room)
        return 200, {"ok": True}
    if body.get("hostToken") != room["host_token"]:
        return error("幹事の操作権限がありません。", 403)
    if action == "add-topic":
        return error("今回は固定の1問だけで遊びます。")
    if action == "start":
        if room["status"] != "lobby":
            return error("この操作は現在できません。")
        if len(room["participants"]) < 2:
            return error("参加者が2人以上必要です。")
        choose_topic(room)
        return 200, {"ok": True}
    if action == "reveal":
        if room["status"] != "voting":
            return error("投票中ではありません。")
        if not room["votes"]:
            return error("少なくとも1票が必要です。")
        room["status"] = "revealed"
        touch(room)
        return 200, {"ok": True}
    if action == "next":
        if room["status"] != "revealed":
            return error("結果発表後に次へ進めます。")
        if len(room["participants"]) < 2:
            return error("参加者が2人以上必要です。")
        choose_topic(room)
        return 200, {"ok": True}
    return error("不明な操作です。", 404)


class Handler(BaseHTTPRequestHandler):
    server_version = "KatteniRanking/1.0"

    def send_bytes(self, code: int, data: bytes, content_type: str, cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, payload):
        self.send_bytes(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in ("/", "/index.html", "/styles.css", "/app.js"):
            name = {"/": "index.html", "/index.html": "index.html", "/styles.css": "styles.css", "/app.js": "app.js"}[path]
            kind = ".html" if name.endswith(".html") else ".css" if name.endswith(".css") else ".js"
            types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}
            self.send_bytes(200, (BASE / "static" / name).read_bytes(), types[kind], cache=kind != ".html")
            return
        if path in ("/hashino.jpg", "/hashino.mp3"):
            kind = "image/jpeg" if path.endswith(".jpg") else "audio/mpeg"
            self.send_bytes(200, (BASE / "static" / path[1:]).read_bytes(), kind, cache=True)
            return
        if path == "/health":
            self.send_json(200, {"ok": True})
            return
        if path == "/api/qr":
            if qrcode is None:
                self.send_json(503, {"error": "QRコード生成には qrcode パッケージが必要です。"})
                return
            target = parse_qs(parsed.query).get("url", [""])[0]
            if not 1 <= len(target) <= 500 or not re.match(r"^https?://", target):
                self.send_json(400, {"error": "URLが無効です。"})
                return
            code = qrcode.QRCode(box_size=9, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
            code.add_data(target)
            code.make(fit=True)
            image = code.make_image(fill_color="#17152b", back_color="#ffffff")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            self.send_bytes(200, buffer.getvalue(), "image/png")
            return
        m = re.fullmatch(r"/api/rooms/([A-Z2-9]{5})/state", path)
        if m:
            with LOCK:
                cleanup()
                room = ROOMS.get(m[1])
                if not room:
                    self.send_json(404, {"error": "部屋が見つかりません。コードを確認してください。"})
                    return
                token = parse_qs(parsed.query).get("token", [""])[0]
                self.send_json(200, get_state(room, token))
            return
        self.send_json(404, {"error": "ページが見つかりません。"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 4096:
            self.send_json(413, {"error": "データが大きすぎます。"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"error": "送信内容が不正です。"})
            return
        path = urlsplit(self.path).path
        with LOCK:
            cleanup()
            if path == "/api/rooms":
                self.send_json(201, new_room())
                return
            m = re.fullmatch(r"/api/rooms/([A-Z2-9]{5})/(join|vote|start|reveal|next|add-topic)", path)
            if m:
                room = ROOMS.get(m[1])
                if not room:
                    self.send_json(404, {"error": "部屋が見つかりません。"})
                    return
                status, result = update_room(room, m[2], body)
                self.send_json(status, result)
                return
        self.send_json(404, {"error": "操作が見つかりません。"})

    def log_message(self, fmt, *args):
        if os.environ.get("VERBOSE") == "1":
            super().log_message(fmt, *args)


def serve():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"勝手にランキング選手権: http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
