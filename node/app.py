#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Node - 雲端硬碟儲存節點
負責實際的檔案儲存與讀取
使用 SQLite 資料庫儲存元數據
"""

import os
import json
import uuid
import hashlib
import time
import sqlite3
import shutil
import mimetypes
import requests
import threading
import zipfile
import io
from functools import wraps
from flask import Flask, request, jsonify, send_file, abort

# 設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

# 讀取配置
config = {}
config_path = os.path.join(BASE_DIR, 'config.yml')
if os.path.exists(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
        for line in content.split('\n'):
            if ':' in line and not line.strip().startswith('#'):
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    config[key] = value

NODE_UUID = config.get('uuid', '')
TOKEN_ID = config.get('token_id', '')
NODE_TOKEN = config.get('token', '')

# 解析 node 區塊
node_config = {}
if 'node' in config:
    # config.yml 可能把 node 區塊當作字串
    pass

# 嘗試讀取 node 子配置
NODE_NAME = 'Unnamed Node'
HOST = '0.0.0.0'
PORT = 5001
MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_STORAGE = 0
DATA_DIR = 'storage'
HEARTBEAT_INTERVAL = 30
PANEL_URL = 'http://localhost:5000'

# 嘗試從 config.yml 讀取 node 區塊的設置
# 解析 Yaml 風格的 node 區塊
node_lines = []
in_node_block = False
for line in content.split('\n'):
    if line.strip().startswith('node:'):
        in_node_block = True
        continue
    if in_node_block:
        if line and not line.startswith(' ') and not line.startswith('\t'):
            in_node_block = False
            break
        if ':' in line:
            node_lines.append(line)

for node_line in node_lines:
    if ':' in node_line:
        key, value = node_line.split(':', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == 'name':
            NODE_NAME = value
        elif key == 'host':
            HOST = value
        elif key == 'port':
            try:
                PORT = int(value)
            except:
                pass
        elif key == 'max_file_size':
            try:
                MAX_FILE_SIZE = int(value)
            except:
                pass
        elif key == 'max_storage_size':
            try:
                MAX_STORAGE = int(value)
            except:
                pass
        elif key == 'data':
            DATA_DIR = value

# 讀取其他配置
try:
    HEARTBEAT_INTERVAL = int(config.get('heartbeat_interval', 30))
except:
    pass
PANEL_URL = config.get('panel_url', 'http://localhost:5000')

# 確保儲存目錄存在
STORAGE_DIR = os.path.join(BASE_DIR, DATA_DIR)
os.makedirs(STORAGE_DIR, exist_ok=True)

# 確保數據目錄存在
NODE_DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(NODE_DATA_DIR, exist_ok=True)

# 資料庫路徑
DB_PATH = os.path.join(NODE_DATA_DIR, 'node.db')

# ==================== 資料庫管理 ====================

def get_db():
    """取得資料庫連線"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """初始化資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 檔案表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            size INTEGER DEFAULT 0,
            user_id TEXT,
            uploaded_at REAL,
            checksum TEXT,
            path TEXT DEFAULT '',
            folder TEXT DEFAULT ''
        )
    ''')
    
    # 資料夾表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            user_id TEXT,
            created_at REAL,
            path TEXT DEFAULT ''
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"節點資料庫初始化完成: {DB_PATH}")

# ==================== 檔案操作 ====================

def load_files():
    """從資料庫載入檔案"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM files')
    files = {}
    for row in cursor.fetchall():
        files[row['id']] = dict(row)
    conn.close()
    return files

def save_file_record(file_id, name, size, user_id, checksum, path, folder):
    """儲存檔案記錄到資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO files (id, name, size, user_id, uploaded_at, checksum, path, folder)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (file_id, name, size, user_id, time.time(), checksum, path, folder))
    conn.commit()
    conn.close()

def delete_file_record(file_id):
    """從資料庫刪除檔案記錄"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
    conn.commit()
    conn.close()

def load_folders():
    """從資料庫載入資料夾"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM folders')
    folders = {}
    for row in cursor.fetchall():
        folders[row['id']] = dict(row)
    conn.close()
    return folders

def save_folder_record(folder_id, name, user_id, path):
    """儲存資料夾記錄到資料庫"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO folders (id, name, user_id, created_at, path)
        VALUES (?, ?, ?, ?, ?)
    ''', (folder_id, name, user_id, time.time(), path))
    conn.commit()
    conn.close()

