from __future__ import annotations

import csv, hashlib, json, shutil, subprocess, sys, time, zipfile
from pathlib import Path
from dataclasses import dataclass, asdict

import fitz
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
MEDIA = OUT / "media"
IMG = MEDIA / "images"
PDF = MEDIA / "pdfs"
PAGE = MEDIA / "pdf_pages"
VID = MEDIA / "videos"
FRAME = MEDIA / "video_frames"
META = OUT / "metadata"
BUNDLE = OUT / "ebina_actual_media_bundle.zip"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "ja,en;q=0.8"})

@dataclass
class Row:
    item_id: str
    category: str
    title: str
    source_url: str
    local_path: str
    status: str
    bytes: int = 0
    sha256: str = ""
    content_type: str = ""
    note: str = ""

rows: list[Row] = []

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def add(item_id, category, title, url, path, status, ctype="", note=""):
    rows.append(Row(item_id, category, title, url, str(path.relative_to(OUT)) if path and path.exists() else "", status, path.stat().st_size if path and path.exists() else 0, sha(path) if path and path.exists() else "", ctype, note))

def get(item_id, category, title, url, dest, referer=None, min_bytes=1000):
    dest.parent.mkdir(parents=True, exist_ok=True)
    err = ""
    for n in range(1,5):
        try:
            headers = {"Referer": referer} if referer else {}
            with S.get(url, headers=headers, stream=True, timeout=(20,120), allow_redirects=True) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1024*256):
                        if chunk: f.write(chunk)
                if tmp.stat().st_size < min_bytes:
                    raise RuntimeError(f"small response {tmp.stat().st_size}")
                tmp.replace(dest)
                add(item_id, category, title, url, dest, "SAVED", r.headers.get("content-type", ""))
                print("SAVED", item_id, dest.stat().st_size, flush=True)
                return True
        except Exception as e:
            err = f"try{n} {type(e).__name__}: {e}"
            print("RETRY", item_id, err, flush=True)
            time.sleep(2*n)
    add(item_id, category, title, url, None, "FAILED", note=err)
    return False

def get_first(item_id, category, title, urls, dest, referer=None):
    for i,u in enumerate(urls,1):
        before=len(rows)
        if get(f"{item_id}_TRY{i}",category,title,u,dest,referer):
            rows[-1].item_id=item_id
            rows[-1].note=f"candidate {i} succeeded"
            return True
        if len(rows)>before:
            rows[-1].note=f"candidate {i} failed; {rows[-1].note}"
    return False

def render(pdf_path: Path, prefix: str):
    if not pdf_path.exists(): return
    doc=fitz.open(pdf_path)
    mat=fitz.Matrix(160/72,160/72)
    for i in range(len(doc)):
        out=PAGE/f"{prefix}_p{i+1:02d}.png"
        doc[i].get_pixmap(matrix=mat,alpha=False).save(out)
        with Image.open(out) as im:
            im.load(); note=f"actual page render {im.width}x{im.height}"
        add(f"{prefix}_P{i+1:02d}","PDF_PAGE",f"{prefix} page {i+1}",f"{pdf_path.name}#page={i+1}",out,"SAVED_RENDER","image/png",note)
    doc.close()

def run(cmd, timeout=2400):
    print("RUN", " ".join(cmd), flush=True)
    return subprocess.run(cmd,text=True,capture_output=True,timeout=timeout)

def thumb(item_id,title,url,stem):
    cp=run([sys.executable,"-m","yt_dlp","--no-playlist","--skip-download","--write-thumbnail","--convert-thumbnails","jpg","-o",str(IMG/f"{stem}.%(ext)s"),url],600)
    (META/f"{stem}_thumb.log").write_text((cp.stdout or "")+"\n"+(cp.stderr or ""),encoding="utf-8")
    found=sorted(IMG.glob(f"{stem}*.jpg"))
    if found:
        for i,p in enumerate(found,1): add(f"{item_id}_TH{i}","VIDEO_THUMBNAIL",title,url,p,"SAVED_IMAGE","image/jpeg")
    else: add(item_id,"VIDEO_THUMBNAIL",title,url,None,"FAILED_IMAGE",note=(cp.stderr or "")[-1500:])

