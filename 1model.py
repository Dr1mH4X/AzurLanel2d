import json
import os
import re
import shutil
import time
import urllib.parse

import requests

# --- 配置 ---
# 网络请求设置
MAX_RETRIES = 5  # 最大重试次数
RETRY_DELAY = 10  # 每次重试前的等待时间（秒）
TIMEOUT = (10, 30)  # 连接超时10秒，读取超时30秒

# URL和路径设置
INDEX_JS_URL = "https://l2d.su/json/index.js"
BASE_URL = "https://l2d.su/json/"
STATIC_HOST = "https://static.l2d.su/"

TARGET_SUBDIR = "json"
FINAL_INDEX_JS_NAME = "index.js"
TEMP_INDEX_JS_NAME = f"index.temp.{int(time.time())}.js"

# 全局会话，提高下载效率
session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
)


def download_file(url, local_filepath):
    """
    使用全局会话下载文件，并包含超时和重试逻辑。
    """
    # 确保目录存在，这个操作只需要执行一次
    try:
        local_dir = os.path.dirname(local_filepath)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
    except IOError as e:
        print(f"\n  X 创建目录失败: {local_dir} | 原因: {e}")
        return False

    for attempt in range(MAX_RETRIES):
        try:
            # 尝试下载
            print(f"  -> 正在下载 (尝试 {attempt + 1}/{MAX_RETRIES}): {url}", end="\r")
            response = session.get(url, stream=True, timeout=TIMEOUT)

            # 检查HTTP状态码，如果是4xx或5xx，则抛出异常
            response.raise_for_status()

            # 写入文件
            with open(local_filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"  √ 下载成功: {local_filepath:<80}")
            return True  # 下载成功，立即返回

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            # 处理网络问题：超时或连接错误
            print(f"\n  ! 网络问题 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")

        except requests.exceptions.HTTPError as e:
            # 处理HTTP错误，例如 404, 503
            status_code = e.response.status_code
            print(
                f"\n  ! HTTP错误 {status_code} (尝试 {attempt + 1}/{MAX_RETRIES}): {url}"
            )
            # 如果是客户端错误(4xx)，比如404 Not Found，重试无用，直接失败
            if 400 <= status_code < 500:
                print("  X 客户端错误，文件不存在或无权限，停止重试。")
                return False
            # 其他错误（如服务器5xx错误）可以继续重试

        except IOError as e:
            # 处理文件写入错误
            print(f"\n  X 保存文件失败: {local_filepath} | 原因: {e}")
            return False  # 磁盘问题，重试无用

        # 如果不是最后一次尝试，则等待后重试
        if attempt < MAX_RETRIES - 1:
            print(f"  ... {RETRY_DELAY}秒后重试 ...")
            time.sleep(RETRY_DELAY)

    # 如果所有尝试都失败了
    print(f"\n  X 最终失败: 经过 {MAX_RETRIES} 次尝试后，下载 {url} 仍失败。")
    return False


# ----- 后续函数 (process_model3_json, process_live2d_master_json, main) 保持不变 -----
# ----- 因为它们都调用了 download_file，所以会自动继承新的健壮性 -----


def process_model3_json(model_local_path, model_full_url):
    """解析 model3.json 文件并下载其所有引用的资源"""
    print(f"    解析资源: {model_local_path}")
    try:
        with open(model_local_path, "r", encoding="utf-8") as f:
            model_data = json.load(f)
    except Exception as e:
        print(f"    X 解析失败: {e}")
        return

    file_refs = model_data.get("FileReferences", {})
    if not file_refs:
        print("    ! 未找到 FileReferences，跳过资源下载。")
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


