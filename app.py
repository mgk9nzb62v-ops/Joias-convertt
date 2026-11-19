from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path
import tempfile, subprocess, shutil, socket, ipaddress, requests
from urllib.parse import urlparse

app = FastAPI(title='Joias Convert')
BASE = Path(__file__).parent
TMP = Path(tempfile.mkdtemp(prefix='joias_convert_'))
MAX_MB = 150

def safe_url(url: str):
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or not p.hostname:
        raise HTTPException(400, 'Use um link HTTP ou HTTPS direto para o arquivo de mídia.')
    try:
        ips = socket.getaddrinfo(p.hostname, None)
        for item in ips:
            ip = ipaddress.ip_address(item[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise HTTPException(400, 'Esse endereço não pode ser acessado por segurança.')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, 'Não foi possível validar o endereço do link.')

def convert_to_mp3(src: Path, bitrate: str):
    if not shutil.which('ffmpeg'):
        raise HTTPException(500, 'FFmpeg não está instalado no servidor.')
    out = TMP / (src.stem[:60] + '_converted.mp3')
    proc = subprocess.run(['ffmpeg','-y','-i',str(src),'-vn','-codec:a','libmp3lame','-b:a',bitrate,'-ar','44100',str(out)], capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not out.exists():
        raise HTTPException(422, 'Não foi possível converter este arquivo. Confira se é um áudio ou vídeo válido.')
    return out

@app.get('/', response_class=HTMLResponse)
def home():
    return (BASE / 'index.html').read_text(encoding='utf-8')

@app.post('/convert-upload')
def upload_convert(file: UploadFile = File(...), bitrate: str = Form('192k')):
    if bitrate not in ('128k','192k','320k'):
        raise HTTPException(400, 'Qualidade inválida.')
    data = file.file.read(MAX_MB*1024*1024 + 1)
    if len(data) > MAX_MB*1024*1024:
        raise HTTPException(413, f'Arquivo maior que {MAX_MB} MB.')
    suffix = Path(file.filename or 'upload.bin').suffix[:10] or '.bin'
    src = TMP / ('upload_' + next(tempfile._get_candidate_names()) + suffix)
    src.write_bytes(data)
    mp3 = convert_to_mp3(src, bitrate)
    src.unlink(missing_ok=True)
    return FileResponse(mp3, media_type='audio/mpeg', filename=(Path(file.filename or 'audio').stem + '.mp3')

@app.post('/convert-url')
def url_convert(url: str = Form(...), bitrate: str = Form('192k')):
    if bitrate not in ('128k','192k','320k'):
        raise HTTPException(400, 'Qualidade inválida.')
    safe_url(url)
    try:
        r = requests.get(url, stream=True, timeout=20, allow_redirects=False, headers={'User-Agent':'JoiasConvert/1.0'})
        if r.status_code in (301,302,303,307,308):
            loc = r.headers.get('Location')
            if not loc: raise HTTPException(400,'Redirecionamento sem destino.')
            safe_url(requests.compat.urljoin(url, loc))
            r = requests.get(requests.compat.urljoin(url, loc), stream=True, timeout=20, allow_redirects=False, headers={'User-Agent':'JoiasConvert/1.0'})
        r.raise_for_status()
        ctype = r.headers.get('Content-Type','').lower()
        if not any(t in ctype for t in ('audio/','video/','application/octet-stream')):
            raise HTTPException(415,'Este link não parece ser um arquivo de mídia direto. Links de páginas (ex.: página do YouTube) não são aceitos.')
        src = TMP / ('remote_' + next(tempfile._get_candidate_names()) + '.media')
        total=0
        with src.open('wb') as f:
            for chunk in r.iter_content(1024*256):
                if chunk:
                    total += len(chunk)
                    if total > MAX_MB*1024*1024: raise HTTPException(413,f'Arquivo maior que {MAX_MB} MB.')
                    f.write(chunk)
        r.close()
        mp3 = convert_to_mp3(src, bitrate)
        src.unlink(missing_ok=True)
        return FileResponse(mp3, media_type='audio/mpeg', filename='joias_convert.mp3')
    except HTTPException:
        raise
    except requests.RequestException:
        raise HTTPException(400,'Falha ao baixar a mídia direta. Verifique o link ou tente enviar o arquivo.')
