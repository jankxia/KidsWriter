# -*- coding: utf-8 -*-
"""阅答题（原童阅写稿器）：文章生成（文字 + 封面 + 逐句音频）、题库出题/校验/上传、在线答题与阅读，确认后再传夸克盘。

用法：
    双击 启动.bat                      打开界面（本地 http://127.0.0.1:8122）
    python 童阅写稿器.py --serve       只起服务
    python 童阅写稿器.py --cli ...     命令行生成（可加 --upload 直接传）
Docker：
    docker run -d --name kidswriter -p 8122:8122 -v /vol1/1000/kidswriter:/app/data kidswriter:1.0
"""

import argparse
import asyncio
import hashlib
import json
import os
import pathlib
import random
import re
import secrets
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = pathlib.Path(os.environ.get("KIDSWRITER_DATA") or APP_DIR)
CONFIG_PATH = DATA_DIR / "config.json"
COVERS = pathlib.Path(os.environ.get("KIDSWRITER_COVERS") or (APP_DIR / "covers"))
OUTPUT = DATA_DIR / "输出"
UI_HTML = pathlib.Path(os.environ.get("KIDSWRITER_UI") or (APP_DIR / "界面.html"))
ACCOUNTS_PATH = DATA_DIR / "accounts.json"
PORT = int(os.environ.get("KIDSWRITER_PORT") or 8122)

# 会话表：token -> {"username":..., "role":"admin|user"}
_SESSIONS = {}
_ACCOUNT_LOCK = threading.Lock()

# 角色可见页面：管理员全部；一般账户只做阅读和答题
ROLE_PAGES = {
    "admin": ["writer", "quiz", "author", "reader"],
    "user": ["quiz", "reader"],
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KidsReaderWriter/1.0"

GRADES = [
    "小学一年级", "小学二年级", "小学三年级", "小学四年级", "小学五年级", "小学六年级",
    "初中一年级", "初中二年级", "初中三年级",
    "高中一年级", "高中二年级", "高中三年级",
    "世界名著",
]

DEFAULT_CHARS = {"小学": 400, "初中": 600, "高中": 800, "世界": 800}

# 界面里「换一个」随机取的不是关键词，而是一段具体情景描述，交给 AI 当灵感
TOPIC_SAMPLES = [
    "放学路上忽然下起小雨，我把书包顶在头上往家跑，跑到楼下才发现鞋子全湿了。",
    "早上起来发现窗台上的花开了，花瓣上还挂着水珠，我蹲在那儿看了很久。",
    "课间十分钟，同桌把橡皮切成小块分给我们，谁也没舍得用。",
    "妈妈在厨房煲汤，我趴在门边闻香味，她说还要再等二十分钟。",
    "操场上刮起大风，风筝线绕在我手上，我一路小跑才把它放上去。",
    "我在院子里埋下一颗种子，每天都去看看它有没有冒头。",
    "爸爸下班回来，鞋子上沾着泥，他坐在门口慢慢把鞋擦干净。",
    "考试没考好，我不敢把卷子拿出来，晚饭时一直低着头。",
    "楼道里的灯坏了，晚上回家我要摸着墙一级一级往上走。",
    "奶奶把旧毛衣拆了重新织，说这样线才不浪费。",
    "最后一节课上到一半停电了，教室一下安静，只有窗外的蝉在叫。",
    "我把捡到的一颗小石子放在窗台上，觉得它像一只睡着的小鸟。",
    "开学第一天换了新教室，我在门口站了一会儿才敢进去。",
    "楼下小卖部的老板娘记得我爱吃哪种橘子，每次都会多给我一个。",
    "我学着煮了一锅面，汤有点咸，爸妈还是全部吃完了。",
    "风把我的作业本吹到地上，我追着它跑了大半个教室。",
    "夏天的蝉在树上叫得很响，我仰着头找了半天也没找到它。",
    "爷爷的老藤椅在阳台上摇了很多年，坐上去就一直响。",
    "我养的那只猫总在半夜跳上窗台，把花瓶碰得直响。",
    "第一次一个人坐公交车去外婆家，一路上盯着站牌不敢眨眼。",
    "下过雨的水洼里有一片天，我踩过去，它就碎成了好几块。",
    "教室里的绿萝长了很长，老师让我们轮流给它浇水。",
    "我把秘密写在一张纸上，折成小方块塞进抽屉最里面。",
    "周末大扫除，我负责擦窗户，擦完才发现外面比里面还干净。",
    "雪落在院子里的石桌上，薄薄一层，我用手按了一个印子。",
    "我在阳台上放了一小碟水，等鸟来喝，等了一整个下午。",
    "爸妈吵架那天，我一个人坐在楼梯上数台阶。",
    "我把旧书整理成一摞，发现里面夹着一张一年级时的画。",
    "同桌转学走了，她留下的半块橡皮我一直放在铅笔盒里。",
    "夜里听见楼下有人弹琴，我趴在窗边听，直到琴声停下来。",
]

COVER_RULES = [
    ("窗台", "g4s6.jpg"), ("绿萝", "g4s6.jpg"), ("豆苗", "g4s6.jpg"), ("盆栽", "g4s6.jpg"),
    ("种子", "g4s6.jpg"), ("水壶", "g4s6.jpg"), ("浇水", "g4s6.jpg"), ("花", "g4s6.jpg"),
    ("大扫除", "g3s4.jpg"), ("教室", "g3s4.jpg"), ("课间", "g3s4.jpg"),
    ("同桌", "g3s4.jpg"), ("同学", "g3s4.jpg"), ("班级", "g3s4.jpg"),
    ("写字", "g6s3.jpg"), ("作业", "g6s3.jpg"), ("老师", "g6s3.jpg"), ("上课", "g6s3.jpg"),
    ("读书", "g5s5.jpg"), ("绘本", "g5s5.jpg"), ("台灯", "g5s5.jpg"), ("看书", "g5s5.jpg"),
    ("做饭", "g6p1.jpg"), ("厨房", "g6p1.jpg"), ("针线", "g6p1.jpg"), ("锅", "g6p1.jpg"),
    ("奶奶", "g5s1.jpg"), ("爷爷", "g5s1.jpg"), ("藤椅", "g5s1.jpg"),
    ("星星", "g5s1.jpg"), ("乘凉", "g5s1.jpg"), ("温暖", "g5s1.jpg"),
    ("停电", "g2p5.jpg"), ("月亮", "g2p5.jpg"),
    ("小雨", "g1s3.jpg"), ("下雨", "g1s3.jpg"), ("水洼", "g1s3.jpg"), ("伞", "g1s3.jpg"),
    ("小猫", "g5p3.jpg"), ("院子", "g5p3.jpg"), ("农家", "g5p3.jpg"), ("村庄", "g5p3.jpg"),
    ("落叶", "g3p3.jpg"), ("秋天", "g3p3.jpg"), ("池塘", "g3p3.jpg"), ("菊花", "g3p3.jpg"),
    ("爸爸", "g2s1.jpg"), ("散步", "g2s1.jpg"), ("风筝", "g2s1.jpg"),
    ("妈妈", "g2s5.jpg"), ("汤", "g2s5.jpg"), ("早饭", "g2s5.jpg"),
    ("帮手", "g2p5.jpg"), ("帮忙", "g2p5.jpg"),
    ("书包", "g4s2.jpg"), ("校园", "g4s2.jpg"), ("学校", "g4s2.jpg"),
    ("秘密", "g4p1.jpg"), ("山里", "g4p1.jpg"),
    ("失败", "g6p5.jpg"), ("出发", "g6p5.jpg"), ("石子", "g6p5.jpg"), ("石头", "g6p5.jpg"),
    ("知了", "bee.jpg"), ("蝉", "bee.jpg"), ("蜜蜂", "bee.jpg"),
    ("操场", "spring.jpg"), ("春天", "spring.jpg"), ("草地", "spring.jpg"),
    ("小卖部", "g4p5.jpg"), ("水乡", "g4p5.jpg"), ("小船", "g4p5.jpg"),
    ("老街", "g4p5.jpg"), ("公交", "g4p5.jpg"),
    ("雪", "g3p7.jpg"), ("冬天", "g3p7.jpg"), ("湖", "g3p7.jpg"),
    ("风", "spring.jpg"), ("夜", "g2p5.jpg"), ("猫", "g5p3.jpg"),
    ("山", "g4p1.jpg"), ("秋", "g3p3.jpg"), ("雨", "g1s3.jpg"),
]

DEFAULT_CONFIG = {
    "server": "https://list.717611.xyz",
    "user": "admin",
    "password": "jankxia",
    "root": "夸克/KidsReader",
    "ai_base": "https://open.bigmodel.cn/api/paas/v4",
    "ai_model": "glm-4-flash",
    "api_key": "860ca4b1b0654eee9941a269d1725f24.oGkFCmF9DQyREQvd",
    "voice": "zh-CN-XiaoyiNeural",
    "rate": "-10%",
    "conc": 4,
    "grade": "小学二年级",
    "chars": 400,
    "count": 2,
    "skip_dup": True,
    # 题库包清单地址留空走默认（内网 OpenList → 外网反代 → GitHub 镜像），填了优先用这个
    "quiz_url": "",
    # 题库在 OpenList 上的目录，电视端 CleanMiTV 与本工具共用这一套
    "quiz_root": "夸克/CleanMiTV/quiz",
}


# ---------------------------------------------------------------- 配置
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))
        except Exception:
            pass
    else:
        try:
            CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return cfg


def save_config(cfg):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- 账户
def accounts_default():
    return {"users": [{"username": "admin", "password": "jankxia", "role": "admin"}]}


def accounts_load():
    if not ACCOUNTS_PATH.exists():
        d = accounts_default()
        accounts_save(d)
        return d
    try:
        d = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(d, dict) and isinstance(d.get("users"), list):
            return d
    except Exception:
        pass
    return accounts_default()


def accounts_save(d):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def auth_check(username, password):
    """校验账号密码，返回 {username, role} 或 None。"""
    username = (username or "").strip()
    for u in accounts_load()["users"]:
        if u.get("username") == username and u.get("password") == password:
            return {"username": u["username"], "role": u.get("role", "user")}
    return None


