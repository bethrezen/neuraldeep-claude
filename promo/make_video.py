#!/usr/bin/env python3
"""
Promo video: NeuralDeep × Claude Code.
Single-canvas approach — draw background + all cards on ONE RGB Image.
Style reference: Linear.app / Vercel dark theme.
"""
from __future__ import annotations
import math, shutil, subprocess, random, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FPS = 30
NFRAMES = FPS * 30   # 30 sec
OUT = Path(__file__).parent / "promo.mp4"
TMP = Path(__file__).parent / "_tf"
random.seed(42)

# ── Palette ──
BG     = (12, 12, 16)
SURF   = (22, 22, 30)
BRDR   = (55, 55, 70)
INDG   = (99, 102, 241)
CYAN   = (6, 182, 212)
PURP   = (139, 92, 246)
GRN    = (34, 197, 94)
YLW    = (234, 179, 8)
RED    = (239, 68, 68)
WH     = (232, 235, 239)
DM     = (148, 163, 184)
FN     = (80, 80, 100)
MX = 80; TP = 60

def lr(a,b,t): return a+(b-a)*max(0.0,min(1.0,t))
def eu(t): return 1-(1-t)**3
def cl(t,s,e): return max(0.,min(1.,(t-s)/max(e-s,1e-9))) if e>s else 1.

def lf(sz, bd=False):
    try: return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", sz) if bd else ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", sz)
    except: return ImageFont.load_default()

FT=lf(54,True); FS=lf(26); FB=lf(22); FM=lf(20); MS=lf(14)

def tw(text, font=None):
    if not font: return len(text)*10, 20
    try:
        bb=font.getmask(text,"RGBA").getbbox()
        if bb: return bb[2]-bb[0], bb[3]-bb[1]
    except: pass
    return len(text)*10, 20

