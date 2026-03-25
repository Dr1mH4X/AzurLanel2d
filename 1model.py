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

            if os.path.exists(local_filepath):
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
    # spine: https://static.l2d.su/live2d/azurlane/tansuozhe_2-spine
    # live2d: https://static.l2d.su/live2d/azurlane/xingdengbao_3/xingdengbao_3.model3.json

    path = urllib.parse.urlparse(url).path.rstrip("/")
    parts = path.split("/")

    if resource_type == "spine":
        # 返回最后一部分，如 tansuozhe_2-spine
        return parts[-1]
    else:  # live2d
        # 返回倒数第二部分，如 xingdengbao_3
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

    # 扫描本地已有的资源
    local_resources = scan_local_resources()
    logging.info(f"Local resources found: {len(local_resources)}")

    # 构建统一的下载列表，用 _type 区分 live2d / spine
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
            for item in character.get("spine", []):
                if "path" in item:
                    resource_dirname = extract_resource_dirname(item["path"], "spine")
                    if resource_dirname not in local_resources:
                        item["_charName"] = character.get("charNameEn", "Unknown")
                        item["_costumeName"] = item.get("costumeNameEn", "Default")
                        item["_type"] = "spine"
                        item_list.append(item)

    total = len(item_list)
    if total == 0:
        logging.info("All resources exist, no download needed")
        return

    logging.info(f"Resources to download: {total}")

    success_count = 0
    failed_items = []

    bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%]"
    with tqdm(total=total, desc="Model sync", bar_format=bar_fmt, ncols=80) as pbar:
        for i, item in enumerate(item_list):
            item_type = item.get("_type", "live2d")
            char_name = item["_charName"]
            costume_name = item["_costumeName"]
            full_url = item["path"]

            # 转换为本地相对路径
            if full_url.startswith(STATIC_HOST):
                relative_path = full_url[len(STATIC_HOST) :]
            else:
                parsed = urllib.parse.urlparse(full_url)
                relative_path = parsed.path.lstrip("/")
            relative_path = relative_path.replace("\\", "/")
            local_path = os.path.join(*relative_path.split("/"))

            # 右侧动态日志：旋转动画 + 角色名 + 服装名 + 类型
            spinner = SPINNERS[i % len(SPINNERS)]
            type_tag = "L2D" if item_type == "live2d" else "SPN"
            short_costume = (
                costume_name[:8] + ".." if len(costume_name) > 10 else costume_name
            )
            pbar.set_postfix_str(
                f"{spinner} {char_name}|{short_costume}|{type_tag}", refresh=False
            )
            pbar.refresh()

            if download_file(full_url, local_path):
                success_count += 1
                item["path"] = relative_path

                # 根据类型处理子资源
                if item_type == "live2d":
                    process_model3_json(local_path, full_url)
                elif item_type == "spine":
                    # Spine 直接创建目录并处理，不需要下载主 URL
                    os.makedirs(local_path, exist_ok=True)
                    process_spine_dir(local_path, full_url)
                    item["path"] = relative_path
                    success_count += 1
            else:
                failed_items.append(f"{char_name} - {costume_name}")

            pbar.update(1)

    # 清理临时元数据
    for item in item_list:
        item.pop("_charName", None)
        item.pop("_costumeName", None)
        item.pop("_type", None)

    # 保存更新后的 JSON
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


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file_path = os.path.join(script_dir, "log.txt")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file_path, encoding="utf-8", mode="w"),  # 写入文件
            # logging.StreamHandler(),  # 输出到控制台
        ],
    )
    os.makedirs(TARGET_SUBDIR, exist_ok=True)
    master_json_path = os.path.join(TARGET_SUBDIR, "live2dMaster.json")

    # --- 阶段 1: 获取 master JSON ---
    # 方案 A: 直接访问 live2dMaster.json
    bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%]"
    with tqdm(total=1, desc="Fetching data", bar_format=bar_fmt, ncols=80) as pbar:
        pbar.set_postfix_str("Direct fetch live2dMaster.json ...", refresh=True)
        if download_file(MASTER_JSON_URL, master_json_path):
            pbar.update(1)
            pbar.set_postfix_str("Fetch successful", refresh=True)
        else:
            # 方案 B: 从 index.js 提取版本号（fallback）
            pbar.set_postfix_str(
                "Direct fetch failed, trying index.js ...", refresh=True
            )
            temp_js = f"index.temp.{int(time.time())}.js"
            if not download_file(INDEX_JS_URL, temp_js):
                pbar.set_postfix_str("Fetch failed", refresh=True)
                return

            try:
                with open(temp_js, "r", encoding="utf-8") as f:
                    js_content = f.read()

                match = re.search(
                    r"'(./json/)?(live2dMaster.*?\.json)\?([a-zA-Z0-9]+)'", js_content
                )
                if not match:
                    pbar.set_postfix_str("Version info not found", refresh=True)
                    return

                json_name, version = match.group(2), match.group(3)
                json_url = urllib.parse.urljoin(BASE_URL, json_name)

                pbar.set_postfix_str(
                    f"Version: {version}, downloading...", refresh=True
                )
                master_json_path = os.path.join(
                    TARGET_SUBDIR, f"live2dMaster{version}.json"
                )

                if not download_file(json_url, master_json_path):
                    pbar.set_postfix_str("Download failed", refresh=True)
                    return

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
            finally:
                if os.path.exists(temp_js):
                    os.remove(temp_js)

    # --- 阶段 2: 下载模型资源 ---
    process_live2d_master_json(master_json_path)
    logging.info("All tasks completed!")


if __name__ == "__main__":
    main()
