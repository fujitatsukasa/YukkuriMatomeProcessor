from __future__ import annotations

import csv, hashlib, json, shutil, subprocess, sys, time, zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'; VIDEOS=OUT/'videos'; THUMBS=OUT/'thumbnails'; LOGS=OUT/'logs'; BUNDLE=OUT/'ebina_video_retry_bundle.zip'
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'*/*'})
rows=[]

def sha(p):
    h=hashlib.sha256();
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def rec(i,title,url,path,status,note=''):
    rows.append({'item_id':i,'title':title,'source_url':url,'local_path':str(path.relative_to(OUT)) if path and path.exists() else '', 'status':status,'bytes':path.stat().st_size if path and path.exists() else 0,'sha256':sha(path) if path and path.exists() else '', 'note':note})

def run(cmd,timeout=2700):
    print('RUN',' '.join(cmd),flush=True)
    return subprocess.run(cmd,text=True,capture_output=True,timeout=timeout)

def get(url,dest):
    dest.parent.mkdir(parents=True,exist_ok=True)
    with S.get(url,stream=True,timeout=(20,180),allow_redirects=True) as r:
        r.raise_for_status(); tmp=dest.with_suffix(dest.suffix+'.part')
        with tmp.open('wb') as f:
            for c in r.iter_content(1024*256):
                if c:f.write(c)
        tmp.replace(dest)
    return dest

def thumb(video_id,item_id,title):
    for name in ['maxresdefault.jpg','sddefault.jpg','hqdefault.jpg']:
        u=f'https://i.ytimg.com/vi/{video_id}/{name}'
        try:
            p=get(u,THUMBS/f'{item_id}_{name}')
            if p.stat().st_size>5000:
                rec(item_id,title,u,p,'SAVED_THUMBNAIL',name); return
        except Exception as e: last=str(e)
    rec(item_id,title,f'https://www.youtube.com/watch?v={video_id}',None,'FAILED_THUMBNAIL',last)

def ytdlp(item_id,title,video_id,section,stem):
    u=f'https://www.youtube.com/watch?v={video_id}'
    cmd=[sys.executable,'-m','yt_dlp','--ignore-config','--no-playlist','--sleep-requests','2','--retries','5','--fragment-retries','5','--socket-timeout','30','--js-runtimes','node','--extractor-args','youtube:player_client=tv,web_safari','--download-sections',section,'--force-keyframes-at-cuts','--merge-output-format','mp4','-f','18/22/b[height<=480]/best[height<=480]','-o',str(VIDEOS/f'{stem}.%(ext)s'),u]
    cp=run(cmd); (LOGS/f'{stem}_ytdlp.log').write_text((cp.stdout or '')+'\n'+(cp.stderr or ''),encoding='utf-8')
    found=[p for p in VIDEOS.glob(f'{stem}.*') if p.suffix.lower() in {'.mp4','.webm','.mkv','.mov'}]
    if cp.returncode==0 and found:
        rec(item_id,title,u,found[0],'SAVED_VIDEO','yt-dlp tv,web_safari'); return found[0]
    rec(item_id,title,u,None,'FAILED_YTDLP',(cp.stderr or '')[-1500:]); return None

def choose_stream(data):
    vids=data.get('videoStreams') or []
    # Prefer combined 360p/480p; otherwise choose video-only.
    combined=[v for v in vids if not v.get('videoOnly') and v.get('url')]
    cand=combined or [v for v in vids if v.get('url')]
    def score(v):
        q=str(v.get('quality') or v.get('qualityLabel') or '')
        num=int(''.join(ch for ch in q if ch.isdigit()) or 0)
        return (num<=480, num, 'mp4' in str(v.get('format','')).lower())
    cand=sorted(cand,key=score,reverse=True)
    video=cand[0] if cand else None
    auds=[a for a in (data.get('audioStreams') or []) if a.get('url')]
    audio=sorted(auds,key=lambda a:int(a.get('bitrate') or 0),reverse=True)[0] if auds else None
    return video,audio

