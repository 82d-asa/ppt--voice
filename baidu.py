from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List
import os
import aiofiles
import re
import requests
import urllib.parse
import uuid

app = FastAPI()

# 百度TTS配置
BAIDU_API_KEY = "bo3TAzl6yF5DcWIvqhHFILEi"
BAIDU_SECRET_KEY = "Sfp2KtchkC89MXe5T3IK8qz31YTzdKgI"
TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
TTS_URL = "https://tsn.baidu.com/text2audio"

# 文件保存目录
UPLOAD_DIR = "/home/guwei/pptjiexi/txt"
WAV_DIR = "/home/guwei/pptjiexi/audio_wav"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WAV_DIR, exist_ok=True)

class PageAudio(BaseModel):
    page_index: int
    audio_path: str

class SpeechSynthesisResponse(BaseModel):
    audios: List[PageAudio]

def get_baidu_access_token():
    params = {
        "grant_type": "client_credentials",
        "client_id": BAIDU_API_KEY,
        "client_secret": BAIDU_SECRET_KEY
    }
    response = requests.post(TOKEN_URL, params=params)
    if response.status_code != 200:
        raise Exception(f"获取百度Access Token失败: {response.text}")
    return response.json()["access_token"]

def parse_txt_content(content: str) -> List[tuple]:
    pattern = r"=== 第(\d+)页 ===\n"
    splits = list(re.finditer(pattern, content))
    results = []
    for i in range(len(splits)):
        start = splits[i].end()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(content)
        page_idx = int(splits[i].group(1))
        page_text = content[start:end].strip()
        if page_text:
            results.append((page_idx, page_text))
    return results

def clean_speech_text(text: str) -> str:
    text = re.sub(r"\*\*Notes:\*\*.*", "", text, flags=re.S)
    text = re.sub(r"\*\*Speech (Text|Script):\*\*", "", text)
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"-{3,}", "", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()

def split_text(text: str, max_len: int = 500) -> List[str]:
    sentences = re.split(r'(?<=[。！？.!?])', text)
    chunks, current = [], ""
    for s in sentences:
        if len(current.encode('gbk', errors='ignore')) + len(s.encode('gbk', errors='ignore')) <= max_len:
            current += s
        else:
            if current:
                chunks.append(current.strip())
            current = s
    if current:
        chunks.append(current.strip())
    return chunks

def synthesize_baidu_short(text: str, token: str) -> bytes:
    encoded_text = urllib.parse.quote(urllib.parse.quote(text))  # 双重 urlencode
    payload = (
        f"tex={encoded_text}&tok={token}&cuid=ppt-gen&ctp=1&lan=zh"
        f"&spd=5&pit=5&vol=5&per=4105&aue=6"
    )
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(TTS_URL, headers=headers, data=payload)
    if response.headers.get("Content-Type", "").startswith("audio"):
        return response.content
    else:
        raise Exception(f"TTS合成失败: {response.text}")

@app.post("/api/speech-from-txt", response_model=SpeechSynthesisResponse)
async def speech_from_txt(file: UploadFile = File(...)):
    if not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="只支持上传TXT文件")

    txt_path = os.path.join(UPLOAD_DIR, file.filename)
    async with aiofiles.open(txt_path, "wb") as f:
        content = await file.read()
        await f.write(content)
    text_str = content.decode("utf-8")
    pages = parse_txt_content(text_str)

    if not pages:
        raise HTTPException(status_code=400, detail="无法解析有效演讲内容")

    try:
        token = get_baidu_access_token()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    results = []
    for page_idx, page_text in pages:
        try:
            cleaned = clean_speech_text(page_text)
            chunks = split_text(cleaned, max_len=500)
            wav_path = os.path.join(WAV_DIR, f"page_{page_idx}_{uuid.uuid4().hex}.wav")
            with open(wav_path, "wb") as f:
                for chunk in chunks:
                    audio_data = synthesize_baidu_short(chunk, token)
                    f.write(audio_data)
            results.append(PageAudio(page_index=page_idx, audio_path=wav_path))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"第{page_idx}页合成失败: {str(e)}")

    return SpeechSynthesisResponse(audios=results)
