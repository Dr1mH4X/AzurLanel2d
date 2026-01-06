import os
import json
import re
import shutil
import urllib.parse
import requests

# --- 配置 ---
ROOT_DIR = '.' # 假设脚本在项目根目录下运行
LIVE2D_DIR = os.path.join(ROOT_DIR, 'live2d', 'azurlane')
JSON_DIR = os.path.join(ROOT_DIR, 'json')
MAX_RETRIES = 3  # 最大重试次数
RETRY_DELAY = 5  # 每次重试前的等待时间（秒）
TIMEOUT = (10, 30)  # 连接超时10秒，读取超时30秒
# 全局会话，提高下载效率
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

def download_file(url, local_filepath):
    """下载文件，包含超时和重试机制"""
    try:
        local_dir = os.path.dirname(local_filepath)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True) # 确保目录存在
            
        print(f"  -> 正在下载: {url}")
        response = session.get(url, stream=True, timeout=TIMEOUT)
        response.raise_for_status() # 检查HTTP状态码，如果是4xx或5xx，则抛出异常
        with open(local_filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        # print(f"     成功保存到: {local_filepath}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"     下载文件失败: {e}")
        return False
    except IOError as e:
        print(f"     保存文件失败: {e}")
        return False

def get_latest_version(json_dir):
    """获取最新的live2dMaster版本号"""
    pattern = re.compile(r"live2dMaster(.*?)\.json")
    versions = []
    for filename in os.listdir(json_dir):
        match = pattern.match(filename)
        if match:
            versions.append(match.group(1))

    if not versions:
        print("错误：未找到任何 live2dMaster JSON 文件。")
        return None

    # 找到名称排序后的最后一个版本号
    latest_version = sorted(versions)[-1]
    return latest_version

def process_audio(model3_path, version):
    """处理model3.json中的Audio项，下载音频并修改JSON"""
    try:
        # 1. 备份原始文件
        backup_path = model3_path.replace(".model3.json", f"{version}webversion.model3.json")
        shutil.copyfile(model3_path, backup_path)
        print(f"已备份文件: {backup_path}")

        # 2. 读取 JSON 文件
        with open(model3_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 3. 遍历 motions 并下载音频
        motions = data.get('FileReferences', {}).get('Motions', {})
        if not motions:
            print(f"  未找到 motions，跳过")
            return

       # 核心逻辑：遍历所有Motion，下载Audio，修改JSON
        audio_found = False
        for group_name, motion_list in motions.items():
            for motion in motion_list:
                if 'Audio' in motion:
                    audio_url = motion['Audio']
                    # 构建本地保存路径
                    audio_filename = os.path.basename(audio_url)
                    audio_dir = os.path.join(os.path.dirname(model3_path), 'audio')
                    local_audio_path = os.path.join(audio_dir, audio_filename).replace("\\","/")

                    # 下载音频文件
                    if download_file(audio_url, local_audio_path):
                        # 修改 JSON
                        motion['Audio'] = os.path.relpath(local_audio_path, os.path.dirname(model3_path)).replace("\\","/")
                        audio_found = True
                        # print(f"     Audio路径已更新为: {motion['Audio']}")
                    else:
                        print(f"  X 下载Audio文件失败: {audio_url}")
        
        if not audio_found:
          print(f"  -- 未找到需要处理的Audio链接")
          return

        # 4. 保存修改后的 JSON
        with open(model3_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"  -> 音频下载并更新JSON成功: {model3_path}")

    except Exception as e:
        print(f"处理文件 {model3_path} 失败：{e}")

def main():
    """主函数"""
    # 1. 获取最新的版本号
    version = get_latest_version(JSON_DIR)
    if not version:
        return

    print(f"使用版本号：{version}")

    # 2. 遍历 live2d/azurlane 目录
    for root, _, files in os.walk(LIVE2D_DIR):
        for filename in files:
            if filename.endswith(".model3.json"):
                model3_path = os.path.join(root, filename)
                print(f"处理文件：{model3_path}")
                process_audio(model3_path, version)

    print("所有音频处理完成！")

if __name__ == "__main__":
    main()
