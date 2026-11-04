#!/usr/bin/env python3
"""Promo video renderer — NeuralDeep x Claude Code.

Verified facts (checked against live catalog, gateway /health, services.py on 2026-11-04):
  * 37 unique models: 17 subscription + 32 wallet (Claude 5.5 — wallet only)
  * max context 1 310 720 (GLM 5.3 Flash); Claude Opus/Sonnet/Kimi K3 — 1 000 000
  * gateway http://127.0.0.1:8787, direct upstream api.neuraldeep.ru (direct_network: true)
  * 15 MCP service groups = 14 billing groups + browser (local Playwright)
  * install: git clone -> .env keys -> ./install.sh --activate
"""
import math, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
TMP = HERE / "_frames"
OUT = HERE / "promo.mp4"
FDIR = HERE / "fonts"

W, H, FPS = 1920, 1080, 30
DUR = 36.0
NFR = int(DUR * FPS)

# ---------- palette ----------
BG0, BG1 = (9, 10, 14), (16, 18, 27)
CARD, CARD_HI, BORDER = (21, 24, 34), (29, 33, 46), (46, 51, 68)
TXT, MUT, DIM = (235, 238, 245), (146, 153, 172), (96, 102, 121)
INDG, INDG_LT = (99, 102, 241), (129, 140, 248)
CYAN, GRN, YEL, RED = (34, 211, 238), (74, 222, 128), (250, 204, 21), (248, 113, 113)
CHIP_S, CHIP_W = (62, 200, 130), (232, 178, 60)
SEL_BG = (43, 46, 92)

# ---------- easing ----------
def cl(t, s, e): return max(0.0, min(1.0, (t - s) / max(e - s, 1e-9)))
def eout(t): t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3
def la(a, b, t): return tuple(int(a[i] + (b[i]-a[i]) * t) for i in range(3))

# ---------- fonts ----------
_c = {}
def F(w, s):
    k = (w, s)
    if k not in _c: _c[k] = ImageFont.truetype(str(FDIR / f"Inter-{w}.ttf"), s)
    return _c[k]
def FM(s, med=False):
    k = ("m", s, med)
    if k not in _c: _c[k] = ImageFont.truetype(str(FDIR / f"JetBrainsMono-{'Medium' if med else 'Regular'}.ttf"), s)
    return _c[k]
def tlen(txt, f): return f.getlength(txt)

def T(d, txt, x, y, f, col, an="la"): d.text((x, y), txt, font=f, fill=col, anchor=an)
def RC(d, box, r, fill=None, outline=None, width=1): d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)