def auth_issue(user):
    token = secrets.token_hex(16)
    _SESSIONS[token] = {"username": user["username"], "role": user["role"]}
    return token


def auth_by_token(token):
    if not token:
        return None
    return _SESSIONS.get(token)


def auth_list_users():
    """账户列表（不回传密码）。"""
    return [{"username": u["username"], "role": u.get("role", "user")}
            for u in accounts_load()["users"]]


def auth_upsert_user(username, password, role):
    """新增或改密；role 仅 admin/user。返回 ok/msg。"""
    username = (username or "").strip()
    if not username or not password:
        return False, "账户名和密码不能为空"
    if role not in ("admin", "user"):
        role = "user"
    d = accounts_load()
    for u in d["users"]:
        if u["username"] == username:
            u["password"] = password
            u["role"] = role
            accounts_save(d)
            return True, "已更新账户 %s" % username
    d["users"].append({"username": username, "password": password, "role": role})
    accounts_save(d)
    return True, "已新增账户 %s" % username


def auth_delete_user(username):
    d = accounts_load()
    admins = [u for u in d["users"] if u.get("role") == "admin"]
    target = next((u for u in d["users"] if u["username"] == username), None)
    if not target:
        return False, "账户不存在"
    if target.get("role") == "admin" and len(admins) <= 1:
        return False, "至少保留一个管理员"
    d["users"] = [u for u in d["users"] if u["username"] != username]
    accounts_save(d)
    for tok, sess in list(_SESSIONS.items()):
        if sess["username"] == username:
            _SESSIONS.pop(tok, None)
    return True, "已删除账户 %s" % username


# ---------------------------------------------------------------- 网盘
class OL:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.token = ""

    def _req(self, path, data=None, method="POST", headers=None):
        body = None if data is None else (
            data if isinstance(data, bytes) else json.dumps(data).encode()
        )
        req = urllib.request.Request(self.base + path, data=body, method=method)
        req.add_header("User-Agent", UA)
        if isinstance(data, (dict, list)) or data is None:
            req.add_header("Content-Type", "application/json")
        else:
            req.add_header("Content-Type", "application/octet-stream")
        if self.token:
            req.add_header("Authorization", self.token)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
        try:
            return json.loads(raw.decode())
        except Exception:
            return {"code": 200, "raw": raw[:200].decode(errors="replace")}

    def login(self, user, password):
        r = self._req("/api/auth/login", {"username": user, "password": password})
        self.token = (r.get("data") or {}).get("token", "")
        if not self.token:
            raise RuntimeError("网盘登录失败：" + str(r)[:160])
        return True

    def list(self, path):
        r = self._req("/api/fs/list", {"path": path, "page": 1, "per_page": 500})
        return (r.get("data") or {}).get("content") or []

    def read(self, path):
        url = self.base + "/d/" + "/".join(urllib.parse.quote(s) for s in path.strip("/").split("/"))
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read()

    def put(self, path, content, retry=3):
        enc = urllib.parse.quote(path, safe="/")
        last = ""
        for i in range(retry):
            try:
                r = self._req("/api/fs/put", content, method="PUT", headers={"File-Path": enc})
                if r.get("code") == 200:
                    return True, ""
                last = r.get("message", "") or str(r)[:80]
            except Exception as exc:
                last = "%s: %s" % (type(exc).__name__, exc)
            time.sleep(1.0 + i)
        return False, last

    def mkdir(self, path):
        r = self._req("/api/fs/mkdir", {"path": path})
        return r.get("code") == 200


# ---------------------------------------------------------------- 题库包
# 题库与 CleanMiTV 电视端共用一套：清单先内网 OpenList，再外网反代，最后 GitHub 镜像。
# 大资源不打进镜像，用的时候按年级文件从网盘拉，后端代理给前端，避免浏览器跨域。
QUIZ_URLS = [
    "http://192.168.1.24:5244/p/%E5%A4%B8%E5%85%8B/CleanMiTV/quiz/index.json",
    "https://list.717611.xyz/p/%E5%A4%B8%E5%85%8B/CleanMiTV/quiz/index.json",
    "https://github.com/jankxia/cleanmitv/releases/download/quiz-pack-v4/index.json",
]

QUIZ_STAGES = {
    "primary": {"label": "小学", "grades": [1, 2, 3, 4, 5, 6],
                "subjects": ["chinese", "math", "english"]},
    "middle": {"label": "初中", "grades": [7, 8, 9],
               "subjects": ["chinese", "math", "english", "history", "physics", "chemistry"]},
    "high": {"label": "高中", "grades": [10, 11, 12],
             "subjects": ["chinese", "math", "english", "physics", "chemistry", "biology",
                          "history", "geography", "politics"]},
}

SUBJECT_LABELS = {
    "chinese": "语文", "math": "数学", "english": "英语", "history": "历史",
    "physics": "物理", "chemistry": "化学", "biology": "生物",
    "geography": "地理", "politics": "政治",
}

QUIZ_FILE_RE = re.compile(r"^(primary|middle|high)-(\d+)\.json$")
QUIZ_CACHE_GAP = 5 * 60          # 清单多久内不重新探一次，秒
QUIZ_CHUNK = 32768               # 长文件断点续读的块大小

_quiz_manifest = {"at": 0.0, "root": None, "base": ""}
_quiz_files = {}                 # 年级文件名 -> 题目列表（后端内存缓存）


def quiz_candidates(cfg):
    out = []
    saved = (cfg.get("quiz_url") or "").strip()
    if saved:
        out.append(saved)
    for u in QUIZ_URLS:
        if u not in out:
            out.append(u)
    return out


def _is_lan(url):
    return url.startswith("http://192.168.") or url.startswith("http://10.") \
        or url.startswith("http://127.0.0.1") or url.startswith("http://localhost/")


def _read_deadline(r, deadline, chunk=65536):
    """分块读取，超过 deadline 直接抛超时；urlopen 的 timeout 只管单次 socket 操作，不包总时长。"""
    out = bytearray()
    while True:
        if time.time() > deadline:
            raise TimeoutError("读取超时")
        part = r.read(chunk)
        if not part:
            break
        out.extend(part)
    return bytes(out)