def clip(item_id,title,url,section,stem):
    cp=run([sys.executable,"-m","yt_dlp","--no-playlist","--retries","4","--fragment-retries","4","--socket-timeout","30","--user-agent",UA,"--extractor-args","youtube:player_client=android,web","--download-sections",section,"--force-keyframes-at-cuts","--merge-output-format","mp4","-f","bv*[height<=480]+ba/b[height<=480]/best[height<=480]","-o",str(VID/f"{stem}.%(ext)s"),url],2700)
    (META/f"{stem}_video.log").write_text((cp.stdout or "")+"\n"+(cp.stderr or ""),encoding="utf-8")
    found=[p for p in VID.glob(f"{stem}.*") if p.suffix.lower() in {".mp4",".mkv",".webm",".mov"}]
    if not found:
        add(item_id,"VIDEO_CLIP",title,url,None,"FAILED_VIDEO",note=(cp.stderr or "")[-1800:]); return
    p=found[0]; add(item_id,"VIDEO_CLIP",title,url,p,"SAVED_VIDEO",note=section)
    probe=run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(p)],120)
    try: dur=float(probe.stdout.strip())
    except: dur=0
    if dur<=0: return
    count=8
    for i in range(count):
        t=dur*(0.06+0.88*i/(count-1))
        out=FRAME/f"{stem}_f{i+1:02d}_{int(t):04d}s.jpg"
        cp2=run(["ffmpeg","-y","-ss",f"{t:.3f}","-i",str(p),"-frames:v","1","-q:v","2",str(out)],180)
        if cp2.returncode==0 and out.exists() and out.stat().st_size>5000:
            with Image.open(out) as im: im.load(); note=f"{t:.3f}s {im.width}x{im.height}"
            add(f"{item_id}_F{i+1:02d}","VIDEO_FRAME",f"{title} frame {i+1}",url,out,"SAVED_FRAME","image/jpeg",note)
        else: add(f"{item_id}_F{i+1:02d}","VIDEO_FRAME",f"{title} frame {i+1}",url,None,"FAILED_FRAME",note=(cp2.stderr or "")[-600:])