def ct(draw,text,y,font,col=WH):
    w,_=tw(text,font); draw.text(((W-w)//2,y),text,font=font,fill=col)
def pt(draw,text,x,y,font,col=WH):
    draw.text((x,y),text,font=font,fill=col)
def rr(draw,xy,radius,fill,outline=None,width=1):
    draw.rounded_rectangle(xy,radius=radius,fill=fill,outline=outline,width=width)

# ════════════════════════
def build():
    TMP.mkdir(exist_ok=True)
    print("Rendering frames...", file=sys.stderr, flush=True)

    secs={"I":(0,4),"P":(4,8),"A":(8,15),"S":(15,21),"C":(21,27.5),"T":(27.5,30)}

    for i in range(NFRAMES):
        if i%30==0: print(f"  {i}/{NFRAMES} ({int(i/NFRAMES*100)}%)", file=sys.stderr, flush=True)
        t=i/FPS

        img=Image.new("RGB",(W,H),BG); d=ImageDraw.Draw(img)

        # ── BG: radial gradient ──
        cx=W//2+int(60*math.sin(i*0.007)); cy=H//2-60+int(30*math.cos(i*0.01))
        rm=380+int(40*math.sin(i*0.004))
        for rad in range(rm,rm-300,30):
            br=int(lr(BG[0]+8,BG[0]+15,1-abs(rad-rm+150)/150))
            col=tuple(max(0,min(255,c+br-BG[0])) for c in INDG)
            d.ellipse([cx-rad,cy-rad,cx+rad,cy+rad],fill=col)
        cs=W*.72+int(80*math.sin(i*0.012)); chs=H*.65+int(50*math.cos(i*0.01))
        rs2=200+int(30*math.sin(i*0.006))
        for rad in range(rs2,rs2-200,25):
            br=int(lr(2,8,1-abs(rad-rs2+100)/100))
            col=tuple(max(0,min(255,c//4+br)) for c in CYAN)
            d.ellipse([cs-rad,chs-rad,cs+rad,chs+rad],fill=col)
        sp=80;dof=(i*0.3)%sp; dof2=(i*0.2)%sp
        for xx in range(int(-sp+dof),W+sp,sp):
            for yy in range(int(-sp+dof2),H+sp,sp):
                d.ellipse([xx,yy,xx+1.5,yy+1.5],fill=tuple(c//3 for c in BRDR))
        np2=30
        for pi in range(np2):
            ang=pi*6.28/np2+i*0.006; rp=250+pi*8
            px=W//2+int(rp*math.cos(ang)*.7); py=H//2-60+int(rp*math.sin(ang)*.45)
            pr=1+int(math.sin(pi*1.5+i*0.04))
            pc=[INDG,CYAN,PURP][pi%3]; bp=int(lr(150,240,.5+.5*math.sin(i*.025+pi)))
            d.ellipse([px-pr,py-pr,px+pr,py+pr],fill=tuple(min(255,c//3+bp//2) for c in pc))

        it=cl(t,*secs["I"]); ie=eu(it)
        if ie>0:
            lg=int(45*ie)
            if lg>5:
                lx=W//2-lg; ly=H//2-170-lg; lw2=W//2+lg; lh2=H//2-170+lg
                mc=tuple(int(lr(SURF[c],INDG[c],.18)) for c in range(3))
                d.ellipse([lx,ly,lw2,lh2],fill=mc)
                d.ellipse([lx+2,ly+2,lw2-2,lh2-2],outline=tuple(c//2+40 for c in CYAN),width=2)
                nf=lf(max(12,lg)); nw,nh=tw("N",nf)
                pt(d,"N",W//2-nw//2,H//2-170-nh//2+4,nf,WH)
            if ie>.2:
                tt=eu(cl(ie,.2,.5)); ty=H//2-75-int(40*(1-tt))
                ct(d,"NeuralDeep × Claude Code",ty,FT,(int(240*tt),))
            if ie>.35:
                tt2=eu(cl(ie,.35,.6)); ty=H//2-25-int(20*(1-tt2))
                ct(d,"Локальный шлюз · Все модели NeuralDeep · Без прокси",ty,FS,(int(200*tt2),))
            if ie>.5:
                bt=eu(cl(ie,.5,.75))
                for ti,(tl,tc,bc) in enumerate([("Python 3.10+",GRN,FN),("Zero dependencies",CYAN,FN),("Linux · Win · macOS",PURP,FN)]):
                    ta=eu(cl(bt,ti*.12,ti*.12+.15))
                    if ta<=0: continue
                    bw=len(tl)*13+24; y=H//2+18-int(15*(1-ta))
                    rr(d,[MX*3+ti*250,y,MX*3+ti*250+bw,y+26],radius=8,fill=bc)
                    pt(d,tl,MX*3+ti*250+10,y+5,MS,(int(240*ta),))

        pt_=cl(t,*secs["P"]); pe=eu(pt_)
        if pe>0:
            hs=int(60*(1-pe))
            rr(d,[MX,TP+10-hs+20,W-MX,TP+50-hs+20],radius=12,fill=(RED[0]//6,RED[1]//6,RED[2]//6),outline=(RED[0]//3,RED[1]//3,RED[2]//3),width=1)
            ct(d,"❌ Проблема",TP+25-hs+20,FT,(int(240*pe),))
            ct_2=TP+80; ch=260
            rr(d,[MX,ct_2,W-MX,ct_2+ch],radius=16,fill=SURF,outline=BRDR,width=1)
            for li,lp in enumerate(["Claude Code работает только через OpenAI API","Российские модели недоступны","Прокси замедляет и небезопасен"]):
                la=eu(cl(pe,.08+li*.2,.22+li*.2))
                if la<=0: continue
                ly_b=ct_2+45+li*70
                rr(d,[MX+24,ly_b+2,MX+27,ly_b+30],radius=2,fill=(RED[0]//2,RED[1]//2,RED[2]//2))
                pt(d,f"{lp}",MX+40,ly_b,FB,(int(200*la),))

        ac=cl(t,*secs["A"]); ae=eu(ac)
        if ae>0:
            ct(d,"✅ Решение",TP+20,FT,(int(240*ae),))
            nd=[(340,225,"Claude\nCode CLI",GRN),(960,225,"NeuralDeep\nGateway",INDG),(1580,225,"NeuralDeep\nAPI",CYAN)]
            ai2=["OpenAI format","","Direct HTTPS"]
            for ni,(nx,ny,nl,nc) in enumerate(nd):
                na=eu(cl(ae,.06+ni*.2,.2+ni*.2))
                if na<=0: continue
                nbw=220;nbh=120;bx=nx-nbw//2;by=ny-nbh//2
                rr(d,[bx,by,bx+nbw,by+nbh],radius=14,fill=SURF,outline=tuple(c//2+30 for c in nc),width=2)
                nly=by+22
                for nli,nll in enumerate(nl.split("\n")):
                    nf2=lf(20 if nli==0 else 16);nw,_=tw(nll,nf2)
                    pt(d,nll,nx-nw//2,nly,nf2,tuple(nc));nly+=28
                if ai2[ni] and ni < len(nd)-1:
                    aa=eu(cl(ae,.35+ni*.12,.5+ni*.12))
                    if aa>0:
                        ax_s2=nx+nbw//2
                        nx_next=nd[ni+1][0]; nbw_next=220
                        ax_e2=nx_next-nbw_next//2
                        ay_a=ny
                        d.line([(ax_s2,ay_a),(ax_e2,ay_a)],fill=tuple(c//3 for c in INDG),width=2)
                        alw,_=tw(ai2[ni],MS)
                        pt(d,ai2[ni],(ax_s2+ax_e2)//2-alw//2,ay_a+20,MS,(int(170*aa),))

            if ae>.6:
                dt2=["• Модель роутинг через каталог","• billing: подписка ($) / кошелёк (₽)","• Effort & thinking по семействам","• Прямой HTTPS, без прокси"]
                dy=400
                for di,dst in enumerate(dt2):
                    da=eu(cl(ae,.65+di*.08,.75+di*.08))
                    if da<=0: continue
                    d.ellipse([MX,dy+di*38-3,MX+3,dy+di*38+3],fill=INDG)
                    pt(d,dst,MX+14,dy+di*38,FB,(int(180*da),))

        ic=cl(t,*secs["S"]); ist=eu(ic)
        if ist>0:
            ct(d,"📦 Установка за 3 команды",TP+20,FT,(int(240*ist),))
            tw2=1200;th2=310;tx2=(W-tw2)//2;ty2=TP+85
            rr(d,[tx2,ty2,tx2+tw2,ty2+th2],radius=12,fill=SURF,outline=BRDR,width=1)
            rr(d,[tx2,ty2,tx2+tw2,ty2+34],radius=12,fill=tuple(c+6 for c in SURF))
            for di,wc in enumerate([RED,YLW,GRN]):d.ellipse([tx2+tw2-24-di*16,ty2+9,tx2+tw2-12-di*16,ty2+21],fill=wc)
            pt(d,"~ ❯ neuraldeep",tx2+14,ty2+20,MS,DM)
            cmds=["$ git clone https://github.com/user/neuraldeep-claude.git","$ cp .env.example .env  # ← ключи подписки и кошелька","$ ./install.sh --activate","","✅ Gateway запущен на http://127.0.0.1:8787"]
            cy2=ty2+52
            for ci,cmd_t in enumerate(cmds):
                ca=eu(cl(ist,ci*.12,(ci+1)*.15))
                if ca<=0:continue
                cc=GRN if "✅" in cmd_t else WH
                pt(d,cmd_t,tx2+18,cy2+ci*44,FM,cc)
            if ist>.7:
                sa=eu(cl(ist,.7,.85));sl_y=cy2+5*44+10
                rr(d,[tx2+18,sl_y,tx2+160,sl_y+20],radius=6,fill=GRN)
                pt(d,"✓ Активно",tx2+26,sl_y+4,MS,WH)

        sh=cl(t,*secs["C"]); ds=eu(sh)
        if ds>0:
            ct(d,"🚀 Работайте как раньше — просто мощнее",TP+20,FT,(int(240*ds),))
            mp_x=MX;mp_y=TP+95;mp_w=(W//2)-MX;mp_h=350
            rr(d,[mp_x,mp_y,mp_x+mp_w,mp_y+mp_h],radius=14,fill=SURF,outline=tuple(c//2+30 for c in INDG),width=1)
            pt(d,"📋 Доступные модели:",mp_x+20,mp_y+18,FT,tuple(INDG))
            models=[("Qwen 3.8 27B","ПОДПИСКА",GRN),("GPT-OSS 120B","₽ КОШЕЛЁК",YLW),("DeepSeek V4","₽ КОШЕЛЁК",YLW),("GLM 5.3 Flash","₽ КОШЕЛЁК",YLW),("Kimi K3 Pro","₽ КОШЕЛЁК",YLW)]
            my_m=mp_y+58
            for mi,(mn,mb,mc) in enumerate(models):
                ma=eu(cl(ds,mi*.06,mi*.06+.08))
                if ma<=0:continue
                isel=mi==0;rh=40
                if isel:rr(d,[mp_x+8,my_m,mp_x+mp_w-8,my_m+rh],radius=8,fill=tuple(c//3+8 for c in INDG))
                ic2=GRN if isel else DM
                pt(d,f"{' 'if not isel else ''}{mn}",mp_x+22,my_m+16,FM,ic2)
                pt(d,mb,mp_x+mp_w-180,my_m+16,FM,tuple(mc)[:3] if isinstance(mc,tuple) else mc)
                my_m+=rh+6
            sp_x=W//2+20;sp_y=TP+95;sp_w=(W//2)-MX;sp_h=350
            rr(d,[sp_x,sp_y,sp_x+sp_w,sp_y+sp_h],radius=14,fill=SURF,outline=tuple(c//3+40 for c in CYAN),width=1)
            pt(d,"🔧 Модульные сервисы:",sp_x+20,sp_y+18,FT,tuple(CYAN))
            svcs=["Search","OCR PDF/IMG","Images","Music","TTS Voice","Transcription","Embeddings","Rerank","PII Anonymize","Drift Agent","Browser MCP"]
            sc=[GRN,CYAN,PURP,YLW,GRN,CYAN,INDG,PURP,GRN,CYAN,YLW]
            svm=sp_y+58;scols=3
            for si,sn in enumerate(svcs):
                ssa=eu(cl(ds,.06+si*.025,.1+si*.025))
                if ssa<=0:continue
                sx3=sp_x+12+(si%scols)*((sp_w-24)//scols);sy3=svm+(si//scols)*40
                sw2=(sp_w-24)//scols-24;sh3=30
                rr(d,[sx3,sy3,sx3+sw2,sy3+sh3],radius=7,fill=tuple(c//4+15 for c in sc[si]))
                pt(d,f"● {sn}",sx3+10,sy3+10,MS,WH)

        ca2=cl(t,*secs["T"]);cta=eu(ca2)
        if cta>0:
            tnw,_=tw("Откройте проект на GitHub",FT)
            pt(d,"Откройте проект на GitHub",(W-tnw//2)-40,H//2-30,FT,(int(240*cta),))

        img.save(TMP/f"frame_{i:04d}.png","PNG")

    print(f"\n{NFRAMES} frames done. Encoding…", file=sys.stderr, flush=True)
    subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",str(TMP/"frame_%04d.png"),
                     "-c:v","libx264","-pix_fmt","yuv420p","-preset","medium","-crf","18",
                     "-movflags","+faststart",str(OUT.with_suffix(".noaudio.mp4"))],check=True,capture_output=True)
    music=Path(__file__).parent/"bgmusic.mp3"
    if music.exists():
        subprocess.run(["ffmpeg","-y","-i",str(OUT.with_suffix(".noaudio.mp4")),"-i",str(music),
                         "-c:v","copy","-c:a","aac","-b:a","192k","-shortest",
                         "-movflags","+faststart",str(OUT)],check=True,capture_output=True)
        OUT.with_suffix(".noaudio.mp4").unlink()
    else:
        OUT.with_suffix(".noaudio.mp4").rename(OUT)
    shutil.rmtree(TMP)
    sz=OUT.stat().st_size/1_048_576
    print(f"Done! {OUT.absolute()} ({sz:.1f} MB)", file=sys.stderr, flush=True)

if __name__=="__main__": build()