import concurrent.futures
_quiz_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _quiz_fetch_once(url, eff):
    deadline = time.time() + eff
    # 内网地址直连，不经过系统代理；外网走系统代理（本机代理 127.0.0.1:2080）
    if _is_lan(url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    else:
        opener = urllib.request.build_opener()
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Connection", "close")
    req.add_header("Accept-Encoding", "identity")
    with opener.open(req, timeout=max(2, eff // 2)) as r:
        return _read_deadline(r, deadline)


def _quiz_is_local(url):
    return url.startswith("file://") or os.path.exists(url)


def _quiz_local_read(url):
    p = url[7:] if url.startswith("file://") else url
    if os.path.isdir(p):
        p = os.path.join(p, "index.json")
    with open(p, "rb") as f:
        return f.read()


def _quiz_join(base, name):
    if _quiz_is_local(base):
        b = base[7:] if base.startswith("file://") else base
        return os.path.join(b, name)
    return base[:base.rfind("/") + 1] + name


def _quiz_http_get(url, timeout):
    """读一个 URL；本地目录直读；OpenList 长连接不主动关，要求 Connection: close，短读再走 Range 续读。"""
    if _quiz_is_local(url):
        return _quiz_local_read(url)
    last = None
    eff = min(5000 if _is_lan(url) else 10000, timeout)
    try:
        fut = _quiz_pool.submit(_quiz_fetch_once, url, eff)
        body = fut.result(timeout=eff + 2)
        if body:
            return body
    except Exception as exc:
        last = exc
        # 连不上、超时、HTTP 错误（含 502）直接换下一个镜像，不做断点续读
        if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError,
                             concurrent.futures.TimeoutError)):
            raise
    # 只剩流式中断这类情况：按 32KB 块断点续读
    return _quiz_http_ranged(url, timeout, last)


def _quiz_http_ranged(url, timeout, last_err):
    out = bytearray()
    total = -1
    eff = min(5000 if _is_lan(url) else 10000, timeout)
    for attempt in range(3):
        pos = len(out)
        end = total > 0 and min(pos + QUIZ_CHUNK, total) - 1 or pos + QUIZ_CHUNK - 1
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        req.add_header("Connection", "close")
        req.add_header("Accept-Encoding", "identity")
        req.add_header("Range", "bytes=%d-%d" % (pos, end))
        try:
            with urllib.request.urlopen(req, timeout=eff) as r:
                code = getattr(r, "status", 200)
                if code == 200:
                    return r.read()
                if code != 206:
                    raise RuntimeError("HTTP %d" % code)
                cr = r.headers.get("Content-Range")
                if cr and total < 0:
                    tail = cr.rsplit("/", 1)[-1]
                    if tail.isdigit():
                        total = int(tail)
                part = r.read()
                if not part:
                    raise RuntimeError("empty range at %d" % pos)
                out.extend(part)
                attempt = 0
                if total > 0 and len(out) >= total:
                    break
                if total < 0 and len(part) < QUIZ_CHUNK:
                    break
        except Exception as exc:
            if attempt == 5:
                raise RuntimeError("续读失败：%s" % exc)
            time.sleep(0.4 * (attempt + 1))
    if total > 0 and len(out) != total:
        raise RuntimeError("短读 %d/%d" % (len(out), total))
    return bytes(out)


def quiz_manifest(cfg, force=False):
    """返回 (清单 dict, 答中的镜像 base)；五分钟内复用缓存。"""
    if not force and _quiz_manifest["root"] and \
            time.time() - _quiz_manifest["at"] < QUIZ_CACHE_GAP:
        return _quiz_manifest["root"], _quiz_manifest["base"]
    last = None
    for base in quiz_candidates(cfg):
        if not base:
            continue
        try:
            body = _quiz_http_get(base, 20000)
            root = json.loads(body.decode("utf-8"))
            files = root.get("files") or []
            if files:
                _quiz_manifest.update(at=time.time(), root=root, base=base)
                return root, base
        except Exception as exc:
            last = exc
    raise RuntimeError("题库清单拉取失败：%s" % str(last)[:120])


def _quiz_file_mirrors(base, entry, name):
    """清单里给了 url 就先用；否则按答中的镜像目录拼；再把其余候选目录都试一遍。"""
    links = []
    link = (entry or {}).get("url") or ""
    if link:
        links.append(link)
    links.append(_quiz_join(base, name))
    for other in quiz_candidates(load_config()):
        links.append(_quiz_join(other, name))
    seen, uniq = set(), []
    for u in links:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def quiz_questions(cfg, name):
    """按年级文件名取题目列表，带 sha256 校验与后端缓存。"""
    m = QUIZ_FILE_RE.match(name or "")
    if not m:
        raise RuntimeError("题库文件名不合法：%s" % name)
    if name in _quiz_files:
        return _quiz_files[name]
    root, base = quiz_manifest(cfg)
    entry = next((f for f in root.get("files", []) if f.get("name") == name), None)
    sha = (entry or {}).get("sha256", "").strip().lower()
    last = None
    for link in _quiz_file_mirrors(base, entry, name):
        try:
            body = _quiz_http_get(link, 60000)
            if sha:
                digest = hashlib.sha256(body).hexdigest()
                if not digest.startswith(sha):
                    raise RuntimeError("校验和不符：%s" % name)
            node = json.loads(body.decode("utf-8"))
            questions = node.get("questions") or []
            if not questions:
                raise RuntimeError("题库为空：%s" % name)
            _quiz_files[name] = questions
            return questions
        except Exception as exc:
            last = exc
    raise RuntimeError("题库 %s 拉取失败：%s" % (name, str(last)[:120]))


def quiz_grade_file(stage, grade):
    return "%s-%d.json" % (stage, int(grade))


# ---------------- 出题 / 校验 / 上传 ----------------
QUIZ_EDIT_DIR = DATA_DIR / "quiz-edit"

STAGE_PREFIX = {"primary": "p", "middle": "m", "high": "h"}
SUBJ_CODE = {
    "chinese": "cs", "math": "ma", "english": "en", "history": "hi",
    "physics": "ph", "chemistry": "ch", "biology": "bi",
    "geography": "ge", "politics": "po",
}


def quiz_edit_path(name):
    return QUIZ_EDIT_DIR / name


def quiz_local_questions(name):
    """本地暂存的题目；没有就返回 None。"""
    p = quiz_edit_path(name)
    if not p.exists():
        return None
    try:
        node = json.loads(p.read_text(encoding="utf-8-sig"))
        return node.get("questions") or []
    except Exception:
        return None


def quiz_next_id(questions, stage, grade, subject):
    pre = STAGE_PREFIX[stage] + str(grade) + SUBJ_CODE.get(subject, "qt")
    seq = 1
    for q in questions:
        qid = str(q.get("id") or "")
        if qid.startswith(pre):
            tail = qid[len(pre):]
            if tail.isdigit():
                seq = max(seq, int(tail) + 1)
    return "%s%04d" % (pre, seq)


def quiz_normalize(q, stage, grade, subject, idx):
    """补齐字段、去空白；返回规范后的题目 dict。"""
    opts = [str(x).strip() for x in (q.get("o") or []) if str(x).strip()]
    a = q.get("a")
    if not isinstance(a, int):
        try:
            a = int(a)
        except Exception:
            a = 0
    level = q.get("l")
    if not isinstance(level, int) or level < 1 or level > 5:
        level = 1
    qid = str(q.get("id") or "").strip() or quiz_next_id([], stage, grade, subject)
    return {
        "id": qid, "st": stage, "g": int(grade), "s": subject,
        "q": str(q.get("q") or "").strip(), "o": opts, "a": a, "l": level,
    }


def quiz_validate(questions, stage, grade, subject):
    """返回错误列表；空列表即通过。"""
    errors, seen = [], set()
    for i, q in enumerate(questions):
        qid = q.get("id") or "#%d" % (i + 1)
        if not q.get("q"):
            errors.append("%s：题干为空" % qid)
        if len(q.get("o") or []) < 2:
            errors.append("%s：选项少于 2 个" % qid)
        a = q.get("a")
        if not isinstance(a, int) or a < 0 or a >= len(q.get("o") or []):
            errors.append("%s：答案序号不合法" % qid)
        if qid in seen:
            errors.append("%s：编号重复" % qid)
        seen.add(qid)
    return errors


def quiz_load_edit(cfg, name):
    """编辑用题目：本地暂存优先，其次网盘基线；都没有返回空列表。"""
    m = QUIZ_FILE_RE.match(name or "")
    if not m:
        raise RuntimeError("题库文件名不合法：%s" % name)
    local = quiz_local_questions(name)
    if local is not None:
        return local, "local"
    try:
        return quiz_questions(cfg, name), "netdisk"
    except Exception:
        return [], "empty"


def quiz_save_local(name, questions):
    """校验通过后写入本地暂存目录，等「上传题库」一起回传网盘。"""
    m = QUIZ_FILE_RE.match(name or "")
    if not m:
        raise RuntimeError("题库文件名不合法：%s" % name)
    stage, grade = m.group(1), int(m.group(2))
    cleaned, errors = [], []
    for i, q in enumerate(questions):
        nq = quiz_normalize(q, stage, grade, q.get("s") or "common", i)
        cleaned.append(nq)
    errors = quiz_validate(cleaned, stage, grade, "")
    if errors:
        raise RuntimeError("校验未通过：" + "；".join(errors[:5]))
    QUIZ_EDIT_DIR.mkdir(parents=True, exist_ok=True)
    node = {"version": 1, "stage": stage, "grade": grade, "questions": cleaned}
    quiz_edit_path(name).write_text(
        json.dumps(node, ensure_ascii=False, indent=2), encoding="utf-8")
    _quiz_files[name] = cleaned
    return len(cleaned)


def _loads_quiz_array(raw):
    """宽松解析 AI 返回的题目 JSON 数组：剥离 markdown 围栏、清理裸换行与尾逗号。"""
    raw = re.sub(r"```(?:json|JSON)?", "", raw or "").strip()
    m = re.search(r"\[[\s\S]*\]", raw)
    if not m:
        raise RuntimeError("AI 没有返回题目数组")
    text = m.group(0)
    try:
        return json.loads(text)
    except Exception:
        pass
    # 去掉对象/数组末尾多余逗号，字符串内裸换行替换为空格
    fixed = re.sub(r",(\s*[\]}])", r"\1", text)
    fixed = fixed.replace("\r", " ").replace("\n", " ")
    try:
        return json.loads(fixed)
    except Exception as exc:
        raise RuntimeError("AI 题目 JSON 解析失败：%s" % exc)


def _quiz_prompt(stage_label, grade, subj, n, hint):
    return (
        "给%s%s的%s出 %d 道单项选择题，%s。\n"
        "只输出 JSON 数组，每题格式："
        "{\"q\":\"题干\",\"o\":[\"选项一\",\"选项二\",\"选项三\",\"选项四\"],\"a\":0,\"l\":1}\n"
        "其中 a 是正确选项序号（0-3），l 是难度 1-5；四个选项都要简短通顺，干扰项要合理。\n"
        "题干和选项里如需引用，请用中文引号「」，不要使用英文双引号；不要换行。\n"
        "不要输出解释、不要 markdown、不要代码块。"
        % (stage_label, grade, subj, n, hint)
    )


def quiz_ai_generate(cfg, stage, grade, subject, count, topic):
    """分批调 AI 出题并规范成题目列表；每批少量、失败重试，降低长输出破损概率。"""
    count = max(1, min(20, int(count or 5)))
    subj = SUBJECT_LABELS.get(subject, subject)
    stage_label = QUIZ_STAGES[stage]["label"]
    hint = "围绕%s" % topic if topic.strip() else "适合该年级水平的常见知识点"
    system = "你是中小学命题老师，只输出符合格式的 JSON 数组。"
    out, remaining, batch = [], count, 20
    while remaining > 0:
        n = min(batch, remaining)
        prompt = _quiz_prompt(stage_label, grade, subj, n, hint)
        arr, last_exc = None, None
        for attempt in range(2):
            raw = ask_ai(cfg, prompt, max_tokens=max(600, n * 300), system=system)
            try:
                arr = _loads_quiz_array(raw)
                break
            except Exception as exc:
                last_exc = exc
                time.sleep(1.0)
        if arr is None:
            raise RuntimeError("AI 题目生成失败：%s" % last_exc)
        for q in arr[:n]:
            nq = quiz_normalize(q, stage, grade, subject, len(out))
            nq["id"] = quiz_next_id(out, stage, grade, subject)
            out.append(nq)
        remaining -= n
    errors = quiz_validate(out, stage, grade, subject)
    if errors:
        raise RuntimeError("AI 题目校验未通过：" + "；".join(errors[:5]))
    return out


def quiz_pack_payload(name, questions):
    """打包成网盘文件内容（与电视端解析格式一致）。"""
    m = QUIZ_FILE_RE.match(name)
    stage, grade = m.group(1), int(m.group(2))
    return {"version": 1, "stage": stage, "grade": grade, "questions": questions}


def quiz_upload_pack(cfg, log):
    """把本地暂存合并进网盘基线，回传有改动的年级文件，重建并上传 index.json 清单。"""
    root = "/" + cfg.get("quiz_root", "夸克/CleanMiTV/quiz").strip("/")
    ol = OL(cfg["server"])
    ol.login(cfg["user"], cfg["password"])
    ol.mkdir(root)

    # 12 个年级文件：本地暂存覆盖网盘基线
    merged, changed = {}, []
    for stage, grades in (("primary", range(1, 7)), ("middle", range(7, 10)),
                          ("high", range(10, 13))):
        for g in grades:
            name = quiz_grade_file(stage, g)
            local = quiz_local_questions(name)
            if local is not None:
                questions = local
                changed.append(name)
            else:
                try:
                    questions = quiz_questions(cfg, name)
                except Exception:
                    questions = []
            merged[name] = questions

    # 回传有改动的年级文件
    for name in changed:
        body = json.dumps(quiz_pack_payload(name, merged[name]),
                           ensure_ascii=False, indent=2).encode("utf-8")
        ok, msg = ol.put("%s/%s" % (root, name), body)
        if not ok:
            raise RuntimeError("上传 %s 失败：%s" % (name, msg))
        log("已上传 %s（%d 题）" % (name, len(merged[name])))

    # 重建清单：版本号取时间戳，带题量、学科、大小、sha256
    files, total = [], 0
    for name, questions in merged.items():
        body = json.dumps(quiz_pack_payload(name, questions),
                          ensure_ascii=False, indent=2).encode("utf-8")
        subjects = sorted({q.get("s", "common") for q in questions})
        files.append({
            "name": name, "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "count": len(questions), "subjects": subjects,
        })
        total += len(questions)
    stamp = time.strftime("%Y-%m-%d-%H%M")
    manifest = {
        "version": stamp, "count": total, "generated": time.strftime("%Y-%m-%d"),
        "files": files,
    }
    mbody = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    ok, msg = ol.put("%s/index.json" % root, mbody)
    if not ok:
        raise RuntimeError("上传清单失败：%s" % msg)
    # 清单更新后清掉内存缓存，下次练习拉到新版本
    _quiz_manifest.update(at=0, root=None, base="")
    _quiz_files.clear()
    return {"changed": changed, "total": total, "version": stamp}


def _quiz_dedup_merge(base, additions):
    """按题干去重合并：保留基线，追加题干不重复的新题。"""
    seen = {str(q.get("q", "")).strip() for q in base}
    merged, added = list(base), 0
    for q in additions:
        key = str(q.get("q", "")).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(q)
        added += 1
    return merged, added


def quiz_ai_commit(cfg, stage, grade, subject, new_questions, log):
    """AI 出题后自动合并基线、落盘暂存并回传网盘，无需手动保存/上传。"""
    name = quiz_grade_file(stage, grade)
    base = quiz_local_questions(name)
    if base is None:
        try:
            base = quiz_questions(cfg, name)
        except Exception:
            base = []
    merged, added = _quiz_dedup_merge(base, new_questions)
    for q in merged[len(base):]:
        q["id"] = quiz_next_id(merged, stage, grade, subject)
    quiz_save_local(name, merged)
    result = quiz_upload_pack(cfg, log)
    return {"name": name, "added": added, "total": len(merged),
            "changed": result["changed"], "version": result["version"]}


# ---------------------------------------------------------------- 阅读（网盘文章）
def _ol_article_dir(cfg):
    return "/" + cfg["root"].strip("/") + "/content/ai"


def _ol_abs_url(cfg, path):
    if not path:
        return ""
    return cfg["server"].rstrip("/") + "/d/" + "/".join(
        urllib.parse.quote(s) for s in path.strip("/").split("/"))


def reader_list_articles(cfg, category=""):
    ol = OL(cfg["server"])
    ol.login(cfg["user"], cfg["password"])
    names = [e["name"] for e in ol.list(_ol_article_dir(cfg)) if e["name"].endswith(".json")]

    def fetch(name):
        try:
            node = json.loads(ol.read(_ol_article_dir(cfg) + "/" + name).decode("utf-8"))
            sents = node.get("sentences") or []
            chars = sum(len(s.get("text", "")) for s in sents)
            return {"id": node.get("id") or name[:-5], "title": node.get("title", ""),
                    "category": node.get("category", ""), "chars": chars,
                    "sents": len(sents), "cover": node.get("cover", "")}
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        items = [x for x in ex.map(fetch, names) if x]
    if category:
        items = [x for x in items if x["category"] == category]
    items.sort(key=lambda x: x["id"])
    return items


def reader_get_article(cfg, aid):
    if not aid or "/" in aid or "\\" in aid:
        raise RuntimeError("文章 id 不合法")
    ol = OL(cfg["server"])
    ol.login(cfg["user"], cfg["password"])
    node = json.loads(ol.read(_ol_article_dir(cfg) + "/" + aid + ".json").decode("utf-8"))
    sents = []
    for s in node.get("sentences") or []:
        sents.append({
            "text": s.get("text", ""),
            "tokens": s.get("tokens") or [],
            "audio": s.get("audio") or "",
            "image": s.get("image") or "",
        })
    chars = sum(len(s.get("text", "")) for s in sents)
    cover = ""
    try:
        entries = ol.list("/" + cfg["root"].strip("/") + "/" + aid)
        if any(e["name"].lower() == "cover.jpg" for e in entries):
            cover = "/api/reader/cover?id=" + aid
    except Exception:
        pass
    return {"id": node.get("id", aid), "title": node.get("title", ""),
            "category": node.get("category", ""), "body": node.get("body", ""),
            "chars": chars, "cover": cover, "sentences": sents}


def reader_audio_bytes(cfg, aid, idx):
    """后端在内网代取某篇文章某句的配音 mp3 字节，供前端同源代理播放，
    避免浏览器直连 OpenList 局域网地址在跨网段/隧道下不可达。"""
    if not aid or "/" in aid or "\\" in aid:
        raise RuntimeError("文章 id 不合法")
    ol = OL(cfg["server"])
    ol.login(cfg["user"], cfg["password"])
    node = json.loads(ol.read(_ol_article_dir(cfg) + "/" + aid + ".json").decode("utf-8"))
    sents = node.get("sentences") or []
    if idx < 0 or idx >= len(sents):
        raise RuntimeError("句子序号不合法")
    rel = sents[idx].get("audio") or ""
    if not rel:
        raise RuntimeError("该句无配音")
    return ol.read(rel)


def reader_cover_bytes(cfg, aid):
    """后端在内网代取文章封面 cover.jpg，供前端同源代理显示。"""
    if not aid or "/" in aid or "\\" in aid:
        raise RuntimeError("文章 id 不合法")
    ol = OL(cfg["server"])
    ol.login(cfg["user"], cfg["password"])
    rel = "/" + cfg["root"].strip("/") + "/" + aid + "/cover.jpg"
    return ol.read(rel)


# ---------------------------------------------------------------- 文本
def split_sentences(text):
    marks = set("。！？；…!?")
    out, buf = [], ""
    for ch in text:
        if ch == "\n":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
            continue
        buf += ch
        if ch in marks and buf.strip():
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return [s for s in out if re.search(r"[A-Za-z0-9\u4e00-\u9fff]", s)]


def pinyin_tokens(text):
    """小学文章逐字注音，返回 [{"h": 字, "p": 拼音}]，标点拼音留空。

    整句交给 pypinyin 才会做「一 / 不」变调和轻声（一个→yí gè、一起→yì qǐ），
    拆成单字逐个查会退回本调。库没收录的生僻字只留汉字、拼音空着，
    电视端照常显示这一格，不会整句塌掉。
    """
    try:
        from pypinyin import lazy_pinyin, Style
    except Exception:
        return []
    t = (text or "").strip()
    if not t:
        return []
    han = re.compile(r"^[\u4e00-\u9fff]$")
    ps = lazy_pinyin(t, style=Style.TONE)
    if len(ps) != len(t):
        ps = [lazy_pinyin(ch, style=Style.TONE)[0] if han.match(ch) else ch for ch in t]
    out = []
    for i, ch in enumerate(t):
        p = ps[i] if i < len(ps) else ""
        if not han.match(ch) or p == ch:
            p = ""
        out.append({"h": ch, "p": p})
    return out


def count_chars(text):
    return len(re.sub(r"\s", "", text or ""))


def ensure_tail(text):
    t = (text or "").rstrip()
    if not t:
        return t
    if t[-1] in "。！？；…!?":
        return t
    idx = max(t.rfind(m) for m in "。！？")
    return t[: idx + 1].rstrip() if idx > 0 else t


def clean_segment(text):
    t = (text or "").strip()
    t = re.sub(r"```[a-zA-Z]*", "", t).replace("```", "").strip()
    t = re.sub(r"^\s*(第[一二三四五六七八九十0-9]+段[：:]?)", "", t)
    t = re.sub(r"^\s*[0-9]+[、.．]\s*", "", t)
    for ch in "**##「」《》（）“”\"'":
        t = t.replace(ch, "")
    return t.strip()


def style_hint(grade):
    if grade.startswith("小学一") or grade.startswith("小学二") or grade.startswith("小学三"):
        return "句子要短，单句不超过 20 字，词语浅白，多用对话和具体画面，不写生僻字。"
    if grade.startswith("小学"):
        return "句子长短适中，有细节和心理描写，语言浅白自然，不写生僻字。"
    if grade.startswith("初中"):
        return "叙事清楚有起伏，可以有一点抒情和议论，语言自然，避免网络用语。"
    if grade.startswith("高中"):
        return "语言凝练，可有适度的议论和思辨，结构完整，避免说教。"
    return "介绍一部经典作品的片段或故事，语言浅白，情节完整。"


def ask_ai(cfg, prompt, max_tokens=1600, system="你是语文阅读内容编辑，只输出要求的格式，不解释。"):
    url = cfg["ai_base"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["ai_model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last = ""
    for i in range(3):
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", UA)
        if cfg.get("api_key"):
            req.add_header("Authorization", "Bearer " + cfg["api_key"])
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = json.loads(r.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except Exception as exc:
            last = "%s: %s" % (type(exc).__name__, exc)
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("AI 调用失败：" + last)


def parse_article(raw):
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        raise ValueError("AI 没有返回 JSON：" + (raw or "")[:100])
    o = json.loads(m.group(0))
    title = clean_segment(o.get("title") or "")[:16]
    body = (o.get("body") or "").strip()
    if not title or not body:
        raise ValueError("标题或正文为空")
    return title, body


def write_long(cfg, grade, topic, target, avoid, log, on_step=None):
    hint = style_hint(grade)
    outline_prompt = (
        "为%s学生写一篇关于下面这个情景的短文，正文要写到 %d 字以上：\n「%s」\n"
        "要求 4 到 6 段，每段用一句话写清这一段讲什么，情节有先后顺序。\n%s\n%s"
        "只输出 JSON：{\"title\":\"不超过14字的标题\",\"outline\":[\"第一段要点\",\"第二段要点\"]}"
        % (grade, target, topic, hint, ("不要和这些标题重复：" + avoid + "\n") if avoid else "")
    )
    raw = ask_ai(cfg, outline_prompt, max_tokens=600)
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("大纲没有返回 JSON")
    o = json.loads(m.group(0))
    title = clean_segment(o.get("title") or "")[:16]
    outline = [str(x).strip() for x in (o.get("outline") or []) if str(x).strip()]
    if len(outline) < 3:
        outline = ["开头：交代时间和人物", "中间：遇到一件小事", "变化：事情有了转折", "结尾：心里的感受"]
    outline = outline[:6]
    log("  [写稿中] 大纲《%s》共 %d 段" % (title, len(outline)))

    parts = []
    seg_target = max(120, int(target * 1.25) // len(outline))
    for idx, point in enumerate(outline):
        prev = parts[-1][-70:] if parts else ""
        if on_step:
            on_step("写第 %d/%d 段" % (idx + 1, len(outline)),
                    int(90 * idx / max(1, len(outline))))
        prompt = (
            "写%s学生文章《%s》的第 %d 段（共 %d 段）正文。\n"
            "全篇情景：%s\n本段要点：%s\n%s%s"
            "字数：不少于 %d 字。\n"
            "只输出这一段正文，不要段号、不要标题、不要 JSON、不要 markdown。"
            % (grade, title, idx + 1, len(outline), topic, point,
               ("上一段结尾：「%s」，要自然衔接。\n" % prev) if prev else "",
               hint, seg_target)
        )
        seg = clean_segment(ask_ai(cfg, prompt, max_tokens=max(600, seg_target * 3)))
        if not seg:
            continue
        parts.append(ensure_tail(seg))
        log("  [写稿中] 第 %d/%d 段 %d 字，累计 %d 字" % (
            idx + 1, len(outline), count_chars(seg), count_chars("".join(parts))))

    body = "\n".join(parts)
    extra = 0
    while count_chars(body) < target and extra < 6 and parts:
        extra += 1
        need = target - count_chars(body)
        if on_step:
            on_step("补写第 %d 段" % (len(parts) + 1), 90)
        prompt = (
            "接着写%s学生文章《%s》的下一段（不是结尾，也不要总结），大约 %d 字，3 到 5 句。\n"
            "%s\n已写内容最后一段：「%s」\n只输出这一段正文，不要段号、不要标题。"
            % (grade, title, max(120, need), hint, parts[-1][-90:])
        )
        seg = clean_segment(ask_ai(cfg, prompt, max_tokens=max(800, need * 4)))
        if not seg:
            break
        parts.append(ensure_tail(seg))
        body = "\n".join(parts)
        log("  [写稿中] 补写第 %d 段，累计 %d 字" % (len(parts), count_chars(body)))

    return title, ensure_tail(body)


def write_once(cfg, grade, topic, target, avoid, log):
    hint = style_hint(grade)
    prompt = (
        "写一篇适合%s学生朗读的中文短文。\n硬性要求：正文字数不少于 %d 字（目标 %d 字）。\n"
        "情景：%s\n正文分 3 到 5 个自然段，每段 3 到 6 句。\n%s\n只用中文标点。\n%s"
        "只输出 JSON，格式：{\"title\":\"不超过14字的标题\",\"body\":\"正文\"}"
        % (grade, int(target * 0.95), target, topic, hint,
           ("不要和这些已有标题重复：" + avoid + "\n") if avoid else "")
    )
    return parse_article(ask_ai(cfg, prompt, max_tokens=max(1200, target * 3)))


def offline_article(grade, topic, chars):
    openers = ["早上出门的时候，天刚亮，风吹在脸上凉凉的。",
               "放学以后，我背着书包慢慢走回家。",
               "周末的下午，我在院子里坐了很久。"]
    middles = ["我看见路边的小草从石头缝里钻出来，绿得很认真。",
               "妈妈说做事情要有耐心，一点一点来就好。",
               "风把树叶吹得沙沙响，像有人在轻轻说话。",
               "我把这件事写进日记本，写了满满一页。",
               "同学病了，我把作业本送到他家门口。"]
    ends = ["我想，这就是今天送给我的礼物。", "回家的路上，我一直想着这件事。", "这一天很普通，可是心里很暖。"]
    sb = [random.choice(openers)]
    for _ in range(max(int(chars // 45), 4)):
        sb.append(random.choice(middles))
    sb.append(random.choice(ends))
    return (topic[:14] or "普通的一天"), "".join(sb)


# ---------------------------------------------------------------- 封面
def cover_pool():
    return sorted(COVERS.glob("*.jpg"))


def pick_cover(aid, title, topic=""):
    text = (title or "") + "|" + (topic or "")
    for kw, name in COVER_RULES:
        if kw and kw in text:
            p = COVERS / name
            if p.exists():
                return p
    files = cover_pool()
    if not files:
        return None
    return files[int(hashlib.md5(aid.encode()).hexdigest(), 16) % len(files)]


# ---------------------------------------------------------------- 配音
def synth_all(jobs, voice, rate, conc, on_progress=None):
    """jobs = [(索引, 文本, 输出路径)]；返回等长 True/False 列表。"""
    import edge_tts

    total = len(jobs)
    state = {"done": 0}

    async def one(text, out, sem):
        async with sem:
            ok = False
            for attempt in range(1, 4):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))
                    if out.exists() and out.stat().st_size > 0:
                        ok = True
                        break
                except Exception:
                    await asyncio.sleep(1.2 * attempt)
            state["done"] += 1
            if on_progress:
                try:
                    on_progress(state["done"], total)
                except Exception:
                    pass
            return ok

    async def run():
        sem = asyncio.Semaphore(max(1, int(conc)))
        return await asyncio.gather(*[one(t, o, sem) for _, t, o in jobs],
                                    return_exceptions=True)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(run())
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)
    return [r is True for r in results]


# ---------------------------------------------------------------- 文章编码（与网盘、APK 共用一套）
ID_STAGE = {"小学": "X", "初中": "C", "高中": "G"}
ID_GRADE = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6"}


def id_prefix(category):
    """小学 X1..X6 / 初中 C1..C3 / 高中 G1..G3 / 名著 MZ。"""
    c = str(category or "").strip()
    if c.startswith("名著") or c == "世界名著" or c.startswith("世界名著"):
        return "MZ"
    stage = c[:2]
    if stage not in ID_STAGE:
        return ""
    return ID_STAGE[stage] + ID_GRADE.get(c[2:3], "")


def title_code(title):
    """标题去掉标点后取最后 3 个字的首字母（汉字取拼音首字母）。"""
    clean = re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", title or "")
    out = ""
    for ch in clean[-3:]:
        if "\u4e00" <= ch <= "\u9fff":
            from pypinyin import Style, lazy_pinyin
            py = lazy_pinyin(ch, style=Style.FIRST_LETTER)
            out += py[0][:1].lower() if py and py[0] else ""
        else:
            out += ch.lower()
    return out or "zzz"


def encode_id(cfg, category, title, fallback=""):
    """生成规范文章 id：前缀 + 5 位序号 + 3 位标题码。失败时回退 fallback。"""
    prefix = id_prefix(category)
    if not prefix:
        return fallback
    seq = 1
    try:
        ol = OL(cfg["server"])
        ol.login(cfg["user"], cfg["password"])
        base = "/%s/content/ai" % cfg["root"].strip("/")
        names = [e["name"][:-5] for e in ol.list(base) if e["name"].endswith(".json")]
        used = []
        for n in names:
            if n.startswith(prefix) and len(n) >= len(prefix) + 5:
                tail = n[len(prefix):len(prefix) + 5]
                if tail.isdigit():
                    used.append(int(tail))
        seq = (max(used) + 1) if used else 1
    except Exception:
        seq = 1
    return "%s%05d%s" % (prefix, seq, title_code(title))


# ---------------------------------------------------------------- 任务状态
TASKS = {}
TASK_ORDER = []
LOCK = threading.Lock()


def task_new(aid, category, topic):
    with LOCK:
        TASKS[aid] = {
            "id": aid, "title": "", "category": category,
            "topic": topic, "status": "排队中", "step": "", "progress": 0,
            "chars": 0, "sents": 0, "mp3": 0, "cover": "", "ready": False,
            "upload_total": 0, "upload_done_count": 0, "upload_done": False,
            "error": "", "updated": time.time(),
        }
        TASK_ORDER.append(aid)


def task_set(aid, **kw):
    with LOCK:
        t = TASKS.get(aid)
        if t:
            t.update(kw)
            t["updated"] = time.time()


def task_snapshot():
    with LOCK:
        return [dict(TASKS[a]) for a in TASK_ORDER if a in TASKS]


def task_rekey(old, new):
    """文章正式编码确定后，把任务条目从临时 id 迁到正式 id。"""
    if old == new:
        return
    with LOCK:
        t = TASKS.pop(old, None)
        if not t:
            return
        t["id"] = new
        TASKS[new] = t
        try:
            TASK_ORDER[TASK_ORDER.index(old)] = new
        except ValueError:
            TASK_ORDER.append(new)


def boot_scan():
    """重启后把本地已生成、还没上传的稿子重新列成「待上传」。"""
    if not OUTPUT.exists():
        return
    dirs = [d for d in OUTPUT.iterdir() if d.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime)
    for d in dirs:
        jf = d / (d.name + ".json")
        if not jf.exists() or (d / ".uploaded").exists():
            continue
        if d.name in TASKS:
            continue
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        task_new(d.name, payload.get("category", ""), "")
        cover_name = ""
        cf = d / ".cover"
        if cf.exists():
            try:
                cover_name = cf.read_text(encoding="utf-8").strip()
            except Exception:
                cover_name = ""
        task_set(d.name, title=payload.get("title", ""),
                 chars=payload.get("maxChars", 0),
                 sents=len(payload.get("sentences") or []),
                 mp3=len(list(d.glob("*.mp3"))),
                 cover=cover_name,
                 status="待上传", step="重启前生成，等确认", progress=100, ready=True)
        push("恢复本地待上传：%s《%s》" % (d.name, payload.get("title", "")))


# ---------------------------------------------------------------- 单篇生成
def gen_one(cfg, grade, chars, topic, aid, titles, opts, log, stop):
    task_id = aid
    task_new(task_id, grade, topic)
    log("")
    log("=== %s ｜ 主题「%s」｜ 目标 %d 字 ===" % (task_id, topic[:24], chars))
    task_set(task_id, status="写稿中", step="生成大纲", progress=0)

    title = body = ""
    if opts.get("offline"):
        title, body = offline_article(grade, topic, chars)
        log("  离线模板成稿（未调 AI）")
        task_set(task_id, step="模板拼稿", progress=90)
    else:
        avoid = "、".join(titles[:30])
        try:
            title, body = write_long(cfg, grade, topic, chars, avoid, log,
                                     on_step=lambda s, p: task_set(task_id, step=s, progress=p))
            if count_chars(body) < chars * 0.8:
                log("  篇幅只有 %d 字，改为整篇重新生成" % count_chars(body))
                task_set(task_id, step="整篇重写", progress=50)
                title, body = write_once(cfg, grade, topic, chars, avoid, log)
        except Exception as exc:
            log("  分段生成失败：%s，改为整篇生成" % exc)
            for attempt in range(3):
                try:
                    task_set(task_id, step="整篇生成 %d/3" % (attempt + 1))
                    title, body = write_once(cfg, grade, topic, chars, avoid, log)
                    break
                except Exception as e2:
                    log("  第 %d 次不合法：%s" % (attempt + 1, e2))
                    time.sleep(1)
        if not body:
            task_set(task_id, status="失败", step="写稿失败", error="连续生成失败")
            log("  放弃这一篇：连续生成失败")
            return None

    body = ensure_tail(body)
    sents = split_sentences(body)
    if not sents:
        task_set(task_id, status="失败", step="没有可用句子", error="切句为空")
        log("  放弃这一篇：正文没有可用句子")
        return None

    # 标题已定，按统一规则生成正式文章编码（学段+年级+序号+标题码）
    aid = encode_id(cfg, grade, title, task_id)
    log("  文章编码 %s（类别 %s）" % (aid, grade))
    task_rekey(task_id, aid)

    task_set(task_id, title=title, chars=count_chars(body), sents=len(sents),
             status="配音中", step="准备配音", progress=0)
    log("  成稿《%s》：%d 字，%d 句" % (title, count_chars(body), len(sents)))

    cover = pick_cover(aid, title, topic) if opts["do_cover"] else None
    out_dir = OUTPUT / aid
    out_dir.mkdir(parents=True, exist_ok=True)
    if cover:
        (out_dir / "cover.jpg").write_bytes(cover.read_bytes())
        (out_dir / ".cover").write_text(cover.name, encoding="utf-8")
        task_set(aid, cover=cover.name)
        log("  封面 %s（%d 字节）" % (cover.name, cover.stat().st_size))

    mp3_files = []
    if opts["do_audio"] and not stop.is_set():
        jobs = [(i, s, out_dir / ("%03d.mp3" % (i + 1))) for i, s in enumerate(sents)]
        log("  配音 %d 句（%s，%s，并发 %d）" % (len(sents), cfg["voice"], cfg["rate"], cfg["conc"]))
        t0 = time.time()

        def on_progress(done, total):
            task_set(aid, step="配音 %d/%d 句" % (done, total),
                     progress=int(100 * done / max(1, total)))
            step = max(1, total // 4)
            if done == 1 or done == total or done % step == 0:
                log("  [配音中] %d/%d 句" % (done, total))

        results = synth_all(jobs, cfg["voice"], cfg["rate"], cfg["conc"], on_progress)
        ok = [jobs[i] for i, r in enumerate(results) if r]
        miss = [jobs[i][0] + 1 for i, r in enumerate(results) if not r]
        mp3_files = [j[2] for j in ok]
        log("  配音完成 %d/%d，%.1f 秒%s" % (
            len(ok), len(sents), time.time() - t0,
            ("；缺第 %s 句，可再生成一次补上" % ",".join(map(str, miss[:10]))) if miss else ""))
    else:
        log("  跳过配音（未勾选或已停止）")

    # 小学一到六年级必须逐字注音，中学和名著不注
    is_primary = str(grade).startswith("小学")
    sent_list = []
    for i, s in enumerate(sents):
        d = {"text": s, "pinyin": "", "image": "",
             "audio": "/%s/%s/%03d.mp3" % (cfg["root"], aid, i + 1)}
        if is_primary:
            toks = pinyin_tokens(s)
            if toks:
                d["tokens"] = toks
        sent_list.append(d)
    if is_primary:
        got = [d for d in sent_list if d.get("tokens")]
        log("  拼音 %d/%d 句（逐字带声调）" % (len(got), len(sents)))
        if len(got) < len(sents):
            log("  有 %d 句没取到拼音，检查 pypinyin 是否装好" % (len(sents) - len(got)))

    payload = {
        "id": aid,
        "title": title,
        "category": grade,
        "body": body,
        "autoChecked": True,
        "autoCheckNote": "电脑写稿器生成" + ("（小学已逐字注音）" if is_primary else ""),
        "manualChecked": False,
        "cover": "/%s/%s/cover.jpg" % (cfg["root"], aid) if cover else "",
        "maxChars": count_chars(body),
        "sentences": sent_list,
    }
    if cover:
        payload["coverVersion"] = cover.stat().st_size
    (out_dir / (aid + ".json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    task_set(aid, status="待上传", step="已生成，等确认", progress=100,
             mp3=len(mp3_files), ready=True)
    log("  已生成完毕，本地在 %s；确认后点「上传」" % out_dir)
    return {"aid": aid, "title": title, "sents": len(sents), "mp3": len(mp3_files)}


# ---------------------------------------------------------------- 上传
def upload_one(cfg, aid, log):
    out_dir = OUTPUT / aid
    jf = out_dir / (aid + ".json")
    if not jf.exists():
        task_set(aid, status="上传失败", step="本地文件缺失", error="没有 json")
        log("  %s 本地没有 json，无法上传" % aid)
        return False
    payload = json.loads(jf.read_text(encoding="utf-8"))
    mp3s = sorted(out_dir.glob("*.mp3"))
    cover = out_dir / "cover.jpg"
    root = "/" + cfg["root"].strip("/")

    task_set(aid, status="上传中", step="连接网盘", progress=0,
             upload_total=len(mp3s), upload_done_count=0)
    ol = OL(cfg["server"])
    try:
        ol.login(cfg["user"], cfg["password"])
    except Exception as exc:
        task_set(aid, status="上传失败", step="登录失败", error=str(exc)[:80])
        log("  网盘登录失败：%s" % exc)
        return False

    ol.mkdir("%s/%s" % (root, aid))
    done = fail = 0
    step = max(1, len(mp3s) // 4)
    for p in mp3s:
        o, m = ol.put("%s/%s/%s" % (root, aid, p.name), p.read_bytes())
        if o:
            done += 1
        else:
            fail += 1
            log("    上传失败 %s %s" % (p.name, m))
        task_set(aid, step="上传 mp3 %d/%d" % (done + fail, len(mp3s)),
                 progress=int(90 * (done + fail) / max(1, len(mp3s))),
                 upload_done_count=done)
        if done == 1 or done + fail == len(mp3s) or (done + fail) % step == 0:
            log("  [上传中] mp3 %d/%d" % (done + fail, len(mp3s)))
    if cover.exists():
        o, m = ol.put("%s/%s/cover.jpg" % (root, aid), cover.read_bytes())
        if not o:
            log("    封面上传失败：%s" % m)
    o, m = ol.put("%s/content/ai/%s.json" % (root, aid),
                  jf.read_bytes())
    log("  上传 %s：mp3 %d/%d，封面 %s，json %s" % (
        aid, done, len(mp3s), "有" if cover.exists() else "无", "已写入" if o else "失败 " + m))
    if not o:
        task_set(aid, status="上传失败", step="json 写入失败", error=m[:80])
        return False
    task_set(aid, status="已上传", step="电视端下次打开即可见", progress=100,
             upload_done_count=done, upload_done=True)
    try:
        (out_dir / ".uploaded").write_text(str(int(time.time())), encoding="utf-8")
    except Exception:
        pass
    return True


# ---------------------------------------------------------------- 生成批次
def run_job(cfg, opts, log, stop, ids=None):
    grade = opts["grade"]
    chars = opts["chars"]
    count = opts["count"]
    base_topic = (opts.get("topic") or "").strip()
    offline = opts.get("offline", False)

    titles = []
    if opts["skip_dup"] and not offline:
        try:
            from concurrent.futures import ThreadPoolExecutor

            ol = OL(cfg["server"])
            ol.login(cfg["user"], cfg["password"])
            base = "/%s/content/ai" % cfg["root"].strip("/")
            names = [e["name"] for e in ol.list(base)[:60] if e["name"].endswith(".json")]
            log("读取网盘已有标题（%d 篇）…" % len(names))

            def fetch(name):
                try:
                    return json.loads(ol.read(base + "/" + name).decode("utf-8")).get("title", "")
                except Exception:
                    return ""

            with ThreadPoolExecutor(max_workers=8) as ex:
                titles = [t for t in ex.map(fetch, names) if t]
            log("网盘已有 %d 篇，会避开同名标题" % len(titles))
        except Exception as exc:
            log("读取已有标题失败（继续）：%s" % exc)

    stamp = int(time.time() * 1000)
    made = []
    for i in range(count):
        if stop.is_set():
            log("已停止")
            break
        if i == 0:
            topic = base_topic or random.choice(TOPIC_SAMPLES)
        else:
            pool = [t for t in TOPIC_SAMPLES if t not in titles]
            topic = random.choice(pool) if pool else random.choice(TOPIC_SAMPLES)
        # 外部（电视端）发起时用调用方预先给的 id，前端才能立刻按 id 盯进度
        aid = ids[i] if ids and i < len(ids) else "gen_%d_%d" % (stamp, i + 1)
        try:
            r = gen_one(cfg, grade, chars, topic, aid, titles, opts, log, stop)
        except Exception as exc:
            task_set(aid, status="失败", step="异常", error="%s: %s" % (type(exc).__name__, exc))
            log("  这一篇失败：%s: %s" % (type(exc).__name__, exc))
            r = None
        if r:
            titles.append(r["title"])
            made.append(r)
            log("  进度 %d/%d 篇" % (len(made), count))
    log("")
    log("=== 本次生成 %d / %d 篇，全部停在「待上传」，确认后点上传按钮 ===" % (len(made), count))
    return made


# ---------------------------------------------------------------- 本地服务
STATE = {"running": False, "lines": [], "seq": 0, "status": "就绪",
         "base": 0, "stop": None, "uploading": False}
LOCK2 = threading.Lock()


def push(msg, status=None):
    with LOCK2:
        STATE["lines"].append(msg)
        if len(STATE["lines"]) > 4000:
            drop = len(STATE["lines"]) - 1500
            STATE["lines"] = STATE["lines"][drop:]
            STATE["base"] += drop
        STATE["seq"] += 1
        if status:
            STATE["status"] = status


class Handler(BaseHTTPRequestHandler):
    server_version = "KidsWriter/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code, data, ctype="application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    # ---- 鉴权 ----
    ADMIN_GET = {"/api/state", "/api/tasks", "/api/quiz/edits"}
    ADMIN_POST = {"/api/start", "/api/stop", "/api/upload", "/api/test",
                  "/api/test/conn", "/api/delete", "/api/delete_many",
                  "/api/quiz/ai", "/api/quiz/save", "/api/quiz/upload"}
    # 登录即可（管理员、一般账户都能访问）的答题/阅读接口
    USER_GET = {"/api/quiz/manifest", "/api/quiz/file", "/api/quiz/edit",
                "/api/reader/articles", "/api/reader/article", "/api/reader/audio",
                "/api/reader/cover"}

    def _read_token(self):
        h = self.headers.get("Authorization", "")
        if h.startswith("Bearer "):
            return h[7:].strip()
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "token":
                return v.strip()
        return ""

    def _current(self):
        return auth_by_token(self._read_token())

    def _guard_admin(self):
        user = self._current()
        if not user:
            self._send(401, {"ok": False, "msg": "未登录，请先登录"})
            return None
        if user["role"] != "admin":
            self._send(403, {"ok": False, "msg": "仅管理员可用此功能"})
            return None
        return user

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/me":
            user = self._current()
            if not user:
                return self._send(200, {"ok": False, "msg": "未登录"})
            return self._send(200, {"ok": True, "username": user["username"],
                                    "role": user["role"],
                                    "pages": ROLE_PAGES.get(user["role"], ROLE_PAGES["user"])})
        if path == "/api/accounts":
            if not self._guard_admin():
                return
            return self._send(200, {"ok": True, "users": auth_list_users()})
        if path in self.ADMIN_GET:
            if not self._guard_admin():
                return
        if path in self.USER_GET and not self._current():
            return self._send(401, {"ok": False, "msg": "未登录，请先登录"})
        if path in ("/", "/index.html"):
            html = UI_HTML.read_text(encoding="utf-8") if UI_HTML.exists() else "缺少 界面.html"
            return self._send(200, html, "text/html; charset=utf-8")
        if path == "/api/state":
            q = urllib.parse.parse_qs(parsed.query)
            since = int((q.get("since") or ["0"])[0])
            with LOCK2:
                if since < STATE["base"]:
                    since = STATE["base"]
                lines = STATE["lines"][since - STATE["base"]:]
                return self._send(200, {
                    "running": STATE["running"], "status": STATE["status"],
                    "seq": STATE["seq"], "from": since,
                    "total": STATE["base"] + len(STATE["lines"]), "lines": lines,
                    "tasks": task_snapshot(),
                })
        if path == "/api/tasks":
            # 给电视端轮询用的精简接口：只回状态和任务，不带日志文本
            with LOCK2:
                return self._send(200, {
                    "running": STATE["running"], "status": STATE["status"],
                    "uploading": bool(STATE.get("uploading")),
                    "seq": STATE["seq"],
                    "tasks": task_snapshot(),
                })
        if path == "/api/config":
            cfg = load_config()
            me = self._current()
            is_admin = bool(me and me["role"] == "admin")
            payload = {
                "grade": cfg["grade"], "chars": cfg["chars"], "count": cfg["count"],
                "voice": cfg["voice"], "rate": cfg["rate"], "root": cfg["root"],
                "covers": len(cover_pool()), "port": PORT,
                "quiz_url": cfg.get("quiz_url", ""),
                "quiz_root": cfg.get("quiz_root", "夸克/CleanMiTV/quiz"),
                "quiz_stages": QUIZ_STAGES, "subject_labels": SUBJECT_LABELS,
            }
            if is_admin:
                payload.update({"server": cfg["server"], "user": cfg["user"],
                                "password": cfg["password"]})
            return self._send(200, payload)
        if path == "/api/quiz/manifest":
            cfg = load_config()
            try:
                root, base = quiz_manifest(cfg)
                files = [{
                    "name": f.get("name"), "size": f.get("size", 0),
                    "sha256": f.get("sha256", ""),
                } for f in root.get("files", [])]
                return self._send(200, {
                    "ok": True, "version": root.get("version", ""),
                    "count": root.get("count", 0), "generated": root.get("generated", ""),
                    "source": base, "files": files,
                    "stages": QUIZ_STAGES, "subject_labels": SUBJECT_LABELS,
                })
            except Exception as exc:
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})
        if path == "/api/quiz/file":
            name = (urllib.parse.parse_qs(parsed.query).get("name") or [""])[0]
            cfg = load_config()
            try:
                questions = quiz_questions(cfg, name)
                return self._send(200, {"ok": True, "name": name, "questions": questions})
            except Exception as exc:
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})
        if path == "/api/quiz/edit":
            name = (urllib.parse.parse_qs(parsed.query).get("name") or [""])[0]
            cfg = load_config()
            try:
                questions, source = quiz_load_edit(cfg, name)
                return self._send(200, {"ok": True, "name": name,
                                        "questions": questions, "source": source})
            except Exception as exc:
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})
        if path == "/api/reader/articles":
            category = (urllib.parse.parse_qs(parsed.query).get("category") or [""])[0]
            cfg = load_config()
            try:
                return self._send(200, {"ok": True, "articles": reader_list_articles(cfg, category)})
            except Exception as exc:
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})
        if path == "/api/reader/article":
            aid = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
            cfg = load_config()
            try:
                return self._send(200, {"ok": True, "article": reader_get_article(cfg, aid)})
            except Exception as exc:
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})
        if path == "/api/reader/audio":
            q = urllib.parse.parse_qs(parsed.query)
            aid = (q.get("id") or [""])[0]
            try:
                idx = int((q.get("i") or ["0"])[0])
            except ValueError:
                idx = -1
            cfg = load_config()
            try:
                data = reader_audio_bytes(cfg, aid, idx)
                return self._send_bytes(200, data, "audio/mpeg")
            except Exception as exc:
                return self._send(404, {"ok": False, "msg": str(exc)[:160]})
        if path == "/api/reader/cover":
            aid = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
            cfg = load_config()
            try:
                data = reader_cover_bytes(cfg, aid)
                return self._send_bytes(200, data, "image/jpeg")
            except Exception as exc:
                return self._send(404, {"ok": False, "msg": str(exc)[:160]})
        if path == "/api/quiz/edits":
            staged = []
            if QUIZ_EDIT_DIR.exists():
                for p in sorted(QUIZ_EDIT_DIR.glob("*.json")):
                    try:
                        node = json.loads(p.read_text(encoding="utf-8-sig"))
                        staged.append({"name": p.name, "count": len(node.get("questions") or [])})
                    except Exception:
                        pass
            return self._send(200, {"ok": True, "staged": staged})
        if path == "/api/topic":
            return self._send(200, {"topic": random.choice(TOPIC_SAMPLES),
                                    "total": len(TOPIC_SAMPLES)})
        if path == "/api/covers":
            return self._send(200, {"count": len(cover_pool()),
                                    "names": [p.name for p in cover_pool()]})
        return self._send(404, "not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            data = {}

        if path == "/api/login":
            user = auth_check(data.get("username"), data.get("password"))
            if not user:
                return self._send(200, {"ok": False, "msg": "账户或密码不正确"})
            token = auth_issue(user)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie",
                             "token=%s; HttpOnly; Path=/; SameSite=Lax" % token)
            body = json.dumps({"ok": True, "username": user["username"],
                               "role": user["role"], "token": token,
                               "pages": ROLE_PAGES.get(user["role"], ROLE_PAGES["user"])},
                              ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/logout":
            token = self._read_token()
            _SESSIONS.pop(token, None)
            self.send_response(200)
            self.send_header("Set-Cookie", "token=; HttpOnly; Path=/; Max-Age=0")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/accounts":
            if not self._guard_admin():
                return
            ok, msg = auth_upsert_user(data.get("username"), data.get("password"),
                                       data.get("role", "user"))
            return self._send(200, {"ok": ok, "msg": msg,
                                    "users": auth_list_users() if ok else None})

        if path == "/api/accounts/delete":
            if not self._guard_admin():
                return
            ok, msg = auth_delete_user(data.get("username"))
            return self._send(200, {"ok": ok, "msg": msg,
                                    "users": auth_list_users() if ok else None})

        if path in self.ADMIN_POST:
            if not self._guard_admin():
                return

        if path == "/api/start":
            if STATE["running"]:
                return self._send(200, {"ok": False, "msg": "正在生成，等这一批结束"})
            opts = self._opts(data)
            cfg = load_config()
            for k in ("server", "user", "password"):
                if data.get(k):
                    cfg[k] = data[k]
            save_config(cfg)
            with LOCK:
                TASKS.clear()
                TASK_ORDER.clear()
            stop = threading.Event()
            with LOCK2:
                STATE.update({"running": True, "lines": [], "seq": 0,
                              "status": "生成中", "stop": stop, "base": 0})

            stamp = int(time.time() * 1000)
            ids = ["gen_%d_%d" % (stamp, i + 1) for i in range(opts["count"])]

            def worker():
                try:
                    run_job(cfg, opts, push, stop, ids)
                except Exception as exc:
                    push("出错：%s: %s" % (type(exc).__name__, exc))
                finally:
                    with LOCK2:
                        STATE["running"] = False
                        STATE["status"] = "生成完成，等上传"
                    push("")

            threading.Thread(target=worker, daemon=True).start()
            return self._send(200, {"ok": True, "ids": ids, "count": len(ids),
                                    "grade": opts["grade"]})

        if path == "/api/stop":
            with LOCK2:
                if STATE["stop"]:
                    STATE["stop"].set()
            push("正在停止…")
            return self._send(200, {"ok": True})

        if path == "/api/upload":
            ids = data.get("ids") or []
            if not ids:
                ids = [t["id"] for t in task_snapshot() if t.get("ready") and not t.get("upload_done")]
            if not ids:
                return self._send(200, {"ok": False, "msg": "没有可上传的文章"})
            cfg = load_config()
            for k in ("server", "user", "password"):
                if data.get(k):
                    cfg[k] = data[k]
            save_config(cfg)

            def up_worker():
                okn = 0
                for aid in ids:
                    push("")
                    push("--- 上传 %s ---" % aid)
                    try:
                        if upload_one(cfg, aid, push):
                            okn += 1
                    except Exception as exc:
                        push("  上传异常：%s: %s" % (type(exc).__name__, exc))
                with LOCK2:
                    STATE["uploading"] = False
                    STATE["status"] = "已上传 %d 篇" % okn
                push("=== 上传结束：成功 %d / %d 篇 ===" % (okn, len(ids)))

            with LOCK2:
                STATE["uploading"] = True
            threading.Thread(target=up_worker, daemon=True).start()
            return self._send(200, {"ok": True, "count": len(ids)})

        if path == "/api/test":
            def job():
                try:
                    o = OL(data.get("server") or load_config()["server"])
                    o.login(data.get("user") or "admin", data.get("password") or "jankxia")
                    root = "/" + (data.get("root") or "夸克/KidsReader").strip("/")
                    n = len(o.list(root + "/content/ai"))
                    push("连接成功：content/ai 现有 %d 篇" % n)
                except Exception as exc:
                    push("连接失败：%s" % exc)
            threading.Thread(target=job, daemon=True).start()
            return self._send(200, {"ok": True})

        if path == "/api/test/conn":
            cfg = load_config()
            kind = (data.get("kind") or "article").strip()
            server = (data.get("server") or cfg["server"]).strip()
            user = (data.get("user") or "admin").strip()
            password = data.get("password") or cfg["password"]
            try:
                o = OL(server)
                o.login(user, password)
                if kind == "quiz":
                    root = "/" + cfg.get("quiz_root", "夸克/CleanMiTV/quiz").strip("/")
                    names = [e["name"] for e in o.list(root)
                             if e["name"].endswith(".json") and e["name"] != "index.json"]
                    return self._send(200, {"ok": True,
                                            "msg": "连接成功，题库目录现有 %d 个年级文件" % len(names)})
                root = "/" + (data.get("root") or cfg.get("root", "夸克/KidsReader")).strip("/")
                n = len(o.list(root + "/content/ai"))
                return self._send(200, {"ok": True, "msg": "连接成功，文章目录现有 %d 篇" % n})
            except Exception as exc:
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})

        if path == "/api/delete":
            aid = (data.get("id") or "").strip()
            if not aid or "/" in aid or "\\" in aid:
                return self._send(200, {"ok": False, "msg": "文章 id 不合法"})
            with LOCK:
                t = TASKS.get(aid) or {}
            if t.get("status") in ("写稿中", "配音中", "上传中"):
                return self._send(200, {"ok": False,
                                        "msg": "这篇正在%s，等它停下来再删" % t.get("status")})
            folder = OUTPUT / aid
            removed = 0
            if folder.exists():
                try:
                    removed = sum(1 for p in folder.iterdir() if p.is_file())
                    shutil.rmtree(folder)
                except Exception as exc:
                    return self._send(200, {"ok": False,
                                            "msg": "删除失败：%s" % exc})
            with LOCK:
                TASKS.pop(aid, None)
                if aid in TASK_ORDER:
                    TASK_ORDER.remove(aid)
            push("已删除本地稿子 %s（%d 个文件）%s" % (
                aid, removed,
                "，网盘上的副本没有动" if t.get("upload_done") else ""))
            return self._send(200, {"ok": True, "removed": removed})

        if path == "/api/quiz/ai":
            cfg = load_config()
            try:
                questions = quiz_ai_generate(
                    cfg, data.get("stage"), int(data.get("grade") or 1),
                    data.get("subject"), int(data.get("count") or 5),
                    data.get("topic") or "")
                resp = {"ok": True, "questions": questions}
                if data.get("autoupload", True):
                    result = quiz_ai_commit(
                        cfg, data.get("stage"), int(data.get("grade") or 1),
                        data.get("subject"), questions, push)
                    resp.update({"uploaded": True, **result})
                return self._send(200, resp)
            except Exception as exc:
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})

        if path == "/api/quiz/save":
            name = (data.get("name") or "").strip()
            questions = data.get("questions") or []
            try:
                count = quiz_save_local(name, questions)
                return self._send(200, {"ok": True, "name": name, "count": count})
            except Exception as exc:
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})

        if path == "/api/quiz/upload":
            cfg = load_config()
            for k in ("server", "user", "password"):
                if data.get(k):
                    cfg[k] = data[k]
            save_config(cfg)
            try:
                result = quiz_upload_pack(cfg, push)
                push("题库上传完成：%d 个年级文件，共 %d 题，版本 %s"
                     % (len(result["changed"]), result["total"], result["version"]))
                return self._send(200, {"ok": True, **result})
            except Exception as exc:
                push("题库上传失败：%s" % exc)
                return self._send(200, {"ok": False, "msg": str(exc)[:160]})

        if path == "/api/delete_many":
            ids = data.get("ids") or []
            if not isinstance(ids, list) or not ids:
                return self._send(200, {"ok": False, "msg": "没有选中文章"})
            removed, skipped = 0, []
            for raw_id in ids:
                aid = str(raw_id or "").strip()
                if not aid or "/" in aid or "\\" in aid:
                    skipped.append({"id": aid, "msg": "id 不合法"})
                    continue
                with LOCK:
                    t = TASKS.get(aid) or {}
                if t.get("status") in ("写稿中", "配音中", "上传中", "排队中"):
                    skipped.append({"id": aid, "msg": "正在%s" % t.get("status")})
                    continue
                folder = OUTPUT / aid
                if not folder.exists() and not t:
                    skipped.append({"id": aid, "msg": "本地没有这篇"})
                    continue
                if folder.exists():
                    try:
                        shutil.rmtree(folder)
                    except Exception as exc:
                        skipped.append({"id": aid, "msg": "删除失败：%s" % exc})
                        continue
                with LOCK:
                    TASKS.pop(aid, None)
                    if aid in TASK_ORDER:
                        TASK_ORDER.remove(aid)
                removed += 1
            push("批量删除：清掉 %d 篇本地稿，跳过 %d 篇（网盘副本未动）" % (removed, len(skipped)))
            return self._send(200, {"ok": True, "removed": removed, "skipped": skipped})

        return self._send(404, "not found")

    def _opts(self, data):
        cfg = load_config()
        try:
            chars = int(data.get("chars") or cfg["chars"])
        except Exception:
            chars = 400
        try:
            count = int(data.get("count") or cfg["count"])
        except Exception:
            count = 1
        return {
            "grade": data.get("grade") or cfg["grade"],
            "chars": max(80, min(2500, chars)),
            "count": max(1, min(10, count)),
            "topic": (data.get("topic") or "").strip(),
            "do_audio": bool(data.get("do_audio", True)),
            "do_cover": bool(data.get("do_cover", True)),
            "skip_dup": bool(data.get("skip_dup", True)),
            "offline": bool(data.get("offline", False)),
        }


