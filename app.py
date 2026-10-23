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
MAX_CUSTOM_TOPICS = 100
MAX_QUESTION_LENGTH = 120
CUSTOM_AWARD = "みんなが選んだNo.1"

TOPICS = [
    ("宝くじで1億円当たっても、翌日ふつうに出社しそうなのは？", "労働界のラスボス"),
    ("無人島に行ったら、いちばん最初に『帰りたい』と言いそうなのは？", "無人島の即日帰宅王"),
    ("『ここだけの話』を5分後には全員に話していそうなのは？", "歩くニュース速報"),
    ("酔っ払ったら、同じ話を3回くらいしそうなのは？", "無限リピート大臣"),
    ("ゾンビ映画で、なぜか最後まで生き残りそうなのは？", "謎の生存力No.1"),
    ("突然100万円もらったら、いちばん謎の物を買いそうなのは？", "浪費のファンタジスタ"),
    ("カラオケでマイクを渡したら、別人格になりそうなのは？", "マイクの封印解除者"),
    ("宇宙人に連れ去られても、友達になって帰ってきそうなのは？", "銀河系コミュ力王"),
    ("旅行前夜に、まったく荷造りしていなさそうなのは？", "準備しない勇者"),
    ("レストランで全員の注文を一瞬で覚えそうなのは？", "注文記憶の天才"),
    ("ドラマ化されたら、絶対に主役より目立ちそうなのは？", "主役を食う名脇役"),
    ("じゃんけんで負けた後、いちばん言い訳が長そうなのは？", "負け惜しみ評論家"),
    ("『今から行く』と言いつつ、まだ家にいそうなのは？", "時空の旅人"),
    ("スーパーの試食だけで夕飯を済ませられそうなのは？", "試食のプロフェッショナル"),
    ("お店の店員さんと、気づけば親友になっていそうなのは？", "初対面フレンド職人"),
    ("朝起きたら有名人になっていても、いちばん平常運転そうなのは？", "平常心の化身"),
    ("『1曲だけ』と言いながら、カラオケで10曲歌いそうなのは？", "アンコール製造機"),
    ("世界が終わる前日にも、ポイントカードを気にしていそうなのは？", "ポイント界の守護神"),
    ("人生で一度は、謎の発明をしてニュースになりそうなのは？", "未来の珍発明家"),
    ("ホテルのビュッフェで、最強の盛り付けを完成させそうなのは？", "ビュッフェ建築家"),
    ("急に漫才コンビを組むなら、ツッコミがうまそうなのは？", "ツッコミの鬼"),
    ("初めての海外旅行でも、なぜか現地に馴染んでいそうなのは？", "世界の地元民"),
    ("コントで『実は犯人でした』が一番似合うのは？", "まさかの黒幕"),
    ("未来から来たと言われても、なぜか信じてしまいそうなのは？", "未来人の説得力"),
    ("プレゼント交換で、一番インパクトのある品を持ってきそうなのは？", "贈り物の革命児"),
    ("動物と会話できるようになったら、真っ先に相談されそうなのは？", "動物界の相談役"),
    ("1日だけ透明人間になったら、意外と何もしなさそうなのは？", "透明な聖人"),
    ("突然の大雨でも、なぜか傘を持っていそうなのは？", "天気予報いらず"),
    ("ゲームのチュートリアルだけで、もう満足していそうなのは？", "チュートリアル覇者"),
    ("街頭インタビューで、いちばん名言を残しそうなのは？", "街角の哲学者"),
]


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
        "used_topics": [], "custom_topics": [], "participants": {}, "candidate_ids": [], "voter_ids": [],
        "votes": {}, "version": 1,
    }
    ROOMS[code] = room
    return {"code": code, "hostToken": host_token}


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
    topic_count = len(TOPICS) + len(room["custom_topics"])
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
    person = room["participants"].get(token)
    topics = TOPICS + room["custom_topics"]
    topic = topics[room["topic_index"]] if room["topic_index"] is not None else None
    participants = [{"id": p["id"], "name": p["name"]} for p in room["participants"].values()]
    payload = {
        "code": room["code"], "status": room["status"], "round": room["round"],
        "version": room["version"], "isHost": is_host,
        "me": {"id": person["id"], "name": person["name"]} if person else None,
        "participants": participants,
        "candidateIds": room["candidate_ids"],
        "eligible": bool(person and person["id"] in room["voter_ids"]),
        "myVote": room["votes"].get(token) if person else None,
        "votedCount": len(room["votes"]), "voterCount": len(room["voter_ids"]),
        "topic": {"question": topic[0], "award": topic[1]} if topic else None,
    }
    if is_host:
        payload["customQuestions"] = [topic[0] for topic in room["custom_topics"]]
    if room["status"] == "revealed":
        payload["results"] = rankings(room)
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
        question = body.get("question")
        if not isinstance(question, str):
            return error("質問を入力してください。")
        question = re.sub(r"\s+", " ", question).strip()
        if not 1 <= len(question) <= MAX_QUESTION_LENGTH or any(ord(c) < 32 for c in question):
            return error(f"質問は1〜{MAX_QUESTION_LENGTH}文字で入力してください。")
        if len(room["custom_topics"]) >= MAX_CUSTOM_TOPICS:
            return error(f"追加できる質問は{MAX_CUSTOM_TOPICS}問までです。")
        if any(question == existing[0] for existing in TOPICS + room["custom_topics"]):
            return error("この質問はすでに登録されています。")
        room["custom_topics"].append((question, CUSTOM_AWARD))
        touch(room)
        return 200, {"ok": True}
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
