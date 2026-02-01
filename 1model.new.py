import json
import logging
import os
import re
import shutil
import signal
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# --- 配置 ---
MAX_RETRIES = 5
RETRY_DELAY = 5
TIMEOUT = (15, 60)  # 增加超时时间
MAX_WORKERS = 8  # 降低并发数以减少“数据流中断”的情况

INDEX_JS_URL = "https://l2d.su/json/index.js"
BASE_URL = "https://l2d.su/json/"
STATIC_HOST = "https://static.l2d.su/"

TARGET_SUBDIR = "json"
FINAL_INDEX_JS_NAME = "index.js"
TEMP_INDEX_JS_NAME = f"index.temp.{int(time.time())}.js"
LOG_FILE = "log.txt"

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger(__name__)

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS * 2
)
session.mount("https://", adapter)
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "keep-alive",
    }
)


def safe_path_join(base, rel_path):
    """
    安全地拼接路径
    """
    if "://" in rel_path:
        rel_path = rel_path.split("://")[-1]

    invalid_chars = r'[\\:*?"<>|]'
    parts = rel_path.replace("\\", "/").split("/")
    clean_parts = [re.sub(invalid_chars, "_", p) for p in parts if p]

    return os.path.normpath(os.path.join(base, *clean_parts))


def download_file(url, local_filepath, force=False, silent=True):
    """
    增强版下载函数：只要大小不一致就更新，不进行严格的大小对等校验
    """
    local_filepath = os.path.normpath(local_filepath)
    local_dir = os.path.dirname(local_filepath)

    if len(local_filepath) > 250:
        local_filepath = "\\\\?\\" + os.path.abspath(local_filepath)

    try:
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
    except Exception as e:
        msg = f"无法创建目录: {local_dir} | 错误: {e}"
        print(f"\n  X {msg}")
        logger.error(msg)
        return False

    # 先尝试获取远程文件大小进行比对
    remote_size = -1
    if not force:
        try:
            head_res = session.head(url, timeout=5, allow_redirects=True)
            if head_res.status_code == 200:
                remote_size = int(head_res.headers.get("Content-Length", -1))
        except:
            pass

    # 逻辑调整：如果本地文件存在且大小与远程一致，则跳过
    if not force and os.path.exists(local_filepath):
        local_size = os.path.getsize(local_filepath)
        if remote_size != -1 and local_size == remote_size:
            logger.info(f"大小匹配，跳过: {local_filepath}")
            return True

    for attempt in range(MAX_RETRIES):
        try:
            p = urllib.parse.urlparse(url)
            encoded_url = urllib.parse.urlunparse(
                p._replace(path=urllib.parse.quote(p.path))
            )

            response = session.get(encoded_url, stream=True, timeout=TIMEOUT)

            if response.status_code == 404:
                msg = f"资源不存在 (404): {url}"
                print(f"\n  ! {msg}")
                logger.warning(msg)
                return False

            response.raise_for_status()

            tmp_path = local_filepath + ".tmp"

            with open(tmp_path, "wb") as f:
                actual_size = 0
                for chunk in response.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
                        actual_size += len(chunk)

            # 不再进行 actual_size != expected_size 的硬性报错
            # 直接接受下载到的结果
            if os.path.exists(local_filepath):
                os.remove(local_filepath)
            os.rename(tmp_path, local_filepath)

            logger.info(f"同步成功: {local_filepath} (大小: {actual_size} bytes)")
            return True

        except (requests.exceptions.RequestException, IOError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                msg = f"彻底失败: {url} | 原因: {e}"
                print(f"\n  X {msg}")
                logger.error(msg)
    return False


def extract_assets(data):
    """递归提取 JSON 中的路径"""
    found = set()
    exts = (".moc3", ".model3.json", ".json", ".png", ".wav", ".mp3")

    def _walk(obj):
        if isinstance(obj, str):
            if any(obj.lower().endswith(e) for e in exts):
                found.add(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for i in obj:
                _walk(i)

    _walk(data)
    return found


def process_model(local_path, url, executor):
    """下载 model3.json 指向的子资源"""
    try:
        with open(local_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return

    base_url = os.path.dirname(url) + "/"
    local_dir = os.path.dirname(local_path)

    futures = []
    for rel in extract_assets(data):
        if os.path.basename(rel) == os.path.basename(local_path):
            continue

        target_url = urllib.parse.urljoin(base_url, rel)
        target_local = safe_path_join(local_dir, rel)
        futures.append(
            executor.submit(download_file, target_url, target_local, silent=True)
        )

    for f in as_completed(futures):
        try:
            f.result()
        except:
            pass


def main():
    logger.info("--- 开始新的同步任务 ---")
    os.makedirs(TARGET_SUBDIR, exist_ok=True)

    print("正在获取在线版本信息...")
    if not download_file(INDEX_JS_URL, TEMP_INDEX_JS_NAME, force=True, silent=True):
        return

    try:
        with open(TEMP_INDEX_JS_NAME, "r", encoding="utf-8") as f:
            js_txt = f.read()

        match = re.search(
            r"'(./json/)?(live2dMaster.*?\.json)\?([a-zA-Z0-9]+)'", js_txt
        )
        if not match:
            logger.error("未在 index.js 中匹配到 Master JSON 路径")
            if os.path.exists(TEMP_INDEX_JS_NAME):
                os.remove(TEMP_INDEX_JS_NAME)
            return

        json_name, version = match.group(2), match.group(3)
        master_url = urllib.parse.urljoin(BASE_URL, json_name)
        master_local = os.path.join(TARGET_SUBDIR, f"live2dMaster{version}.json")

        if not download_file(master_url, master_local, force=True, silent=True):
            if os.path.exists(TEMP_INDEX_JS_NAME):
                os.remove(TEMP_INDEX_JS_NAME)
            return

        new_js_content = js_txt.replace(
            match.group(0), f"'{TARGET_SUBDIR}/live2dMaster{version}.json'"
        )
        with open(
            os.path.join(TARGET_SUBDIR, FINAL_INDEX_JS_NAME), "w", encoding="utf-8"
        ) as f:
            f.write(new_js_content)

        with open(master_local, "r", encoding="utf-8") as f:
            master_data = json.load(f)

        models = []
        for g in master_data.get("Master", []):
            for c in g.get("character", []):
                for l in c.get("live2d", []):
                    if "path" in l:
                        models.append(l)

        total_models = len(models)
        print(f"\n开始同步 {total_models} 个模型资源...")

        executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        try:
            for i, m in enumerate(models):
                url = m["path"]
                rel = (
                    url[len(STATIC_HOST) :]
                    if url.startswith(STATIC_HOST)
                    else url.split("://")[-1]
                )
                local = safe_path_join("", rel)

                print(f"[{i + 1}/{total_models}] 同步中: {local}", end="\r", flush=True)
                logger.info(f"正在处理核心模型文件: {local}")

                if download_file(url, local, silent=True):
                    m["path"] = rel.replace("\\", "/")
                    process_model(local, url, executor)

            with open(master_local, "w", encoding="utf-8") as f:
                json.dump(master_data, f, ensure_ascii=False, indent=4)

            msg = f"同步完成！共处理 {total_models} 个模型。"
            print(f"\n\n{msg}")
            logger.info(msg)

        except KeyboardInterrupt:
            msg = "正在停止..."
            print(f"\n\n{msg}")
            logger.warning(msg)
            executor.shutdown(wait=False, cancel_futures=True)
            if os.path.exists(TEMP_INDEX_JS_NAME):
                os.remove(TEMP_INDEX_JS_NAME)
            sys.exit(0)
        finally:
            executor.shutdown(wait=True)

    finally:
        # 无论成功失败，只要读取完信息就清理掉临时 js 文件
        if os.path.exists(TEMP_INDEX_JS_NAME):
            os.remove(TEMP_INDEX_JS_NAME)


if __name__ == "__main__":
    main()