def serve(port=None, open_browser=True):
    port = port or PORT
    boot_scan()
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("阅答题已启动：http://127.0.0.1:%d （关闭窗口即退出）" % port, flush=True)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:%d" % port)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


# ---------------------------------------------------------------- 命令行
def run_cli(args):
    cfg = load_config()
    opts = {
        "grade": args.grade,
        "chars": args.chars or DEFAULT_CHARS.get(args.grade[:2], 400),
        "count": args.count,
        "topic": args.topic,
        "do_audio": not args.no_audio,
        "do_cover": not args.no_cover,
        "skip_dup": not args.no_dup,
        "offline": args.offline,
    }
    log = lambda m: print(m, flush=True)
    made = run_job(cfg, opts, log, threading.Event())
    if args.upload and made:
        ok = 0
        for m in made:
            if upload_one(cfg, m["aid"], log):
                ok += 1
        log("上传完成 %d / %d 篇" % (ok, len(made)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--cli", action="store_true")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--grade", default="小学二年级")
    ap.add_argument("--chars", type=int, default=0)
    ap.add_argument("--topic", default="")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--no-cover", action="store_true")
    ap.add_argument("--no-dup", action="store_true")
    ap.add_argument("--upload", action="store_true", help="命令行模式下生成后直接上传")
    args = ap.parse_args()
    if args.cli:
        run_cli(args)
    else:
        serve(args.port, not args.no_browser)


if __name__ == "__main__":
    main()
