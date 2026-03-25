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
            # logging.StreamHandler(), # 控制台查看
        ],
    )


def download_file(url, local_filepath):
    """下载文件，包含超时和重试逻辑。成功返回 True。"""
    try:
        local_dir = os.path.dirname(local_filepath)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
    except IOError:
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
            return True
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            pass
        except requests.exceptions.HTTPError as e:
            if 400 <= e.response.status_code < 500:
                return False
        except IOError:
            return False

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)

    return False


def process_model3_json(model_local_path, model_full_url):
    """解析 model3.json 并下载其引用的所有子资源"""
    try:
        with open(model_local_path, "r", encoding="utf-8") as f:
            model_data = json.load(f)
    except Exception:
        return

    file_refs = model_data.get("FileReferences", {})
    if not file_refs:
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

    for relative_asset_path in set(asset_paths):
        asset_url = urllib.parse.urljoin(model_base_url, relative_asset_path)
        local_asset_path = os.path.join(
            model_local_dir, *relative_asset_path.split("/")
        )
        download_file(asset_url, local_asset_path)


def process_spine_dir(dir_local_path, dir_full_url):
    """下载 spine 目录下的 .skel 和 .atlas 文件"""
    dir_name = os.path.basename(dir_full_url.rstrip("/"))
    for ext in [".skel", ".atlas"]:
        file_url = f"{dir_full_url}/{dir_name}{ext}"
        local_file_path = os.path.join(dir_local_path, f"{dir_name}{ext}")
        download_file(file_url, local_file_path)


def scan_local_resources():
    """扫描本地 live2d/azurlane 目录，返回已有的资源集合"""
    local_resources = set()
    live2d_dir = os.path.join("live2d", "azurlane")
    if os.path.exists(live2d_dir):
        for item in os.listdir(live2d_dir):
            if os.path.isdir(os.path.join(live2d_dir, item)):
                local_resources.add(item)
    return local_resources


def extract_resource_dirname(url, resource_type):
    """从 URL 中提取资源目录名"""
    path = urllib.parse.urlparse(url).path.rstrip("/")
    parts = path.split("/")
    if resource_type == "spine":
        return parts[-1]
    else:
        return parts[-2]


def process_live2d_master_json(master_json_path):
    """处理 live2dMaster.json，下载模型资源并更新路径为本地相对路径"""
    webversion_backup_path = master_json_path.replace(".json", "webversion.json")
    try:
        shutil.copyfile(master_json_path, webversion_backup_path)
    except (shutil.Error, IOError):
        pass

    try:
        with open(master_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    local_resources = scan_local_resources()
    logging.info(f"Local resources found: {len(local_resources)}")

    item_list = []
    for game in data.get("Master", []):
        for character in game.get("character", []):
            for item in character.get("live2d", []):
                if "path" in item:
                    resource_dirname = extract_resource_dirname(item["path"], "live2d")
                    if resource_dirname not in local_resources:
                        item["_charName"] = character.get("charNameEn", "Unknown")
                        item["_costumeName"] = item.get("costumeNameEn", "Default")
                        item["_type"] = "live2d"
                        item_list.append(item)
            # for item in character.get("spine", []):
            #     if "path" in item:
            #         resource_dirname = extract_resource_dirname(item["path"], "spine")
            # NEED SPINE PATH

    total = len(item_list)
    if total == 0:
        logging.info("All resources exist, no download needed")
        return

    logging.info(f"Resources to download: {total}")
    success_count = 0
    failed_items = []
    bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%] {postfix}"
    with tqdm(total=total, desc="Model sync", bar_format=bar_fmt, ncols=80) as pbar:
        for i, item in enumerate(item_list):
            item_type = item.get("_type", "live2d")
            char_name = item["_charName"]
            costume_name = item["_costumeName"]
            full_url = item["path"]

            if full_url.startswith(STATIC_HOST):
                relative_path = full_url[len(STATIC_HOST) :]
            else:
                parsed = urllib.parse.urlparse(full_url)
                relative_path = parsed.path.lstrip("/")
            relative_path = relative_path.replace("\\", "/")
            local_path = os.path.join(*relative_path.split("/"))

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

            if item_type == "live2d":
                if download_file(full_url, local_path):
                    success_count += 1
                    item["path"] = relative_path
                    process_model3_json(local_path, full_url)
                else:
                    failed_items.append(f"{char_name} - {costume_name}")

            elif item_type == "spine":
                os.makedirs(local_path, exist_ok=True)
                process_spine_dir(local_path, full_url)
                item["path"] = relative_path
                success_count += 1

            pbar.update(1)

    for item in item_list:
        item.pop("_charName", None)
        item.pop("_costumeName", None)
        item.pop("_type", None)

    try:
        with open(master_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError:
        pass

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
    os.makedirs(TARGET_SUBDIR, exist_ok=True)
    master_json_path = os.path.join(TARGET_SUBDIR, "live2dMaster.json")
    bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%] {postfix}"

    with tqdm(total=1, desc="Fetching data", bar_format=bar_fmt, ncols=80) as pbar:
        # 方案 A: 直接下载
        pbar.set_postfix_str("Direct fetch live2dMaster.json ...", refresh=True)
        if download_file(MASTER_JSON_URL, master_json_path):
            pbar.update(1)
            pbar.set_postfix_str("Fetch successful", refresh=True)
            return master_json_path

        # 方案 B: 从 index.js 解析
        pbar.set_postfix_str("Direct fetch failed, trying index.js ...", refresh=True)
        temp_js = f"index.temp.{int(time.time())}.js"

        if not download_file(INDEX_JS_URL, temp_js):
            pbar.set_postfix_str("Fetch failed", refresh=True)
            return None

        try:
            with open(temp_js, "r", encoding="utf-8") as f:
                js_content = f.read()

            match = re.search(
                r"'(./json/)?(live2dMaster.*?\.json)\?([a-zA-Z0-9]+)'", js_content
            )
            if not match:
                pbar.set_postfix_str("Version info not found", refresh=True)
                return None

            json_name, version = match.group(2), match.group(3)
            json_url = urllib.parse.urljoin(BASE_URL, json_name)
            pbar.set_postfix_str(f"Version: {version}, downloading...", refresh=True)

            master_json_path = os.path.join(
                TARGET_SUBDIR, f"live2dMaster{version}.json"
            )

            if not download_file(json_url, master_json_path):
                pbar.set_postfix_str("Download failed", refresh=True)
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

            # 备份原始 js
            shutil.move(temp_js, os.path.join(TARGET_SUBDIR, f"index_{version}.js"))
            pbar.update(1)
            pbar.set_postfix_str("Fetch successful", refresh=True)
            return master_json_path

        finally:
            if os.path.exists(temp_js):
                os.remove(temp_js)


def main():
    # 1. 初始化日志
    setup_logging()
    try:
        # 2. 获取数据
        master_json_path = fetch_master_json()

        # 3. 处理资源
        if master_json_path:
            process_live2d_master_json(master_json_path)

        logging.info("All tasks completed!")

    except KeyboardInterrupt:
        # 捕获 Ctrl+C 中断
        print("\n")  # 打印一个空行，避免和进度条挤在一起
        logging.warning("(KeyboardInterrupt)Exiting...")


if __name__ == "__main__":
    main()
