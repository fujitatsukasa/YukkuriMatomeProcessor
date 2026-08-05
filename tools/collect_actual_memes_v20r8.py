#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36"
OUT = Path("actual_meme_output")
MEDIA = OUT / "実在ミーム素材"
ART = Path("actual_meme_artifacts")
TIMEOUT = 20
MAX_BYTES = 35 * 1024 * 1024
MAX_ASSETS = 480

CURATED = [
    ("Huh Cat", "TENOR_ACTUAL_GIF", "https://tenor.com/view/huh-cat-stu-gif-338418250328780606", "https://media1.tenor.com/m/BLJNmwxbLz4AAAAd/huh-cat.gif"),
    ("Nyan Cat", "KYM_REPRESENTATIVE", "https://knowyourmeme.com/memes/nyan-cat-pop-tart-cat", "https://i.kym-cdn.com/entries/icons/original/000/005/608/nyan-cat-01-625x450.jpg"),
    ("Doge", "KYM_REPRESENTATIVE", "https://knowyourmeme.com/memes/doge", "https://i.kym-cdn.com/entries/icons/facebook/000/013/564/doge.jpg"),
    ("Dramatic Chipmunk", "KYM_REPRESENTATIVE", "https://knowyourmeme.com/memes/dramatic-chipmunk", "https://i.kym-cdn.com/entries/icons/facebook/000/000/016/71919385_dramatic_chipmunk.jpg"),
    ("Special Feeling", "KYM_REPRESENTATIVE", "https://knowyourmeme.com/memes/special-feeling-%E7%89%B9%E5%88%A5%E3%81%AA%E6%B0%97%E5%88%86", "https://i.kym-cdn.com/entries/icons/original/000/013/159/special-feeling.jpg"),
    ("Coffin Dance", "KYM_REPRESENTATIVE", "https://knowyourmeme.com/memes/coffin-dance-dancing-pallbearers", "https://i.kym-cdn.com/entries/icons/facebook/000/033/381/dancing_coffin.jpg"),
    ("We Outta Tires", "KYM_REPRESENTATIVE", "https://knowyourmeme.com/memes/we-outta-tires", "https://i.kym-cdn.com/entries/icons/original/000/051/289/we_outta_tires.jpg"),
    ("Houtou Yeah", "KYM_REPRESENTATIVE", "https://knowyourmeme.com/memes/houtou-yeah", "https://i.kym-cdn.com/entries/icons/original/000/057/027/Houtou_Yeah.jpg"),
    ("Keyboard Cat", "KYM_ACTUAL_PHOTO", "https://knowyourmeme.com/memes/keyboard-cat", "https://i.kym-cdn.com/photos/images/newsfeed/000/000/016/dscn0413.jpg"),
    ("強風オールバック", "OFFICIAL_VIDEO_THUMBNAIL", "https://www.youtube.com/watch?v=D6DVTLvOupE", "https://img.youtube.com/vi/D6DVTLvOupE/hqdefault.jpg"),
    ("好きな惣菜発表ドラゴン", "OFFICIAL_VIDEO_THUMBNAIL", "https://www.youtube.com/watch?v=OnCFEo_pXaY", "https://img.youtube.com/vi/OnCFEo_pXaY/hqdefault.jpg"),
    ("INTERNET YAMERO", "OFFICIAL_VIDEO_THUMBNAIL", "https://www.youtube.com/watch?v=51GIxXFKbzk", "https://img.youtube.com/vi/51GIxXFKbzk/hqdefault.jpg"),
    ("匿名M", "OFFICIAL_VIDEO_THUMBNAIL", "https://www.youtube.com/watch?v=yiqEEL7ac6M", "https://img.youtube.com/vi/yiqEEL7ac6M/hqdefault.jpg"),
    ("PPAP", "OFFICIAL_VIDEO_THUMBNAIL", "https://www.youtube.com/watch?v=0E00Zuayv9Q", "https://img.youtube.com/vi/0E00Zuayv9Q/hqdefault.jpg"),
    ("Rickroll", "OFFICIAL_VIDEO_THUMBNAIL", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"),
    ("Gangnam Style", "OFFICIAL_VIDEO_THUMBNAIL", "https://www.youtube.com/watch?v=9bZkp7q19f0", "https://img.youtube.com/vi/9bZkp7q19f0/hqdefault.jpg"),
]

SEEDS = [
    "https://knowyourmeme.com/memes/special-feeling-%E7%89%B9%E5%88%A5%E3%81%AA%E6%B0%97%E5%88%86",
    "https://knowyourmeme.com/memes/houtou-yeah",
    "https://knowyourmeme.com/memes/futae-no-kiwami",
    "https://knowyourmeme.com/memes/fukkireta-%E5%90%B9%E3%81%A3%E5%88%87%E3%82%8C%E3%81%9F",
    "https://knowyourmeme.com/memes/yukkuri-shiteitte-ne",
    "https://knowyourmeme.com/memes/plasma-chan",
    "https://knowyourmeme.com/memes/hai-yorokonde",
    "https://knowyourmeme.com/memes/motteke-sailor-fuku",
    "https://knowyourmeme.com/memes/yatta",
    "https://knowyourmeme.com/memes/kumamon",
    "https://knowyourmeme.com/memes/nyan-cat-pop-tart-cat",
    "https://knowyourmeme.com/memes/doge",
    "https://knowyourmeme.com/memes/dramatic-chipmunk",
    "https://knowyourmeme.com/memes/coffin-dance-dancing-pallbearers",
]

NICO_QUERIES = [
    "フタエノキワミ", "吹っ切れた", "ゆっくりしていってね", "エアーマンが倒せない",
    "魔理沙は大変なものを盗んでいきました", "Bad Apple", "おっくせんまん", "ニコニコ組曲",
    "IKZO", "キーボードクラッシャー", "ドナルド", "松岡修造", "チャージマン研", "音MAD",
    "重音テト 吹っ切れた", "強風オールバック", "好きな惣菜発表ドラゴン", "はいよろこんで パロディ",
    "やらないか", "レッツゴー陰陽師", "きしめん", "ウッーウッーウマウマ", "ゲッダン", "男女"
]

COMMONS = [
    "File:1san.png", "File:Aramaki.png", "File:Dousitekounatta.png",
    "File:%E3%82%AE%E3%82%B3%E7%8C%AB_(AA).svg", "File:Mona01.svg",
    "File:%E3%83%A2%E3%83%8A%E3%83%BC_(AA).svg", "File:%E3%83%A2%E3%83%A9%E3%83%A9%E3%83%BC_(AA).svg",
    "File:%E3%81%AC%E3%82%8B%E3%81%BD_(AA).svg", "File:%E3%82%84%E3%82%8B%E3%81%8A.png",
    "File:Japanese_Danmaku_example.jpg", "File:BIRDBRAIN_Teto_head_bob.gif"
]


def sess():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ja,en-US;q=0.8,en;q=0.6"})
    return s


def get(s, url, stream=False):
    try:
        r = s.get(url, timeout=TIMEOUT, allow_redirects=True, stream=stream)
        return r if r.status_code == 200 else None
    except requests.RequestException:
        return None


def safe_name(x, limit=80):
    x = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", x or "")
    x = re.sub(r"\s+", "_", x).strip("._ ")
    return x[:limit] or "meme"


def decode(data):
    try:
        with Image.open(io.BytesIO(data)) as im:
            size = im.size
            fmt = (im.format or "").upper()
            frames = getattr(im, "n_frames", 1)
            im.verify()
        return size[0], size[1], fmt, frames
    except Exception:
        return None


def ext(fmt):
    return {"PNG": ".png", "JPEG": ".jpg", "JPG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}.get(fmt, "")


def discover_kym():
    s = sess()
    urls = set(SEEDS)
    for page in range(1, 18):
        for u in (f"https://knowyourmeme.com/categories/japan/page/{page}", f"https://knowyourmeme.com/search?page={page}&q=japanese+meme"):
            r = get(s, u)
            if not r:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select('a[href*="/memes/"]'):
                href = (a.get("href") or "").split("?")[0].split("#")[0]
                if re.match(r"^/memes/[^/]+/?$", href):
                    urls.add(urljoin("https://knowyourmeme.com", href))
            if len(urls) >= 320:
                return sorted(urls)[:320]
    return sorted(urls)[:320]


def parse_kym(url):
    s = sess(); r = get(s, url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    ogt = soup.find("meta", property="og:title")
    title = ogt.get("content", "") if ogt else (soup.title.get_text(" ", strip=True) if soup.title else url)
    out = []
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        out.append((title, "KYM_REPRESENTATIVE", url, og["content"]))
    photos = []
    for a in soup.select('a[href*="/photos/"]'):
        href = a.get("href", "")
        if re.match(r"^/photos/\d+", href):
            full = urljoin("https://knowyourmeme.com", href.split("?")[0])
            if full not in photos:
                photos.append(full)
        if len(photos) >= 3:
            break
    for p in photos:
        pr = get(s, p)
        if not pr:
            continue
        ps = BeautifulSoup(pr.text, "html.parser")
        pog = ps.find("meta", property="og:image")
        if pog and pog.get("content"):
            out.append((title, "KYM_GALLERY_POST", p, pog["content"]))
    return out


def nico_candidates():
    s = sess(); out = []
    endpoint = "https://snapshot.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
    for q in NICO_QUERIES:
        params = {"q": q, "targets": "title,description,tags", "fields": "contentId,title,thumbnailUrl,viewCounter", "_sort": "-viewCounter", "_limit": "4", "_context": "v20r8_actual_only"}
        try:
            r = s.get(endpoint, params=params, timeout=TIMEOUT)
            data = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            data = []
        for d in data[:2]:
            if d.get("contentId") and d.get("thumbnailUrl"):
                out.append((d.get("title") or q, "NICONICO_ACTUAL_THUMBNAIL", f"https://www.nicovideo.jp/watch/{d['contentId']}", d["thumbnailUrl"]))
    return out


def commons_candidates():
    s = sess(); out = []
    endpoint = "https://commons.wikimedia.org/w/api.php"
    for title in COMMONS:
        params = {"action": "query", "format": "json", "titles": title, "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": "1800"}
        try:
            r = s.get(endpoint, params=params, timeout=TIMEOUT)
            pages = (r.json().get("query") or {}).get("pages", {}) if r.status_code == 200 else {}
        except Exception:
            pages = {}
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            u = ii.get("thumburl") or ii.get("url")
            if u:
                out.append((p.get("title", title), "WIKIMEDIA_ACTUAL", "https://commons.wikimedia.org/wiki/" + quote_plus(p.get("title", title).replace(" ", "_")), u))
    return out


def download(candidate, num):
    title, kind, page, media_url = candidate
    s = sess(); r = get(s, media_url, stream=True)
    if not r:
        return None
    buf = io.BytesIO(); total = 0
    try:
        for chunk in r.iter_content(131072):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_BYTES:
                return None
            buf.write(chunk)
    except requests.RequestException:
        return None
    data = buf.getvalue()
    if len(data) < 2500:
        return None
    d = decode(data)
    if not d:
        return None
    w, h, fmt, frames = d
    if w < 160 or h < 100:
        return None
    low = (media_url + " " + title).lower()
    if any(x in low for x in ("logo", "avatar", "placeholder", "cosplay")):
        return None
    sha = hashlib.sha256(data).hexdigest()
    suffix = ext(fmt)
    if not suffix:
        return None
    folder = MEDIA / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ACTUAL_{num:05d}_{safe_name(title, 55)}_{sha[:10]}{suffix}"
    path.write_bytes(data)
    return {"素材ID": f"ACTUAL-{num:05d}", "ミーム名": title, "素材区分": kind, "元ページURL": page, "直接媒体URL": media_url, "ローカルファイル": path.as_posix(), "SHA-256": sha, "幅": w, "高さ": h, "形式": fmt, "フレーム数": frames, "取得日時UTC": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}


def write_csv(path, rows):
    fields = ["素材ID", "ミーム名", "素材区分", "元ページURL", "直接媒体URL", "ローカルファイル", "SHA-256", "幅", "高さ", "形式", "フレーム数", "取得日時UTC"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def build_parts(rows, count=6):
    files = [(Path(r["ローカルファイル"]), r) for r in rows]
    files = [(p, r) for p, r in files if p.exists()]
    groups = [[] for _ in range(count)]
    sizes = [0] * count
    for p, r in sorted(files, key=lambda x: x[0].stat().st_size, reverse=True):
        i = sizes.index(min(sizes))
        groups[i].append((p, r)); sizes[i] += p.stat().st_size
    ART.mkdir(parents=True, exist_ok=True)
    summary = []
    for i, group in enumerate(groups, 1):
        zp = ART / f"実在ミーム素材のみ_第{i:02d}分冊_V20R8.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            subset = []
            for p, r in group:
                arc = p.relative_to(OUT).as_posix()
                z.write(p, arc); subset.append({**r, "ローカルファイル": arc})
            sio = io.StringIO(); fields = ["素材ID", "ミーム名", "素材区分", "元ページURL", "直接媒体URL", "ローカルファイル", "SHA-256", "幅", "高さ", "形式", "フレーム数", "取得日時UTC"]
            w = csv.DictWriter(sio, fieldnames=fields); w.writeheader(); w.writerows(subset)
            z.writestr("00_実在素材索引.csv", '\ufeff' + sio.getvalue())
        sha = hashlib.sha256(zp.read_bytes()).hexdigest()
        (ART / (zp.name + ".sha256")).write_text(f"{sha}  {zp.name}\n", encoding="utf-8")
        summary.append((zp.name, len(group), zp.stat().st_size, sha))
    with (ART / "全分冊一覧.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["ファイル", "素材件数", "ZIP容量", "SHA-256"]); w.writerows(summary)


def main():
    MEDIA.mkdir(parents=True, exist_ok=True)
    candidates = list(CURATED)
    urls = discover_kym()
    (OUT / "00_KYM収集対象URL.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=8) as ex:
        for result in ex.map(parse_kym, urls):
            candidates.extend(result)
    candidates.extend(nico_candidates())
    candidates.extend(commons_candidates())
    unique = []
    seen_url = set()
    for c in candidates:
        if c[3] and c[3] not in seen_url:
            seen_url.add(c[3]); unique.append(c)
    rows = []
    seen_sha = set()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(download, c, i): c for i, c in enumerate(unique, 1)}
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception:
                r = None
            if r and r["SHA-256"] not in seen_sha:
                seen_sha.add(r["SHA-256"]); rows.append(r)
                if len(rows) >= MAX_ASSETS:
                    break
    rows.sort(key=lambda x: (x["素材区分"], x["ミーム名"], x["SHA-256"]))
    write_csv(OUT / "00_実在素材全索引.csv", rows)
    (OUT / "00_回収結果.txt").write_text(f"実在素材件数: {len(rows)}\n自作説明カード: 0\n自作GIF・MP4: 0\n代替コスプレ写真: 0\n完全SHA重複: 0\n", encoding="utf-8")
    build_parts(rows, 6)
    print({"actual_media": len(rows), "candidate_urls": len(unique), "parts": 6})


if __name__ == "__main__":
    main()