def ffmpeg_remote(video_url,audio_url,start,dur,out):
    out.parent.mkdir(parents=True,exist_ok=True)
    if audio_url:
        cmd=['ffmpeg','-y','-ss',str(start),'-i',video_url,'-ss',str(start),'-i',audio_url,'-t',str(dur),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','veryfast','-crf','22','-c:a','aac','-b:a','128k','-movflags','+faststart',str(out)]
    else:
        cmd=['ffmpeg','-y','-ss',str(start),'-i',video_url,'-t',str(dur),'-c:v','libx264','-preset','veryfast','-crf','22','-c:a','aac','-b:a','128k','-movflags','+faststart',str(out)]
    cp=run(cmd,3600); return cp

def piped(item_id,title,video_id,start,dur,stem):
    bases=['https://pipedapi.adminforge.de','https://pipedapi.reallyaweso.me','https://pipedapi.drgns.space','https://pipedapi.kavin.rocks']
    for base in bases:
        try:
            r=S.get(f'{base}/streams/{video_id}',timeout=(15,60)); r.raise_for_status(); data=r.json(); v,a=choose_stream(data)
            if not v: raise RuntimeError('no stream')
            out=VIDEOS/f'{stem}_piped.mp4'; cp=ffmpeg_remote(v['url'],None if not v.get('videoOnly') else (a or {}).get('url'),start,dur,out)
            (LOGS/f'{stem}_{urlparse(base).netloc}.log').write_text((cp.stdout or '')+'\n'+(cp.stderr or ''),encoding='utf-8')
            if cp.returncode==0 and out.exists() and out.stat().st_size>100000:
                rec(item_id,title,f'https://www.youtube.com/watch?v={video_id}',out,'SAVED_VIDEO',f'Piped {base}'); return out
        except Exception as e:
            (LOGS/f'{stem}_{urlparse(base).netloc}_api.log').write_text(str(e),encoding='utf-8')
    rec(item_id,title,f'https://www.youtube.com/watch?v={video_id}',None,'FAILED_PIPED','all instances failed'); return None

def invidious(item_id,title,video_id,start,dur,stem):
    bases=['https://inv.nadeko.net','https://invidious.nerdvpn.de','https://yewtu.be']
    for base in bases:
        try:
            r=S.get(f'{base}/api/v1/videos/{video_id}',timeout=(15,60)); r.raise_for_status(); data=r.json(); fs=data.get('formatStreams') or []
            fs=[x for x in fs if x.get('url')]
            if not fs: raise RuntimeError('no formatStreams')
            fs=sorted(fs,key=lambda x:int(''.join(c for c in str(x.get('qualityLabel','')) if c.isdigit()) or 0),reverse=True)
            out=VIDEOS/f'{stem}_invidious.mp4'; cp=ffmpeg_remote(fs[0]['url'],None,start,dur,out)
            (LOGS/f'{stem}_{urlparse(base).netloc}.log').write_text((cp.stdout or '')+'\n'+(cp.stderr or ''),encoding='utf-8')
            if cp.returncode==0 and out.exists() and out.stat().st_size>100000:
                rec(item_id,title,f'https://www.youtube.com/watch?v={video_id}',out,'SAVED_VIDEO',f'Invidious {base}'); return out
        except Exception as e:
            (LOGS/f'{stem}_{urlparse(base).netloc}_api.log').write_text(str(e),encoding='utf-8')
    rec(item_id,title,f'https://www.youtube.com/watch?v={video_id}',None,'FAILED_INVIDIOUS','all instances failed'); return None

def collect(item_id,title,video_id,section,start,dur,stem):
    thumb(video_id,item_id+'_TH',title+' thumbnail')
    p=ytdlp(item_id,title,video_id,section,stem)
    if not p: p=piped(item_id,title,video_id,start,dur,stem)
    if not p: p=invidious(item_id,title,video_id,start,dur,stem)
    return p

def main():
    if OUT.exists():shutil.rmtree(OUT)
    for p in [VIDEOS,THUMBS,LOGS]:p.mkdir(parents=True,exist_ok=True)
    collect('YT_AUG_CLIP','8月20日市長臨時記者会見・本件区間','iYKusML9XB8','*00:00:00-00:18:00',0,1080,'YT_AUG_00m00s_18m00s')
    collect('YT_JUL_CLIP','7月24日市長定例記者会見・監査区間','XjAr01tJCiY','*00:42:00-00:55:00',2520,780,'YT_JUL_42m00s_55m00s')
    collect('TVA_VIDEO','テレ朝news報道動画','OxqTN8m-2ck','*00:00:00-00:03:00',0,180,'TVA_00m00s_03m00s')
    fields=list(rows[0])
    with (OUT/'video_retry_log.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,quoting=csv.QUOTE_ALL);w.writeheader();w.writerows(rows)
    summary={'saved_videos':sum(r['status']=='SAVED_VIDEO' for r in rows),'saved_thumbnails':sum(r['status']=='SAVED_THUMBNAIL' for r in rows),'failed':sum(r['status'].startswith('FAILED') for r in rows),'bytes':sum(r['bytes'] for r in rows)}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(BUNDLE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=4,allowZip64=True) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file() and p!=BUNDLE:z.write(p,p.relative_to(OUT))
    print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