def delete_folder_record(folder_path, user_id):
    """從資料庫刪除資料夾記錄"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM folders WHERE path = ? AND user_id = ?', (folder_path, user_id))
    conn.commit()
    conn.close()

# ==================== 節點綁定 ====================

def bind_to_panel():
    """綁定到 Panel（兩步驟）"""
    global NODE_UUID
    
    if not TOKEN_ID or not NODE_TOKEN:
        print("錯誤: 缺少 token_id 或 token 配置")
        return False
    
    if not PANEL_URL:
        print("錯誤: 缺少 panel_url 配置")
        return False
    
    # 第一步：驗證 token_id
    try:
        verify_response = requests.post(
            f"{PANEL_URL}/api/node/verify",
            json={'token_id': TOKEN_ID},
            timeout=10
        )
        verify_result = verify_response.json()
        
        if not verify_result.get('success'):
            print(f"節點驗證失敗: {verify_result.get('error')}")
            return False
        
        print("Token ID 驗證成功，正在進行綁定...")
        
    except Exception as e:
        print(f"連接 Panel 驗證失敗: {e}")
        return False
    
    # 第二步：發送 token 進行綁定
    try:
        bind_response = requests.post(
            f"{PANEL_URL}/api/node/bind",
            json={
                'token_id': TOKEN_ID,
                'token': NODE_TOKEN,
                'uuid': NODE_UUID,
                'name': NODE_NAME,
                'host': HOST,
                'port': PORT,
                'capacity': get_storage_info()['capacity']
            },
            timeout=10
        )
        bind_result = bind_response.json()
        
        if bind_result.get('success'):
            if bind_result.get('node_id'):
                NODE_UUID = bind_result['node_id']
                # 更新 config.yml 中的 uuid
                update_config_uuid(NODE_UUID)
            print(f"節點綁定成功: {bind_result.get('message')}")
            return True
        else:
            print(f"節點綁定失敗: {bind_result.get('error')}")
            return False
            
    except Exception as e:
        print(f"連接 Panel 綁定失敗: {e}")
        return False

def update_config_uuid(new_uuid):
    """更新 config.yml 中的 uuid"""
    try:
        config_path = os.path.join(BASE_DIR, 'config.yml')
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 更新 uuid 行
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            if line.strip().startswith('uuid:'):
                new_lines.append(f'uuid: "{new_uuid}"')
            else:
                new_lines.append(line)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines))
        
        print(f"已更新 config.yml 中的 uuid 為: {new_uuid}")
    except Exception as e:
        print(f"更新 uuid 失敗: {e}")

def send_heartbeat():
    """發送心跳"""
    global HEARTBEAT_INTERVAL
    
    if not TOKEN_ID or not NODE_TOKEN:
        return False
    
    try:
        response = requests.post(
            f"{PANEL_URL}/api/node/heartbeat",
            json={
                'token_id': TOKEN_ID,
                'token': NODE_TOKEN,
                'capacity': get_storage_info()['capacity'],
                'used': get_storage_info()['used']
            },
            timeout=10
        )
        result = response.json()
        if result.get('success'):
            print(f"心跳發送成功")
            return True
        else:
            print(f"心跳發送失敗: {result.get('error')}")
            return False
    except Exception as e:
        print(f"心跳發送失敗: {e}")
        return False

def heartbeat_loop():
    """心跳迴圈"""
    global HEARTBEAT_INTERVAL
    
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        if TOKEN_ID and NODE_TOKEN:
            send_heartbeat()

# ==================== 認證 ====================

def verify_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 檢查請求是否來自本機（Panel 和 Node 同一台機器時允許）
        # 這樣 Panel 可以直接調用 Node API，無需額外驗證
        request_host = request.host.split(':')[0]
        is_local = request_host in ['localhost', '127.0.0.1', '::1'] or request.remote_addr == '127.0.0.1'
        
        # 從本機來的請求視為來自 Panel，已通過 Panel 的認證
        if is_local:
            return f(*args, **kwargs)
        
        # 非本機請求需要通過 Node Token 驗證
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            if token == NODE_TOKEN:
                return f(*args, **kwargs)
        
        token = request.args.get('token', '')
        if token == NODE_TOKEN:
            return f(*args, **kwargs)
        
        # 也支援 token_id + token 的驗證方式
        token_id = request.headers.get('X-Token-Id', '')
        if token_id == TOKEN_ID and token == NODE_TOKEN:
            return f(*args, **kwargs)
        
        return jsonify({'success': False, 'error': '未授權'}), 401
    return decorated_function

# ==================== 節點 API ====================

@app.route('/api/node/info', methods=['GET'])
@verify_token
def node_info():
    storage_info = get_storage_info()
    return jsonify({
        'success': True,
        'uuid': NODE_UUID,
        'name': NODE_NAME,
        'capacity': storage_info['capacity'],
        'used': storage_info['used'],
        'available': storage_info['available']
    })

def get_storage_info():
    """獲取儲存空間資訊"""
    total = MAX_STORAGE
    used = 0
    
    for root, dirs, files in os.walk(STORAGE_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                used += os.path.getsize(file_path)
            except:
                pass
    
    if total == 0:
        total = used + (100 * 1024 * 1024 * 1024)  # 預設 100GB
    
    return {
        'capacity': total,
        'used': used,
        'available': total - used
    }

# ==================== 檔案儲存 API ====================

@app.route('/api/node/store', methods=['POST'])
@verify_token
def store_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '無檔案'}), 400
    
    file = request.files['file']
    file_id = request.form.get('file_id', str(uuid.uuid4()))
    user_id = request.form.get('user_id', 'unknown')
    folder = request.form.get('folder', '').strip()
    
    if file.filename == '':
        return jsonify({'success': False, 'error': '檔案名稱為空'}), 400
    
    filename = os.path.basename(file.filename)
    if '..' in filename or '/' in filename:
        return jsonify({'success': False, 'error': '無效的檔案名稱'}), 400
    
    # 處理資料夾路徑
    user_dir = os.path.join(STORAGE_DIR, user_id)
    if folder:
        user_dir = os.path.join(user_dir, folder)
    os.makedirs(user_dir, exist_ok=True)
    
    file_path = os.path.join(user_dir, file_id)
    
    content = file.read()
    size = len(content)
    
    if MAX_STORAGE > 0:
        storage_info = get_storage_info()
        if storage_info['used'] + size > storage_info['capacity']:
            return jsonify({'success': False, 'error': '儲存空間不足'}), 400
    
    if MAX_FILE_SIZE > 0 and size > MAX_FILE_SIZE:
        return jsonify({'success': False, 'error': '檔案過大'}), 400
    
    with open(file_path, 'wb') as f:
        f.write(content)
    
    checksum = hashlib.md5(content).hexdigest()
    
    # 儲存到資料庫（包含路徑）
    save_file_record(file_id, filename, size, user_id, checksum, filename, folder)
    
    return jsonify({
        'success': True, 
        'file_id': file_id, 
        'checksum': checksum,
        'size': size,
        'folder': folder,
        'name': filename
    })

@app.route('/api/node/retrieve/<file_id>', methods=['GET'])
@verify_token
def retrieve_file(file_id):
    files = load_files()
    
    if file_id not in files:
        return jsonify({'success': False, 'error': '檔案不存在'}), 404
    
    file_info = files[file_id]
    user_id = file_info.get('user_id', 'unknown')
    folder = file_info.get('folder', '')
    
    # 建構檔案的完整路徑
    user_dir = os.path.join(STORAGE_DIR, user_id)
    if folder:
        user_dir = os.path.join(user_dir, folder)
    file_path = os.path.join(user_dir, file_id)
    
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': '檔案不存在'}), 404
    
    filename = file_info.get('name', 'file')
    
    try:
        return send_file(file_path, download_name=filename, as_attachment=True)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/node/batch-download', methods=['POST'])
@verify_token
def batch_download():
    """批次下載多個檔案為 ZIP 壓縮檔"""
    data = request.get_json() or {}
    file_ids = data.get('file_ids', [])
    folder_path = data.get('folder_path', '')
    user_id = data.get('user_id', 'unknown')
    
    if not file_ids:
        return jsonify({'success': False, 'error': '請選擇要下載的檔案'}), 400
    
    files = load_files()
    
    # 創建記憶體中的 ZIP 檔案
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_id in file_ids:
            if file_id not in files:
                continue
            
            file_info = files[file_id]
            folder = file_info.get('folder', '')
            
            # 建構檔案的完整路徑
            user_dir = os.path.join(STORAGE_DIR, user_id)
            if folder:
                user_dir = os.path.join(user_dir, folder)
            file_path = os.path.join(user_dir, file_id)
            
            if os.path.exists(file_path):
                # 使用原始檔案名稱作為 ZIP 內的檔案名稱
                filename = file_info.get('name', file_id)
                if folder_path:
                    # 如果有指定資料夾路徑，將檔案放入 ZIP 中的該資料夾
                    arcname = os.path.join(folder_path, filename)
                else:
                    arcname = filename
                zipf.write(file_path, arcname)
    
    zip_buffer.seek(0)
    
    # 生成 ZIP 檔案名稱
    zip_name = f"download_{int(time.time())}.zip"
    
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_name
    )

@app.route('/api/node/delete/<file_id>', methods=['DELETE'])
@verify_token
def delete_file(file_id):
    files = load_files()
    
    if file_id not in files:
        return jsonify({'success': False, 'error': '檔案不存在'}), 404
    
    file_info = files[file_id]
    user_id = file_info.get('user_id', 'unknown')
    folder = file_info.get('folder', '')
    
    # 建構檔案的完整路徑
    user_dir = os.path.join(STORAGE_DIR, user_id)
    if folder:
        user_dir = os.path.join(user_dir, folder)
    file_path = os.path.join(user_dir, file_id)
    
    if os.path.exists(file_path):
        os.remove(file_path)
    
    # 從資料庫刪除
    delete_file_record(file_id)
    
    return jsonify({'success': True})

# ==================== 資料夾 API ====================

@app.route('/api/node/folder/create', methods=['POST'])
@verify_token
def create_folder():
    data = request.get_json() or {}
    user_id = data.get('user_id', 'unknown')
    folder_path = data.get('folder_path', '').strip()
    
    if not folder_path:
        return jsonify({'success': False, 'error': '請輸入資料夾名稱'}), 400
    
    if '..' in folder_path:
        return jsonify({'success': False, 'error': '無效的路徑'}), 400
    
    user_dir = os.path.join(STORAGE_DIR, user_id)
    full_path = os.path.join(user_dir, folder_path)
    
    if os.path.exists(full_path):
        return jsonify({'success': False, 'error': '資料夾已存在'}), 400
    
    os.makedirs(full_path, exist_ok=True)
    
    # 儲存到資料庫
    folder_id = str(uuid.uuid4())
    save_folder_record(folder_id, os.path.basename(folder_path), user_id, folder_path)
    
    return jsonify({'success': True})

@app.route('/api/node/folder/delete', methods=['POST'])
@verify_token
def delete_folder():
    data = request.get_json() or {}
    user_id = data.get('user_id', 'unknown')
    folder_path = data.get('folder_path', '').strip()
    
    if not folder_path or folder_path == '/':
        return jsonify({'success': False, 'error': '無法刪除根目錄'}), 400
    
    if '..' in folder_path:
        return jsonify({'success': False, 'error': '無效的路徑'}), 400
    
    # 先計算要刪除的檔案大小
    deleted_size = calculate_folder_size(user_id, folder_path)
    
    user_dir = os.path.join(STORAGE_DIR, user_id)
    full_path = os.path.join(user_dir, folder_path)
    
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'error': '資料夾不存在'}), 404
    
    if os.path.isdir(full_path):
        shutil.rmtree(full_path)
    
    # 從資料庫刪除該資料夾及其所有子資料夾和檔案
    delete_folder_and_contents(user_id, folder_path)
    
    return jsonify({'success': True, 'deleted_size': deleted_size})

def calculate_folder_size(user_id, folder_path):
    """計算資料夾內所有檔案的總大小"""
    folder_path = normalize_path(folder_path)
    prefix = folder_path + '/' if folder_path else ''
    
    files = load_files()
    total_size = 0
    
    for file_id, file_info in files.items():
        if file_info.get('user_id') == user_id:
            f_folder = normalize_path(file_info.get('folder', ''))
            if f_folder == folder_path or f_folder.startswith(prefix):
                total_size += file_info.get('size', 0)
    
    return total_size

def delete_folder_and_contents(user_id, folder_path):
    """刪除資料夾及其所有子資料夾和檔案的資料庫記錄"""
    folder_path = normalize_path(folder_path)
    prefix = folder_path + '/' if folder_path else ''
    
    folders = load_folders()
    files = load_files()
    
    # 找出要刪除的資料夾記錄
    folders_to_delete = []
    for folder_id, folder_info in folders.items():
        if folder_info.get('user_id') == user_id:
            f_path = normalize_path(folder_info.get('path', ''))
            if f_path == folder_path or f_path.startswith(prefix):
                folders_to_delete.append(folder_id)
    
    # 找出要刪除的檔案記錄
    files_to_delete = []
    for file_id, file_info in files.items():
        if file_info.get('user_id') == user_id:
            f_folder = normalize_path(file_info.get('folder', ''))
            if f_folder == folder_path or f_folder.startswith(prefix):
                files_to_delete.append(file_id)
    
    # 刪除檔案記錄
    for file_id in files_to_delete:
        delete_file_record(file_id)
    
    # 刪除資料夾記錄
    for folder_id in folders_to_delete:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM folders WHERE id = ?', (folder_id,))
        conn.commit()
        conn.close()

@app.route('/api/node/folder/move', methods=['POST'])
@verify_token
def move_folder():
    data = request.get_json() or {}
    user_id = data.get('user_id', 'unknown')
    source_path = data.get('source_path', '').strip()
    target_path = data.get('target_path', '').strip()

    if not source_path:
        return jsonify({'success': False, 'error': '來源路徑不能為空'}), 400

    if '..' in source_path or '..' in target_path:
        return jsonify({'success': False, 'error': '不支持路徑中使用 ..'}), 400

    # 檢查目標是否是來源的子資料夾（防止循環移動）
    if target_path.startswith(source_path + '/'):
        return jsonify({'success': False, 'error': '不能將資料夾移動到其子資料夾'}), 400

    user_dir = os.path.join(STORAGE_DIR, user_id)
    source_full_path = os.path.join(user_dir, source_path)
    target_full_path = os.path.join(user_dir, target_path) if target_path else user_dir

    if not os.path.exists(source_full_path):
        return jsonify({'success': False, 'error': '來源資料夾不存在'}), 404

    if not os.path.isdir(source_full_path):
        return jsonify({'success': False, 'error': '來源路徑不是資料夾'}), 400

    # 確保目標資料夾存在
    os.makedirs(target_full_path, exist_ok=True)

    # 獲取來源資料夾名稱
    folder_name = os.path.basename(source_path)
    new_folder_path = os.path.join(target_path, folder_name) if target_path else folder_name
    new_full_path = os.path.join(user_dir, new_folder_path)

    # 檢查目標資料夾是否已存在
    if os.path.exists(new_full_path):
        return jsonify({'success': False, 'error': '目標位置已存在同名資料夾'}), 400

    # 先更新資料庫中的路徑（因為移動後可能無法訪問舊路徑下的檔案）
    update_folder_paths(user_id, source_path, new_folder_path)

    # 移動資料夾
    shutil.move(source_full_path, new_full_path)

    return jsonify({'success': True})

def normalize_path(path):
    """標準化路徑分隔符（將反斜槓轉為正斜槓）"""
    return path.replace('\\', '/').strip('/')

def update_folder_paths(user_id, old_path_prefix, new_path_prefix):
    """更新所有受影響的資料夾和檔案路徑"""
    folders = load_folders()
    files = load_files()
    
    # 標準化路徑格式（使用統一的正斜槓）
    old_path_prefix = normalize_path(old_path_prefix)
    new_path_prefix = normalize_path(new_path_prefix) if new_path_prefix else ''
    
    # 同時檢查帶斜槓和不帶斜槓的版本
    old_prefix_with_slash = old_path_prefix + '/' if old_path_prefix else ''
    
    # 更新資料夾路徑
    for folder_id, folder_info in folders.items():
        if folder_info.get('user_id') == user_id:
            # 標準化資料夾路徑
            folder_path = normalize_path(folder_info.get('path', ''))
            
            # 匹配：以 old_path_prefix 開頭的資料夾
            # 包括本身(old_path_prefix)和所有子資料夾
            if folder_path == old_path_prefix or (old_prefix_with_slash and folder_path.startswith(old_prefix_with_slash)):
                if folder_path == old_path_prefix:
                    # 這是本身
                    new_folder_path = new_path_prefix
                else:
                    # 這是子資料夾
                    new_folder_path = folder_path.replace(old_path_prefix, new_path_prefix, 1)
                save_folder_record(folder_id, folder_info.get('name'), user_id, new_folder_path)
    
    # 更新檔案路徑
    for file_id, file_info in files.items():
        if file_info.get('user_id') == user_id:
            # 標準化檔案路徑
            file_folder = normalize_path(file_info.get('folder', ''))
            
            # 匹配：以 old_path_prefix 開頭的檔案
            if file_folder == old_path_prefix or (old_prefix_with_slash and file_folder.startswith(old_prefix_with_slash)):
                if file_folder == old_path_prefix:
                    # 檔案直接在來源資料夾中
                    new_file_folder = new_path_prefix
                else:
                    # 檔案在子資料夾中
                    new_file_folder = file_folder.replace(old_path_prefix, new_path_prefix, 1)
                save_file_record(
                    file_id,
                    file_info.get('name'),
                    file_info.get('size', 0),
                    user_id,
                    file_info.get('checksum', ''),
                    file_info.get('name'),
                    new_file_folder
                )

@app.route('/api/node/folder/list', methods=['GET'])
@verify_token
def list_folder():
    user_id = request.args.get('user_id', 'unknown')
    path = request.args.get('path', '').strip()
    
    user_dir = os.path.join(STORAGE_DIR, user_id)
    if path:
        user_dir = os.path.join(user_dir, path)
    
    folders = []
    files = []
    
    # 列出資料夾（從實際檔案系統）
    try:
        if os.path.exists(user_dir):
            for item in os.listdir(user_dir):
                item_path = os.path.join(user_dir, item)
                if os.path.isdir(item_path):
                    folder_full_path = (path + '/' + item) if path else item
                    folders.append({
                        'name': item,
                        'path': folder_full_path,
                        'type': 'folder'
                    })
    except:
        pass
    
    # 從資料庫獲取檔案資訊
    all_files = load_files()
    for file_id, file_info in all_files.items():
        if file_info.get('user_id') == user_id:
            file_folder = file_info.get('folder', '')
            # 匹配當前路徑下的檔案
            if (path == '' and file_folder == '') or (file_folder == path):
                file_full_path = (path + '/' + file_info.get('name', '')) if path else file_info.get('name', '')
                files.append({
                    'id': file_id,
                    'name': file_info.get('name', 'unknown'),
                    'path': file_full_path,
                    'size': file_info.get('size', 0),
                    'type': 'file'
                })
    
    return jsonify({'success': True, 'folders': folders, 'files': files})

@app.route('/api/node/files/list', methods=['GET'])
@verify_token
def list_node_files():
    """列出 Node 上的所有檔案（用於後台管理）"""
    user_id = request.args.get('user_id', '')
    
    all_files = load_files()
    files_list = []
    
    for file_id, file_info in all_files.items():
        # 如果指定了 user_id，則只返回該用戶的檔案
        if user_id and file_info.get('user_id') != user_id:
            continue
        
        files_list.append({
            'id': file_id,
            'name': file_info.get('name', 'unknown'),
            'size': file_info.get('size', 0),
            'user_id': file_info.get('user_id', 'unknown'),
            'folder': file_info.get('folder', ''),
            'uploaded_at': file_info.get('uploaded_at', 0),
            'checksum': file_info.get('checksum', '')
        })
    
    return jsonify({
        'success': True, 
        'files': files_list,
        'total': len(files_list)
    })

# ==================== 檔案移動 API ====================

@app.route('/api/node/file/move', methods=['POST'])
@verify_token
def move_file():
    data = request.get_json() or {}
    user_id = data.get('user_id', 'unknown')
    file_id = data.get('file_id')
    target_folder = data.get('target_folder', '').strip()
    
    if not file_id:
        return jsonify({'success': False, 'error': '無檔案ID'}), 400
    
    files = load_files()
    if file_id not in files:
        return jsonify({'success': False, 'error': '檔案不存在'}), 404
    
    file_info = files[file_id]
    
    # 取得檔案目前的資料夾位置
    current_folder = file_info.get('folder', '')
    
    # 建構檔案的完整路徑
    old_user_dir = os.path.join(STORAGE_DIR, user_id)
    if current_folder:
        old_user_dir = os.path.join(old_user_dir, current_folder)
    old_file_path = os.path.join(old_user_dir, file_id)
    
    if not os.path.exists(old_file_path):
        return jsonify({'success': False, 'error': '檔案不存在'}), 404
    
    # 建立目標資料夾
    target_user_dir = os.path.join(STORAGE_DIR, user_id)
    if target_folder:
        target_user_dir = os.path.join(target_user_dir, target_folder)
    os.makedirs(target_user_dir, exist_ok=True)
    
    # 移動檔案
    new_file_path = os.path.join(target_user_dir, file_id)
    shutil.move(old_file_path, new_file_path)
    
    # 更新資料庫中的 folder 欄位
    save_file_record(
        file_id,
        file_info.get('name'),
        file_info.get('size', 0),
        user_id,
        file_info.get('checksum', ''),
        file_info.get('name', ''),  # path
        target_folder  # folder
    )
    
    return jsonify({'success': True})

# ==================== 預覽 API ====================

@app.route('/api/node/preview/<path:file_path>', methods=['GET'])
@verify_token
def preview_file(file_path):
    user_id = request.args.get('user_id', 'unknown')
    
    user_dir = os.path.join(STORAGE_DIR, user_id)
    
    # 首先檢查直接路徑是否存在（可能是 UUID 作為檔名）
    direct_path = os.path.join(user_dir, file_path)
    if os.path.exists(direct_path) and os.path.isfile(direct_path):
        full_path = direct_path
    else:
        # 如果直接路徑不存在，嘗試從資料庫中查找對應的 file_id
        filename = os.path.basename(file_path)
        
        # 從資料庫查找對應的檔案記錄
        all_files = load_files()
        file_id = None
        for fid, finfo in all_files.items():
            if finfo.get('user_id') == user_id and finfo.get('name') == filename:
                file_id = fid
                break
        
        if file_id:
            full_path = os.path.join(user_dir, file_id)
        else:
            # 如果資料庫中也找不到，嘗試最後一個路徑段作為 file_id
            path_parts = file_path.split('/')
            last_part = path_parts[-1] if path_parts else file_path
            full_path = os.path.join(user_dir, last_part)
    
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'error': '檔案不存在'}), 404
    
    if os.path.isdir(full_path):
        return jsonify({'success': False, 'error': '這是資料夾'}), 400
    
    # 嘗試從資料庫獲取原始檔案名稱來猜測 MIME 類型
    all_files = load_files()
    original_filename = None
    for fid, finfo in all_files.items():
        if fid == os.path.basename(full_path):
            original_filename = finfo.get('name', '')
            break
    
    # 如果有原始檔案名稱，使用它來猜測 MIME 類型
    if original_filename:
        mime_type, _ = mimetypes.guess_type(original_filename)
    else:
        mime_type, _ = mimetypes.guess_type(full_path)
    
    # 如果仍然無法識別 MIME 類型，嘗試讀取檔案內容來檢測
    if mime_type is None:
        try:
            # 讀取檔案前幾個位元組來檢測類型
            with open(full_path, 'rb') as f:
                header = f.read(8)
            
            # 檢測常見的圖片格式
            if header.startswith(b'\xff\xd8\xff'):  # JPEG
                mime_type = 'image/jpeg'
            elif header.startswith(b'\x89PNG\r\n\x1a\n'):  # PNG
                mime_type = 'image/png'
            elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):  # GIF
                mime_type = 'image/gif'
            elif header.startswith(b'RIFF') and header[8:12] == b'WEBP':  # WebP
                mime_type = 'image/webp'
            elif header.startswith(b'BM'):  # BMP
                mime_type = 'image/bmp'
        except Exception:
            pass
    
    if mime_type and mime_type.startswith('image/'):
        try:
            with open(full_path, 'rb') as f:
                return f.read(), 200, {'Content-Type': mime_type}
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    elif mime_type == 'application/pdf':
        try:
            with open(full_path, 'rb') as f:
                return f.read(), 200, {'Content-Type': mime_type}
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    else:
        return jsonify({'success': False, 'error': '不支援預覽'}), 400

# ==================== 初始化 ====================

if __name__ == '__main__':
    init_database()
    
    # 嘗試綁定到 Panel
    if TOKEN_ID and NODE_TOKEN and PANEL_URL:
        print(f"正在連接到 Panel: {PANEL_URL}")
        bind_success = bind_to_panel()
        
        if not bind_success:
            print("警告: 節點無法綁定到 Panel，請檢查配置")
    else:
        print("警告: 缺少必要配置，無法綁定到 Panel")
        print(f"  token_id: {'已設定' if TOKEN_ID else '未設定'}")
        print(f"  token: {'已設定' if NODE_TOKEN else '未設定'}")
        print(f"  panel_url: {'已設定' if PANEL_URL else '未設定'}")
    
    print(f"\nHimCloud Node 啟動中...")
    print(f"節點名稱: {NODE_NAME}")
    print(f"監聽地址: {HOST}:{PORT}")
    print(f"Panel URL: {PANEL_URL}")
    print(f"儲存目錄: {STORAGE_DIR}")
    print(f"心跳間隔: {HEARTBEAT_INTERVAL}秒")
    
    # 啟動心跳執行緒
    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    
    app.run(host=HOST, port=PORT, debug=False)