def process_live2d_master_json(master_json_path, version_string):
    """处理live2dMaster.json，下载模型、资源并更新路径"""
    print("\n--- 阶段 2: 处理 live2dMaster JSON 文件和模型资源 ---")
    webversion_backup_path = os.path.join(
        TARGET_SUBDIR, f"live2dMaster{version_string}webversion.json"
    )
    try:
        shutil.copyfile(master_json_path, webversion_backup_path)
        print(f"已创建Web版本备份: {webversion_backup_path}")
    except (shutil.Error, IOError) as e:
        print(f"创建备份文件失败: {e}")
        return

    try:
        with open(master_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"读取或解析 {master_json_path} 失败: {e}")
        return

    path_list = []
    for game in data.get("Master", []):
        for character in game.get("character", []):
            for live2d_item in character.get("live2d", []):
                if "path" in live2d_item:
                    live2d_item["_charName"] = character.get("charName", "未知角色")
                    live2d_item["_costumeName"] = live2d_item.get("costumeName", "默认")
                    path_list.append(live2d_item)

    total_models = len(path_list)
    print(f"共找到 {total_models} 个模型需要处理。")
    downloaded_count = 0
    for i, live2d_item in enumerate(path_list):
        full_url = live2d_item["path"]

        if full_url.startswith(STATIC_HOST):
            relative_path = full_url[len(STATIC_HOST) :]
        else:
            parsed_url = urllib.parse.urlparse(full_url)
            relative_path = parsed_url.path.lstrip("/")

        relative_path = relative_path.replace("\\", "/")
        local_model_path = os.path.join(*relative_path.split("/"))

        print(
            f"\n[{i + 1}/{total_models}] 处理: {live2d_item['_charName']} - {live2d_item['_costumeName']}"
        )

        if download_file(full_url, local_model_path):
            downloaded_count += 1
            live2d_item["path"] = relative_path.replace("\\", "/")
            print(f"  * 路径已更新为: {live2d_item['path']}")
            process_model3_json(local_model_path, full_url)
        else:
            print(f"  X 模型主文件 {full_url} 下载失败，将跳过此模型的所有资源。")

    for item in path_list:
        del item["_charName"]
        del item["_costumeName"]

    print(f"\n--- 模型处理完成 ---")
    print(f"成功下载 {downloaded_count} / {total_models} 个模型的主文件及其资源。")
    try:
        with open(master_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"已成功更新并保存修改后的主文件: {master_json_path}")
    except IOError as e:
        print(f"回写 {master_json_path} 失败: {e}")


def main():
    """主执行函数"""
    os.makedirs(TARGET_SUBDIR, exist_ok=True)
    print(f"--- 阶段 1: 更新JS和主JSON文件 ---")
    print(f"已确保目录 '{TARGET_SUBDIR}/' 存在。")

    if not download_file(INDEX_JS_URL, TEMP_INDEX_JS_NAME):
        return

    try:
        with open(TEMP_INDEX_JS_NAME, "r", encoding="utf-8") as f:
            index_js_content = f.read()
    except IOError as e:
        print(f"读取临时文件失败: {e}")
        os.remove(TEMP_INDEX_JS_NAME)
        return

    pattern = re.compile(r"'(./json/)?(live2dMaster.*?\.json)\?([a-zA-Z0-9]+)'")
    match = pattern.search(index_js_content)

    if not match:
        print("错误: 在 index.js 中未找到 live2dMaster.json 的版本信息。")
        os.remove(TEMP_INDEX_JS_NAME)
        return

    original_fetch_path_str, json_filename_from_js, version_string = (
        match.groups(0)[0],
        match.group(2),
        match.group(3),
    )
    print(f"成功找到信息: 版本号 -> {version_string}")

    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            print(f"version_string={version_string}", file=f)

    json_download_url = urllib.parse.urljoin(BASE_URL, json_filename_from_js)
    new_json_filename = f"live2dMaster{version_string}.json"
    master_json_path = os.path.join(TARGET_SUBDIR, new_json_filename)

    if not download_file(json_download_url, master_json_path):
        os.remove(TEMP_INDEX_JS_NAME)
        return

    new_local_path_in_js = f"'{TARGET_SUBDIR}/{new_json_filename}'"
    modified_content = index_js_content.replace(match.group(0), new_local_path_in_js)

    final_index_js_path = os.path.join(TARGET_SUBDIR, FINAL_INDEX_JS_NAME)
    with open(final_index_js_path, "w", encoding="utf-8") as f:
        f.write(modified_content)
    print(f"已创建修改后的主文件: {final_index_js_path}")

    original_js_backup_name = f"index_{version_string}.js"
    backup_save_path = os.path.join(TARGET_SUBDIR, original_js_backup_name)
    shutil.move(TEMP_INDEX_JS_NAME, backup_save_path)
    print(f"原始JS文件已备份为: {backup_save_path}")

    process_live2d_master_json(master_json_path, version_string)

    print("\n所有任务执行完毕！")


if __name__ == "__main__":
    main()
