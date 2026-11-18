# -*- coding: utf-8 -*-
"""童阅写稿器：生成文章（文字 + 封面 + 逐句音频），确认后再上传夸克盘。

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
import shutil
import sys
import threading
import time
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
PORT = int(os.environ.get("KIDSWRITER_PORT") or 8122)

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
    task_new(aid, grade, topic)
    log("")
    log("=== %s ｜ 主题「%s」｜ 目标 %d 字 ===" % (aid, topic[:24], chars))
    task_set(aid, status="写稿中", step="生成大纲", progress=0)

    title = body = ""
    if opts.get("offline"):
        title, body = offline_article(grade, topic, chars)
        log("  离线模板成稿（未调 AI）")
        task_set(aid, step="模板拼稿", progress=90)
    else:
        avoid = "、".join(titles[:30])
        try:
            title, body = write_long(cfg, grade, topic, chars, avoid, log,
                                     on_step=lambda s, p: task_set(aid, step=s, progress=p))
            if count_chars(body) < chars * 0.8:
                log("  篇幅只有 %d 字，改为整篇重新生成" % count_chars(body))
                task_set(aid, step="整篇重写", progress=50)
                title, body = write_once(cfg, grade, topic, chars, avoid, log)
        except Exception as exc:
            log("  分段生成失败：%s，改为整篇生成" % exc)
            for attempt in range(3):
                try:
                    task_set(aid, step="整篇生成 %d/3" % (attempt + 1))
                    title, body = write_once(cfg, grade, topic, chars, avoid, log)
                    break
                except Exception as e2:
                    log("  第 %d 次不合法：%s" % (attempt + 1, e2))
                    time.sleep(1)
        if not body:
            task_set(aid, status="失败", step="写稿失败", error="连续生成失败")
            log("  放弃这一篇：连续生成失败")
            return None

    body = ensure_tail(body)
    sents = split_sentences(body)
    if not sents:
        task_set(aid, status="失败", step="没有可用句子", error="切句为空")
        log("  放弃这一篇：正文没有可用句子")
        return None

    task_set(aid, title=title, chars=count_chars(body), sents=len(sents),
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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
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
            return self._send(200, {
                "server": cfg["server"], "user": cfg["user"], "password": cfg["password"],
                "grade": cfg["grade"], "chars": cfg["chars"], "count": cfg["count"],
                "voice": cfg["voice"], "rate": cfg["rate"], "root": cfg["root"],
                "covers": len(cover_pool()), "port": PORT,
            })
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
    print("童阅写稿器已启动：http://127.0.0.1:%d （关闭窗口即退出）" % port, flush=True)
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