def main():
    if OUT.exists(): shutil.rmtree(OUT)
    for p in [IMG,PDF,PAGE,VID,FRAME,META]: p.mkdir(parents=True,exist_ok=True)
    tv="https://news.tv-asahi.co.jp/news_society/articles/900197603.html"
    tvimgs=[
      "https://news.tv-asahi.co.jp/articles_img/900197603_img_4630e1a6d855f6c1f4c35a8bcb70f54d86616.jpg",
      "https://news.tv-asahi.co.jp/articles_img/900197603_img_314225800456b3c5161b96d633a5ee25105245.jpg",
      "https://news.tv-asahi.co.jp/articles_img/900197603_img_101c86be649e95096c92770a641ce9b0611675.jpg",
      "https://news.tv-asahi.co.jp/articles_img/900197603_img_9a4a0362f351e1ce433708ca7623a00d134814.jpg",
      "https://news.tv-asahi.co.jp/articles_img/900197603_img_f794023f40ec7a41aa6114af447db3cd127851.jpg",
      "https://news.tv-asahi.co.jp/articles_img/900197603_img_12cbe0d9bbb60ecc8db14c975e8114d913197.jpg"]
    for i,u in enumerate(tvimgs,1): get(f"TVA_{i:02d}","NEWS_IMAGE",f"テレ朝news写真{i}",u,IMG/f"TVA_{i:02d}.jpg",tv)
    people=[
      ("MAYOR_01","内野優市長公式写真1","https://www.city.ebina.kanagawa.jp/_res/projects/default_project/_page_/001/000/908/151204181035_0s.jpg","https://www.city.ebina.kanagawa.jp/mayor/profile/1000908.html"),
      ("MAYOR_02","内野優市長公式写真2","https://www.city.ebina.kanagawa.jp/_res/projects/default_project/_page_/001/000/908/151204181110_0s.jpg","https://www.city.ebina.kanagawa.jp/mayor/profile/1000908.html"),
      ("DEPUTY_01","萩原圭一副市長公式写真","https://www.city.ebina.kanagawa.jp/_res/projects/default_project/_page_/001/016/480/0226fukushityou.jpg","https://www.city.ebina.kanagawa.jp/shisei/gaiyo/profile/1016480.html"),
      ("COUNCILOR_01","吉田みな子市議公式写真","https://ebina.gijiroku.com/voices/GikaiDoc/attach/Giin/Gn25_yoshida_2023.jpg","https://ebina.gijiroku.com/")]
    for iid,t,u,r in people: get(iid,"PERSON_IMAGE",t,u,IMG/f"{iid}.jpg",r)
    agri=[
      ("AGRI_01","サツマイモ収穫",["https://ebina-nogyo.jp/wp/wp-content/uploads/2025/10/IMG_2247-scaled-e1759362681653.jpeg","https://ebina-nogyo.jp/wp/wp-content/uploads/2025/10/IMG_2247-scaled-e1759362681653-300x225.jpeg"]),
      ("AGRI_02","サツマイモ収穫別会場",["https://ebina-nogyo.jp/wp/wp-content/uploads/2025/09/image0-2-scaled-e1757052331475.jpeg","https://ebina-nogyo.jp/wp/wp-content/uploads/2025/09/image0-2-scaled-e1757052331475-225x300.jpeg"]),
      ("AGRI_03","エダマメ圃場",["https://ebina-nogyo.jp/wp/wp-content/uploads/2025/07/DSC00056.jpg","https://ebina-nogyo.jp/wp/wp-content/uploads/2025/07/DSC00056-300x225.jpg"]),
      ("AGRI_04","ジャガイモ収穫",["https://ebina-nogyo.jp/wp/wp-content/uploads/2022/04/img-event-potato.jpg","https://ebina-nogyo.jp/wp/wp-content/uploads/2022/04/img-event-potato-300x200.jpg"]),
      ("AGRI_05","ジャガイモ圃場",["https://ebina-nogyo.jp/wp/wp-content/uploads/2025/06/DSC00022-1.jpg","https://ebina-nogyo.jp/wp/wp-content/uploads/2025/06/DSC00022-1-300x225.jpg"])]
    for iid,t,urls in agri: get_first(iid,"AGRICULTURE_IMAGE",t,urls,IMG/f"{iid}.jpg","https://ebina-nogyo.jp/experience")
    pdfs=[
      ("REPORT","全件調査報告書","https://www.city.ebina.kanagawa.jp/_res/projects/default_project/_page_/001/019/258/tyousakekka.pdf"),
      ("PRESS","8月20日臨時会見資料","https://www.city.ebina.kanagawa.jp/_res/projects/default_project/_page_/001/019/256/rinzikaiken.pdf"),
      ("DISCIPLINE","職員処分公表","https://www.city.ebina.kanagawa.jp/_res/projects/default_project/_page_/001/019/257/20260820.pdf"),
      ("AUDIT","監査委員告示第9号","https://www.city.ebina.kanagawa.jp/_res/projects/default_project/_page_/001/008/461/R080721zaimukansa.pdf"),
      ("AUDIT_SUMMARY","7月24日会見資料7","https://www.city.ebina.kanagawa.jp/_res/projects/default_project/_page_/001/019/143/nousei.pdf")]
    for iid,t,u in pdfs:
        p=PDF/f"{iid}.pdf"
        if get(iid,"OFFICIAL_PDF",t,u,p,"https://www.city.ebina.kanagawa.jp/"): render(p,iid)
    html=[
      ("PAGE_REPORT","全件調査ページ","https://www.city.ebina.kanagawa.jp/shisei/soshiki/jinji/1019258.html"),
      ("PAGE_DISCIPLINE","職員処分ページ","https://www.city.ebina.kanagawa.jp/koho/1007115/press/1018489/1019151/1019257.html"),
      ("PAGE_PRESS","臨時記者会見ページ","https://www.city.ebina.kanagawa.jp/koho/1007115/kishakaiken/1018499/1019256.html"),
      ("PAGE_TVA","テレ朝news記事",tv)]
    for iid,t,u in html: get(iid,"SOURCE_HTML",t,u,META/f"{iid}.html",min_bytes=300)
    aug="https://www.youtube.com/watch?v=iYKusML9XB8"; jul="https://www.youtube.com/watch?v=XjAr01tJCiY"
    thumb("YT_AUG","8月20日市長臨時記者会見",aug,"YT_AUG")
    thumb("YT_JUL","7月24日市長定例記者会見",jul,"YT_JUL")
    clip("YT_AUG_CLIP","8月20日市長臨時記者会見本件区間",aug,"*00:00:00-00:18:00","YT_AUG_00m00s_18m00s")
    clip("YT_JUL_CLIP","7月24日市長定例記者会見監査区間",jul,"*00:42:00-00:55:00","YT_JUL_42m00s_55m00s")
    clip("TVA_VIDEO","テレ朝news埋め込み動画",tv,"*00:00:00-00:03:00","TVA_ARTICLE_CLIP")
    fields=list(asdict(rows[0]).keys())
    with (META/"download_log.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,quoting=csv.QUOTE_ALL); w.writeheader(); [w.writerow(asdict(r)) for r in rows]
    summary={"records":len(rows),"saved":sum(r.status.startswith("SAVED") for r in rows),"failed":sum(r.status.startswith("FAILED") for r in rows),"images":sum(r.local_path.lower().endswith((".jpg",".jpeg",".png",".webp")) for r in rows),"videos":sum(r.local_path.lower().endswith((".mp4",".mkv",".webm",".mov")) for r in rows),"pdfs":sum(r.local_path.lower().endswith(".pdf") for r in rows),"bytes":sum(r.bytes for r in rows)}
    (META/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    with zipfile.ZipFile(BUNDLE,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for p in sorted(OUT.rglob("*")):
            if p.is_file() and p!=BUNDLE: z.write(p,p.relative_to(OUT))
    print(json.dumps(summary,ensure_ascii=False),flush=True); print("BUNDLE",BUNDLE.stat().st_size,flush=True)

if __name__=="__main__": main()