# ---------- background ----------
def make_bg():
    strip = Image.new("RGB", (1, H))
    for yy in range(H): strip.putpixel((0, yy), la(BG0, BG1, yy/(H-1)))
    base = strip.resize((W, H))
    def glow_layer(spots):
        g = Image.new("L", (W, H), 0)
        gd = ImageDraw.Draw(g)
        for cx, cy, rad, val in spots:
            gd.ellipse([cx-rad, cy-rad, cx+rad, cy+rad], fill=val)
        return g.filter(ImageFilter.GaussianBlur(110))
    bg = Image.composite(Image.new("RGB", (W, H), INDG), base,
                         glow_layer([(int(W*.5), int(H*.34), 520, 46), (int(W*.5), int(H*.34), 300, 34),
                                     (int(W*.94), int(H*.10), 360, 15)]))
    bg = Image.composite(Image.new("RGB", (W, H), CYAN), bg,
                         glow_layer([(int(W*.07), int(H*.88), 430, 15)]))
    dd = ImageDraw.Draw(bg)
    step = 46
    for yy in range(step//2, H, step):
        for xx in range(step//2, W, step):
            dd.point((xx, yy), fill=(23, 26, 36))
    return bg

def particles(t, alpha=1.0):
    if alpha <= .01: return None
    s = 1234
    def r():
        nonlocal s
        s = (s * 1103515245 + 12345) & 0x7fffffff
        return s / 0x7fffffff
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(30):
        x0, y0 = r()*W, r()*H
        sp = 5 + r()*14
        size = 1.3 + r()*2.0
        col = CYAN if r() < .3 else (INDG_LT if r() < .7 else TXT)
        x = (x0 + math.sin(t*0.22 + i)*16) % W
        y = (y0 - t*sp) % H
        a = int(alpha * (38 + 34*math.sin(t*1.1 + i*1.7)))
        if a <= 2: continue
        rr = int(size)
        ld.ellipse([x-rr, y-rr, x+rr, y+rr], fill=col + (max(0, a),))
    return layer

# ---------- shared pieces ----------
def kicker_title(d, kicker, title, cx, y, t, t0, sub=None, kcol=INDG_LT, tsize=60):
    a = eout(cl(t, t0, t0 + .45))
    if a <= 0: return y
    ay = y + int(16*(1-a))
    fk, ft = F("SemiBold", 21), F("ExtraBold", tsize)
    kw = tlen(kicker.upper(), fk)
    rw = 34
    x0 = cx - (rw + 14 + kw)//2
    d.line([x0, ay+13, x0+rw, ay+13], fill=kcol + (int(255*a),), width=3)
    T(d, kicker.upper(), x0+rw+14, ay-1, fk, kcol + (int(255*a),))
    T(d, title, cx, ay+30, ft, TXT + (int(255*a),), an="ma")
    ny = ay + 30 + tsize + 36
    if sub:
        a2 = eout(cl(t, t0+.25, t0+.7))
        if a2 > 0:
            T(d, sub, cx, ny, F("Regular", 25), MUT + (int(235*a2),), an="ma")
            ny += 44
    return ny

def win_chrome(d, x, y, ww, hh, title):
    RC(d, [x, y, x+ww, y+hh], 18, fill=CARD + (255,), outline=BORDER + (255,), width=1)
    RC(d, [x, y, x+ww, y+46], 18, fill=CARD_HI + (255,))
    d.rectangle([x, y+30, x+ww, y+46], fill=CARD_HI + (255,))
    for i, c in enumerate([(255,95,86),(255,189,46),(39,201,63)]):
        cx = x+26+i*22
        d.ellipse([cx-6, y+17, cx+6, y+29], fill=c)
    T(d, title, x+ww//2, y+14, F("Medium", 17), MUT, an="ma")

def billing_chip(d, txt, x, y, wallet, a=1.0):
    col = CHIP_W if wallet else CHIP_S
    f = F("SemiBold", 16)
    w = tlen(txt, f) + 30
    RC(d, [x, y, x+w, y+30], 15, fill=(col[0]//6, col[1]//6, col[2]//6) + (int(255*a),),
       outline=col + (int(190*a),), width=1)
    T(d, txt, x+w//2, y+15, f, col + (int(245*a),), an="mm")
    return w

# ---------- scenes ----------
def scene_intro(t, bg):
    l = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(l)
    cx = W//2
    a = eout(cl(t, .1, .8))
    y = int(H*0.32) + int(26*(1-a))
    f_big = F("ExtraBold", 92)
    t1, t2 = "NeuralDeep", "Claude Code"
    w1, w2 = tlen(t1, f_big), tlen(t2, f_big)
    fx = F("Regular", 58)
    wm = tlen("  ×  ", fx)
    total = w1 + wm + w2
    x = cx - total/2
    T(d, t1, x, y, f_big, TXT + (int(255*a),))
    a2 = eout(cl(t, .4, 1.05))
    T(d, "×", x + w1 + wm/2, y+16, fx, DIM + (int(255*a2),), an="mm")
    T(d, t2, x + w1 + wm, y, f_big, INDG_LT + (int(255*a2),))
    a3 = eout(cl(t, .75, 1.35))
    T(d, "Локальный шлюз: все модели и сервисы NeuralDeep в Claude Code",
      cx, y+142, F("Regular", 29), MUT + (int(240*a3),), an="ma")
    a4 = eout(cl(t, 1.05, 1.6))
    if a4 > 0:
        chips = [("37 моделей", INDG_LT), ("15 MCP-сервисов", CYAN),
                 ("Linux · Windows · macOS", GRN), ("Python 3.10+", MUT)]
        fc = F("SemiBold", 19)
        ws = [tlen(c, fc) + 38 for c, _ in chips]
        gap = 14
        tot = sum(ws) + gap*(len(chips)-1)
        x = cx - tot/2
        for (c, col), bw in zip(chips, ws):
            RC(d, [x, y+214, x+bw, y+214+42], 21,
               fill=CARD + (int(235*a4),), outline=col + (int(130*a4),), width=1)
            T(d, c, x+bw//2, y+214+21, fc, col + (int(245*a4),), an="mm")
            x += bw + gap
    return [l]

PROBLEM_CARDS = [
    ("Тарифы в долларах",
     "Подписка Claude и оплата токенов в долларах — нужна карта зарубежного банка",
     "money"),
    ("Прокси и посредники",
     "Обход через сторонние сервисы: задержки, риск утечки ключей, нестабильный доступ",
     "proxy"),
    ("Всё по отдельности",
     "Код, картинки, музыка, OCR — отдельные сервисы и отдельные ключи",
     "apps"),
]

def scene_problem(t, bg):
    l = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(l)
    cx = W//2
    kicker_title(d, "Знакомо?", "Барьеры на старте", cx, 104, t, .1)
    cw, ch, gap = 480, 356, 42
    x0 = cx - (cw*3 + gap*2)//2
    cy0 = 300
    fh, fb = F("Bold", 30), F("Regular", 22)
    for i, (h, b, ic) in enumerate(PROBLEM_CARDS):
        a = eout(cl(t, .4+i*.18, .95+i*.18))
        if a <= 0: continue
        x = x0 + i*(cw+gap)
        yy = cy0 + int(22*(1-a))
        RC(d, [x, yy, x+cw, yy+ch], 22, fill=CARD + (int(245*a),),
           outline=BORDER + (int(210*a),), width=1)
        icx, icy = x+40, yy+40
        RC(d, [icx-12, icy-12, icx+52, icy+52], 16, fill=(58, 32, 40) + (int(235*a),))
        s = int(255*a)
        rd = (248, 150, 150, s)
        if ic == "money":
            d.rounded_rectangle([icx, icy+2, icx+40, icy+34], 6, outline=rd, width=3)
            d.ellipse([icx+14, icy+12, icx+26, icy+24], outline=rd, width=3)
            d.line([icx+6, icy+9, icx+10, icy+9], fill=rd[:3], width=2)
            d.line([icx+30, icy+27, icx+34, icy+27], fill=rd[:3], width=2)
        elif ic == "proxy":
            for k in range(3):
                axx, ayy = icx + k*12, icy + 4 + k*12
                d.rounded_rectangle([axx, ayy, axx+14, ayy+12], 4, outline=rd, width=3)
        else:
            for k in range(4):
                axx = icx + (k % 2)*20; ayy = icy + (k//2)*20
                d.rounded_rectangle([axx, ayy, axx+16, ayy+16], 5, outline=rd, width=3)
        T(d, h, x+38, yy+122, fh, TXT + (int(252*a),))
        words, line, ly = b.split(), "", yy+180
        for wd in words:
            if tlen(line + wd, fb) > cw-76:
                T(d, line, x+38, ly, fb, MUT + (int(235*a),)); line = wd + " "; ly += 33
            else: line += wd + " "
        T(d, line, x+38, ly, fb, MUT + (int(235*a),))
    a5 = eout(cl(t, 1.7, 2.2))
    if a5 > 0:
        T(d, "Нужен прямой путь — без долларов, посредников и лишних ключей", cx, 800,
          F("Medium", 27), la(MUT, TXT, .4) + (int(235*a5),), an="ma")
    return [l]

ARCH_NODES = [
    (250, "Claude Code", "CLI и Desktop", "работает по Anthropic API", INDG_LT),
    (770, "Local Gateway", "127.0.0.1:8787", "преобразует запросы", CYAN),
    (1290, "NeuralDeep", "api.neuraldeep.ru", "прямое HTTPS-соединение", GRN),
]
MODEL_ROWS = [
    ("Claude Opus 5.5", 1), ("Claude Sonnet 5.5", 1), ("Kimi K3.1 Pro", 1),
    ("DeepSeek V4 Pro", 1), ("GLM 5.3 Flash", 1), ("MiniMax M2.5", 1),
    ("Qwen 3.8 27B", 0), ("GPT-OSS 120B", 0),
]
SERVICE_TILES = [
    ("Поиск", "web · crawl"), ("OCR", "PDF / IMG"), ("Изображения", "image_generate"),
    ("Музыка", "Lyria"), ("TTS", "speak"), ("Транскрипция", "аудио→текст"),
    ("Диаризация", "разделение голосов"), ("Эмбеддинги", "e5-large"), ("Rerank", "релевантность"),
    ("PII", "обезличивание"), ("Decisions", "выбор варианта"), ("Drift", "агенты"),
    ("Book", "книги"), ("SpeechCore", "совещания"), ("Browser", "Playwright"),
]

def scene_arch(t, bg):
    l = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(l)
    cx = W//2
    kicker_title(d, "Как это работает", "Один локальный шлюз", cx, 104, t, .1)
    nw, nh, ny0 = 380, 200, 330
    for i, (nx, ttl, l1, l2, col) in enumerate(ARCH_NODES):
        a = eout(cl(t, .3+i*.2, .8+i*.2))
        if a <= 0: continue
        x = nx; yy = ny0 + int(18*(1-a))
        RC(d, [x, yy, x+nw, yy+nh], 20, fill=CARD + (int(248*a),),
           outline=BORDER + (int(225*a),), width=1)
        RC(d, [x, yy, x+nw, yy+5], 3, fill=col + (int(215*a),))
        d.ellipse([x+28, yy+36, x+46, yy+54], outline=col + (int(245*a),), width=3)
        d.ellipse([x+34, yy+42, x+40, yy+48], fill=col + (int(245*a),))
        T(d, ttl, x+60, yy+32, F("Bold", 27), TXT + (int(252*a),))
        T(d, l1, x+28, yy+92, FM(19, med=True), la(TXT, MUT, .15) + (int(235*a),))
        T(d, l2, x+28, yy+132, FM(17), MUT + (int(225*a),))
    arrows = [(250+nw+14, 770-14), (770+nw+14, 1290-14)]
    labs = ["/v1/messages", "chat/completions"]
    for ai, (ax0, ax1) in enumerate(arrows):
        a = eout(cl(t, 1.0+ai*.3, 1.5+ai*.3))
        if a <= 0: continue
        ay = ny0 + nh//2
        T(d, labs[ai], (ax0+ax1)//2, ay-44, FM(17), DIM + (int(220*a),), an="ma")
        x1 = ax0 + int((ax1-ax0)*a)
        d.line([ax0, ay, x1, ay], fill=BORDER + (255,), width=3)
        if a > .97:
            d.polygon([(ax1, ay-8), (ax1+12, ay), (ax1, ay+8)], fill=BORDER + (255,))
            pp = (t*0.5 + ai*0.5) % 1.0
            pxp = ax0 + (ax1-ax0)*pp
            d.ellipse([pxp-5, ay-5, pxp+5, ay+5],
                      fill=(INDG_LT if ai == 0 else GRN) + (235,))
    a_lg = eout(cl(t, 1.7, 2.2))
    if a_lg > 0:
        items = [("Подписка", CHIP_S, "фиксированный тариф · 17 моделей"),
                 ("Кошелёк", CHIP_W, "оплата за токены · 32 модели"),
                 ("Маршрутизация", INDG_LT, "одна модель = один канал оплаты")]
        lw2, lh2 = 500, 100
        tot = lw2*3 + 32*2
        lx = cx - tot//2; ly2 = 640
        for i, (ttl, col, desc) in enumerate(items):
            x = lx + i*(lw2+32)
            RC(d, [x, ly2, x+lw2, ly2+lh2], 16, fill=CARD + (int(238*a_lg),),
               outline=BORDER + (int(180*a_lg),), width=1)
            d.ellipse([x+24, ly2+28, x+44, ly2+48], fill=col + (int(245*a_lg),))
            T(d, ttl, x+60, ly2+20, F("Bold", 23), col + (int(252*a_lg),))
            T(d, desc, x+60, ly2+56, F("Regular", 19), MUT + (int(225*a_lg),))
        T(d, "Без сторонних зависимостей: нужен только Python 3.10+", cx, 800,
          F("Medium", 24), la(MUT, TXT, .3) + (int(220*a_lg),), an="ma")
    return [l]

def scene_models(t, bg):
    l = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(l)
    cx = W//2
    kicker_title(d, "Каталог", "37 моделей в одном списке", cx, 104, t, .1,
                 sub="Общий список подписки и кошелька · обновление: ./update-models.sh")
    a = eout(cl(t, .3, .8))
    if a > 0:
        ww, hh = 1020, 452
        x0 = 170; y0 = 302
        win_chrome(d, x0, y0, ww, hh, "claude /model")
        f_m = F("Medium", 24)
        ry, rowh = y0+60, 47
        sel = int(((t-0.5)*0.9) % len(MODEL_ROWS))
        for ri, (mn, wal) in enumerate(MODEL_ROWS):
            ar = eout(cl(t, .45+ri*.07, .85+ri*.07))
            if ar <= 0: continue
            yy = ry + ri*rowh
            if ri == sel:
                RC(d, [x0+10, yy, x0+ww-10, yy+rowh-5], 10, fill=SEL_BG + (255,))
                d.rectangle([x0+10, yy+4, x0+14, yy+rowh-9], fill=INDG_LT + (255,))
            T(d, mn, x0+34, yy+9, f_m, (TXT if ri == sel else la(TXT, MUT, .4)) + (int(252*ar),))
            billing_chip(d, "КОШЕЛЁК" if wal else "ПОДПИСКА", x0+ww-176, yy+6, bool(wal), ar)
    a2 = eout(cl(t, .8, 1.35))
    if a2 > 0:
        rw2, rh2 = 480, 452
        rx = 170 + 1020 + 36; ry0 = 302
        RC(d, [rx, ry0, rx+rw2, ry0+rh2], 18, fill=CARD + (int(250*a2),),
           outline=BORDER + (int(205*a2),), width=1)
        T(d, "Контекст — до", rx+rw2//2, ry0+36, F("Medium", 22), MUT + (int(240*a2),), an="ma")
        T(d, "1 310 720", rx+rw2//2, ry0+78, F("ExtraBold", 54), INDG_LT + (int(255*a2),), an="ma")
        T(d, "GLM 5.3 Flash · Claude Opus/Sonnet 5.5 · Kimi K3",
          rx+rw2//2, ry0+158, F("Regular", 19), MUT + (int(225*a2),), an="ma")
        d.line([rx+36, ry0+210, rx+rw2-36, ry0+210], fill=BORDER + (int(210*a2),), width=1)
        T(d, "Effort — low → max", rx+rw2//2, ry0+236, F("Bold", 26), TXT + (int(252*a2),), an="ma")
        lvls = ["low", "med", "high", "xhigh", "max"]
        bw2 = (rw2-100)//5
        bx = rx+50
        lit = ((t-0.5)*1.5) % 5.9
        for i, lv in enumerate(lvls):
            on = lit > i
            RC(d, [bx+i*bw2+4, ry0+296, bx+(i+1)*bw2-4, ry0+322], 8,
               fill=(INDG_LT if on else (58, 62, 82)) + (int(242*a2),))
            T(d, lv, bx+i*bw2+bw2//2, ry0+334, F("Medium", 15),
              (MUT if on else DIM) + (int(220*a2),), an="ma")
        T(d, "там, где модель это поддерживает", rx+rw2//2, ry0+378, F("Regular", 17), DIM + (int(210*a2),), an="ma")
    return [l]

def scene_services(t, bg):
    l = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(l)
    cx = W//2
    kicker_title(d, "Сервисы", "15 MCP-сервисов по запросу", cx, 104, t, .1,
                 sub="Включайте только нужное: выключенный сервис не попадает в список инструментов")
    cols, rows = 5, 3
    gw, gh, gap = 300, 148, 24
    x0 = cx - (gw*cols + gap*(cols-1))//2
    y0 = 312
    for si, (ttl, sub2) in enumerate(SERVICE_TILES):
        ri, ci = divmod(si, cols)
        a = eout(cl(t, .4+si*.05, .85+si*.05))
        if a <= 0: continue
        x = x0 + ci*(gw+gap)
        yy = y0 + ri*(gh+gap) + int(14*(1-a))
        RC(d, [x, yy, x+gw, yy+gh], 18, fill=CARD + (int(247*a),),
           outline=BORDER + (int(195*a),), width=1)
        col = [CYAN, INDG_LT, GRN][si % 3]
        d.ellipse([x+24, yy+28, x+38, yy+42], fill=col + (int(245*a),))
        T(d, ttl, x+52, yy+22, F("Bold", 24), TXT + (int(252*a),))
        T(d, sub2, x+26, yy+74, FM(17), MUT + (int(225*a),))
    a2 = eout(cl(t, 1.75, 2.25))
    if a2 > 0:
        T(d, "scripts/nd.py services enable all · disable music images", cx,
          y0 + rows*(gh+gap) + 34, FM(20), la(MUT, TXT, .25) + (int(225*a2),), an="ma")
    return [l]

def scene_install(t, bg):
    L = []
    l = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(l)
    cx = W//2
    kicker_title(d, "Установка", "Три команды до запуска", cx, 104, t, .1)
    L.append(l)
    tw2, th2 = 980, 396
    x0 = 170; y0 = 300
    tt = max(0.0, t - .55)
    win_chrome(d, x0, y0, tw2, th2, "terminal — Linux / macOS")
    f = FM(21, med=True)
    px, py, lh = x0+34, y0+66, 46
    lines = [
        ("cmd", "git clone https://github.com/bethrezen/neuraldeep-claude.git"),
        ("dim", "cp .env.example .env   # ключи подписки и кошелька"),
        ("cmd", "./install.sh --activate"),
        ("ok",  "✓ gateway: http://127.0.0.1:8787 · direct_network: true"),
    ]
    budget = int(tt*54)
    for kind, s in lines:
        if kind == "cmd":
            if budget <= 0:
                if int(t*2.6) % 2 == 0:
                    d.rectangle([px, py+2, px+11, py+28], fill=CYAN + (210,))
                break
            n = min(len(s), budget)
            T(d, "❯", px-26, py, f, CYAN)
            T(d, s[:n], px, py, f, TXT)
            budget -= n
            if n == len(s): py += lh
            else:
                if int(t*2.6) % 2 == 0:
                    cxp = px + tlen(s[:n], f) + 4
                    d.rectangle([cxp, py+2, cxp+11, py+28], fill=CYAN + (210,))
                break
        else:
            if budget <= 0: break
            budget -= 2
            col = {"ok": GRN, "dim": MUT}.get(kind, TXT)
            T(d, s, px, py, f, col)
            py += lh
    a2 = eout(cl(t, .6, 1.2))
    if a2 > 0:
        rx = x0 + tw2 + 36; rw2 = 500
        RC(d, [rx, y0, rx+rw2, y0+th2], 18, fill=CARD + (int(250*a2),),
           outline=BORDER + (int(205*a2),), width=1)
        T(d, "Ключи — только в .env", rx+28, y0+24, F("Bold", 23), TXT + (int(252*a2),))
        opts = [("Windows", ".\\install.ps1 --activate"),
                ("любая ОС", "python3 scripts/nd.py install --activate"),
                ("Desktop", "scripts/nd.py desktop launch")]
        yy = y0+76
        for ttl, cmd in opts:
            RC(d, [rx+24, yy, rx+rw2-24, yy+92], 12, fill=CARD_HI + (int(238*a2),))
            T(d, ttl, rx+42, yy+12, F("SemiBold", 20), MUT + (int(235*a2),))
            T(d, cmd, rx+42, yy+46, FM(17), INDG_LT + (int(235*a2),))
            yy += 106
    return L

def scene_showcase(t, bg):
    l = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(l)
    cx = W//2
    kicker_title(d, "В работе", "Привычный claude — просто мощнее", cx, 104, t, .1)
    tw2, th2 = 1400, 470
    x0 = cx - tw2//2; y0 = 292
    win_chrome(d, x0, y0, tw2, th2, "claude — qwen3.8-27b [ПОДПИСКА]")
    a = eout(cl(t, .35, .75))
    if a > 0:
        q = "нарисуй схему архитектуры и озвучь отчёт"
        f_q = F("Medium", 23)
        bw2, bh2 = tlen(q, f_q) + 44, 50
        ux = x0 + tw2 - 36
        RC(d, [ux-bw2, y0+70, ux, y0+70+bh2], 14, fill=SEL_BG + (int(255*a),))
        T(d, q, ux-bw2+22, y0+70+12, f_q, TXT + (int(255*a),))
    a2 = eout(cl(t, .85, 1.3))
    if a2 > 0:
        ty = y0 + 148
        RC(d, [x0+30, ty, x0+tw2-30, ty+54], 12, fill=CARD_HI + (int(242*a2),),
           outline=BORDER + (int(185*a2),), width=1)
        d.ellipse([x0+50, ty+19, x0+66, ty+35], fill=CYAN + (int(245*a2),))
        T(d, "tool_call", x0+80, ty+16, FM(19, med=True), CYAN + (int(245*a2),))
        T(d, "neuraldeep-images.image_generate  ·  neuraldeep-tts.speak",
          x0+200, ty+16, FM(19), la(TXT, MUT, .25) + (int(238*a2),))
        if t < 2.1:
            dots = "." * (int(t*3) % 4)
            T(d, "выполняется" + dots, x0+tw2-46, ty+27, F("Medium", 18), MUT + (int(235*a2),), an="rm")
        else:
            T(d, "✓ готово: 2 файла", x0+tw2-46, ty+27, F("Medium", 18), GRN + (int(240*a2),), an="rm")
    a3 = cl(t, 1.45, 2.7)
    if a3 > 0:
        resp = ["Схема нарисована, озвучка собрана.",
                "Модель и способ оплаты выбраны из каталога автоматически."]
        yy = y0 + 232
        f_r = F("Regular", 24)
        budget = int(a3 * sum(len(r) for r in resp))
        for r in resp:
            if budget <= 0: break
            n = min(len(r), budget); budget -= n
            T(d, r[:n], x0+34, yy, f_r, TXT + (245,))
            if n == len(r): yy += 42
            else:
                if int(t*2.6) % 2 == 0:
                    cxp = x0 + 34 + tlen(r[:n], f_r) + 4
                    d.rectangle([cxp, yy+2, cxp+11, yy+28], fill=INDG_LT + (210,))
                break
    a4 = eout(cl(t, 2.4, 2.9))
    if a4 > 0:
        T(d, "Поиск, OCR, музыка и транскрипция — те же tool_call, без единого прокси",
          cx, y0+th2+52, F("Medium", 25), la(MUT, TXT, .35) + (int(235*a4),), an="ma")
    return [l]

def scene_cta(t, bg):
    L = []
    cx = W//2
    my = int(H*0.24)
    glow = Image.new("RGBA", (W, H), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    a0 = eout(cl(t, .1, 1.0))
    gd.ellipse([cx-190, my+59-190, cx+190, my+59+190], fill=INDG + (int(70*a0),))
    L.append(glow.filter(ImageFilter.GaussianBlur(70)))
    l = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(l)
    L.append(l)
    msz = 118; mx = cx - msz//2
    RC(d, [mx, my, mx+msz, my+msz], 30, fill=INDG + (int(255*a0),))
    ink = (22, 24, 38)
    d.line([mx+43, my+45, mx+75, my+75], fill=ink + (int(255*a0),), width=6)
    d.ellipse([mx+32, my+32, mx+54, my+54], fill=ink + (int(255*a0),))
    d.ellipse([mx+66, my+66, mx+88, my+88], fill=ink + (int(255*a0),))
    d.ellipse([mx+70, my+28, mx+86, my+44], fill=ink + (int(230*a0),))
    a1 = eout(cl(t, .35, 1.0))
    T(d, "NeuralDeep × Claude Code", cx, my+msz+34, F("ExtraBold", 64), TXT + (int(255*a1),), an="ma")
    a2 = eout(cl(t, .6, 1.15))
    T(d, "Все модели и сервисы NeuralDeep · установка за три команды", cx, my+msz+130,
      F("Regular", 28), MUT + (int(240*a2),), an="ma")
    a3 = eout(cl(t, .9, 1.4))
    if a3 > 0:
        url = "github.com/bethrezen/neuraldeep-claude"
        fu = F("SemiBold", 28)
        bw2, bh2 = tlen(url, fu) + 88, 72
        bx = cx - bw2//2; by = my + msz + 200
        RC(d, [bx, by, bx+bw2, by+bh2], bh2//2, fill=INDG + (int(255*a3),))
        T(d, url, cx, by+bh2//2-1, fu, TXT + (int(255*a3),), an="mm")
    return L

SCENES = [
    (0.0,  4.5,  scene_intro),
    (4.5,  9.0,  scene_problem),
    (9.0,  14.0, scene_arch),
    (14.0, 19.0, scene_models),
    (19.0, 23.5, scene_services),
    (23.5, 28.0, scene_showcase),
    (28.0, 32.0, scene_install),
    (32.0, 36.0, scene_cta),
]
XFADE = 0.4

def compose(bg_base, fn, t_abs, s):
    layers = fn(t_abs - s, bg_base)
    img = bg_base.copy()
    p = particles(t_abs)
    if p: img.paste(p, (0, 0), p)
    for lyr in layers:
        if lyr: img.paste(lyr, (0, 0), lyr)
    return img

if __name__ == "__main__":
    print("Background…", file=sys.stderr, flush=True)
    bg_base = make_bg()
    TMP.mkdir(exist_ok=True)
    for f in TMP.glob("*.png"): f.unlink()
    print(f"Rendering {NFR} frames @ {FPS}fps…", file=sys.stderr, flush=True)
    for i in range(NFR):
        t = i / FPS
        cur_i = len(SCENES) - 1
        for si, (s, e, fn) in enumerate(SCENES):
            if s <= t < e:
                cur_i = si; break
        s, e, fn = SCENES[cur_i]
        img = compose(bg_base, fn, t, s)
        for si, (s2, e2, fn2) in enumerate(SCENES[:-1]):
            if e2 - XFADE <= t < e2:
                s3, e3, fn3 = SCENES[si+1]
                img2 = compose(bg_base, fn3, t, s3)
                img = Image.blend(img, img2, eout(1 - (e2 - t)/XFADE))
                break
        img.save(TMP / f"frame_{i:04d}.png", "PNG")
        if i % 90 == 0:
            print(f"  {i}/{NFR} ({i*100//NFR}%)", file=sys.stderr, flush=True)
    print("Encoding…", file=sys.stderr, flush=True)
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS),
                    "-i", str(TMP/"frame_%04d.png"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
                    "-movflags", "+faststart", str(HERE/"_video_noaudio.mp4")],
                   check=True, capture_output=True)
    mus = HERE/"bgmusic.mp3"
    if mus.exists():
        subprocess.run(["ffmpeg", "-y", "-i", str(HERE/"_video_noaudio.mp4"),
                        "-i", str(mus), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart", str(OUT)],
                       check=True, capture_output=True)
        (HERE/"_video_noaudio.mp4").unlink()
    else:
        (HERE/"_video_noaudio.mp4").rename(OUT)
    print(f"Done! {OUT} ({OUT.stat().st_size/1e6:.1f} MB)", file=sys.stderr, flush=True)
