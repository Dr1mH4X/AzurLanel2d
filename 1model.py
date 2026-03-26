import json
import logging
import os
import re
import shutil
import time
import urllib.parse

import requests
from tqdm import tqdm

# --- 配置 ---
MAX_RETRIES = 5
RETRY_DELAY = 10
TIMEOUT = (10, 30)
MASTER_JSON_URL = "https://l2d.su/json/live2dMaster.json"
INDEX_JS_URL = "https://l2d.su/json/index.js"
BASE_URL = "https://l2d.su/json/"
STATIC_HOST = "https://static.l2d.su/"
TARGET_SUBDIR = "json"
FINAL_INDEX_JS_NAME = "index.js"

# 进度条字符
SPINNERS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
)


def setup_logging():
    """配置日志系统，输出到文件"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file_path = os.path.join(script_dir, "log.txt")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file_path, encoding="utf-8", mode="w"),
            # logging.StreamHandler(),  # 控制台查看
        ],
    )


def download_file(url, local_filepath):
    """下载文件，包含超时和重试逻辑。成功返回 True。"""
    logging.info(f"[DOWNLOAD] Starting: {url}")
    try:
        local_dir = os.path.dirname(local_filepath)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
    except IOError as e:
        logging.error(
            f"[DOWNLOAD] Failed to create directory for {local_filepath}: {e}"
        )
        return False

    local_filepath = os.path.normpath(local_filepath)

    for attempt in range(MAX_RETRIES):
        try:
            p = urllib.parse.urlparse(url)
            encoded_url = urllib.parse.urlunparse(
                p._replace(path=urllib.parse.quote(p.path))
            )
            response = session.get(encoded_url, stream=True, timeout=TIMEOUT)
            response.raise_for_status()
            tmp_path = local_filepath + ".tmp"
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            os.replace(tmp_path, local_filepath)
            logging.info(f"[DOWNLOAD] Success: {local_filepath}")
            return True
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logging.warning(
                f"[DOWNLOAD] Retry {attempt + 1}/{MAX_RETRIES} for {url}: {type(e).__name__}"
            )
        except requests.exceptions.HTTPError as e:
            logging.warning(f"[DOWNLOAD] HTTP Error {e.response.status_code} for {url}")
            if 400 <= e.response.status_code < 500:
                logging.error(f"[DOWNLOAD] Client error (4xx), skipping: {url}")
                return False
        except IOError as e:
            logging.error(f"[DOWNLOAD] IOError for {url}: {e}")

        if attempt < MAX_RETRIES - 1:
            logging.info(f"[DOWNLOAD] Waiting {RETRY_DELAY}s before retry...")
            time.sleep(RETRY_DELAY)

    logging.error(f"[DOWNLOAD] Failed after {MAX_RETRIES} attempts: {url}")
    return False


def process_model3_json(model_local_path, model_full_url):
    """解析 model3.json 并下载其引用的所有子资源"""
    logging.info(f"[MODEL3] Processing: {model_local_path}")
    try:
        with open(model_local_path, "r", encoding="utf-8") as f:
            model_data = json.load(f)
    except Exception as e:
        logging.error(f"[MODEL3] Failed to read {model_local_path}: {e}")
        return

    file_refs = model_data.get("FileReferences", {})
    if not file_refs:
        logging.warning(f"[MODEL3] No FileReferences found in {model_local_path}")
        return

    model_base_url = os.path.dirname(model_full_url) + "/"
    model_local_dir = os.path.dirname(model_local_path)

    asset_paths = []
    if file_refs.get("Moc"):
        asset_paths.append(file_refs["Moc"])
    if file_refs.get("Physics"):
        asset_paths.append(file_refs["Physics"])
    if file_refs.get("Pose"):
        asset_paths.append(file_refs["Pose"])
    asset_paths.extend(file_refs.get("Textures", []))
    for exp in file_refs.get("Expressions", []):
        if exp.get("File"):
            asset_paths.append(exp["File"])
    for motion_group in file_refs.get("Motions", {}).values():
        for motion in motion_group:
            if motion.get("File"):
                asset_paths.append(motion["File"])

    unique_assets = list(set(asset_paths))
    logging.info(f"[MODEL3] Found {len(unique_assets)} assets to download")

    for relative_asset_path in unique_assets:
        asset_url = urllib.parse.urljoin(model_base_url, relative_asset_path)
        local_asset_path = os.path.join(
            model_local_dir, *relative_asset_path.split("/")
        )
        result = download_file(asset_url, local_asset_path)
        if result:
            logging.info(f"[MODEL3] Downloaded asset: {relative_asset_path}")
        else:
            logging.warning(f"[MODEL3] Failed to download asset: {relative_asset_path}")


def process_spine_dir(dir_local_path, dir_full_url):
    """下载 spine 目录下的 .skel、.atlas 和 .webp 文件"""
    logging.info(f"[SPINE] Processing directory: {dir_full_url}")

    # 从 URL 中提取目录名
    parsed = urllib.parse.urlparse(dir_full_url)
    path = parsed.path.rstrip("/")
    dir_name = os.path.basename(path)

    # 文件基础名：去掉 "-spine" 后缀
    if dir_name.endswith("-spine"):
        file_basename = dir_name[:-6]  # 去掉 "-spine"
    else:
        file_basename = dir_name

    # 确保本地目录存在
    os.makedirs(dir_local_path, exist_ok=True)

    # 下载三种文件
    for ext in [".skel", ".atlas", ".webp"]:
        file_url = f"{dir_full_url}/{file_basename}{ext}"
        local_file_path = os.path.join(dir_local_path, f"{file_basename}{ext}")
        result = download_file(file_url, local_file_path)
        if result:
            logging.info(f"[SPINE] Downloaded: {file_basename}{ext}")
        else:
            logging.warning(f"[SPINE] Failed to download: {file_basename}{ext}")


def scan_local_resources():
    """扫描本地 live2d/azurlane 目录，返回已有的资源集合"""
    logging.info("[SCAN] Scanning local resources...")
    local_resources = set()
    live2d_dir = os.path.join("live2d", "azurlane")
    if os.path.exists(live2d_dir):
        for item in os.listdir(live2d_dir):
            if os.path.isdir(os.path.join(live2d_dir, item)):
                local_resources.add(item)
    logging.info(
        f"[SCAN] Found {len(local_resources)} local resources: {sorted(local_resources)}"
    )
    return local_resources


def extract_resource_dirname(url, resource_type):
    """从 URL 中提取资源目录名"""
    path = urllib.parse.urlparse(url).path.rstrip("/")
    parts = path.split("/")

    match resource_type:
        case "spine":
            # spine 的 URL 是目录路径，最后一部分就是目录名
            # 例如: /live2d/azurlane/niaohai_3-spine -> "niaohai_3-spine"
            return parts[-1]
        case "live2d":
            # live2d 的 URL 是文件路径，倒数第二部分是目录名
            # 例如: /live2d/azurlane/mingji_2/mingji_2.model3.json -> "mingji_2"
            return parts[-2]
        case _:
            # 默认按 live2d 处理
            return parts[-2]


def process_live2d_master_json(master_json_path):
    """处理 live2dMaster.json，下载模型资源并更新路径为本地相对路径"""
    # 1. 备份
    webversion_backup_path = master_json_path.replace(".json", "webversion.json")
    try:
        shutil.copyfile(master_json_path, webversion_backup_path)
    except (shutil.Error, IOError):
        pass

    # 2. 读取 JSON
    try:
        with open(master_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    local_resources = scan_local_resources()
    logging.info(f"Local resources found: {len(local_resources)}")

    # 用于存放需要下载的任务信息
    download_tasks = []

    # --- 第一步：遍历所有数据，更新路径并收集下载任务 ---
    for game in data.get("Master", []):
        for character in game.get("character", []):
            # 处理 Live2D
            for item in character.get("live2d", []):
                if "path" not in item:
                    continue

                original_url = item["path"]

                # 统一转换路径逻辑
                if original_url.startswith(STATIC_HOST):
                    relative_path = original_url[len(STATIC_HOST) :]
                else:
                    parsed = urllib.parse.urlparse(original_url)
                    relative_path = parsed.path.lstrip("/")
                relative_path = relative_path.replace("\\", "/")

                # 【关键】无论是否下载，都立即更新内存中的路径
                item["path"] = relative_path

                # 检查是否需要下载
                resource_dirname = extract_resource_dirname(original_url, "live2d")
                if resource_dirname not in local_resources:
                    download_tasks.append(
                        {
                            "type": "live2d",
                            "original_url": original_url,
                            "relative_path": relative_path,
                            "char_name": character.get("charNameEn", "Unknown"),
                            "costume_name": item.get("costumeNameEn", "Default"),
                        }
                    )

            # 处理 Spine
            for item in character.get("spine", []):
                if "path" not in item:
                    continue

                original_url = item["path"]

                # 转换路径逻辑
                if original_url.startswith(STATIC_HOST):
                    relative_path = original_url[len(STATIC_HOST) :]
                else:
                    parsed = urllib.parse.urlparse(original_url)
                    relative_path = parsed.path.lstrip("/")
                relative_path = relative_path.replace("\\", "/")

                item["path"] = relative_path

                # 检查是否需要下载
                resource_dirname = extract_resource_dirname(original_url, "spine")
                if resource_dirname not in local_resources:
                    download_tasks.append(
                        {
                            "type": "spine",
                            "original_url": original_url,
                            "relative_path": relative_path,
                            "char_name": character.get("charNameEn", "Unknown"),
                            "costume_name": item.get("costumeNameEn", "Default"),
                        }
                    )

    # --- 第二步：保存 JSON ---
    try:
        with open(master_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logging.info("Updated master JSON paths to local relative paths.")
    except IOError as e:
        logging.error(f"Failed to save master JSON: {e}")

    # --- 第三步：执行下载任务 (如果需要) ---
    total = len(download_tasks)
    if total == 0:
        logging.info("All resources exist, no download needed.")
        return

    logging.info(f"Resources to download: {total}")
    success_count = 0
    failed_items = []
    bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%] {postfix}"

    with tqdm(total=total, desc="Model sync", bar_format=bar_fmt, ncols=80) as pbar:
        for i, task in enumerate(download_tasks):
            item_type = task["type"]
            original_url = task["original_url"]
            relative_path = task["relative_path"]
            char_name = task["char_name"]
            costume_name = task["costume_name"]

            # 准备进度条显示
            spinner = SPINNERS[i % len(SPINNERS)]
            type_tag = "L2D" if item_type == "live2d" else "SPN"
            short_costume = (
                costume_name[:8] + ".." if len(costume_name) > 10 else costume_name
            )
            status_text = (
                f"{spinner} Downloading: {char_name} | {short_costume} | {type_tag}"
            )
            pbar.set_postfix_str(status_text, refresh=True)
            pbar.refresh()

            # 执行下载逻辑
            if item_type == "live2d":
                logging.info(f"[SYNC] Processing live2d: {char_name} - {costume_name}")

                # 转换为系统路径格式
                local_path = os.path.join(*relative_path.split("/"))

                # 下载主模型文件
                if download_file(original_url, local_path):
                    success_count += 1
                    logging.info(f"[SYNC] Processing model3.json for: {costume_name}")
                    # 下载子资源
                    process_model3_json(local_path, original_url)
                else:
                    logging.warning(
                        f"[SYNC] Failed to download: {char_name} - {costume_name}"
                    )
                    failed_items.append(f"{char_name} - {costume_name}")

            elif item_type == "spine":
                logging.info(f"[SYNC] Processing spine: {char_name} - {costume_name}")
                # Spine 下载逻辑
                local_path = os.path.join(*relative_path.split("/"))
                process_spine_dir(local_path, original_url)
                success_count += 1

            pbar.update(1)

    logging.info(f"Sync completed: {success_count}/{total} successful")
    if failed_items:
        logging.warning(f"Failed items ({len(failed_items)}):")
        for name in failed_items:
            logging.warning(f" - {name}")


def fetch_master_json():
    """
    获取 Master JSON 文件。
    优先直接下载，失败则尝试从 index.js 解析版本号下载。
    返回下载后的本地文件路径，失败返回 None。
    """
    logging.info("[MASTER] Starting fetch_master_json")
    os.makedirs(TARGET_SUBDIR, exist_ok=True)
    master_json_path = os.path.join(TARGET_SUBDIR, "live2dMaster.json")

    bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%] {postfix}"
    with tqdm(total=1, desc="Fetching data", bar_format=bar_fmt, ncols=80) as pbar:
        # 方案 A: 直接下载
        pbar.set_postfix_str("Direct fetch live2dMaster.json ...", refresh=True)
        logging.info("[MASTER] Trying direct fetch: live2dMaster.json")
        if download_file(MASTER_JSON_URL, master_json_path):
            pbar.update(1)
            pbar.set_postfix_str("Fetch successful", refresh=True)
            logging.info(f"[MASTER] Direct fetch successful: {master_json_path}")
            return master_json_path

        # 方案 B: 从 index.js 解析
        pbar.set_postfix_str("Direct fetch failed, trying index.js ...", refresh=True)
        logging.warning("[MASTER] Direct fetch failed, trying index.js")
        temp_js = f"index.temp.{int(time.time())}.js"
        if not download_file(INDEX_JS_URL, temp_js):
            pbar.set_postfix_str("Fetch failed", refresh=True)
            logging.error("[MASTER] Failed to fetch index.js")
            return None

        try:
            with open(temp_js, "r", encoding="utf-8") as f:
                js_content = f.read()

            match = re.search(
                r"'(./json/)?(live2dMaster.*?\.json)\?([a-zA-Z0-9]+)'", js_content
            )
            if not match:
                pbar.set_postfix_str("Version info not found", refresh=True)
                logging.error("[MASTER] Version info not found in index.js")
                return None

            json_name, version = match.group(2), match.group(3)
            json_url = urllib.parse.urljoin(BASE_URL, json_name)
            pbar.set_postfix_str(f"Version: {version}, downloading...", refresh=True)
            logging.info(f"[MASTER] Parsed version: {version}, URL: {json_url}")

            master_json_path = os.path.join(
                TARGET_SUBDIR, f"live2dMaster{version}.json"
            )
            if not download_file(json_url, master_json_path):
                pbar.set_postfix_str("Download failed", refresh=True)
                logging.error(f"[MASTER] Failed to download versioned JSON: {json_url}")
                return None

            # 保存修改后的 index.js
            modified = js_content.replace(
                match.group(0), f"'{TARGET_SUBDIR}/live2dMaster{version}.json'"
            )
            with open(
                os.path.join(TARGET_SUBDIR, FINAL_INDEX_JS_NAME),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(modified)
            logging.info(f"[MASTER] Saved modified index.js to {FINAL_INDEX_JS_NAME}")

            # 备份原始 js
            shutil.move(temp_js, os.path.join(TARGET_SUBDIR, f"index_{version}.js"))
            pbar.update(1)
            pbar.set_postfix_str("Fetch successful", refresh=True)
            logging.info(f"[MASTER] Fetch completed successfully: {master_json_path}")
            return master_json_path
        finally:
            if os.path.exists(temp_js):
                os.remove(temp_js)


def main():
    # 1. 初始化日志
    setup_logging()
    logging.info("=" * 50)
    logging.info("[START] Live2D Model Sync Started")
    logging.info("=" * 50)

    try:
        # 2. 获取数据
        logging.info("[MAIN] Fetching master JSON...")
        master_json_path = fetch_master_json()

        # 3. 处理资源
        if master_json_path:
            logging.info(f"[MAIN] Processing resources from: {master_json_path}")
            process_live2d_master_json(master_json_path)
        else:
            logging.warning(
                "[MAIN] No master JSON obtained, skipping resource processing"
            )

        logging.info("=" * 50)
        logging.info("[END] All tasks completed!")
        logging.info("=" * 50)
    except KeyboardInterrupt:
        # 捕获 Ctrl+C 中断
        print("\n")  # 打印一个空行，避免和进度条挤在一起
        logging.warning("[MAIN] (KeyboardInterrupt) Exiting...")


if __name__ == "__main__":
    main()
